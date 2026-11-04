"""Load, concurrency and recovery test (M14): python -m scripts.loadtest [options].

Runs the real system as separate OS processes against an isolated database (`aos_load`,
dropped and recreated; the name must start with `aos_load`, so a real database can never be
targeted):

  A. concurrent workflows: N runs submitted at once and driven through both human gates by
     API clients (simulated humans that approve immediately);
  B. API latency: C concurrent clients reading metadata endpoints for D seconds;
  C. mixed: phase B's readers while another N runs execute;
  D. recovery: a worker killed abruptly mid-research (fault injection) and a healthy worker
     taking over; plus a graceful worker shutdown.

Measures latency percentiles, error rates, workflow completion time (automated time only,
human approval waits excluded), database connections, process memory, recovery time, and
checks integrity (no duplicate reports, budgets and tool limits held, no cross-workspace
reads). Fake agents and fake search only: this measures the platform, not model latency.
"""

import argparse
import asyncio
import json
import os
import platform
import signal
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1]
API_PORT = 8300
SAMPLE_BRIEF = json.loads((BACKEND.parent / "eval" / "briefs" / "dev" / "dev-01.json").read_text("utf-8"))[
    "brief"
]


def _env_file() -> dict[str, str]:
    path = BACKEND / ".env"
    if not path.exists():
        return {}
    return dict(
        line.strip().split("=", 1)
        for line in path.read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    )


def load_database_url() -> str:
    url = os.environ.get("AOS_LOAD_DATABASE_URL") or _env_file().get("AOS_LOAD_DATABASE_URL")
    if not url:
        base = os.environ.get("AOS_DATABASE_URL") or _env_file().get("AOS_DATABASE_URL")
        if not base:
            raise SystemExit("Set AOS_LOAD_DATABASE_URL (or AOS_DATABASE_URL to derive it)")
        url = base.rsplit("/", 1)[0] + "/aos_load"
    if not url.rsplit("/", 1)[1].split("?")[0].startswith("aos_load"):
        raise SystemExit("Refusing: the load-test database name must start with 'aos_load'")
    return url


def recreate_database(url: str) -> None:
    import psycopg

    name = url.rsplit("/", 1)[1].split("?")[0]
    admin = url.rsplit("/", 1)[0] + "/postgres"
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{name}"')


def rss_mb(pid: int) -> float | None:
    """Resident memory of a process and its direct children (on Windows the venv python.exe
    is a launcher whose child is the real interpreter), without extra dependencies."""
    try:
        if sys.platform == "win32":
            out = subprocess.run(  # noqa: S603
                [  # noqa: S607
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid} or ParentProcessId={pid}'"
                    " | Measure-Object WorkingSetSize -Sum).Sum",
                ],
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip()
            return round(int(out) / 1024 / 1024, 1) if out.isdigit() else None
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return round(int(line.split()[1]) / 1024, 1)
    except Exception:
        return None
    return None


class ConnectionSampler(threading.Thread):
    """Samples pg_stat_activity for the load database while a phase runs."""

    def __init__(self, url: str) -> None:
        super().__init__(daemon=True)
        self.url, self.peak, self.samples, self.stop = url, 0, [], threading.Event()

    def run(self) -> None:
        import psycopg

        name = self.url.rsplit("/", 1)[1].split("?")[0]
        with psycopg.connect(self.url, autocommit=True) as conn:
            while not self.stop.wait(0.5):
                n = conn.execute(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname = %s", (name,)
                ).fetchone()
                count = int(n[0]) if n else 0
                self.samples.append(count)
                self.peak = max(self.peak, count)

    def result(self) -> dict[str, Any]:
        self.stop.set()
        self.join(timeout=2)
        return {"peak": self.peak, "mean": round(statistics.fmean(self.samples), 1) if self.samples else None}


@dataclass
class Actor:
    name: str
    cookie: str
    csrf: str
    workspace_id: str


@dataclass
class World:
    analysts: list[Actor]
    reviewer: Actor
    outsider: Actor


