"""Single-process deployment for hosts without pre-deploy commands or background workers
(Render's free plan; render.free.yaml, ADR 0022).

    python -m app.serve --migrate --with-worker

1. `--migrate`: apply migrations (`alembic upgrade head`) before serving. Migrations are
   additive and the previous build stays compatible (ADR 0020), so this is safe on restart.
2. `--with-worker`: run the background worker as a child process, restarted if it exits.
3. Serve the API and the built SPA with uvicorn on $PORT, as the Dockerfile's default command.

SIGTERM stops uvicorn gracefully, then asks the worker to finish its current pass.
"""

import argparse
import logging
import os
import subprocess
import sys
import threading

import uvicorn

from app.config import BACKEND_DIR, get_settings
from app.observability.logging import configure_logging

log = logging.getLogger("aos.serve")


def migrate() -> None:
    from alembic import command
    from alembic.config import Config

    log.info("applying migrations")
    command.upgrade(Config(str(BACKEND_DIR / "alembic.ini")), "head")


class WorkerSupervisor:
    """Keeps one `python -m app.workers.runner` child alive until stopped."""

    def __init__(self, restart_delay: float = 5.0) -> None:
        self.restart_delay = restart_delay
        self.stopping = threading.Event()
        self.process: subprocess.Popen[bytes] | None = None
        self.thread = threading.Thread(target=self._run, name="worker-supervisor", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def _run(self) -> None:
        while not self.stopping.is_set():
            self.process = subprocess.Popen([sys.executable, "-m", "app.workers.runner"])
            code = self.process.wait()
            if self.stopping.is_set():
                return
            log.error("worker exited; restarting", extra={"exit_code": code, "delay_s": self.restart_delay})
            self.stopping.wait(self.restart_delay)

    def stop(self, timeout: float = 25.0) -> None:
        self.stopping.set()
        process = self.process
        if process is None or process.poll() is not None:
            return
        process.terminate()  # SIGTERM: the worker finishes its current pass, then exits
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            log.warning("worker did not stop in time; killing it")
            process.kill()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--migrate", action="store_true", help="run alembic upgrade head first")
    parser.add_argument("--with-worker", action="store_true", help="also run the background worker")
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    if args.migrate:
        migrate()
    supervisor = WorkerSupervisor() if args.with_worker else None
    if supervisor:
        supervisor.start()
    try:
        uvicorn.run(
            "app.main:app",
            host="0.0.0.0",  # noqa: S104 - the platform's load balancer is the only route in
            port=int(os.environ.get("PORT", "10000")),
            # Forwarded headers are read by the app only, as AOS_TRUSTED_PROXY_HOPS allows (ADR 0025).
            proxy_headers=False,
            timeout_graceful_shutdown=20,
            log_config=None,
        )
    finally:
        if supervisor:
            supervisor.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
