"""app/serve.py: the single-process deployment used by render.free.yaml."""

import threading
from typing import Any

import pytest

from app import serve


class FakeProcess:
    """Exits on its own the first time (a crash), then runs until terminated."""

    started = 0

    def __init__(self, args: list[str]) -> None:
        assert args[1:] == ["-m", "app.workers.runner"]
        FakeProcess.started += 1
        self.crash = FakeProcess.started == 1
        self.done = threading.Event()
        self.terminated = False

    def wait(self, timeout: float | None = None) -> int:
        if self.crash:
            return 1
        self.done.wait(timeout)
        return 0

    def poll(self) -> int | None:
        return 0 if self.crash or self.done.is_set() else None

    def terminate(self) -> None:
        self.terminated = True
        self.done.set()

    def kill(self) -> None:
        self.done.set()


def test_supervisor_restarts_a_crashed_worker_and_stops_it_gracefully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeProcess.started = 0
    monkeypatch.setattr(serve.subprocess, "Popen", FakeProcess)
    supervisor = serve.WorkerSupervisor(restart_delay=0.01)
    supervisor.start()
    for _ in range(200):
        if FakeProcess.started == 2:
            break
        threading.Event().wait(0.01)
    assert FakeProcess.started == 2, "the crashed worker was restarted"
    running = supervisor.process
    supervisor.stop(timeout=1)
    assert isinstance(running, FakeProcess) and running.terminated
    supervisor.thread.join(timeout=1)
    assert not supervisor.thread.is_alive()


def test_serve_migrates_then_runs_uvicorn_without_trusting_proxy_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, Any] = {}
    monkeypatch.setattr(serve, "migrate", lambda: calls.setdefault("migrated", True))
    monkeypatch.setattr(serve.uvicorn, "run", lambda app, **kw: calls.update(app=app, **kw))
    monkeypatch.setenv("PORT", "10123")
    assert serve.main(["--migrate"]) == 0
    assert calls["migrated"] and calls["app"] == "app.main:app"
    # The app reads X-Forwarded-For itself, by trusted hop count (ADR 0025).
    assert calls["port"] == 10123 and calls["proxy_headers"] is False
    assert "forwarded_allow_ips" not in calls
    assert calls["host"] == "0.0.0.0"  # noqa: S104 - behind the platform load balancer
