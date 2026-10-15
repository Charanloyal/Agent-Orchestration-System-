"""Application settings. Values come from environment variables prefixed with AOS_ or from
backend/.env (git-ignored). Secrets are SecretStr so they never appear in logs or reprs."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AOS_", env_file=BACKEND_DIR / ".env", extra="ignore", frozen=True
    )

    env: Literal["dev", "test", "prod"] = "dev"
    database_url: SecretStr | None = None
    log_level: str = "INFO"
    log_json: bool = True

    # Browser-facing origin (the Vite dev server or the reverse proxy in front of the API).
    public_url: str = "http://127.0.0.1:5173"

    session_cookie_name: str = "aos_session"
    session_ttl_minutes: int = 480
    cookie_secure: bool = False

    oidc_issuer: str = "http://127.0.0.1:8001"
    oidc_client_id: str = "aos-local"
    oidc_client_secret: SecretStr | None = None
    oidc_scopes: str = "openid email profile"
    oidc_http_timeout_seconds: float = 10.0
    # Server-to-server base URL for the issuer when it differs from the public issuer URL
    # (for example inside Docker Compose). The `iss` claim is still checked against oidc_issuer.
    oidc_backchannel_url: str | None = None

    # Workflow execution
    agent_mode: Literal["fake", "llm"] = "fake"
    worker_lease_seconds: float = 30.0
    worker_heartbeat_seconds: float = 10.0
    worker_poll_seconds: float = 1.0
    job_max_attempts: int = 5
    retry_backoff_base_seconds: float = 2.0
    retry_backoff_max_seconds: float = 60.0
    approval_ttl_hours: float = 72.0
    sse_poll_seconds: float = 1.0
    # Test-only fault injection (ignored unless env is dev/test).
    crash_at: str | None = None

    @field_validator("public_url", "oidc_issuer")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @model_validator(mode="after")
    def _production_safety(self) -> Settings:
        if self.env == "prod":
            if not self.cookie_secure:
                raise ValueError("AOS_COOKIE_SECURE must be true in prod")
            if not self.oidc_issuer.startswith("https://"):
                raise ValueError("AOS_OIDC_ISSUER must use https in prod")
            if not self.public_url.startswith("https://"):
                raise ValueError("AOS_PUBLIC_URL must use https in prod")
        return self

    @property
    def oidc_redirect_uri(self) -> str:
        return f"{self.public_url}/api/v1/auth/callback"

    def sqlalchemy_url(self) -> str:
        if self.database_url is None:
            raise RuntimeError("AOS_DATABASE_URL is not configured")
        url = self.database_url.get_secret_value()
        for prefix in ("postgresql+psycopg://", "postgresql://", "postgres://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix) :]
        raise RuntimeError("AOS_DATABASE_URL must be a postgresql:// URL")

    def libpq_url(self) -> str:
        """Plain libpq URL for psycopg (used by the LangGraph checkpointer)."""
        return self.sqlalchemy_url().replace("postgresql+psycopg://", "postgresql://", 1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
