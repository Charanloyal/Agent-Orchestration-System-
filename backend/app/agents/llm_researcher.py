"""LLM-backed researcher (FR-05/06 support, threat model T1).

Search and collection are deterministic code driven by the approved task; the model only
*reads* the collected passages and reports findings. It has no tools and no way to request
URLs or actions, so instructions embedded in retrieved pages can at most distort a finding,
which the citation checks, the reviewer, and the human approval then catch.
"""

import json

from app.agents.base import AgentCall, EvidenceRef, ResearchTools
from app.agents.prompts import RESEARCHER_SYSTEM, RESEARCHER_USER, RESEARCHER_VERSION
from app.agents.structured import call_structured, schema_for
from app.contracts import Brief, PlanTask, ResearcherOutput
from app.providers.llm import LlmProvider
from app.providers.search import SearchHit

MAX_PASSAGES = 8
MAX_HITS_PER_SEARCH = 3


def format_passages(refs: list[EvidenceRef], titles: dict[str, str]) -> str:
    """Delimit untrusted text so it cannot impersonate the prompt structure."""
    blocks = []
    for ref in refs:
        text = ref.text.replace("</passage", "</ passage").replace("<passage", "< passage")
        title = titles.get(ref.source_id, ref.source_id).replace('"', "'")
        blocks.append(f'<passage id="{ref.evidence_id}" source="{title}">\n{text}\n</passage>')
    return "\n\n".join(blocks)


class LlmResearcher:
    def __init__(self, llm: LlmProvider, *, max_output_tokens: int = 1500) -> None:
        self.llm = llm
        self.max_output_tokens = max_output_tokens

    def research(self, brief: Brief, task: PlanTask, tools: ResearchTools) -> AgentCall[ResearcherOutput]:
        hits: list[SearchHit] = []
        if "web_search" in task.tools:
            hits += tools.search(task.question)[:MAX_HITS_PER_SEARCH]
        if "search_uploads" in task.tools:
            hits += tools.search_uploads(task.question)[:MAX_HITS_PER_SEARCH]
        refs: list[EvidenceRef] = []
        titles: dict[str, str] = {}
        for hit in hits:
            collected = tools.collect(hit)
            for ref in collected:
                titles.setdefault(ref.source_id, hit.title)
            refs += collected
        refs = list({r.evidence_id: r for r in refs}.values())[:MAX_PASSAGES]
        if not refs:
            # Nothing to read: no model call, no cost; the gap is reported honestly.
            return AgentCall(
                ResearcherOutput(task_id=task.task_id, unresolved_questions=[task.question]),
                0,
                generation={"provider": "none", "reason": "no evidence collected"},
            )

        allowed = {r.evidence_id for r in refs}

        def server_checks(output: ResearcherOutput) -> None:
            if output.task_id != task.task_id:
                raise ValueError(f"task_id must be {task.task_id!r}")
            if unknown := sorted(set(output.evidence_ids) - allowed):
                raise ValueError(f"evidence_ids not among the provided passages: {unknown[:5]}")

        call = call_structured(
            self.llm,
            ResearcherOutput,
            step="research",
            system=RESEARCHER_SYSTEM,
            user=RESEARCHER_USER.format(
                task_json=json.dumps(task.model_dump(mode="json"), indent=2),
                topic=brief.topic,
                passages=format_passages(refs, titles),
                schema=schema_for(ResearcherOutput),
            ),
            max_output_tokens=self.max_output_tokens,
            validate=server_checks,
        )
        return AgentCall(
            call.output,
            call.attempts,
            generation={
                "provider": self.llm.name,
                "model": self.llm.model,
                "prompt_version": RESEARCHER_VERSION,
                "attempts": call.attempts,
                "input_tokens": sum(u.input_tokens for u in call.usage),
                "output_tokens": sum(u.output_tokens for u in call.usage),
            },
            usage=tuple(call.usage),
        )
