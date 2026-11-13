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
from app.contracts import Brief, PlanTask, ResearcherOutput, ResearchFinding
from app.providers.llm import LlmProvider
from app.providers.search import SearchHit
from app.tools.chunking import sentences
from app.workflow.errors import StepFailed, TransientError

MAX_PASSAGES = 36
MAX_HITS_PER_SEARCH = 3
# A short uploaded document comes back whole (ADR 0031); keep all of it.
MAX_UPLOAD_HITS = 25


QUOTED_FINDINGS = 8


def quoted_findings(
    task: PlanTask, refs: list[EvidenceRef], titles: dict[str, str], *, reason: str, source: str
) -> AgentCall[ResearcherOutput]:
    """The task's result without a model (ADR 0032): one finding per passage, quoting the
    passage's first sentence and citing it. Nothing is paraphrased or invented, so every
    finding is supported by construction; the writer and reviewer then work as usual."""
    findings = []
    for ref in refs[:QUOTED_FINDINGS]:
        first = next(iter(sentences(" ".join(ref.text.split()))), "")[:400]
        if first:
            title = titles.get(ref.source_id, ref.source_id)
            findings.append(ResearchFinding(statement=f'{title}: "{first}"', evidence_ids=[ref.evidence_id]))
    output = ResearcherOutput(
        task_id=task.task_id,
        evidence_ids=sorted({f.evidence_ids[0] for f in findings}),
        findings=findings,
        unresolved_questions=[] if findings else [task.question],
    )
    return AgentCall(
        output,
        0,
        generation={
            "provider": "fake",
            "method": "quoted passages",
            "fallback_reason": reason[:300],
            "fallback_from": source,
        },
    )


def format_passages(refs: list[EvidenceRef], titles: dict[str, str]) -> str:
    """Delimit untrusted text so it cannot impersonate the prompt structure."""
    blocks = []
    for ref in refs:
        text = ref.text.replace("</passage", "</ passage").replace("<passage", "< passage")
        title = titles.get(ref.source_id, ref.source_id).replace('"', "'")
        blocks.append(f'<passage id="{ref.evidence_id}" source="{title}">\n{text}\n</passage>')
    return "\n\n".join(blocks)


class LlmResearcher:
    def __init__(self, llm: LlmProvider, *, max_output_tokens: int = 1500, fallback: bool = False) -> None:
        self.llm = llm
        self.max_output_tokens = max_output_tokens
        # When every model is unavailable, summarise the collected passages by quoting them
        # instead of failing the task (ADR 0032).
        self.fallback = fallback

    def research(self, brief: Brief, task: PlanTask, tools: ResearchTools) -> AgentCall[ResearcherOutput]:
        refs: list[EvidenceRef] = []
        titles: dict[str, str] = {}
        # A retry of this task reads the passages its earlier attempt already collected: no
        # second search or fetch, and no repeated "source collected" events (ADR 0032).
        earlier = getattr(tools, "collected", None)
        for ref, title in earlier() if callable(earlier) else []:
            refs.append(ref)
            titles.setdefault(ref.source_id, title)
        if not refs:
            hits: list[SearchHit] = []
            # Uploads first: a short document comes back whole and must not be cut by the limit.
            if "search_uploads" in task.tools:
                hits += tools.search_uploads(task.question)[:MAX_UPLOAD_HITS]
            if "web_search" in task.tools:
                hits += tools.search(task.question)[:MAX_HITS_PER_SEARCH]
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

        try:
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
        except (TransientError, StepFailed) as exc:
            if not self.fallback:
                raise
            return quoted_findings(
                task, refs, titles, reason=str(exc), source=f"{self.llm.name}/{self.llm.model}"
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
