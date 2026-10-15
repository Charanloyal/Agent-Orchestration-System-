"""Role-based permissions. The single source of truth for who may do what in a workspace."""

from enum import StrEnum

from app.db.models import Role


class Action(StrEnum):
    WORKSPACE_READ = "workspace.read"
    MEMBERS_MANAGE = "members.manage"
    RUN_CREATE = "run.create"
    RUN_READ = "run.read"
    RUN_CANCEL = "run.cancel"
    RUN_RETRY = "run.retry"
    PLAN_DECIDE = "plan.decide"
    REPORT_DECIDE = "report.decide"
    UPLOAD_CREATE = "upload.create"
    USAGE_READ = "usage.read"
    DATA_DELETE = "data.delete"


_ANALYST = {
    Action.WORKSPACE_READ,
    Action.RUN_CREATE,
    Action.RUN_READ,
    Action.RUN_CANCEL,
    Action.RUN_RETRY,
    Action.PLAN_DECIDE,
    Action.UPLOAD_CREATE,
    Action.USAGE_READ,
}
# Reviewers inspect evidence and decide on reports; they cannot start or steer runs.
_REVIEWER = {Action.WORKSPACE_READ, Action.RUN_READ, Action.REPORT_DECIDE}

ROLE_PERMISSIONS: dict[str, frozenset[Action]] = {
    Role.ANALYST: frozenset(_ANALYST),
    Role.REVIEWER: frozenset(_REVIEWER),
    Role.ADMIN: frozenset(Action),
}


def is_allowed(role: str, action: Action) -> bool:
    return action in ROLE_PERMISSIONS.get(role, frozenset())
