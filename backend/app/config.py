"""Application settings. Values come from environment variables prefixed with AOS_ or from
backend/.env (git-ignored). Secrets are SecretStr so they never appear in logs or reprs."""

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _is_local_url(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1", "0.0.0.0") or host.endswith(".localhost")  # noqa: S104


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
    # LLM provider (ADR 0002): any OpenAI-compatible chat-completions endpoint.
    llm_api_style: Literal["openai", "azure"] = "openai"
    llm_base_url: str | None = None  # e.g. https://api.groq.com/openai/v1, http://127.0.0.1:11434/v1
    llm_api_key: SecretStr | None = None
    llm_model: str = "gpt-4o-mini"
    llm_azure_endpoint: str | None = None
    llm_azure_api_version: str = "2024-10-21"
    llm_response_format: Literal["json_object", "none"] = "json_object"
    llm_temperature: float = 0.2
    llm_max_output_tokens: int = 2500
    llm_seed: int | None = 7
    llm_timeout_seconds: float = 60.0

    # Estimated-cost accounting (FR-09). Configured estimates, not quotes: verify against
    # current provider price pages. Defaults reflect publicly listed small-model pricing.
    price_schedule_id: str = "configured-2026-10"
    price_llm_input_per_million: float = 0.15
    price_llm_output_per_million: float = 0.60
    price_search_per_credit: float = 0.008
    search_provider: Literal["fake", "tavily", "corpus"] = "fake"
    tavily_api_key: SecretStr | None = None
    corpus_dir: Path = BACKEND_DIR.parent / "eval" / "corpus" / "v1"
    object_store_dir: Path = BACKEND_DIR / ".data" / "objects"
    upload_max_bytes: int = 10_000_000
    fetch_max_bytes: int = 2_000_000
    fetch_timeout_seconds: float = 10.0
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
    # Observability (ADR 0016). Traces are off unless an exporter is chosen.
    otel_exporter: Literal["none", "console", "otlp"] = "none"
    otel_endpoint: str = "http://127.0.0.1:4318/v1/traces"
    metrics_token: SecretStr | None = None
    # Rate limits per fixed window (0 disables a limit).
    rate_run_create_per_user_hour: int = 20
    rate_run_create_per_workspace_hour: int = 60
    rate_upload_per_user_hour: int = 30
    rate_export_per_user_hour: int = 60
    rate_login_per_ip_5min: int = 30
    rate_access_request_per_ip_hour: int = 5
    # Proxies in front of the app that append to X-Forwarded-For (ADR 0025). 0: use the socket
    # peer and ignore the header. N: the Nth entry from the right is the client, because only
    # the right-hand entries are written by trusted proxies; the client controls the rest.
    trusted_proxy_hops: int = Field(default=0, ge=0, le=5)
    # Provider circuit breaker: consecutive transient failures before opening, and cooldown.
    breaker_failure_threshold: int = 5
    breaker_cooldown_seconds: float = 60.0
    # Sign-in allowlist (ADR 0018). Comma-separated; matched against the provider's *verified*
    # email. These addresses and domains may always sign in, whatever the signup mode.
    allowed_emails: str = ""
    allowed_email_domains: str = ""
    # Access model (ADR 0021). Who may sign in besides the allowlist and platform admins:
    # - invite: people on the in-app access list or with a pending workspace invitation;
    # - request: the same, plus a public "request access" form that platform admins review;
    # - open: anyone with a verified email (refused in prod together with model agents).
    # Unset: open in dev/test when no allowlist is configured, otherwise invite.
    signup_mode: Literal["invite", "request", "open"] | None = None
    # Comma-separated verified emails that manage access for the whole deployment. Required
    # in prod, so someone can always approve requests and administer the access list.
    platform_admin_emails: str = ""
    # Who may create workspaces. Unset: everyone in dev/test, platform admins in prod.
    workspace_creation: Literal["everyone", "platform_admins"] | None = None
    invitation_ttl_days: int = 14
    # Name shown on the sign-in button ("Continue with ..."). Unset: derived from the issuer.
    oidc_provider_label: str | None = None
    # Single-origin deployment: when set, the API also serves the built SPA from this folder.
    static_dir: Path | None = None
    # Largest accepted request body for JSON endpoints; uploads get upload_max_bytes + 1 MB.
    max_request_bytes: int = 1_000_000
    # Data retention (ADR 0018). 0 disables a sweep.
    retention_run_days: int = 0
    retention_upload_days: int = 0
    # Decided (approved or denied) access requests are removed after this many days.
    retention_access_request_days: int = 90

    @property
    def allowed_email_set(self) -> frozenset[str]:
        return frozenset(e.strip().lower() for e in self.allowed_emails.split(",") if e.strip())

    @property
    def allowed_domain_set(self) -> frozenset[str]:
        return frozenset(
            d.strip().lower().lstrip("@") for d in self.allowed_email_domains.split(",") if d.strip()
        )

    @property
    def platform_admin_set(self) -> frozenset[str]:
        return frozenset(e.strip().lower() for e in self.platform_admin_emails.split(",") if e.strip())

    @property
    def effective_signup_mode(self) -> Literal["invite", "request", "open"]:
        if self.signup_mode is not None:
            return self.signup_mode
        if self.env != "prod" and not self.allowed_email_set and not self.allowed_domain_set:
            return "open"
        return "invite"

    @property
    def effective_workspace_creation(self) -> Literal["everyone", "platform_admins"]:
        if self.workspace_creation is not None:
            return self.workspace_creation
        return "platform_admins" if self.env == "prod" else "everyone"

    @property
    def provider_label(self) -> str:
        if self.oidc_provider_label:
            return self.oidc_provider_label
        host = (urlsplit(self.oidc_issuer).hostname or "").lower()
        if host == "accounts.google.com":
            return "Google"
        if host == "login.microsoftonline.com":
            return "Microsoft"
        if _is_local_url(self.oidc_issuer):
            return "dev sign-in"
        return "your organization"

    def email_allowed(self, email: str | None) -> bool:
        """Legacy allowlist check: with no allowlist configured, anyone passes."""
        if not self.allowed_email_set and not self.allowed_domain_set:
            return True
        return self.email_on_allowlist(email)

    def email_on_allowlist(self, email: str | None) -> bool:
        if not email:
            return False
        email = email.lower()
        return email in self.allowed_email_set or email.rsplit("@", 1)[-1] in self.allowed_domain_set

    def is_platform_admin(self, email: str | None) -> bool:
        return email is not None and email.lower() in self.platform_admin_set

    @field_validator("public_url", "oidc_issuer")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @model_validator(mode="after")
    def _production_safety(self) -> Settings:
        """Refuse to start in prod with any development default that would be unsafe there.
        Each message names the variable to fix. Settings only the web service uses are checked
        when the web app is created (`web_problems`), so the worker needs none of them."""
        if self.env == "prod":
            problems = []
            if self.database_url is None:
                problems.append("AOS_DATABASE_URL is required")
            if self.effective_signup_mode == "open" and self.agent_mode == "llm":
                problems.append(
                    "AOS_SIGNUP_MODE=open lets any verified account spend model budget; use invite or "
                    "request with AOS_AGENT_MODE=llm"
                )
            if self.crash_at:
                problems.append("AOS_CRASH_AT is a test-only setting")
            if problems:
                raise ValueError("unsafe production configuration: " + "; ".join(problems))
        return self

    def web_problems(self) -> list[str]:
        """Production checks for the settings only the web service uses: sign-in, cookies and
        its public URL. Empty outside prod."""
        if self.env != "prod":
            return []
        problems = []
        if not self.cookie_secure:
            problems.append("AOS_COOKIE_SECURE must be true")
        if not self.oidc_issuer.startswith("https://"):
            problems.append("AOS_OIDC_ISSUER must be an https URL of a real identity provider")
        if _is_local_url(self.oidc_issuer) or self.oidc_client_id == "aos-local":
            problems.append("the bundled dev OIDC issuer/client must never be used in prod")
        if self.oidc_backchannel_url and _is_local_url(self.oidc_backchannel_url):
            problems.append("AOS_OIDC_BACKCHANNEL_URL must not point at a local dev issuer in prod")
        if not self.public_url.startswith("https://"):
            problems.append("AOS_PUBLIC_URL must use https")
        if not self.platform_admin_set:
            problems.append(
                "set AOS_PLATFORM_ADMIN_EMAILS (at least one person must be able to manage access)"
            )
        return problems

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
