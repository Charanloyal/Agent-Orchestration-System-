import logging
import re
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.observability.context import reset_request_id, set_request_id
from app.observability.metrics import http_metrics
from app.observability.tracing import annotate, span

log = logging.getLogger("aos.http")
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")

SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"cache-control", b"no-store"),
]


class RequestContextMiddleware:
    """Assigns a request ID, adds security headers, and logs one summary line per request.

    Pure ASGI (not BaseHTTPMiddleware) so streaming responses such as SSE are not buffered.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope["headers"]).get(b"x-request-id", b"").decode("latin-1")
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        token = set_request_id(request_id)
        started = time.perf_counter()
        status = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = list(message.get("headers", []))
                existing = {k.lower() for k, _ in headers}
                headers.append((b"x-request-id", request_id.encode()))
                headers.extend(h for h in SECURITY_HEADERS if h[0] not in existing)
                message["headers"] = headers
            await send(message)

        try:
            with span(
                "HTTP request", request_id=request_id, **{"http.request.method": scope["method"]}
            ) as current:
                await self.app(scope, receive, send_wrapper)
                route_path = getattr(scope.get("route"), "path", None) or "<unmatched>"
                current.update_name(f"{scope['method']} {route_path}")
                annotate(current, **{"http.route": route_path, "http.response.status_code": status})
        finally:
            route = scope.get("route")
            route_path = getattr(route, "path", None) or "<unmatched>"
            elapsed = time.perf_counter() - started
            http_metrics.observe(scope["method"], route_path, status, elapsed)
            log.info(
                "request",
                extra={
                    "method": scope["method"],
                    "route": route_path,
                    "status": status,
                    "duration_ms": round(elapsed * 1000, 1),
                },
            )
            reset_request_id(token)
