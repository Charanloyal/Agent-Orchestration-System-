"""Which model engine a workspace uses (ADR 0029), in this order:

1. the workspace's own engine, saved by a workspace admin (key encrypted with AOS_SECRETS_KEY);
2. the deployment's engine from the environment (AOS_AGENT_MODE=llm or auto with a key, ADR 0028);
3. the deterministic demo agents.

Keys are never returned by the API: only the provider, the model and the key's last 4 characters.
"""

import base64
import hashlib
import time
import uuid
from dataclasses import dataclass
from typing import Literal

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import WorkspaceAiConfig
from app.providers.gemini import (
    BY_ID,
    DEFAULT_MODEL,
    MODEL_IDS,
    GeminiLlm,
    normalize_model,
    thinking_level_for,
)
from app.providers.llm import LlmProvider, OpenAICompatibleLlm

Provider = Literal["gemini", "groq", "openai"]


@dataclass(frozen=True)
class ProviderInfo:
    label: str
    models: tuple[str, ...]
    base_url: str | None  # OpenAI-compatible endpoint; None for Gemini (native API) and OpenAI


PROVIDERS: dict[Provider, ProviderInfo] = {
    "gemini": ProviderInfo("Google Gemini", MODEL_IDS, None),
    "groq": ProviderInfo(
        "Groq", ("llama-3.3-70b-versatile", "llama-3.1-8b-instant"), "https://api.groq.com/openai/v1"
    ),
    "openai": ProviderInfo("OpenAI", ("gpt-4o-mini", "gpt-4o"), None),
}
_DEV_SECRET = "aos-development-only-secret"  # noqa: S105  (dev/test only; prod requires AOS_SECRETS_KEY)


def current_model(provider: str, model: str) -> str:
    """A saved or configured Gemini model ID that Google has retired is used as its
    replacement (gemini-2.5-flash -> gemini-3.8-flash) without anyone re-saving settings."""
    return normalize_model(model) if provider == "gemini" else model


def thinking_levels(provider: str, model: str) -> tuple[str, ...]:
    info = BY_ID.get(model) if provider == "gemini" else None
    return info.levels if info else ()


def model_details(provider: str) -> list[dict[str, object]]:
    """Each offered model with its label, free-tier availability and thinking levels."""
    out: list[dict[str, object]] = []
    for model in PROVIDERS[provider].models:  # type: ignore[index]
        info = BY_ID.get(model) if provider == "gemini" else None
        out.append(
            {
                "id": model,
                "label": info.label if info else model,
                "free_tier": info.free_tier if info else None,
                "thinking_levels": list(info.levels) if info else [],
            }
        )
    return out


class SecretsUnavailable(Exception):
    """Saving a key needs AOS_SECRETS_KEY in production."""


def _fernet(settings: Settings) -> Fernet:
    if settings.secrets_key is not None:
        secret = settings.secrets_key.get_secret_value()
    elif settings.env != "prod":
        secret = _DEV_SECRET
    else:
        raise SecretsUnavailable("Saving a model key needs AOS_SECRETS_KEY on the server")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))


def encrypt_key(settings: Settings, api_key: str) -> str:
    return _fernet(settings).encrypt(api_key.encode()).decode()


def decrypt_key(settings: Settings, ciphertext: str) -> str | None:
    """None when the key cannot be decrypted (AOS_SECRETS_KEY changed or missing)."""
    try:
        return _fernet(settings).decrypt(ciphertext.encode()).decode()
    except InvalidToken, SecretsUnavailable:
        return None


@dataclass(frozen=True)
class Engine:
    source: Literal["workspace", "environment", "demo"]
    provider: str | None
    model: str | None
    key_hint: str | None = None
    problem: str | None = None  # e.g. a saved key that can no longer be decrypted
    thinking_level: str | None = None  # None: each model's own default

    @property
    def live(self) -> bool:
        return self.source != "demo"

    @property
    def label(self) -> str:
        if not self.live:
            return "Deterministic demo agents"
        info = PROVIDERS.get(self.provider)  # type: ignore[call-overload]
        name = info.label if info else "Language model"
        return f"{name} · {self.model}"

    def roles(self) -> list[tuple[str, str, str]]:
        """(role, model, thinking) as the agents will call it, for the Agents page."""
        if not self.live or self.model is None:
            return []
        if self.provider != "gemini":
            return [("All agents and the Style studio", self.model, "provider default")]
        research_model = (
            self.model if self.model in ("gemini-3.8-flash", "gemini-3.5-flash-lite") else DEFAULT_MODEL
        )
        main = thinking_level_for(self.model, self.thinking_level) or "model default"
        research = thinking_level_for(research_model, "medium") or "model default"
        return [
            ("Planner, writer, reviewer and Style studio", self.model, main),
            ("Researchers (parallel)", research_model, research),
        ]


