from fastapi import FastAPI

from app.api import access, auth, health, runs, uploads, workspaces
from app.config import Settings, get_settings
from app.errors import install_error_handlers
from app.observability.logging import configure_logging, startup_summary
from app.observability.middleware import RequestContextMiddleware
from app.observability.tracing import configure_tracing
from app.version import __version__
from app.web import BodySizeLimitMiddleware, mount_spa


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)
    configure_tracing(settings, "aos-api")
    prod = settings.env == "prod"
    app = FastAPI(
        title="Agent Orchestration System API",
        version=__version__,
        # Interactive docs and the schema document are development aids, not public surface.
        docs_url=None if prod else "/api/docs",
        redoc_url=None,
        openapi_url=None if prod else "/api/openapi.json",
    )
    # Added first, so it runs inside the request-context middleware (errors carry request ids).
    app.add_middleware(BodySizeLimitMiddleware, settings=get_settings)
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)
    routers = (health.router, auth.router, access.router, workspaces.router, runs.router, uploads.router)
    for router in routers:
        app.include_router(router)
    if settings.static_dir is not None:
        mount_spa(app, settings.static_dir)
    startup_summary(settings, "api")
    return app


app = create_app()
