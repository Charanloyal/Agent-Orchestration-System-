"""LLM provider adapter (ADR 0002): one OpenAI-compatible chat-completions client.

Works with OpenAI, Azure OpenAI, Groq, and local servers such as Ollama via `base_url`.
Validation and the bounded repair loop live in our code (app/agents/structured.py), never in
the provider. Errors are classified so only transient failures are retried by the worker.
"""

from dataclasses import dataclass
from typing import Any, Protocol

import openai

from app.config import Settings
from app.workflow.errors import StepFailed, TransientError


@dataclass(frozen=True)
class LlmUsage:
    provider: str
    model: str
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class LlmResult:
    text: str
    usage: LlmUsage
    request_id: str | None = None


class LlmProvider(Protocol):
    name: str
    model: str

    def complete(self, *, system: str, user: str, json_output: bool, max_output_tokens: int) -> LlmResult: ...


def _retry_after(error: openai.APIStatusError) -> float | None:
    value = error.response.headers.get("retry-after", "")
    try:
        return float(value)
    except ValueError:
        return None


class OpenAICompatibleLlm:
    def __init__(self, settings: Settings, *, client: Any | None = None) -> None:
        self.model = settings.llm_model
        self._settings = settings
        if client is not None:
            self._client = client
            self.name = "openai-compatible"
        elif settings.llm_api_style == "azure":
            if not settings.llm_azure_endpoint or settings.llm_api_key is None:
                raise RuntimeError("Azure OpenAI needs AOS_LLM_AZURE_ENDPOINT and AOS_LLM_API_KEY")
            self._client = openai.AzureOpenAI(
                azure_endpoint=settings.llm_azure_endpoint,
                api_key=settings.llm_api_key.get_secret_value(),
                api_version=settings.llm_azure_api_version,
                timeout=settings.llm_timeout_seconds,
                max_retries=0,  # the worker owns retries (bounded, classified, visible)
            )
            self.name = "azure-openai"
        else:
            key = (
                settings.llm_api_key.get_secret_value()
                if settings.llm_api_key
                else "not-needed-for-local-servers"
            )
            self._client = openai.OpenAI(
                api_key=key,
                base_url=settings.llm_base_url,
                timeout=settings.llm_timeout_seconds,
                max_retries=0,
            )
            self.name = "openai-compatible"

    def complete(self, *, system: str, user: str, json_output: bool, max_output_tokens: int) -> LlmResult:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": self._settings.llm_temperature,
            "max_tokens": max_output_tokens,
        }
        if self._settings.llm_seed is not None:
            kwargs["seed"] = self._settings.llm_seed
        if json_output and self._settings.llm_response_format == "json_object":
            kwargs["response_format"] = {"type": "json_object"}
        try:
            completion = self._client.chat.completions.create(**kwargs)
        except openai.APITimeoutError as exc:
            raise TransientError("model provider timeout") from exc
        except openai.APIConnectionError as exc:
            raise TransientError("model provider unreachable") from exc
        except openai.RateLimitError as exc:
            raise TransientError("model provider rate limit", retry_after=_retry_after(exc)) from exc
        except openai.InternalServerError as exc:
            raise TransientError(
                f"model provider HTTP {exc.status_code}", retry_after=_retry_after(exc)
            ) from exc
        except openai.APIStatusError as exc:
            # 400/401/403/404/422: configuration or request errors; retrying cannot help.
            raise StepFailed(
                "model", f"model provider rejected the request (HTTP {exc.status_code})"
            ) from exc
        choice = completion.choices[0] if completion.choices else None
        text = (choice.message.content or "") if choice else ""
        usage = completion.usage
        return LlmResult(
            text=text,
            usage=LlmUsage(
                provider=self.name,
                model=str(completion.model or self.model),
                input_tokens=int(usage.prompt_tokens) if usage else 0,
                output_tokens=int(usage.completion_tokens) if usage else 0,
            ),
            request_id=getattr(completion, "_request_id", None),
        )


class ScriptedLlm:
    """Deterministic provider for tests: returns scripted texts in order and records prompts."""

    name = "scripted"
    model = "scripted-model"

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def complete(self, *, system: str, user: str, json_output: bool, max_output_tokens: int) -> LlmResult:
        if not self._responses:
            raise AssertionError("ScriptedLlm ran out of responses")
        self.calls.append({"system": system, "user": user, "json_output": json_output})
        text = self._responses.pop(0)
        return LlmResult(text, LlmUsage(self.name, self.model, len(system + user) // 4, len(text) // 4))
