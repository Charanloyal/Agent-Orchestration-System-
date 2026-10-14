"""Planner output contract and server-side plan policy (FR-03)."""

from typing import Literal

from pydantic import Field, model_validator

from app.contracts.common import Identifier, LongText, ShortText, StrictModel, find_duplicates

ToolName = Literal["web_search", "fetch_url", "search_uploads"]


class OutlineSection(StrictModel):
    section_id: Identifier
    title: ShortText
    purpose: ShortText


class PlanTask(StrictModel):
    task_id: Identifier
    question: ShortText
    depends_on: list[Identifier] = Field(default_factory=list, max_length=12)
    tools: list[ToolName] = Field(min_length=1, max_length=3)
    expected_evidence: ShortText
    section_ids: list[Identifier] = Field(min_length=1, max_length=12)


class Plan(StrictModel):
    plan_version: int = Field(ge=1)
    tasks: list[PlanTask] = Field(min_length=1, max_length=50)
    outline: list[OutlineSection] = Field(min_length=1, max_length=20)
    source_strategy: LongText
    assumptions: list[ShortText] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _structurally_valid(self) -> "Plan":
        task_ids = [t.task_id for t in self.tasks]
        if duplicates := find_duplicates(task_ids):
            raise ValueError(f"duplicate task_id: {duplicates}")
        section_ids = [s.section_id for s in self.outline]
        if duplicates := find_duplicates(section_ids):
            raise ValueError(f"duplicate section_id: {duplicates}")

        known_tasks = set(task_ids)
        known_sections = set(section_ids)
        for task in self.tasks:
            if task.task_id in task.depends_on:
                raise ValueError(f"task {task.task_id!r} depends on itself")
            if unknown := sorted(set(task.depends_on) - known_tasks):
                raise ValueError(f"task {task.task_id!r} depends on unknown tasks: {unknown}")
            if unknown := sorted(set(task.section_ids) - known_sections):
                raise ValueError(f"task {task.task_id!r} references unknown sections: {unknown}")

        if cycle := _find_cycle({t.task_id: list(t.depends_on) for t in self.tasks}):
            raise ValueError(f"dependency cycle: {' -> '.join(cycle)}")
        return self

    def execution_order(self) -> list[list[str]]:
        """Group task IDs into dependency levels; tasks in one level may run in parallel."""
        remaining = {t.task_id: set(t.depends_on) for t in self.tasks}
        levels: list[list[str]] = []
        done: set[str] = set()
        while remaining:
            ready = sorted(tid for tid, deps in remaining.items() if deps <= done)
            levels.append(ready)
            done.update(ready)
            for tid in ready:
                del remaining[tid]
        return levels


def _find_cycle(graph: dict[str, list[str]]) -> list[str] | None:
    """Return one dependency cycle as a path, or None. Iterative DFS (no recursion limit)."""
    state: dict[str, int] = {}  # 1 = on current path, 2 = finished
    for start in sorted(graph):
        if start in state:
            continue
        path: list[str] = []
        stack: list[tuple[str, int]] = [(start, 0)]
        while stack:
            node, index = stack.pop()
            if index == 0:
                state[node] = 1
                path.append(node)
            deps = graph[node]
            if index < len(deps):
                stack.append((node, index + 1))
                dep = deps[index]
                if state.get(dep) == 1:
                    return path[path.index(dep) :] + [dep]
                if dep not in state:
                    stack.append((dep, 0))
            else:
                state[node] = 2
                path.pop()
    return None


class PlanPolicy(StrictModel):
    """Server-owned limits. Comes from workspace configuration, never from model output."""

    allowed_tools: frozenset[ToolName]
    max_tasks: int = Field(ge=1, le=50)


class PlanPolicyViolation(ValueError):
    def __init__(self, violations: list[str]) -> None:
        super().__init__("; ".join(violations))
        self.violations = violations


def enforce_plan_policy(plan: Plan, policy: PlanPolicy) -> None:
    """Reject plans that exceed server limits. The planner cannot expand the tool allowlist."""
    violations: list[str] = []
    if len(plan.tasks) > policy.max_tasks:
        violations.append(f"plan has {len(plan.tasks)} tasks; limit is {policy.max_tasks}")
    for task in plan.tasks:
        if disallowed := sorted(set(task.tools) - policy.allowed_tools):
            violations.append(f"task {task.task_id!r} requests disallowed tools: {disallowed}")
    if violations:
        raise PlanPolicyViolation(violations)
