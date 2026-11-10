"""Operator commands.

python -m app.cli seed-demo [--sample-run]   demo workspaces, dev-issuer users and an
                                             example run awaiting plan approval (dev/test only)
"""

import argparse
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Membership, Role, User, Workspace
from app.db.session import get_sessionmaker
from app.services.access import grant_access

DEMO_WORKSPACE = "Demo Research Team"
OTHER_WORKSPACE = "Other Team"

# Subjects match devtools/dev_oidc.DEFAULT_USERS.
DEMO_USERS = [
    ("dev-alice", "alice@example.test", "Alice Analyst", DEMO_WORKSPACE, Role.ANALYST),
    ("dev-bob", "bob@example.test", "Bob Reviewer", DEMO_WORKSPACE, Role.REVIEWER),
    ("dev-carol", "carol@example.test", "Carol Admin", DEMO_WORKSPACE, Role.ADMIN),
    (
        "dev-mallory",
        "mallory@example.test",
        "Mallory Outsider",
        OTHER_WORKSPACE,
        Role.ADMIN,
    ),
]


def seed_demo(db: Session, issuer: str) -> dict[str, Workspace]:
    workspaces: dict[str, Workspace] = {}
    for name in (DEMO_WORKSPACE, OTHER_WORKSPACE):
        workspace = db.scalar(select(Workspace).where(Workspace.name == name))
        if workspace is None:
            workspace = Workspace(name=name)
            db.add(workspace)
            db.flush()
        workspaces[name] = workspace
    for subject, email, display_name, workspace_name, role in DEMO_USERS:
        user = db.scalar(select(User).where(User.oidc_issuer == issuer, User.oidc_subject == subject))
        if user is None:
            user = User(
                oidc_issuer=issuer,
                oidc_subject=subject,
                email=email,
                display_name=display_name,
            )
            db.add(user)
            db.flush()
        workspace = workspaces[workspace_name]
        if db.get(Membership, (workspace.id, user.id)) is None:
            db.add(Membership(workspace_id=workspace.id, user_id=user.id, role=role))
        # Seeded people may sign in whatever the signup mode. dev-dana and dev-erin are
        # deliberately not seeded: they exercise the invitation and access-request flows.
        grant_access(db, email, source="seed", added_by=None, note="Demo user")
    db.commit()
    return workspaces


def seed_sample_run(db: Session, issuer: str, workspace: Workspace) -> str:
    """Submit the example brief as Alice and run the planner, so the demo opens on a plan
    waiting for approval. Uses the deterministic fake agents (labelled in the UI)."""
    import json
    import uuid as _uuid
    from pathlib import Path

    from app.auth.deps import Principal
    from app.contracts import Brief
    from app.services.runs import create_run
    from app.workers.checkpointer import setup_checkpointer
    from app.workers.runner import process_one

    settings = get_settings()
    alice = db.scalar(select(User).where(User.oidc_issuer == issuer, User.oidc_subject == "dev-alice"))
    assert alice is not None
    brief = Brief.model_validate(json.loads((Path(__file__).parent / "demo_brief.json").read_text("utf-8")))
    principal = Principal(alice.id, _uuid.uuid4(), "seed", alice.email, alice.display_name)
    created = create_run(
        db,
        principal,
        workspace_id=workspace.id,
        brief=brief,
        idempotency_key="demo-sample-run-v1",
        settings=settings,
    )
    if created.created:
        setup_checkpointer(settings)
        process_one(settings.model_copy(update={"agent_mode": "fake"}), run_id=created.run.id)
    return str(created.run.id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    seed = sub.add_parser("seed-demo", help="create demo workspaces and users (dev/test only)")
    seed.add_argument(
        "--sample-run",
        action="store_true",
        help="also submit app/demo_brief.json as Alice and plan it (idempotent)",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    if args.command == "seed-demo":
        if settings.env == "prod":
            print("seed-demo is disabled in prod", file=sys.stderr)
            return 2
        with get_sessionmaker()() as db:
            workspaces = seed_demo(db, settings.oidc_issuer)
            for name, workspace in workspaces.items():
                print(f"{name}: {workspace.id}")
            if args.sample_run:
                run_id = seed_sample_run(db, settings.oidc_issuer, workspaces[DEMO_WORKSPACE])
                print(f"Sample run (awaiting plan approval): {settings.public_url}/runs/{run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
