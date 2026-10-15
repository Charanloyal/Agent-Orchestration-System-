"""Prompt-reading stand-ins for the writer and reviewer models, used by scripted LLM tests.

They answer from what is actually in the prompt (outline ids, passage ids and text), like a
cooperative model would, so tests exercise the real prompt construction and validation."""

import json
import re

PASSAGE = re.compile(r'<passage id="([^"]+)" source="[^"]*">\n(.*?)\n</passage>', re.DOTALL)


def is_writer(system: str) -> bool:
    return "report writer" in system


def is_reviewer(system: str) -> bool:
    return "reviewer of an evidence-backed" in system


def writer_reply(user: str, *, claim_text: str | None = None) -> str:
    """Quotes the first sentence of up to three passages as fact claims."""
    version, plan_version = map(
        int,
        re.search(r"Report version to produce: (\d+); plan version: (\d+)", user).groups(),  # type: ignore[union-attr]
    )
    outline = re.findall(r"^- ([a-z0-9][a-z0-9_-]*): ", user.split("Report outline", 1)[1], re.MULTILINE)
    claims = []
    for i, (evidence_id, text) in enumerate(PASSAGE.findall(user)[:3], 1):
        sentence = re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0][:300]
        claims.append(
            {
                "claim_id": f"c{i}",
                "kind": "fact",
                "text": claim_text or sentence,
                "evidence_ids": [evidence_id],
            }
        )
    if not claims:
        claims.append(
            {
                "claim_id": "c1",
                "kind": "unknown",
                "text": "No evidence answers the brief.",
                "evidence_ids": [],
            }
        )
    return json.dumps(
        {
            "report_version": version,
            "plan_version": plan_version,
            "sections": [{"section_id": outline[0], "title": "Findings", "claims": claims}],
        }
    )


def reviewer_reply(user: str, *, findings: list[dict[str, object]] | None = None) -> str:
    review_round, version = map(int, re.search(r"Review round: (\d+); report version: (\d+)", user).groups())  # type: ignore[union-attr]
    outcome = "revise" if findings else "pass"
    return json.dumps(
        {
            "report_version": version,
            "review_round": review_round,
            "outcome": outcome,
            "findings": findings or [],
        }
    )