def seed(url: str, analysts: int) -> World:
    """Users, memberships and sessions created directly (no identity provider needed)."""
    from app.auth.sessions import create_session
    from app.config import get_settings
    from app.db.models import Membership, Role, User, Workspace
    from app.db.session import get_sessionmaker

    settings = get_settings()
    with get_sessionmaker()() as db:
        home, other = Workspace(name="Load team"), Workspace(name="Other team")
        db.add_all([home, other])
        db.flush()

        def actor(label: str, workspace: Workspace, role: Role) -> Actor:
            user = User(
                oidc_issuer="urn:aos:load",
                oidc_subject=f"{label}-{uuid.uuid4().hex[:6]}",
                email=None,
                display_name=label,
            )
            db.add(user)
            db.flush()
            db.add(Membership(workspace_id=workspace.id, user_id=user.id, role=role))
            raw, session = create_session(db, user.id, settings)
            return Actor(label, raw, session.csrf_token, str(workspace.id))

        world = World(
            analysts=[actor(f"analyst-{i}", home, Role.ANALYST) for i in range(analysts)],
            reviewer=actor("reviewer", home, Role.REVIEWER),
            outsider=actor("outsider", other, Role.ADMIN),
        )
        db.commit()
    return world


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, max(0, round(q * len(ordered)) - 1))], 2)


def latency_summary(samples: list[tuple[str, int, float]]) -> dict[str, Any]:
    by_endpoint: dict[str, list[float]] = defaultdict(list)
    errors = sum(1 for _, status, _ in samples if status >= 500 or status == 0)
    for endpoint, _, ms in samples:
        by_endpoint[endpoint].append(ms)
    every = [ms for _, _, ms in samples]
    return {
        "requests": len(samples),
        "errors_5xx_or_network": errors,
        "error_rate": round(errors / len(samples), 4) if samples else None,
        "latency_ms": {
            "p50": percentile(every, 0.5),
            "p95": percentile(every, 0.95),
            "p99": percentile(every, 0.99),
            "max": round(max(every), 1) if every else None,
        },
        "by_endpoint_p95_ms": {k: percentile(v, 0.95) for k, v in sorted(by_endpoint.items())},
        "status_counts": {str(k): v for k, v in sorted(Counter(status for _, status, _ in samples).items())},
    }


class Stack:
    def __init__(self, url: str, logdir: Path, lease_seconds: float) -> None:
        self.url, self.logdir, self.lease = url, logdir, lease_seconds
        self.api: subprocess.Popen[bytes] | None = None
        self.workers: dict[str, subprocess.Popen[bytes]] = {}

    def env(self, **extra: str) -> dict[str, str]:
        env = {
            **os.environ,
            "AOS_DATABASE_URL": self.url,
            "AOS_ENV": "dev",
            "AOS_LOG_LEVEL": "WARNING",
            "AOS_LOG_JSON": "true",
            "AOS_PUBLIC_URL": f"http://127.0.0.1:{API_PORT}",
            "AOS_WORKER_LEASE_SECONDS": str(self.lease),
            "AOS_WORKER_HEARTBEAT_SECONDS": str(max(1.0, self.lease / 3)),
            "AOS_WORKER_POLL_SECONDS": "0.2",
            "AOS_SSE_POLL_SECONDS": "0.5",
            "AOS_OBJECT_STORE_DIR": str(self.logdir / "objects"),
        }
        env.pop("AOS_CRASH_AT", None)
        env.update(extra)
        return env

    def _spawn(self, args: list[str], log: str, **extra: str) -> subprocess.Popen[bytes]:
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
        handle = (self.logdir / log).open("ab")
        return subprocess.Popen(  # noqa: S603
            [sys.executable, *args],
            cwd=BACKEND,
            env=self.env(**extra),
            stdout=handle,
            stderr=subprocess.STDOUT,
            creationflags=flags,
        )

    def start_api(self) -> None:
        self.api = self._spawn(
            [
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(API_PORT),
                "--log-level",
                "warning",
            ],
            "api.log",
        )

    def start_worker(self, worker_id: str, **extra: str) -> subprocess.Popen[bytes]:
        proc = self._spawn(
            ["-m", "app.workers.runner", "--worker-id", worker_id], f"{worker_id}.log", **extra
        )
        self.workers[worker_id] = proc
        return proc

    def stop_worker_gracefully(self, worker_id: str, timeout: float = 60) -> float:
        proc = self.workers.pop(worker_id)
        started = time.perf_counter()
        if sys.platform == "win32":
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=timeout)
        return round(time.perf_counter() - started, 2)

    def stop_all(self) -> None:
        for proc in [*self.workers.values(), *([self.api] if self.api else [])]:
            if proc.poll() is None:
                proc.kill()
        self.workers.clear()


