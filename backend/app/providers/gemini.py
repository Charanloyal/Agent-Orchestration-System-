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
        self.model = model
        self._key = api_key
        self._temperature = temperature
        self._client = client or httpx.Client(timeout=timeout_seconds)

    def complete(self, *, system: str, user: str, json_output: bool, max_output_tokens: int) -> LlmResult:
        config: dict[str, Any] = {"temperature": self._temperature, "maxOutputTokens": max_output_tokens}
        if json_output:
            config["responseMimeType"] = "application/json"
        if "flash" in self.model:
            # 2.5 Flash spends output tokens on "thinking" unless told not to; the agents need
            # the whole budget for their answer. Pro models require thinking and keep it.
            config["thinkingConfig"] = {"thinkingBudget": 0}
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": config,
        }
        try:
            response = self._client.post(
                f"{GEMINI_BASE_URL}/models/{self.model}:generateContent",
                json=body,
                headers={"x-goog-api-key": self._key},
            )
        except httpx.TimeoutException as exc:
            raise TransientError("model provider timeout") from exc
        except httpx.TransportError as exc:
            raise TransientError("model provider unreachable") from exc
        if response.status_code == 429:
            raise TransientError("model provider rate limit", retry_after=_retry_after(response))
        if response.status_code >= 500:
            raise TransientError(
                f"model provider HTTP {response.status_code}", retry_after=_retry_after(response)
            )
        if response.status_code >= 400:
            raise StepFailed("model", f"model provider rejected the request (HTTP {response.status_code})")
        data = response.json()
        candidates = data.get("candidates") or []
        parts = (candidates[0].get("content") or {}).get("parts") or [] if candidates else []
        text = "".join(str(p.get("text", "")) for p in parts if not p.get("thought"))
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


def _retry_after(response: httpx.Response) -> float | None:
    try:
        return float(response.headers.get("retry-after", ""))
    except ValueError:
        return None
