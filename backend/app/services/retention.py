"""Data lifecycle: user-requested deletion and retention sweeps (ADR 0018).

What a run deletion removes (one transaction, then stored objects):
- the brief, the run and, through ON DELETE CASCADE, its job, events, plan and report
  versions, approvals, sources, evidence, task results, tool executions, budget
  reservations, review findings and export records;
- its LangGraph checkpoints (schema `lg`, keyed by thread id = run id);
- exported Markdown files in the object store (after the commit).

What it never removes: audit events. They are append-only (database trigger) and record
the deletion itself, with ids and counts but no content.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.contracts.run_state import TERMINAL_STATES
from app.db.models import Brief, ReportExport, Run, RunJob, Upload
from app.errors import Conflict
from app.services.audit import audit
from app.storage import ObjectStore, get_object_store

log = logging.getLogger("aos.retention")

CHECKPOINT_TABLES = ("checkpoint_writes", "checkpoint_blobs", "checkpoints")


@dataclass
class Deletion:
    runs: int = 0
    uploads: int = 0
    objects: list[str] = field(default_factory=list)


def _delete_run_rows(db: Session, run: Run) -> list[str]:
    keys = list(db.scalars(select(ReportExport.object_key).where(ReportExport.run_id == run.id)))
    for table in CHECKPOINT_TABLES:
        db.execute(text(f"DELETE FROM lg.{table} WHERE thread_id = :t"), {"t": str(run.id)})  # noqa: S608
    db.execute(delete(Brief).where(Brief.id == run.brief_id))  # cascades to the run and its rows
    return keys


def delete_run(
    db: Session, store: ObjectStore, run_id: uuid.UUID, *, actor_user_id: uuid.UUID, role: str
) -> None:
    """User-requested deletion of a finished run. Active runs must be cancelled first, so a
    worker never has its run removed underneath it."""
    job = db.execute(select(RunJob).where(RunJob.run_id == run_id).with_for_update()).scalar_one_or_none()
    run = db.execute(select(Run).where(Run.id == run_id).with_for_update()).scalar_one()
    if run.state not in TERMINAL_STATES or (job is not None and job.state == "LEASED"):
        raise Conflict("Only finished runs can be deleted; cancel the run first")
    keys = _delete_run_rows(db, run)
    audit(
        db,
        "run.delete",
        actor_user_id=actor_user_id,
        workspace_id=run.workspace_id,
        target=str(run_id),
        details={"role": role, "state": run.state, "exports_removed": len(keys)},
    )
    db.commit()
    _remove_objects(store, keys)


def delete_upload(
    db: Session, store: ObjectStore, upload: Upload, *, actor_user_id: uuid.UUID | None
) -> None:
    key = upload.object_key
    workspace_id, upload_id = upload.workspace_id, upload.id
    db.delete(upload)
    audit(
        db,
        "upload.delete" if actor_user_id else "upload.retention_delete",
        actor_user_id=actor_user_id,
        workspace_id=workspace_id,
        target=str(upload_id),
    )
    db.commit()
    _remove_objects(store, [key])


def _remove_objects(store: ObjectStore, keys: list[str]) -> None:
    for key in keys:
        try:
            store.delete(key)
        except Exception:
            # The database no longer references it; an orphaned file is logged for cleanup.
            log.exception("could not delete stored object", extra={"object_key": key})


def sweep(sm: sessionmaker[Session], *, run_days: int, upload_days: int, batch: int = 20) -> Deletion:
    """Delete finished runs and uploads older than the configured retention periods. Runs are
    aged by their last update, so a run that is still being looked at is not removed."""
    result = Deletion()
    store = get_object_store()
    if run_days > 0:
        with sm() as db:
            cutoff = db.scalar(select(func.now() - timedelta(days=run_days)))
            run_ids = list(
                db.scalars(
                    select(Run.id)
                    .where(Run.state.in_([s.value for s in TERMINAL_STATES]), Run.updated_at < cutoff)
                    .order_by(Run.updated_at)
                    .limit(batch)
                )
            )
        for run_id in run_ids:
            with sm() as db:
                run = db.execute(
                    select(Run).where(Run.id == run_id).with_for_update(skip_locked=True)
                ).scalar_one_or_none()
                if run is None:
                    continue
                keys = _delete_run_rows(db, run)
                audit(
                    db,
                    "run.retention_delete",
                    actor_user_id=None,
                    workspace_id=run.workspace_id,
                    target=str(run_id),
                    details={"retention_days": run_days, "state": run.state},
                )
                db.commit()
            _remove_objects(store, keys)
            result.runs += 1
    if upload_days > 0:
        with sm() as db:
            cutoff = db.scalar(select(func.now() - timedelta(days=upload_days)))
            uploads = list(
                db.scalars(
                    select(Upload).where(Upload.created_at < cutoff).order_by(Upload.created_at).limit(batch)
                )
            )
            for upload in uploads:
                delete_upload(db, store, upload, actor_user_id=None)
                result.uploads += 1
    return result
