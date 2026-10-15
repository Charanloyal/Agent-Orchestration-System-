"""Research tools bound to one run and task. Every external call is recorded before it is
made; evidence is persisted with deterministic IDs so re-execution is idempotent."""

import hashlib
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, update
from sqlalchemy.dialects.postgresql import insert

from app.agents.base import EvidenceRef
from app.db.models import EvidencePassage, Source, ToolExecution
from app.providers.search import SearchHit
from app.services.events import append_event
from app.tools.policy import domain_permitted, is_stale, source_id_for
from app.workflow.context import RunContext

PASSAGE_TARGET_CHARS = 1200
MAX_PASSAGES_PER_SOURCE = 8
MAX_SEARCH_RESULTS = 5


def _chunks(paragraph: str) -> list[str]:
    chunks = []
    while len(paragraph) > PASSAGE_TARGET_CHARS:
        cut = paragraph.rfind(" ", 0, PASSAGE_TARGET_CHARS)
        if cut < PASSAGE_TARGET_CHARS // 2:
            cut = PASSAGE_TARGET_CHARS
        chunks.append(paragraph[:cut].strip())
        paragraph = paragraph[cut:].strip()
    if paragraph:
        chunks.append(paragraph)
    return chunks


def split_passages(text: str) -> list[str]:
    """Paragraph-aware chunking: pack paragraphs (split if oversized) into passages of at most
    PASSAGE_TARGET_CHARS so each passage is a citable, reviewable unit."""
    passages: list[str] = []
    current = ""
    for paragraph in (p.strip() for p in text.replace("\r\n", "\n").split("\n\n")):
        for chunk in _chunks(paragraph):
            if current and len(current) + 1 + len(chunk) > PASSAGE_TARGET_CHARS:
                passages.append(current)
                current = chunk
            else:
                current = f"{current}\n{chunk}" if current else chunk
    if current:
        passages.append(current)
    return passages[:MAX_PASSAGES_PER_SOURCE]


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class RunResearchTools:
    def __init__(self, ctx: RunContext, task_id: str) -> None:
        self.ctx = ctx
        self.task_id = task_id
        self.policy = ctx.brief.source_policy

    def search(self, query: str) -> list[SearchHit]:
        execution_id = self._start("web_search")
        try:
            hits = self.ctx.search.search(
                query,
                max_results=MAX_SEARCH_RESULTS,
                allowed_domains=list(self.policy.allowed_domains),
                blocked_domains=list(self.policy.blocked_domains),
            )
        except Exception as exc:
            self._finish(execution_id, "failed", type(exc).__name__)
            raise
        self._finish(execution_id, "succeeded")
        # Enforce the source policy on results, whatever the provider claims to filter.
        permitted = [h for h in hits if domain_permitted(h.url, self.policy)]
        fresh = [h for h in permitted if not is_stale(h.published_on, self.policy)]
        if len(fresh) < len(hits):
            self.ctx.event(
                "search_results_filtered",
                {
                    "task_id": self.task_id,
                    "returned": len(hits),
                    "kept": len(fresh),
                    "blocked_by_domain_policy": len(hits) - len(permitted),
                    "stale": len(permitted) - len(fresh),
                },
            )
        return fresh

    def collect(self, hit: SearchHit) -> list[EvidenceRef]:
        if not domain_permitted(hit.url, self.policy):
            return []
        text = hit.content
        if text is None:
            return []  # fetching arrives with the safe fetcher (M5)
        source_id = source_id_for(hit.url)
        passages = split_passages(text)
        refs = [
            EvidenceRef("ev-" + _sha(f"{source_id}|{i}|{_sha(p)}")[:16], source_id, p)
            for i, p in enumerate(passages)
        ]
        with self.ctx.fenced() as session:
            session.execute(
                insert(Source)
                .values(
                    run_id=self.ctx.run_id,
                    source_id=source_id,
                    workspace_id=self.ctx.workspace_id,
                    kind="web",
                    url=hit.url,
                    title=hit.title[:500],
                    retrieved_at=datetime.now(UTC),
                    published_on=hit.published_on,
                    fetch_status="fetched",
                    content_sha256=_sha(text),
                )
                .on_conflict_do_nothing()
            )
            for index, ref in enumerate(refs, 1):
                session.execute(
                    insert(EvidencePassage)
                    .values(
                        run_id=self.ctx.run_id,
                        evidence_id=ref.evidence_id,
                        workspace_id=self.ctx.workspace_id,
                        source_id=source_id,
                        task_id=self.task_id,
                        locator=f"passage {index}",
                        text=ref.text,
                        text_sha256=_sha(ref.text),
                        fencing_token=self.ctx.lease.token,
                    )
                    .on_conflict_do_nothing()
                )
            append_event(
                session,
                self.ctx.run_id,
                self.ctx.workspace_id,
                "source_collected",
                {"task_id": self.task_id, "source_id": source_id, "passages": len(refs)},
            )
        return refs

    def _start(self, tool: str) -> uuid.UUID:
        execution_id = uuid.uuid4()
        with self.ctx.fenced() as session:
            session.add(
                ToolExecution(
                    id=execution_id,
                    run_id=self.ctx.run_id,
                    task_id=self.task_id,
                    tool=tool,
                    status="started",
                    fencing_token=self.ctx.lease.token,
                )
            )
        return execution_id

    def _finish(self, execution_id: uuid.UUID, status: str, error_class: str | None = None) -> None:
        with self.ctx.fenced() as session:
            session.execute(
                update(ToolExecution)
                .where(ToolExecution.id == execution_id)
                .values(status=status, error_class=error_class, finished_at=func.now())
            )
