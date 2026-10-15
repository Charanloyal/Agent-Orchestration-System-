import pytest
from pydantic import ValidationError

from app.contracts import (
    Plan,
    PlanPolicy,
    PlanPolicyViolation,
    artifact_digest,
    enforce_plan_policy,
)


def make_plan(**overrides: object) -> dict:
    plan: dict = {
        "plan_version": 1,
        "outline": [
            {
                "section_id": "summary",
                "title": "Summary",
                "purpose": "Answer the brief",
            },
            {
                "section_id": "pricing",
                "title": "Pricing",
                "purpose": "Compare public pricing",
            },
        ],
        "tasks": [
            {
                "task_id": "t1",
                "question": "What does vendor A charge?",
                "tools": ["web_search", "fetch_url"],
                "expected_evidence": "Vendor pricing page",
                "section_ids": ["pricing"],
            },
            {
                "task_id": "t2",
                "question": "What does vendor B charge?",
                "tools": ["web_search"],
                "expected_evidence": "Vendor pricing page",
                "section_ids": ["pricing"],
            },
            {
                "task_id": "t3",
                "question": "How do A and B compare?",
                "depends_on": ["t1", "t2"],
                "tools": ["web_search"],
                "expected_evidence": "Comparison of findings",
                "section_ids": ["summary"],
            },
        ],
        "source_strategy": "Vendor documentation first, then independent reviews.",
    }
    plan.update(overrides)
    return plan


POLICY = PlanPolicy(allowed_tools=frozenset({"web_search", "fetch_url"}), max_tasks=5)


def test_valid_plan_and_execution_levels() -> None:
    plan = Plan.model_validate(make_plan())
    assert plan.execution_order() == [["t1", "t2"], ["t3"]]
    enforce_plan_policy(plan, POLICY)


def test_rejects_cycle() -> None:
    data = make_plan()
    data["tasks"][0]["depends_on"] = ["t3"]
    with pytest.raises(ValidationError, match="dependency cycle"):
        Plan.model_validate(data)


def test_rejects_self_dependency() -> None:
    data = make_plan()
    data["tasks"][0]["depends_on"] = ["t1"]
    with pytest.raises(ValidationError, match="depends on itself"):
        Plan.model_validate(data)


def test_rejects_unknown_task_reference() -> None:
    data = make_plan()
    data["tasks"][2]["depends_on"] = ["t1", "t9"]
    with pytest.raises(ValidationError, match="unknown tasks"):
        Plan.model_validate(data)


def test_rejects_unknown_section_reference() -> None:
    data = make_plan()
    data["tasks"][0]["section_ids"] = ["nope"]
    with pytest.raises(ValidationError, match="unknown sections"):
        Plan.model_validate(data)


def test_rejects_duplicate_task_ids() -> None:
    data = make_plan()
    data["tasks"][1]["task_id"] = "t1"
    with pytest.raises(ValidationError, match="duplicate task_id"):
        Plan.model_validate(data)


def test_rejects_unknown_tool_name_at_schema_level() -> None:
    data = make_plan()
    data["tasks"][0]["tools"] = ["run_python"]
    with pytest.raises(ValidationError):
        Plan.model_validate(data)


def test_rejects_extra_fields_from_model_output() -> None:
    data = make_plan(grant_permissions=["admin"])
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        Plan.model_validate(data)


def test_policy_rejects_tool_outside_server_allowlist() -> None:
    data = make_plan()
    data["tasks"][1]["tools"] = ["search_uploads"]
    plan = Plan.model_validate(data)
    with pytest.raises(PlanPolicyViolation, match="disallowed tools"):
        enforce_plan_policy(plan, POLICY)


def test_policy_rejects_plan_over_task_limit() -> None:
    plan = Plan.model_validate(make_plan())
    with pytest.raises(PlanPolicyViolation, match="limit is 2"):
        enforce_plan_policy(plan, PlanPolicy(allowed_tools=POLICY.allowed_tools, max_tasks=2))


def test_long_dependency_chain_has_no_recursion_limit() -> None:
    tasks = [
        {
            "task_id": f"t{i}",
            "question": "q",
            "depends_on": [f"t{i - 1}"] if i else [],
            "tools": ["web_search"],
            "expected_evidence": "e",
            "section_ids": ["summary"],
        }
        for i in range(50)
    ]
    plan = Plan.model_validate(make_plan(tasks=tasks))
    assert len(plan.execution_order()) == 50


def test_digest_is_stable_and_detects_edits() -> None:
    data = make_plan()
    reordered = dict(reversed(list(data.items())))
    assert artifact_digest(Plan.model_validate(data)) == artifact_digest(Plan.model_validate(reordered))
    edited = make_plan(source_strategy="Something else entirely.")
    assert artifact_digest(Plan.model_validate(data)) != artifact_digest(Plan.model_validate(edited))
