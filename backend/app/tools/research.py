"""Research tools bound to one run and task (ADR 0010).

Every external call is recorded before it is made; evidence is persisted with deterministic
IDs inside fenced transactions, so re-execution is idempotent. Policy (allowed domains,
staleness, workspace scope, SSRF rules) is enforced here in code, never by prompts.
"""

import hashlib
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, update
from sqlalchemy.dialects.postgresql import insert

from app.agents.base import EvidenceRef
from app.db.models import EvidencePassage, Source, ToolExecution
from app.providers.search import SearchHit
from app.services.events import append_event
from app.services.uploads import search_chunks
from app.tools.chunking import split_passages
from app.tools.extract import ExtractionError, Segment, extract
from app.tools.fetcher import FetchError
from app.tools.policy import domain_permitted, is_stale, source_id_for
from app.workflow.context import RunContext

MAX_SEARCH_RESULTS = 5
MAX_UPLOAD_RESULTS = 5


def sha256_hex(text: str | bytes) -> str:
    return hashlib.sha256(text.encode() if isinstance(text, str) else text).hexdigest()


class RunResearchTools:
    def __init__(self, ctx: RunContext, task_id: str) -> None:
        self.ctx = ctx
        self.task_id = task_id
        self.policy = ctx.brief.source_policy

    # --- search -------------------------------------------------------------------------

    def search(self, query: str) -> list[SearchHit]:
        execution_id = self._start(f"web_search:{self.ctx.search.name}")
        try:
            response = self.ctx.search.search(
                query,
                max_results=MAX_SEARCH_RESULTS,
                allowed_domains=list(self.policy.allowed_domains),
                blocked_domains=list(self.policy.blocked_domains),
            )
        except Exception as exc:
            self._finish(execution_id, "failed", type(exc).__name__)
            raise
        self._finish(execution_id, "succeeded")
        hits = response.hits
        # Enforce the source policy on results, whatever the provider claims to filter.
        permitted = [h for h in hits if h.url and domain_permitted(h.url, self.policy)]
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

    def search_uploads(self, query: str) -> list[SearchHit]:
        """Full-text search over this workspace's uploaded documents only."""
        if "uploaded_documents" not in self.policy.allowed_source_types:
            return []
        execution_id = self._start("search_uploads")
        with self.ctx.sm() as session:
            chunks = search_chunks(
                session, self.ctx.workspace_id, query, limit=MAX_UPLOAD_RESULTS, match_any=True
            )
        self._finish(execution_id, "succeeded")
        return [
            SearchHit(
                url=None,
                title=c.title or c.filename,
                snippet=c.text[:200],
                content=c.text,
                kind="upload",
                upload_id=c.upload_id,
                locator=c.locator,
            )
            for c in chunks
        ]

    # --- collect ------------------------------------------------------------------------

    def collect(self, hit: SearchHit) -> list[EvidenceRef]:
        if hit.kind == "upload":
            return self._collect_upload(hit)
        if not hit.url or not domain_permitted(hit.url, self.policy):
            return []
        source_id = source_id_for(hit.url)
        if hit.content is not None:
            segments = [Segment(None, hit.content)]
            content_sha, title, final_url = sha256_hex(hit.content), hit.title, hit.url
        else:
            fetched = self._fetch(hit, source_id)
            if fetched is None:
                return []
            segments, content_sha, title, final_url = fetched
        return self._store(
            source_id=source_id,
            kind="corpus" if hit.kind == "corpus" else "web",
            url=final_url,
            upload_id=None,
            title=title,
            published_on=hit.published_on,
            content_sha=content_sha,
            passages=[(seg.locator, text) for seg in segments for text in split_passages(seg.text)],
        )

    def _fetch(self, hit: SearchHit, source_id: str) -> tuple[list[Segment], str, str, str] | None:
        assert hit.url is not None
        execution_id = self._start("fetch_url")
        try:
            result = self.ctx.fetcher.fetch(hit.url)
            if not domain_permitted(result.url, self.policy):
                raise FetchError("redirected_outside_source_policy")
            document = extract(result.body, result.content_type, result.charset)
        except (FetchError, ExtractionError) as exc:
            self._finish(execution_id, "failed", exc.reason[:60])
            self._record_failure(hit, source_id, exc.reason)
            return None
        self._finish(execution_id, "succeeded")
        return document.segments, sha256_hex(result.body), (document.title or hit.title), result.url

    def _collect_upload(self, hit: SearchHit) -> list[EvidenceRef]:
        assert hit.upload_id is not None
        assert hit.content is not None
        source_id = "upl-" + hit.upload_id.hex[:16]
        return self._store(
            source_id=source_id,
            kind="upload",
            url=None,
            upload_id=hit.upload_id,
            title=hit.title,
            published_on=None,
            content_sha=None,
            passages=[(hit.locator, hit.content)],
        )

    # --- persistence --------------------------------------------------------------------

    def _store(
        self,
        *,
        source_id: str,
        kind: str,
        url: str | None,
        upload_id: uuid.UUID | None,
        title: str,
        published_on: str | None,
        content_sha: str | None,
        passages: list[tuple[str | None, str]],
    ) -> list[EvidenceRef]:
        refs: list[EvidenceRef] = []
        with self.ctx.fenced() as session:
            session.execute(
                insert(Source)
                .values(
                    run_id=self.ctx.run_id,
                    source_id=source_id,
                    workspace_id=self.ctx.workspace_id,
                    kind=kind,
                    url=url,
                    upload_id=upload_id,
                    title=title[:500],
                    retrieved_at=datetime.now(UTC),
                    published_on=published_on,
                    fetch_status="fetched",
                    content_sha256=content_sha or sha256_hex("".join(p for _, p in passages)),
                )
                .on_conflict_do_nothing()
            )
            for index, (locator, text) in enumerate(passages, 1):
                evidence_id = "ev-" + sha256_hex(f"{source_id}|{locator}|{index}|{sha256_hex(text)}")[:16]
                session.execute(
                    insert(EvidencePassage)
                    .values(
                        run_id=self.ctx.run_id,
                        evidence_id=evidence_id,
                        workspace_id=self.ctx.workspace_id,
                        source_id=source_id,
                        task_id=self.task_id,
                        locator=(locator or f"passage {index}")[:200],
                        text=text,
                        text_sha256=sha256_hex(text),
                        fencing_token=self.ctx.lease.token,
                    )
                    .on_conflict_do_nothing()
                )
                refs.append(EvidenceRef(evidence_id, source_id, text))
            append_event(
                session,
                self.ctx.run_id,
                self.ctx.workspace_id,
                "source_collected",
                {"task_id": self.task_id, "source_id": source_id, "kind": kind, "passages": len(refs)},
            )
        return refs

    def _record_failure(self, hit: SearchHit, source_id: str, reason: str) -> None:
        """FR-05: failed fetches are recorded, never represented as read sources."""
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
                    fetch_status="failed",
                    failure_reason=reason[:500],
                )
                .on_conflict_do_nothing()
            )
            append_event(
                session,
                self.ctx.run_id,
                self.ctx.workspace_id,
                "source_failed",
                {"task_id": self.task_id, "source_id": source_id, "reason": reason[:100]},
            )

    def _start(self, tool: str) -> uuid.UUID:
        execution_id = uuid.uuid4()
        with self.ctx.fenced() as session:
            session.add(
                ToolExecution(
                    id=execution_id,
                    run_id=self.ctx.run_id,
                    task_id=self.task_id,
                    tool=tool[:40],
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
