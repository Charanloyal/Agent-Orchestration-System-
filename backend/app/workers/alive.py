"""The worker's liveness signal for container health checks (`python -m app.healthcheck`).

A worker serves no HTTP, so it touches a file (AOS_WORKER_ALIVE_FILE, set in the image) each
time its loop turns and each time it extends a lease during a long pass.
"""

import contextlib

from app.config import Settings


def mark_alive(settings: Settings) -> None:
    if settings.worker_alive_file is None:
        return
    with contextlib.suppress(OSError):  # a health signal must never stop the worker
        settings.worker_alive_file.touch()
