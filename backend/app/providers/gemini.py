"""Google Gemini through its native REST API (`models/{model}:generateContent`), ADR 0029.

The key goes in the `x-goog-api-key` header, never in the URL, so it cannot appear in access
logs or error messages. Errors are classified like the OpenAI-compatible adapter: only
transient failures are retried by the worker.

Models, levels and tiers follow the Gemini API documentation (Models, Pricing, What's new in
Gemini 4 Hydrogen; read 2026-11-13):
- `gemini-4-hydrogen` is the default: free and paid tiers, thinking low/medium/high (default)/xhigh;
- `gemini-4-argon`, `gemini-4-carbon` and `gemini-3.1-pro-preview` are paid-tier only;
- `gemini-3.8-flash` (low/medium/high) and `gemini-3.5-flash-lite` (default minimal) are free too.
Gemini 3 and 4 ignore `temperature`; `minimal` is rejected by 3.8 Flash and Gemini 4;
`maxOutputTokens` caps thinking plus answer, so thinking models get the documented 65,536.
"""

from dataclasses import dataclass
from typing import Any

import httpx

from app.providers.llm import LlmResult, LlmUsage
from app.workflow.errors import StepFailed, TransientError

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-4-hydrogen"


@dataclass(frozen=True)
class GeminiModel:
    id: str
    label: str
    free_tier: bool
    levels: tuple[str, ...]  # thinking levels the model accepts; () = do not send one


MODELS: tuple[GeminiModel, ...] = (
    GeminiModel("gemini-4-hydrogen", "Gemini 4 Hydrogen", True, ("low", "medium", "high", "xhigh")),
    GeminiModel("gemini-3.1-pro-preview", "Gemini 3.1 Pro (preview)", False, ()),
    GeminiModel("gemini-4-argon", "Gemini 4 Argon", False, ("low", "medium", "high")),
    GeminiModel("gemini-4-carbon", "Gemini 4 Carbon", False, ("low", "medium", "high")),
    GeminiModel("gemini-3.8-flash", "Gemini 3.8 Flash", True, ("low", "medium", "high")),
    GeminiModel("gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite", True, ("medium", "high")),
)
BY_ID = {m.id: m for m in MODELS}
MODEL_IDS: tuple[str, ...] = tuple(m.id for m in MODELS)
# After the chosen model, in this order, when it is unavailable for the key or out of quota.
FALLBACK_CHAIN: tuple[str, ...] = (
    "gemini-4-hydrogen",
    "gemini-3.1-pro-preview",
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
)
# Retired or redirected IDs (Gemini API deprecations page) and what this app uses instead.
_REPLACED = {
    "gemini-2.0-flash": DEFAULT_MODEL,
    "gemini-2.5-flash": DEFAULT_MODEL,
    "gemini-2.5-pro": DEFAULT_MODEL,
    "gemini-3.0-flash": DEFAULT_MODEL,
    "gemini-3-flash-preview": DEFAULT_MODEL,
    "gemini-3.5-flash": DEFAULT_MODEL,
    "gemini-3.6-flash": DEFAULT_MODEL,
    "gemini-3.7-flash": DEFAULT_MODEL,
}
LEVEL_ORDER = ("low", "medium", "high", "xhigh")
THINKING_MAX_OUTPUT = 65_536


def normalize_model(model: str) -> str:
    """'models/Gemini-2.5-Flash ' becomes 'gemini-4-hydrogen': prefix, case and spaces
    removed, retired IDs replaced."""
    cleaned = model.strip().removeprefix("models/").strip().lower() or DEFAULT_MODEL
    return _REPLACED.get(cleaned, cleaned)


def thinking_level_for(model: str, requested: str | None) -> str | None:
    """The requested level if the model accepts it, else the nearest one it does accept
    (xhigh -> high on Argon); None leaves the model's own default."""
    info = BY_ID.get(model)
    if requested is None or info is None or not info.levels:
        return None
    if requested in info.levels:
        return requested
    rank = LEVEL_ORDER.index(requested)
    return min(info.levels, key=lambda level: abs(LEVEL_ORDER.index(level) - rank))


def generation_config(
    model: str, *, json_output: bool, max_output_tokens: int, temperature: float, thinking: str | None
) -> dict[str, Any]:
    config: dict[str, Any] = {"maxOutputTokens": max_output_tokens}
    if json_output:
        config["responseMimeType"] = "application/json"
    if model.startswith("gemini-2"):
        config["temperature"] = temperature
        if "flash" in model:
            config["thinkingConfig"] = {"thinkingBudget": 0}
        return config
    # Gemini 3 and 4 think by default; thinking and answer share maxOutputTokens.
    config["maxOutputTokens"] = max(max_output_tokens, THINKING_MAX_OUTPUT)
    if level := thinking_level_for(model, thinking):
        config["thinkingConfig"] = {"thinkingLevel": level}
    return config


class GeminiLlm:
    name = "google-gemini"

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        temperature: float = 0.2,
        timeout_seconds: float = 120.0,
        client: httpx.Client | None = None,
        fallback_models: bool = True,
        thinking_level: str | None = None,
    ) -> None:
        self.model = normalize_model(model)
        self.thinking_level = thinking_level
        self._key = api_key.strip()
        self._temperature = temperature
        self._timeout = timeout_seconds
        self._fallback = fallback_models
        self._client = client or httpx.Client(timeout=timeout_seconds)
        chain = [m for m in FALLBACK_CHAIN if m != self.model] if fallback_models else []
        self._chain = [self.model, *chain]

    def with_role(self, role: str) -> GeminiLlm:
        """Role routing (ADR 0029): researchers run in parallel, so they use Gemini 4 Hydrogen
        (free tier, fast) at medium thinking unless a Flash model was chosen; every other role
        uses the chosen model and thinking level."""
        if role != "research":
            return self
        model = self.model if self.model in ("gemini-3.8-flash", "gemini-3.5-flash-lite") else DEFAULT_MODEL
        return GeminiLlm(
            self._key,
            model,
            temperature=self._temperature,
            timeout_seconds=self._timeout,
            client=self._client,
            fallback_models=self._fallback,
            thinking_level="medium",
        )

    def output_cap(self, max_output_tokens: int) -> int:
        """The output limit actually sent (thinking included), for the budget reservation."""
        return int(
            generation_config(
                self.model,
                json_output=False,
                max_output_tokens=max_output_tokens,
                temperature=0,
                thinking=None,
            )["maxOutputTokens"]
        )

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
            model,
            json_output=json_output,
            max_output_tokens=max_tokens,
            temperature=self._temperature,
            thinking=self.thinking_level,
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
    """The model is unknown or retired for this key (404), not open to it (403, e.g. a paid-only
    model on a free key), or out of quota (429): another model may still answer. A bad key or a
    bad request never moves on."""
    if response.status_code in (404, 429):
        return True
    text = _error_message(response).lower()
    if response.status_code == 403:
        return "api key" not in text
    if response.status_code == 400 and not _is_key_problem(response):
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
