"""Google Gemini through its native REST API (`models/{model}:generateContent`), ADR 0029.

The key goes in the `x-goog-api-key` header, never in the URL, so it cannot appear in access
logs or error messages. Errors are classified like the OpenAI-compatible adapter: only
transient failures are retried by the worker.
"""

from typing import Any

import httpx

from app.providers.llm import LlmResult, LlmUsage
from app.workflow.errors import StepFailed, TransientError

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiLlm:
    name = "google-gemini"

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        temperature: float = 0.2,
        timeout_seconds: float = 60.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.model = normalize_model(model)
        self._key = api_key.strip()
        self._temperature = temperature
        self._client = client or httpx.Client(timeout=timeout_seconds)

    def complete(self, *, system: str, user: str, json_output: bool, max_output_tokens: int) -> LlmResult:
        config: dict[str, Any] = {"temperature": self._temperature, "maxOutputTokens": max_output_tokens}
        if json_output:
            config["responseMimeType"] = "application/json"
        if self.model.startswith("gemini-2.5-flash"):
            # 2.5 Flash spends output tokens on "thinking" unless told not to; the agents need
            # the whole budget for their answer. Pro models require thinking and keep it.
            config["thinkingConfig"] = {"thinkingBudget": 0}
        response = self._post(system, user, config)
        if response.status_code == 400 and not _is_key_problem(response) and len(config) > 2:
            # Some models or accounts reject optional settings (JSON mode, thinking budget).
            # Retry once with only the basics; the agents parse JSON from plain text too.
            response = self._post(system, user, {"maxOutputTokens": max_output_tokens})
        if response.status_code == 429:
            raise TransientError(
                f"model provider rate limit: {self._detail(response)}", retry_after=_retry_after(response)
            )
        if response.status_code >= 500:
            raise TransientError(
                f"model provider HTTP {response.status_code}: {self._detail(response)}",
                retry_after=_retry_after(response),
            )
        if response.status_code >= 400:
            detail = f"HTTP {response.status_code}: {self._detail(response)}"
            raise StepFailed("model", f"model provider rejected the request ({detail})")
        data = response.json()
        candidates = data.get("candidates") or []
        parts = (candidates[0].get("content") or {}).get("parts") or [] if candidates else []
        text = "".join(str(p.get("text", "")) for p in parts if not p.get("thought"))
        if not text and candidates and candidates[0].get("finishReason") not in (None, "STOP"):
            raise StepFailed(
                "model", f"model returned no text (finish reason {candidates[0].get('finishReason')})"
            )
        usage = data.get("usageMetadata") or {}
        return LlmResult(
            text=text,
            usage=LlmUsage(
                provider=self.name,
                model=str(data.get("modelVersion") or self.model),
                input_tokens=int(usage.get("promptTokenCount") or 0),
                output_tokens=int(usage.get("candidatesTokenCount") or 0),
            ),
            request_id=data.get("responseId"),
        )

    def _post(self, system: str, user: str, config: dict[str, Any]) -> httpx.Response:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": config,
        }
        try:
            return self._client.post(
                f"{GEMINI_BASE_URL}/models/{self.model}:generateContent",
                json=body,
                headers={"x-goog-api-key": self._key},
            )
        except httpx.TimeoutException as exc:
            raise TransientError("model provider timeout") from exc
        except httpx.TransportError as exc:
            raise TransientError("model provider unreachable") from exc

    def _detail(self, response: httpx.Response) -> str:
        """Google's own error message, without the key, for the timeline and the settings test."""
        return (
            _error_message(response).replace(self._key, "***")[:300]
            if self._key
            else _error_message(response)[:300]
        )


def normalize_model(model: str) -> str:
    """'models/gemini-2.5-flash ' and 'Gemini-2.5-Flash' both become 'gemini-2.5-flash'."""
    model = model.strip()
    return (model.removeprefix("models/") or model).lower()


def _error_message(response: httpx.Response) -> str:
    try:
        error = response.json().get("error") or {}
        message = str(error.get("message") or "").strip()
        status = str(error.get("status") or "").strip()
    except ValueError:
        return response.text[:200] or "no details"
    return f"{status}: {message}" if status and message else message or status or "no details"


def _is_key_problem(response: httpx.Response) -> bool:
    text = _error_message(response).lower()
    return "api key" in text or "api_key" in text or "permission" in text


def _retry_after(response: httpx.Response) -> float | None:
    try:
        return float(response.headers.get("retry-after", ""))
    except ValueError:
        return None
