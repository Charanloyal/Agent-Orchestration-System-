"""G4: one Docker HEALTHCHECK that fits each role of the image (web, worker, or both)."""

import http.server
import os
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from app import healthcheck
from app.config import Settings
from app.workers.alive import mark_alive


class Ok(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200 if self.path == "/healthz" else 404)
        self.end_headers()

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def web_port() -> Iterator[int]:
    server = http.server.HTTPServer(("127.0.0.1", 0), Ok)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1]
    server.shutdown()
    server.server_close()


def closed_port() -> int:
    server = http.server.HTTPServer(("127.0.0.1", 0), Ok)
    port = server.server_address[1]
    server.server_close()
    return port


def fresh(path: Path) -> Path:
    path.write_text("")
    return path


def stale(path: Path, age: float) -> Path:
    fresh(path)
    past = time.time() - age
    os.utime(path, (past, past))
    return path


def test_web_container_is_healthy_when_healthz_answers(web_port: int, tmp_path: Path) -> None:
    assert healthcheck.check(web_port, tmp_path / "absent", max_age=120) == (True, "web ok")


def test_worker_container_is_healthy_while_its_loop_marks_it_alive(tmp_path: Path) -> None:
    alive = fresh(tmp_path / "alive")
    assert healthcheck.check(closed_port(), alive, max_age=120) == (True, "worker ok")


def test_a_stuck_worker_is_unhealthy(tmp_path: Path) -> None:
    ok, reason = healthcheck.check(closed_port(), stale(tmp_path / "alive", 300), max_age=120)
    assert not ok and "worker" in reason


def test_single_process_needs_both_roles(web_port: int, tmp_path: Path) -> None:
    assert healthcheck.check(web_port, fresh(tmp_path / "alive"), max_age=120) == (True, "web ok, worker ok")
    ok, reason = healthcheck.check(web_port, stale(tmp_path / "alive", 300), max_age=120)
    assert not ok and "worker" in reason


def test_nothing_running_is_unhealthy(tmp_path: Path) -> None:
    ok, reason = healthcheck.check(closed_port(), tmp_path / "absent", max_age=120)
    assert not ok and reason == "neither the web server nor a worker is running"


def test_the_worker_marks_itself_alive(tmp_path: Path) -> None:
    alive = tmp_path / "alive"
    mark_alive(Settings(worker_alive_file=alive))
    assert alive.exists() and time.time() - alive.stat().st_mtime < 5
    mark_alive(Settings(worker_alive_file=None))  # outside the image: no file, no error
