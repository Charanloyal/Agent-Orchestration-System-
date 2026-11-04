"""HTTP edge concerns: request-size limits and single-origin SPA serving (ADR 0018)."""

import json
import re
from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import Settings
from app.errors import NotFound, error_body

_UPLOAD_PATH = re.compile(r"^/api/v1/workspaces/[^/]+/uploads/?$")
_BODY_METHODS = frozenset({"POST", "PUT", "PATCH"})
UPLOAD_OVERHEAD_BYTES = 1_000_000  # multipart boundaries and headers around the file

# Same policy the nginx front end uses (docker-compose); the SPA needs nothing external.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)


class BodySizeLimitMiddleware:
    """Rejects oversized request bodies with 413 before they are buffered or parsed. Checks
    the declared Content-Length and counts streamed bytes, so chunked uploads cannot bypass it."""

    def __init__(self, app: ASGIApp, settings: Callable[[], Settings]) -> None:
        self.app = app
        self.settings = settings

    def limit_for(self, path: str) -> int:
        s = self.settings()
        return s.upload_max_bytes + UPLOAD_OVERHEAD_BYTES if _UPLOAD_PATH.match(path) else s.max_request_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in _BODY_METHODS:
            await self.app(scope, receive, send)
            return
        limit = self.limit_for(scope["path"])
        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            await _reject(send, limit)
            return
        received = 0
        started = False
        rejected = False

        async def counting_receive() -> Message:
            # Raising here would be swallowed by FastAPI's body parsing (as a 400), so the
            # middleware answers 413 itself and tells the app the client went away.
            nonlocal received, started, rejected
            if rejected:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    rejected = True
                    if not started:
                        started = True
                        await _reject(send, limit)
                    return {"type": "http.disconnect"}
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if rejected:
                return  # the 413 has been sent; drop whatever the app tries to answer
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except Exception:
            if not rejected:
                raise


async def _reject(send: Send, limit: int) -> None:
    body = json.dumps(
        error_body("payload_too_large", f"Request body exceeds the {limit // 1_000_000 or 1} MB limit")
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        }
    )
    await send({"type": "http.response.body", "body": body})


class _ImmutableAssets(StaticFiles):
    """Vite emits content-hashed asset names, so they can be cached for a year."""

    def file_response(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


def mount_spa(app: FastAPI, static_dir: Path) -> None:
    """Serve the built frontend from the API's origin (one Render web service, no CORS, and
    first-party cookies). Unknown non-API paths return index.html for client-side routing;
    unknown /api paths keep returning the JSON 404 envelope."""
    root = static_dir.resolve()
    index = root / "index.html"
    if not index.is_file():
        raise RuntimeError(
            f"AOS_STATIC_DIR={static_dir} does not contain index.html (run the frontend build)"
        )
    if (root / "assets").is_dir():
        app.mount("/assets", _ImmutableAssets(directory=root / "assets"), name="assets")

    def html(path: Path) -> FileResponse:
        response = FileResponse(path)
        if path.suffix == ".html":
            response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise NotFound("Not found")
        candidate = (root / path).resolve()
        if path and candidate.is_file() and root in candidate.parents:
            return html(candidate)
        return html(index)
