"""Structured JSON logging with secret redaction.

Log execution summaries, never prompts, model outputs, source text, cookies, or tokens.
The redaction filter is a safety net, not a licence to log sensitive values.
"""

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.observability.context import current_request_id

if TYPE_CHECKING:
    from app.config import Settings

_STANDARD_ATTRS = set(vars(logging.makeLogRecord({}))) | {
    "message",
    "asctime",
    "taskName",
}

_SECRET_PATTERNS = [
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-+/=]{8,}"), r"\1[REDACTED]"),
    (
        re.compile(
            r"(?i)((?:api[_-]?key|token|secret|password|passwd|authorization)[\"']?\s*[:=]\s*[\"']?)"
            r"[^\s\"',;]{4,}"
        ),
        r"\1[REDACTED]",
    ),
    (
        re.compile(r"(postgres(?:ql)?(?:\+psycopg)?://[^:/\s@]+:)[^@\s]+(@)"),
        r"\1[REDACTED]\2",
    ),
    (re.compile(r"\b(sk-|tvly-|gsk_)[A-Za-z0-9_\-]{8,}"), r"\1[REDACTED]"),
]
_SENSITIVE_KEYS = re.compile(r"(?i)(password|secret|token|api[_-]?key|authorization|cookie|code_verifier)")


def redact(text: str) -> str:
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact_value(key: str, value: Any) -> Any:
    if _SENSITIVE_KEYS.search(key):
        return "[REDACTED]"
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: redact_value(str(k), v) for k, v in value.items()}
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        if request_id := current_request_id():
            payload["request_id"] = request_id
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                payload[key] = redact_value(key, value)
        if record.exc_info:
            payload["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", json_output: bool = True) -> None:
    handler = logging.StreamHandler(sys.stdout)
    formatter = JsonFormatter() if json_output else logging.Formatter("%(levelname)s %(name)s %(message)s")
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # Third-party request loggers can include full URLs with query strings; Alembic's plugin
    # registration is noise at INFO (it runs on the first readiness check).
    for noisy in ("httpx", "httpcore", "uvicorn.access", "alembic.runtime.plugins"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def startup_summary(settings: Settings, component: str) -> None:
    """One structured line describing how this process is configured. Hostnames and modes
    only: never secrets, full URLs with credentials, or the allowlist contents."""
    from urllib.parse import urlsplit

    web = {"oidc_issuer_host": urlsplit(settings.oidc_issuer).hostname, "public_url": settings.public_url}
    logging.getLogger("aos.startup").info(
        "starting",
        extra={
            "component": component,
            "env": settings.env,
            "agent_mode": settings.agent_mode,
            "search_provider": settings.search_provider,
            **(web if component == "api" else {}),
            "database_configured": settings.database_url is not None,
            "serves_frontend": settings.static_dir is not None,
            "signin_allowlist": bool(settings.allowed_email_set or settings.allowed_domain_set),
            "tracing": settings.otel_exporter,
        },
    )
