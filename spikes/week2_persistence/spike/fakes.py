"""Deterministic fake model/search providers and bounded schema repair. No network calls."""

import json
from typing import TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

MAX_SCHEMA_REPAIRS = 1


class FakeModel:
    """Returns scripted raw outputs in order. Running out of script is a test bug."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        if not self._responses:
            raise RuntimeError("FakeModel script exhausted")
        self.prompts.append(prompt)
        return self._responses.pop(0)


class SchemaRepairExhausted(RuntimeError):
    def __init__(self, schema: str, attempts: int, error_count: int) -> None:
        super().__init__(f"{schema}: invalid output after {attempts} attempts ({error_count} errors)")
        self.schema = schema
        self.attempts = attempts
        self.error_count = error_count


def _summarize(exc: ValidationError) -> str:
    # Field locations and messages only; never echo model output or source text into logs.
    errors = exc.errors(include_input=False)[:5]
    return "; ".join(f"{'.'.join(map(str, e['loc'])) or '<root>'}: {e['msg']}" for e in errors)


def call_structured(
    model: FakeModel, schema: type[T], prompt: str, max_repairs: int = MAX_SCHEMA_REPAIRS
) -> tuple[T, int]:
    """Validate model output against `schema`, allowing at most `max_repairs` repair calls."""
    raw = model.complete(prompt)
    attempts = 0
    while True:
        attempts += 1
        try:
            return schema.model_validate_json(raw), attempts
        except ValidationError as exc:
            if attempts > max_repairs:
                raise SchemaRepairExhausted(schema.__name__, attempts, exc.error_count()) from None
            raw = model.complete(
                f"{prompt}\n\nYour previous output was invalid: {_summarize(exc)}. "
                "Return only valid JSON."
            )


FAKE_PLAN = {
    "plan_version": 1,
    "outline": [
        {"section_id": "summary", "title": "Summary", "purpose": "Answer the brief"},
        {"section_id": "findings", "title": "Findings", "purpose": "Evidence per question"},
    ],
    "tasks": [
        {"task_id": "t1", "question": "Option A capabilities", "tools": ["web_search"],
         "expected_evidence": "Vendor documentation", "section_ids": ["findings"]},
        {"task_id": "t2", "question": "Option B capabilities", "tools": ["web_search"],
         "expected_evidence": "Vendor documentation", "section_ids": ["findings"]},
        {"task_id": "t3", "question": "Comparison", "depends_on": ["t1", "t2"],
         "tools": ["web_search"], "expected_evidence": "Comparative sources",
         "section_ids": ["summary"]},
    ],
    "source_strategy": "Fake provider: deterministic synthetic passages only.",
}

INVALID_PLAN_OUTPUTS = ["Sure! Here is your plan.", json.dumps({"plan_version": 1, "tasks": []})]


def planner_model(mode: str) -> FakeModel:
    valid = json.dumps(FAKE_PLAN)
    if mode == "invalid_once":
        return FakeModel([INVALID_PLAN_OUTPUTS[0], valid])
    if mode == "invalid_always":
        return FakeModel(INVALID_PLAN_OUTPUTS)
    return FakeModel([valid])


def fake_search(task_id: str, question: str) -> list[str]:
    return [f"Synthetic passage {n} for {task_id}: {question}." for n in (1, 2)]


def writer_model(evidence_ids: list[str], report_version: int, plan_version: int) -> FakeModel:
    claims = [
        {"claim_id": f"c{i}", "kind": "fact", "text": f"Synthetic fact supported by {eid}.",
         "evidence_ids": [eid]}
        for i, eid in enumerate(sorted(evidence_ids), 1)
    ]
    claims.append(
        {"claim_id": "rec1", "kind": "recommendation", "text": "Pilot both options.", "evidence_ids": []}
    )
    draft = {
        "report_version": report_version,
        "plan_version": plan_version,
        "sections": [{"section_id": "findings", "title": "Findings", "claims": claims}],
    }
    return FakeModel([json.dumps(draft)])