def _environment_engine(settings: Settings) -> Engine:
    if settings.agent_mode != "llm":
        return Engine("demo", None, None)
    base = settings.llm_base_url or ""
    provider = "groq" if "groq.com" in base else "gemini" if "googleapis.com" in base else "openai"
    return Engine("environment", provider, current_model(provider, settings.llm_model))


def resolve(db: Session, settings: Settings, workspace_id: uuid.UUID) -> Engine:
    config = db.get(WorkspaceAiConfig, workspace_id)
    if config is not None:
        if decrypt_key(settings, config.key_ciphertext) is not None:
            return Engine(
                "workspace",
                config.provider,
                current_model(config.provider, config.model),
                config.key_hint,
                thinking_level=config.thinking_level,
            )
        fallback = _environment_engine(settings)
        return Engine(
            fallback.source,
            fallback.provider,
            fallback.model,
            problem="The saved key can no longer be decrypted (AOS_SECRETS_KEY changed); save it again.",
        )
    return _environment_engine(settings)


def build_llm(
    settings: Settings, provider: str, model: str, api_key: str, thinking_level: str | None = None
) -> LlmProvider:
    if provider == "gemini":
        return GeminiLlm(
            api_key,
            model,
            temperature=settings.llm_temperature,
            # Thinking models can take longer than a chat completion.
            timeout_seconds=max(settings.llm_timeout_seconds, 180.0),
            thinking_level=thinking_level,
        )
    info = PROVIDERS["groq" if provider == "groq" else "openai"]
    overrides = settings.model_copy(
        update={
            "llm_api_style": "openai",
            "llm_base_url": info.base_url,
            "llm_model": model,
            "llm_api_key": None,
        }
    )
    return OpenAICompatibleLlm(overrides, api_key=api_key)


def default_llm(settings: Settings) -> LlmProvider:
    """The deployment's model from the environment. A Gemini key uses the native API, which
    accepts the agents' JSON mode reliably, rather than Gemini's OpenAI-compatible endpoint."""
    base = settings.llm_base_url or ""
    if (
        settings.llm_api_style == "openai"
        and "generativelanguage.googleapis.com" in base
        and settings.llm_api_key
    ):
        return GeminiLlm(
            settings.llm_api_key.get_secret_value(),
            settings.llm_model,
            temperature=settings.llm_temperature,
            timeout_seconds=max(settings.llm_timeout_seconds, 180.0),
        )
    return OpenAICompatibleLlm(settings)


def workspace_llm(db: Session, settings: Settings, workspace_id: uuid.UUID) -> LlmProvider | None:
    """The workspace's own model, or None to use the deployment's engine."""
    config = db.get(WorkspaceAiConfig, workspace_id)
    if config is None:
        return None
    key = decrypt_key(settings, config.key_ciphertext)
    return (
        build_llm(
            settings,
            config.provider,
            current_model(config.provider, config.model),
            key,
            config.thinking_level,
        )
        if key
        else None
    )


def engine_llm(db: Session, settings: Settings, workspace_id: uuid.UUID) -> LlmProvider | None:
    """The model this workspace's work should use, or None for the deterministic fallback."""
    own = workspace_llm(db, settings, workspace_id)
    if own is not None:
        return own
    return default_llm(settings) if settings.agent_mode == "llm" else None


@dataclass(frozen=True)
class Ping:
    ok: bool
    latency_ms: int
    model: str
    detail: str


def ping(llm: LlmProvider) -> Ping:
    """One tiny live request, timed. The detail never contains the key."""
    started = time.perf_counter()
    try:
        result = llm.complete(
            system="Reply with the single word: ready", user="ping", json_output=False, max_output_tokens=16
        )
    except Exception as exc:  # reported to the admin; the message never contains the key
        return Ping(False, round((time.perf_counter() - started) * 1000), llm.model, str(exc)[:200])
    latency = round((time.perf_counter() - started) * 1000)
    return Ping(True, latency, result.usage.model, (result.text or "").strip()[:40] or "empty reply")
