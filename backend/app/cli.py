"""Operator commands.

python -m app.cli seed-demo     create demo workspaces and dev-issuer users (dev/test only)
"""

import argparse
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Membership, Role, User, Workspace
from app.db.session import get_sessionmaker

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
    db.commit()
    return workspaces


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed-demo", help="create demo workspaces and users (dev/test only)")
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
