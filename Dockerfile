# syntax=docker/dockerfile:1
# Single-origin production image (ADR 0018): the API serves the built React app, so one web
# service needs no CORS and keeps cookies first-party. The same image runs the background
# worker with a different command. The dev OIDC issuer (backend/devtools) is NOT included.
#
#   docker build -t aos .
#   web:    docker run -e PORT=10000 ... aos
#   worker: docker run ... aos python -m app.workers.runner
#   migrate (pre-deploy): docker run ... aos alembic upgrade head

FROM node:24-alpine AS web
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.14-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    AOS_STATIC_DIR=/srv/web \
    AOS_OBJECT_STORE_DIR=/srv/data/objects \
    AOS_WORKER_ALIVE_FILE=/tmp/aos-worker-alive \
    PORT=10000

WORKDIR /srv/backend
RUN useradd --create-home --uid 10001 aos \
    && mkdir -p /srv/data/objects \
    && chown -R aos:aos /srv/data

COPY backend/requirements.txt ./
RUN pip install -r requirements.txt

COPY backend/alembic.ini ./
COPY backend/migrations ./migrations
COPY backend/app ./app
COPY --from=web /src/dist /srv/web

USER aos
EXPOSE 10000
# One check for every role (app/healthcheck.py): the web server must answer /healthz, a worker
# must have marked itself alive within two minutes; the single-process command needs both.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["python", "-m", "app.healthcheck"]
# Binds 0.0.0.0:$PORT (Render's default is 10000). Uvicorn handles SIGTERM gracefully. It does
# not trust forwarded headers; the app reads them only as AOS_TRUSTED_PROXY_HOPS allows (ADR 0025).
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port \"${PORT}\" --no-proxy-headers --timeout-graceful-shutdown 25"]