async def wait_ready(base: str, timeout: float = 60) -> None:
    import httpx

    deadline = time.monotonic() + timeout
    async with httpx.AsyncClient(trust_env=False, timeout=5) as client:
        while time.monotonic() < deadline:
            try:
                if (await client.get(f"{base}/readyz")).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.5)
    raise RuntimeError("API did not become ready")


def client_for(base: str, actor: Actor) -> Any:
    import httpx

    return httpx.AsyncClient(
        base_url=base,
        cookies={"aos_session": actor.cookie},
        trust_env=False,
        timeout=30,
        headers={"X-CSRF-Token": actor.csrf},
    )


@dataclass
class RunTiming:
    run_id: str
    created: float
    plan_ready: float | None = None
    plan_approved: float | None = None
    report_ready: float | None = None
    report_approved: float | None = None
    done: float | None = None
    final_state: str | None = None
    errors: list[str] = field(default_factory=list)

    def automated_seconds(self) -> float | None:
        if None in (self.plan_ready, self.plan_approved, self.report_ready, self.report_approved, self.done):
            return None
        return round(
            (self.plan_ready - self.created)
            + (self.report_ready - self.plan_approved)  # type: ignore[operator]
            + (self.done - self.report_approved),
            2,
        )  # type: ignore[operator]


