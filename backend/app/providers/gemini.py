"""Google Gemini through its native REST API (`models/{model}:generateContent`), ADR 0029/0031.

The key goes in the `x-goog-api-key` header, never in the URL, so it cannot appear in access
logs or error messages. Errors are classified like the OpenAI-compatible adapter: only
transient failures are retried by the worker.

Current models (Gemini API docs, November 2026): `gemini-3.8-flash` is the default;
`gemini-3.5-flash-lite` and `gemini-3.6-flash` follow it in the fallback chain. Gemini 3 models
ignore `temperature` (later generations reject it), set reasoning with `thinkingLevel`, and
3.8 Flash rejects the `minimal` level. Retired IDs are mapped to their replacements.
"""

from typing import Any

import httpx

from app.providers.llm import LlmResult, LlmUsage
from app.workflow.errors import StepFailed, TransientError

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-3.8-flash"
# Tried in this order when a model is unavailable for the key or out of quota.
FALLBACK_CHAIN: tuple[str, ...] = ("gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.6-flash")
# Deprecated IDs and what Google routes (or recommends routing) them to.
_REPLACED = {
    "gemini-2.0-flash": DEFAULT_MODEL,
    "gemini-2.5-flash": DEFAULT_MODEL,
    "gemini-2.5-pro": DEFAULT_MODEL,
    "gemini-3.0-flash": DEFAULT_MODEL,
    "gemini-3-flash-preview": DEFAULT_MODEL,
    "gemini-3.5-flash": "gemini-3.6-flash",
    "gemini-3.7-flash": DEFAULT_MODEL,
}
# Reasoning effort per model for the agents' structured tasks: enough to plan well, fast enough
# for a demonstration. Models not listed keep their own default.
_THINKING_LEVEL = {"gemini-3.8-flash": "low", "gemini-3.6-flash": "low"}
# Thinking tokens count against maxOutputTokens; leave room so the answer is never cut off.
_THINKING_HEADROOM = 4096


def normalize_model(model: str) -> str:
    """'models/Gemini-2.5-Flash ' becomes 'gemini-3.8-flash': prefix, case and spaces removed,
    retired IDs replaced."""
    cleaned = model.strip().removeprefix("models/").strip().lower() or DEFAULT_MODEL
    return _REPLACED.get(cleaned, cleaned)


def generation_config(
    model: str, *, json_output: bool, max_output_tokens: int, temperature: float
) -> dict[str, Any]:
    config: dict[str, Any] = {"maxOutputTokens": max_output_tokens}
    if json_output:
        config["responseMimeType"] = "application/json"
    if model.startswith("gemini-2"):
        config["temperature"] = temperature
        if "flash" in model:
            config["thinkingConfig"] = {"thinkingBudget": 0}
    elif level := _THINKING_LEVEL.get(model):
        config["thinkingConfig"] = {"thinkingLevel": level}
        config["maxOutputTokens"] = max_output_tokens + _THINKING_HEADROOM
    return config


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
        fallback_models: bool = True,
    ) -> None:
        self.model = normalize_model(model)
        self._key = api_key.strip()
        self._temperature = temperature
        self._client = client or httpx.Client(timeout=timeout_seconds)
        chain = [m for m in FALLBACK_CHAIN if m != self.model] if fallback_models else []
        self._chain = [self.model, *chain]

    def complete(self, *, system: str, user: str, json_output: bool, max_output_tokens: int) -> LlmResult:
        notes: list[str] = []
        response: httpx.Response | None = None
        model = self.model
        for model in self._chain:
            response = self._attempt(model, system, user, json_output, max_output_tokens)
            if not _try_next_model(response):
                break
            notes.append(f"{model}: {self._detail(response)}")
        assert response is not None
        if response.status_code == 429:
            raise TransientError(
                f"model provider rate limit: {'; '.join(notes) or self._detail(response)}",
                retry_after=_retry_after(response),
            )
        if response.status_code >= 500:
            raise TransientError(
                f"model provider HTTP {response.status_code}: {self._detail(response)}",
                retry_after=_retry_after(response),
            )
        if response.status_code >= 400:
            detail = f"HTTP {response.status_code}: {'; '.join(notes) or self._detail(response)}"
            raise StepFailed("model", f"model provider rejected the request ({detail})")
        return self._result(response.json(), model)

    def _attempt(
        self, model: str, system: str, user: str, json_output: bool, max_tokens: int
    ) -> httpx.Response:
        config = generation_config(
            model, json_output=json_output, max_output_tokens=max_tokens, temperature=self._temperature
        )
        response = self._post(model, system, user, config)
        if response.status_code == 400 and not _is_key_problem(response) and len(config) > 1:
            # Some models or accounts reject optional settings (JSON mode, thinking). Retry once
            # with only the output limit; the agents parse JSON from plain text too.
            response = self._post(model, system, user, {"maxOutputTokens": config["maxOutputTokens"]})
        return response

    def _result(self, data: dict[str, Any], model: str) -> LlmResult:
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
                model=str(data.get("modelVersion") or model),
                input_tokens=int(usage.get("promptTokenCount") or 0),
                # Thinking tokens are billed as output.
                output_tokens=int(usage.get("candidatesTokenCount") or 0)
                + int(usage.get("thoughtsTokenCount") or 0),
            ),
            request_id=data.get("responseId"),
        )

    def _post(self, model: str, system: str, user: str, config: dict[str, Any]) -> httpx.Response:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": config,
        }
        try:
            return self._client.post(
                f"{GEMINI_BASE_URL}/models/{model}:generateContent",
                json=body,
                headers={"x-goog-api-key": self._key},
            )
        except httpx.TimeoutException as exc:
            raise TransientError("model provider timeout") from exc
        except httpx.TransportError as exc:
            raise TransientError("model provider unreachable") from exc

    def _detail(self, response: httpx.Response) -> str:
        """Google's own error message, without the key, for the timeline and the settings test."""
        message = _error_message(response)
        return (message.replace(self._key, "***") if self._key else message)[:300]


def _try_next_model(response: httpx.Response) -> bool:
    """The model is unknown or retired for this key (404), or this model's quota is used up
    (429): another model may still answer. A bad key or a bad request never moves on."""
    if response.status_code == 404:
        return True
    if response.status_code == 429:
        return True
    if response.status_code == 400 and not _is_key_problem(response):
        text = _error_message(response).lower()
        return "not found" in text or "not supported" in text or "is not available" in text
    return False


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
