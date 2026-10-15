"""Schema-validated model calls with exactly one bounded repair attempt (non-negotiable #4).

The model's raw output is never trusted: it is parsed and validated against the Pydantic
contract. On failure the model gets one repair turn listing only field locations and
messages (never echoing its own output or any source text). Persistent invalid output becomes
a visible StepFailed; it is not retried by the worker.
"""

import json
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from app.providers.llm import LlmProvider, LlmUsage
from app.workflow.errors import StepFailed

MAX_REPAIRS = 1


@dataclass(frozen=True)
class StructuredCall[T: BaseModel]:
    output: T
    attempts: int
    usage: list[LlmUsage] = field(default_factory=list)


def _extract_json(text: str) -> str:
    """Tolerate code fences or leading prose some providers add even in JSON mode."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        stripped = stripped[stripped.find("{") :] if "{" in stripped else stripped
    start, end = stripped.find("{"), stripped.rfind("}")
    return stripped[start : end + 1] if start != -1 and end > start else stripped


def _summarize(error: ValidationError | ValueError) -> str:
    if isinstance(error, ValidationError):
        parts = [
            f"{'.'.join(str(p) for p in e['loc']) or '<root>'}: {e['msg']}"
            for e in error.errors(include_input=False)[:8]
        ]
        return "; ".join(parts)
    return "the output was not a single valid JSON object"


def schema_for(model: type[BaseModel]) -> str:
    return json.dumps(model.model_json_schema(), separators=(",", ":"))


def call_structured[T: BaseModel](
    llm: LlmProvider,
    schema: type[T],
    *,
    step: str,
    system: str,
    user: str,
    max_output_tokens: int,
    validate: Any = None,
) -> StructuredCall[T]:
    """Call the model and return a validated `schema` instance.

    `validate` may apply extra server-side checks (raising ValueError) that also qualify for
    the single repair, e.g. citations that must resolve to known evidence."""
    usage: list[LlmUsage] = []
    prompt = user
    last_error = "unknown"
    for attempt in range(1, MAX_REPAIRS + 2):
        result = llm.complete(
            system=system, user=prompt, json_output=True, max_output_tokens=max_output_tokens
        )
        usage.append(result.usage)
        try:
            parsed = schema.model_validate_json(_extract_json(result.text))
            if validate is not None:
                validate(parsed)
            return StructuredCall(parsed, attempt, usage)
        except (ValidationError, ValueError) as error:
            last_error = _summarize(error) if isinstance(error, ValidationError) else str(error)[:500]
            prompt = (
                f"{user}\n\nYour previous answer was rejected by the validator: {last_error}\n"
                "Reply again with only a corrected JSON object that satisfies the schema."
            )
    raise StepFailed(step, f"invalid model output after {MAX_REPAIRS + 1} attempts ({last_error[:200]})")