async def drive_run(base: str, analyst: Actor, reviewer: Actor, label: str, timeout: float) -> RunTiming:
    async with client_for(base, analyst) as a, client_for(base, reviewer) as r:
        brief = {**SAMPLE_BRIEF, "topic": f"{SAMPLE_BRIEF['topic']} ({label})"}
        created = await a.post(
            "/api/v1/runs",
            json={"workspace_id": analyst.workspace_id, "brief": brief},
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
        if created.status_code != 201:
            timing = RunTiming("-", time.perf_counter())
            timing.errors.append(f"create {created.status_code}")
            return timing
        timing = RunTiming(created.json()["id"], time.perf_counter())
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            detail = (await a.get(f"/api/v1/runs/{timing.run_id}")).json()
            state, pending = detail["state"], detail["pending_decision"]
            now = time.perf_counter()
            if state == "AWAITING_PLAN_APPROVAL" and pending and timing.plan_approved is None:
                timing.plan_ready = now
                body = {"version": pending["version"], "digest": pending["digest"], "decision": "approve"}
                resp = await a.post(f"/api/v1/runs/{timing.run_id}/plan-decisions", json=body)
                if resp.status_code != 201:
                    timing.errors.append(f"plan decision {resp.status_code}")
                timing.plan_approved = time.perf_counter()
            elif state == "AWAITING_REPORT_APPROVAL" and pending and timing.report_approved is None:
                timing.report_ready = now
                body = {"version": pending["version"], "digest": pending["digest"], "decision": "approve"}
                resp = await r.post(f"/api/v1/reports/{timing.run_id}/decisions", json=body)
                if resp.status_code != 201:
                    timing.errors.append(f"report decision {resp.status_code}")
                timing.report_approved = time.perf_counter()
            elif state in ("SUCCEEDED", "FAILED", "NEEDS_ATTENTION", "CANCELLED", "EXPIRED"):
                timing.done, timing.final_state = now, state
                return timing
            await asyncio.sleep(0.2)
        timing.errors.append("timeout")
        return timing


async def readers(
    base: str, actors: list[Actor], run_ids: list[str], clients: int, duration: float
) -> list[tuple[str, int, float]]:
    samples: list[tuple[str, int, float]] = []
    deadline = time.monotonic() + duration

    async def one(index: int) -> None:
        actor = actors[index % len(actors)]
        endpoints = [
            ("GET /auth/me", "/api/v1/auth/me"),
            ("GET /runs (list)", f"/api/v1/runs?workspace_id={actor.workspace_id}"),
        ]
        for run_id in run_ids[:3]:
            endpoints += [
                ("GET /runs/{id}", f"/api/v1/runs/{run_id}"),
                ("GET /runs/{id}/timeline", f"/api/v1/runs/{run_id}/timeline"),
                ("GET /runs/{id}/evidence", f"/api/v1/runs/{run_id}/evidence"),
            ]
        async with client_for(base, actor) as client:
            i = index
            while time.monotonic() < deadline:
                name, path = endpoints[i % len(endpoints)]
                i += 1
                started = time.perf_counter()
                try:
                    status = (await client.get(path)).status_code
                except Exception:
                    status = 0
                samples.append((name, status, (time.perf_counter() - started) * 1000))

    await asyncio.gather(*(one(i) for i in range(clients)))
    return samples


def integrity(url: str, run_ids: list[str]) -> dict[str, Any]:
    import psycopg

    with psycopg.connect(url) as conn:

        def scalar(sql: str, *args: Any) -> Any:
            row = conn.execute(sql, args).fetchone()
            return row[0] if row else None

        ids = [uuid.UUID(r) for r in run_ids if r != "-"]
        return {
            "runs_checked": len(ids),
            "runs_with_more_report_versions_than_review_rounds_allow": scalar(
                "SELECT count(*) FROM (SELECT run_id FROM report_versions WHERE run_id = ANY(%s) "
                "GROUP BY run_id HAVING count(*) > 2) x",
                ids,
            ),
            "duplicate_task_results": scalar(
                "SELECT count(*) - count(DISTINCT (run_id, task_id)) FROM task_results "
                "WHERE run_id = ANY(%s)",
                ids,
            ),
            "tool_calls_left_started": scalar(
                "SELECT count(*) FROM tool_executions WHERE run_id = ANY(%s) AND status = 'started'", ids
            ),
            "runs_over_tool_limit": scalar(
                "SELECT count(*) FROM (SELECT t.run_id FROM tool_executions t WHERE t.run_id = ANY(%s) "
                "GROUP BY t.run_id HAVING count(*) > 60) x",
                ids,
            ),
            "runs_over_budget": scalar(
                "SELECT count(*) FROM (SELECT run_id, sum(coalesce(actual_cost, estimated_cost)) s "
                "FROM budget_reservations WHERE run_id = ANY(%s) GROUP BY run_id) x WHERE s > 2.00",
                ids,
            ),
            "reservations_left_reserved": scalar(
                "SELECT count(*) FROM budget_reservations WHERE run_id = ANY(%s) AND status = 'reserved'", ids
            ),
        }


async def cross_workspace_probe(
    base: str, outsider: Actor, home_workspace: str, run_ids: list[str]
) -> dict[str, Any]:
    async with client_for(base, outsider) as client:
        listing = await client.get(f"/api/v1/runs?workspace_id={home_workspace}")
        detail = [await client.get(f"/api/v1/runs/{r}") for r in run_ids[:5]]
        evidence = [await client.get(f"/api/v1/runs/{r}/evidence") for r in run_ids[:5]]
        own = await client.get(f"/api/v1/runs?workspace_id={outsider.workspace_id}")
    return {
        "list_other_workspace_status": listing.status_code,
        "other_workspace_run_reads_not_404": sum(1 for r in [*detail, *evidence] if r.status_code != 404),
        "own_workspace_runs_visible": len(own.json()) if own.status_code == 200 else None,
    }


async def phase_workflows(base: str, world: World, runs: int, label: str, timeout: float) -> list[RunTiming]:
    return list(
        await asyncio.gather(
            *(
                drive_run(
                    base, world.analysts[i % len(world.analysts)], world.reviewer, f"{label}-{i}", timeout
                )
                for i in range(runs)
            )
        )
    )


def workflow_summary(timings: list[RunTiming]) -> dict[str, Any]:
    automated = [t.automated_seconds() for t in timings if t.automated_seconds() is not None]
    wall = [round(t.done - t.created, 2) for t in timings if t.done is not None]
    return {
        "runs": len(timings),
        "succeeded": sum(1 for t in timings if t.final_state == "SUCCEEDED"),
        "final_states": {
            str(k): v for k, v in sorted(Counter(t.final_state for t in timings).items(), key=str)
        },
        "errors": [e for t in timings for e in t.errors],
        "automated_seconds": {
            "median": round(statistics.median(automated), 2) if automated else None,
            "p95": percentile(automated, 0.95),
            "max": max(automated) if automated else None,
        },
        "wall_seconds_incl_simulated_approvals": {
            "median": round(statistics.median(wall), 2) if wall else None,
            "max": max(wall) if wall else None,
        },
    }


async def phase_recovery(base: str, url: str, stack: Stack, world: World, lease: float) -> dict[str, Any]:
    """Kill a worker mid-research (fault injection after the first task commits), then start
    a healthy worker and time the takeover and completion."""
    import psycopg

    for worker_id in list(stack.workers):
        stack.stop_worker_gracefully(worker_id)
    analyst, reviewer = world.analysts[0], world.reviewer
    async with client_for(base, analyst) as a:
        created = await a.post(
            "/api/v1/runs",
            json={"workspace_id": analyst.workspace_id, "brief": SAMPLE_BRIEF},
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
        run_id = created.json()["id"]
        stack.start_worker("planner-worker")
        while (await a.get(f"/api/v1/runs/{run_id}")).json()["state"] != "AWAITING_PLAN_APPROVAL":
            await asyncio.sleep(0.2)
        stack.stop_worker_gracefully("planner-worker")
        pending = (await a.get(f"/api/v1/runs/{run_id}")).json()["pending_decision"]
        await a.post(
            f"/api/v1/runs/{run_id}/plan-decisions",
            json={"version": pending["version"], "digest": pending["digest"], "decision": "approve"},
        )
    doomed = stack.start_worker("doomed-worker", AOS_CRASH_AT="after_task_commit")
    doomed.wait(timeout=120)
    crashed_at = time.perf_counter()
    stack.workers.pop("doomed-worker", None)
    with psycopg.connect(url) as conn:
        row = conn.execute(
            "SELECT fencing_token, state FROM run_jobs WHERE run_id = %s", (run_id,)
        ).fetchone()
        token_at_crash = row[0] if row else None
        tasks_at_crash = conn.execute(
            "SELECT count(*) FROM task_results WHERE run_id = %s", (run_id,)
        ).fetchone()
    stack.start_worker("rescue-worker")
    takeover = None
    deadline = time.monotonic() + lease * 4 + 30
    with psycopg.connect(url, autocommit=True) as conn:
        while time.monotonic() < deadline:
            row = conn.execute("SELECT fencing_token FROM run_jobs WHERE run_id = %s", (run_id,)).fetchone()
            if row and token_at_crash is not None and row[0] > token_at_crash:
                takeover = round(time.perf_counter() - crashed_at, 2)
                break
            time.sleep(0.1)
    timing = await drive_run_existing(base, analyst, reviewer, run_id, timeout=120)
    with psycopg.connect(url) as conn:
        tasks_after = conn.execute(
            "SELECT count(*) - count(DISTINCT task_id) FROM task_results WHERE run_id = %s", (run_id,)
        ).fetchone()
        abandoned = conn.execute(
            "SELECT count(*) FROM tool_executions WHERE run_id = %s AND status = 'abandoned'", (run_id,)
        ).fetchone()
    return {
        "lease_seconds": lease,
        "crash_point": "after_task_commit",
        "doomed_worker_exit_code": doomed.returncode,
        "tasks_committed_before_crash": tasks_at_crash[0] if tasks_at_crash else None,
        "seconds_from_crash_to_takeover": takeover,
        "seconds_from_crash_to_reviewable_draft": round(timing.report_ready - crashed_at, 2)
        if timing.report_ready
        else None,
        "final_state": timing.final_state,
        "duplicate_task_results": tasks_after[0] if tasks_after else None,
        "abandoned_tool_calls_recorded": abandoned[0] if abandoned else None,
    }


async def drive_run_existing(
    base: str, analyst: Actor, reviewer: Actor, run_id: str, timeout: float
) -> RunTiming:
    async with client_for(base, reviewer) as r, client_for(base, analyst) as a:
        timing = RunTiming(run_id, time.perf_counter())
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            detail = (await a.get(f"/api/v1/runs/{run_id}")).json()
            if detail["state"] == "AWAITING_REPORT_APPROVAL" and detail["pending_decision"]:
                timing.report_ready = time.perf_counter()
                p = detail["pending_decision"]
                await r.post(
                    f"/api/v1/reports/{run_id}/decisions",
                    json={"version": p["version"], "digest": p["digest"], "decision": "approve"},
                )
            elif detail["state"] in ("SUCCEEDED", "FAILED", "NEEDS_ATTENTION"):
                timing.final_state = detail["state"]
                return timing
            await asyncio.sleep(0.2)
        timing.errors.append("timeout")
        return timing


async def main_async(args: argparse.Namespace) -> dict[str, Any]:
    url = load_database_url()
    recreate_database(url)
    os.environ["AOS_DATABASE_URL"] = url
    os.environ.setdefault("AOS_LOG_LEVEL", "WARNING")
    from alembic import command
    from alembic.config import Config

    from app.config import get_settings
    from app.workers.checkpointer import setup_checkpointer

    command.upgrade(Config(str(BACKEND / "alembic.ini")), "head")
    setup_checkpointer(get_settings())
    world = seed(url, args.analysts)
    base = f"http://127.0.0.1:{API_PORT}"
    logdir = Path(tempfile.mkdtemp(prefix="aos-load-"))
    stack = Stack(url, logdir, args.lease_seconds)
    results: dict[str, Any] = {}
    try:
        stack.start_api()
        for i in range(args.workers):
            stack.start_worker(f"worker-{i + 1}")
        await wait_ready(base)

        sampler = ConnectionSampler(url)
        sampler.start()
        started = time.perf_counter()
        timings = await phase_workflows(base, world, args.runs, "A", args.run_timeout)
        results["A_concurrent_workflows"] = {
            **workflow_summary(timings),
            "phase_seconds": round(time.perf_counter() - started, 2),
            "db_connections": sampler.result(),
        }
        run_ids = [t.run_id for t in timings if t.run_id != "-"]

        sampler = ConnectionSampler(url)
        sampler.start()
        samples = await readers(base, [*world.analysts, world.reviewer], run_ids, args.clients, args.duration)
        results["B_read_latency"] = {
            **latency_summary(samples),
            "clients": args.clients,
            "seconds": args.duration,
            "requests_per_second": round(len(samples) / args.duration, 1),
            "db_connections": sampler.result(),
        }

        sampler = ConnectionSampler(url)
        sampler.start()
        reader_task = asyncio.create_task(
            readers(base, [*world.analysts, world.reviewer], run_ids, args.clients, args.duration)
        )
        mixed_timings = await phase_workflows(base, world, args.runs, "C", args.run_timeout)
        mixed_samples = await reader_task
        results["C_mixed"] = {
            "reads": latency_summary(mixed_samples),
            "workflows": workflow_summary(mixed_timings),
            "db_connections": sampler.result(),
        }
        run_ids += [t.run_id for t in mixed_timings if t.run_id != "-"]

        results["integrity"] = integrity(url, run_ids)
        results["cross_workspace"] = await cross_workspace_probe(
            base, world.outsider, world.analysts[0].workspace_id, run_ids
        )
        results["memory_mb_after_load"] = {
            "api": rss_mb(stack.api.pid) if stack.api else None,
            **{wid: rss_mb(p.pid) for wid, p in stack.workers.items()},
        }
        graceful = {wid: stack.stop_worker_gracefully(wid) for wid in list(stack.workers)}
        results["graceful_worker_shutdown_seconds"] = graceful
        results["D_recovery"] = await phase_recovery(base, url, stack, world, args.lease_seconds)
    finally:
        stack.stop_all()
    results["logs"] = str(logdir)
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.loadtest", description=__doc__.split("\n\n")[0])
    parser.add_argument("--clients", type=int, default=20)
    parser.add_argument("--duration", type=float, default=30.0, help="seconds per read phase")
    parser.add_argument("--runs", type=int, default=5, help="concurrent workflows per workflow phase")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--analysts", type=int, default=5)
    parser.add_argument("--lease-seconds", type=float, default=6.0)
    parser.add_argument("--run-timeout", type=float, default=180.0)
    parser.add_argument("--out", type=Path, default=None, help="write the JSON result here")
    args = parser.parse_args(argv)

    started = datetime.now(UTC)
    results = asyncio.run(main_async(args))
    report = {
        "started_at": started.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "environment": {
            "os": platform.platform(),
            "python": platform.python_version(),
            "cpu_count": os.cpu_count(),
            "machine": platform.machine(),
        },
        "parameters": {k: (str(v) if isinstance(v, Path) else v) for k, v in vars(args).items()},
        "agents": "deterministic fake agents and fake search (platform overhead only)",
        "results": results,
    }
    text = json.dumps(report, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
