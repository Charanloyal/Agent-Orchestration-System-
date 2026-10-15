"""OpenTelemetry tracing (ADR 0016, threat model T10).

Spans describe *what happened* (route, step, provider, model, token counts, outcome), never
*content*: attribute keys are allowlisted, string values pass the log redactor and are
truncated, so prompts, source text, URLs with queries, and secrets cannot reach a trace
backend even if a caller passes them by mistake.
"""

import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.trace import Span, Status, StatusCode

from app.config import Settings
from app.observability.logging import redact

SAFE_KEYS = frozenset(
    {
        "aos.run_id",
        "aos.workspace_id",
        "aos.worker",
        "aos.fencing_token",
        "aos.step",
        "aos.task_id",
        "aos.outcome",
        "aos.attempt",
        "aos.provider",
        "aos.model",
        "aos.prompt_version",
        "aos.input_tokens",
        "aos.output_tokens",
        "aos.estimated_cost",
        "aos.results",
        "aos.tool",
        "aos.domain",
        "aos.bytes",
        "aos.request_id",
        "http.request.method",
        "http.route",
        "http.response.status_code",
        "error.type",
    }
)
MAX_VALUE_CHARS = 200
# Attributes that libraries (e.g. FastAPI's own spans) may add and that carry no content.
LIBRARY_SAFE_KEYS = frozenset({"code.function.name"})

_configured = False
_lock = threading.Lock()
tracer = trace.get_tracer("aos")


class RedactingExporter(SpanExporter):
    """Last line of defence for every exported span, including spans created by libraries:
    attributes are reduced to the allowlists and events (which can hold exception messages)
    are dropped before anything leaves the process."""

    def __init__(self, inner: SpanExporter) -> None:
        self.inner = inner

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        return self.inner.export([_scrub(s) for s in spans])

    def shutdown(self) -> None:
        self.inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self.inner.force_flush(timeout_millis)


def _scrub(span_: ReadableSpan) -> ReadableSpan:
    attributes = {
        k: v for k, v in (span_.attributes or {}).items() if k in SAFE_KEYS or k in LIBRARY_SAFE_KEYS
    }
    return ReadableSpan(
        name=span_.name,
        context=span_.context,
        parent=span_.parent,
        resource=span_.resource,
        attributes=safe_attributes(attributes)
        | {k: v for k, v in attributes.items() if k in LIBRARY_SAFE_KEYS},
        events=(),
        links=span_.links,
        kind=span_.kind,
        status=span_.status,
        start_time=span_.start_time,
        end_time=span_.end_time,
        instrumentation_scope=span_.instrumentation_scope,
    )


def safe_attributes(attributes: dict[str, Any]) -> dict[str, str | int | float | bool]:
    clean: dict[str, str | int | float | bool] = {}
    for key, value in attributes.items():
        if key not in SAFE_KEYS or value is None:
            continue
        if isinstance(value, bool | int | float):
            clean[key] = value
        else:
            clean[key] = redact(str(value))[:MAX_VALUE_CHARS]
    return clean


def configure_tracing(settings: Settings, service: str, exporter: SpanExporter | None = None) -> bool:
    """Install the process-wide tracer provider once. Returns False if tracing stays off."""
    global _configured
    with _lock:
        if _configured:
            return True
        if exporter is None and settings.otel_exporter == "none":
            return False
        provider = TracerProvider(
            resource=Resource.create({"service.name": service, "deployment.environment": settings.env})
        )
        if exporter is not None:
            provider.add_span_processor(SimpleSpanProcessor(RedactingExporter(exporter)))
        elif settings.otel_exporter == "console":
            provider.add_span_processor(BatchSpanProcessor(RedactingExporter(ConsoleSpanExporter())))
        else:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            provider.add_span_processor(
                BatchSpanProcessor(RedactingExporter(OTLPSpanExporter(endpoint=settings.otel_endpoint)))
            )
        trace.set_tracer_provider(provider)
        _configured = True
        return True


@contextmanager
def span(name: str, *, expected: tuple[type[BaseException], ...] = (), **attributes: Any) -> Iterator[Span]:
    """A span whose attributes are filtered; exceptions are recorded by type only. `expected`
    exceptions are control flow (e.g. a workflow interrupt), not errors."""
    keyed = {
        f"aos.{k}" if not k.startswith(("aos.", "http.", "error.")) else k: v for k, v in attributes.items()
    }
    with tracer.start_as_current_span(
        name, attributes=safe_attributes(keyed), record_exception=False, set_status_on_exception=False
    ) as current:
        try:
            yield current
        except expected:
            current.set_attribute("aos.outcome", "interrupted")
            raise
        except BaseException as exc:
            current.set_attribute("error.type", type(exc).__name__)
            current.set_status(Status(StatusCode.ERROR))
            raise


def annotate(current: Span, **attributes: Any) -> None:
    keyed = {
        f"aos.{k}" if not k.startswith(("aos.", "http.", "error.")) else k: v for k, v in attributes.items()
    }
    for key, value in safe_attributes(keyed).items():
        current.set_attribute(key, value)
