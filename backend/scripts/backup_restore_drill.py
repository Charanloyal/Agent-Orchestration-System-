"""Backup and restore drill (M14): python -m scripts.backup_restore_drill [--source-db aos_load].

Dumps a source database with pg_dump (custom format), restores it into a *fresh* database
named `aos_restore_drill` (dropped and recreated; the name is fixed so nothing else can be
overwritten), then verifies the copy:

- every application table (public schema) and checkpoint table (lg schema) has the same row count;
- `alembic_version` matches, and the application considers the restored schema current;
- the append-only audit trigger survived the restore;
- a sample of runs, reports and approvals is byte-identical (digest comparison).

Prints a JSON report with durations and sizes. The source is only read (pg_dump).
"""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1]
TARGET_DB = "aos_restore_drill"


def _env_file() -> dict[str, str]:
    path = BACKEND / ".env"
    if not path.exists():
        return {}
    return dict(
        line.strip().split("=", 1)
        for line in path.read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    )


def pg_bin(name: str) -> str:
    candidates = [
        os.environ.get("AOS_PG_BIN"),
        str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "postgresql-17" / "pgsql" / "bin"),
    ]
    for folder in candidates:
        if folder:
            exe = Path(folder) / (f"{name}.exe" if sys.platform == "win32" else name)
            if exe.exists():
                return str(exe)
    found = shutil.which(name)
    if not found:
        raise SystemExit(f"{name} not found; set AOS_PG_BIN to the PostgreSQL bin folder")
    return found


def with_db(url: str, name: str) -> str:
    return url.rsplit("/", 1)[0] + "/" + name


def counts(url: str) -> dict[str, int]:
    import psycopg

    with psycopg.connect(url) as conn:
        tables = conn.execute(
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_schema IN ('public', 'lg') AND table_type = 'BASE TABLE' ORDER BY 1, 2"
        ).fetchall()
        return {
            f"{schema}.{table}": int(conn.execute(f'SELECT count(*) FROM "{schema}"."{table}"').fetchone()[0])  # type: ignore[index]  # noqa: S608
            for schema, table in tables
        }


def fingerprints(url: str) -> dict[str, Any]:
    import psycopg

    with psycopg.connect(url) as conn:

        def one(sql: str) -> Any:
            row = conn.execute(sql).fetchone()
            return row[0] if row else None

        return {
            "alembic_version": one("SELECT string_agg(version_num, ',') FROM alembic_version"),
            "runs_md5": one("SELECT md5(string_agg(id::text || state, ',' ORDER BY id)) FROM runs"),
            "reports_md5": one(
                "SELECT md5(string_agg(run_id::text || version || digest, ',' ORDER BY run_id, version)) "
                "FROM report_versions"
            ),
            "approvals_md5": one(
                "SELECT md5(string_agg(id::text || artifact_digest || decision, ',' ORDER BY id)) "
                "FROM approvals"
            ),
            "audit_trigger_present": one(
                "SELECT count(*) FROM pg_trigger "
                "WHERE tgname = 'audit_events_append_only' AND NOT tgisinternal"
            )
            == 1,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.backup_restore_drill")
    parser.add_argument("--source-db", default="aos_load", help="database to back up (read-only)")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    base = os.environ.get("AOS_DATABASE_URL") or _env_file().get("AOS_DATABASE_URL")
    if not base:
        raise SystemExit("AOS_DATABASE_URL is needed to locate the server")
    if args.source_db == TARGET_DB:
        raise SystemExit("source and target must differ")
    source, target = with_db(base, args.source_db), with_db(base, TARGET_DB)

    import psycopg

    with psycopg.connect(with_db(base, "postgres"), autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{TARGET_DB}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{TARGET_DB}"')

    dump = Path(tempfile.mkdtemp(prefix="aos-backup-")) / f"{args.source_db}.dump"
    started = time.perf_counter()
    subprocess.run(  # noqa: S603
        [pg_bin("pg_dump"), "--format=custom", "--no-owner", "--file", str(dump), source], check=True
    )
    dump_seconds = round(time.perf_counter() - started, 2)
    started = time.perf_counter()
    subprocess.run(  # noqa: S603
        [pg_bin("pg_restore"), "--no-owner", "--exit-on-error", "--dbname", target, str(dump)], check=True
    )
    restore_seconds = round(time.perf_counter() - started, 2)

    before, after = counts(source), counts(target)
    mismatched = {
        t: (before.get(t), after.get(t))
        for t in sorted(set(before) | set(after))
        if before.get(t) != after.get(t)
    }
    fp_source, fp_target = fingerprints(source), fingerprints(target)

    os.environ["AOS_DATABASE_URL"] = target
    from app.db import schema_state
    from app.db.session import get_sessionmaker

    with get_sessionmaker()() as db:
        schema_current = schema_state.schema_is_current(db)

    report = {
        "at": datetime.now(UTC).isoformat(),
        "environment": {
            "os": platform.platform(),
            "pg_dump": subprocess.run(  # noqa: S603
                [pg_bin("pg_dump"), "--version"], capture_output=True, text=True, check=True
            ).stdout.strip(),
        },
        "source_db": args.source_db,
        "target_db": TARGET_DB,
        "dump_bytes": dump.stat().st_size,
        "dump_seconds": dump_seconds,
        "restore_seconds": restore_seconds,
        "tables_compared": len(before),
        "rows_total": sum(before.values()),
        "row_count_mismatches": mismatched,
        "fingerprints_equal": fp_source == fp_target,
        "fingerprints": fp_target,
        "restored_schema_current_for_app": schema_current,
        "verdict": "PASS" if not mismatched and fp_source == fp_target and schema_current else "FAIL",
    }
    dump.unlink()
    text = json.dumps(report, indent=2)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
