from fastapi import FastAPI

from app.api import auth, health, runs, workspaces
from app.config import get_settings
from app.errors import install_error_handlers
from app.observability.logging import configure_logging
from app.observability.middleware import RequestContextMiddleware


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    app = FastAPI(
        title="Agent Orchestration System API",
        version="0.3.0",
        docs_url="/api/docs" if settings.env != "prod" else None,
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)
    for router in (health.router, auth.router, workspaces.router, runs.router):
        app.include_router(router)
    return app


app = create_app()
