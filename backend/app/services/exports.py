"""Server-side Markdown export of a report version (FR-11, threat model T6/T7).

Every exported byte comes from stored, validated artifacts; model text and source titles are
escaped so a claim or page title cannot inject Markdown structure, raw HTML, or links. Only
http(s) source URLs become links. An export is "approved" only when a human approved exactly
this version and digest; anything else is watermarked as a draft.
"""

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import quote, urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import WriterOutput
from app.db.models import Approval, Brief, EvidencePassage, ReportExport, ReportVersion, Run, Source, User
from app.errors import NotFound
from app.services.audit import audit
from app.services.events import append_event
from app.storage import ObjectStore

DRAFT_MARK = "DRAFT - NOT APPROVED"
KIND_LABELS = {
    "fact": "Fact",
    "inference": "Inference",
    "conflict": "Conflict",
    "recommendation": "Recommendation",
    "unknown": "Unknown",
}
_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+!|<>~=^$])")
_WHITESPACE = re.compile(r"\s+")


def md_text(value: str, limit: int | None = None) -> str:
    """Inline-safe Markdown text: one line, every structural character backslash-escaped,
    and '&' encoded so entity references cannot smuggle markup."""
    flat = _WHITESPACE.sub(" ", value).strip()
    if limit is not None and len(flat) > limit:
        flat = flat[: limit - 1].rstrip() + "…"
    return _SPECIAL.sub(r"\\\1", flat.replace("&", "&amp;"))


def safe_url(url: str | None) -> str | None:
    """http(s) URLs only, percent-encoded so they cannot break out of a Markdown link."""
    if not url:
        return None
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        return None
    return quote(url.strip(), safe=":/?#@!$&'*+,;=%-._~")


@dataclass(frozen=True)
class ExportedReport:
    export: ReportExport
    filename: str
    content: bytes


@dataclass(frozen=True)
class _Citation:
    number: int
    evidence_id: str
    title: str | None
    url: str | None
    kind: str
    published_on: str | None
    locator: str | None
    excerpt: str


def render_markdown(
    *,
    topic: str,
    run_id: uuid.UUID,
    report: ReportVersion,
    citations: dict[str, _Citation],
    approval: Approval | None,
    approver: str | None,
    generated_at: datetime,
) -> str:
    draft = WriterOutput.model_validate(report.body)
    approved = approval is not None and approval.decision == "approve"
    lines: list[str] = []
    if not approved:
        lines += [f"> **{DRAFT_MARK}.** This report has not been approved by a human reviewer.", ""]
    lines += [f"# Research report: {md_text(topic, 300)}", ""]
    if approved and approval is not None:
        status = f"Approved by {md_text(approver or 'unknown', 120)} at {approval.decided_at.isoformat()}"
    elif approval is not None:
        status = f"Rejected by {md_text(approver or 'unknown', 120)} at {approval.decided_at.isoformat()}"
    else:
        status = "Awaiting human review"
    lines += [
        "| Field | Value |",
        "| --- | --- |",
        f"| Run | `{run_id}` |",
        f"| Report version | {report.version} (plan version {report.plan_version}) |",
        f"| Report digest (SHA-256) | `{report.digest}` |",
        f"| Status | {status} |",
        f"| Exported at | {generated_at.isoformat()} |",
        "",
        "Claim labels: **Fact** is stated by the cited sources; **Inference** is a conclusion drawn "
        "from them; **Conflict** marks sources that disagree; **Recommendation** is advice; "
        "**Unknown** is a question the evidence does not answer.",
        "",
    ]
    for section in draft.sections:
        lines += [f"## {md_text(section.title, 200)}", ""]
        for claim in section.claims:
            refs = "".join(f"[{citations[e].number}]" for e in claim.evidence_ids if e in citations)
            refs = refs.replace("[", "\\[").replace("]", "\\]")
            lines.append(
                f"- **{KIND_LABELS[claim.kind]}:** {md_text(claim.text)}{' ' + refs if refs else ''}"
            )
        lines.append("")
    if citations:
        lines += ["## Sources", ""]
        for cite in sorted(citations.values(), key=lambda c: c.number):
            title = md_text(cite.title or cite.evidence_id, 200)
            url = safe_url(cite.url)
            label = f"[{title}]({url})" if url else title
            meta = [cite.kind]
            if cite.published_on:
                meta.append(f"published {md_text(cite.published_on, 40)}")
            if cite.locator:
                meta.append(md_text(cite.locator, 80))
            lines.append(
                f"{cite.number}\\. {label} ({', '.join(meta)}), evidence `{cite.evidence_id}`  \n"
                f"   > {md_text(cite.excerpt, 300)}"
            )
        lines.append("")
    if not approved:
        lines += ["---", "", f"**{DRAFT_MARK}.**", ""]
    return "\n".join(lines)


def _citations(db: Session, run_id: uuid.UUID, draft: WriterOutput) -> dict[str, _Citation]:
    order: list[str] = []
    for section in draft.sections:
        for claim in section.claims:
            order += [e for e in claim.evidence_ids if e not in order]
    if not order:
        return {}
    rows = db.execute(
        select(EvidencePassage, Source)
        .join(
            Source,
            (Source.run_id == EvidencePassage.run_id) & (Source.source_id == EvidencePassage.source_id),
        )
        .where(EvidencePassage.run_id == run_id, EvidencePassage.evidence_id.in_(order))
    ).all()
    found = {e.evidence_id: (e, s) for e, s in rows}
    citations: dict[str, _Citation] = {}
    for evidence_id in order:
        if evidence_id not in found:
            continue
        passage, source = found[evidence_id]
        citations[evidence_id] = _Citation(
            number=len(citations) + 1,
            evidence_id=evidence_id,
            title=source.title,
            url=source.url,
            kind=source.kind,
            published_on=source.published_on,
            locator=passage.locator,
            excerpt=passage.text,
        )
    return citations


def export_report(
    db: Session, store: ObjectStore, *, run: Run, version: int, user_id: uuid.UUID
) -> ExportedReport:
    report = db.get(ReportVersion, (run.id, version))
    if report is None:
        raise NotFound("Report version not found")
    approval = db.scalar(
        select(Approval).where(
            Approval.run_id == run.id,
            Approval.artifact_kind == "report",
            Approval.artifact_version == version,
            Approval.artifact_digest == report.digest,
        )
    )
    approver_row = db.get(User, approval.decided_by) if approval is not None else None
    approver = approver_row.display_name if approver_row is not None else None
    brief = db.get(Brief, run.brief_id)
    topic = str(brief.body.get("topic", "")) if brief else ""
    kind = "approved" if approval is not None and approval.decision == "approve" else "draft"
    now = datetime.now(UTC)
    content = render_markdown(
        topic=topic,
        run_id=run.id,
        report=report,
        citations=_citations(db, run.id, WriterOutput.model_validate(report.body)),
        approval=approval,
        approver=approver,
        generated_at=now,
    ).encode()
    export_id = uuid.uuid4()
    key = f"exports/{run.workspace_id}/{run.id}/{export_id}.md"
    store.put(key, content)
    sha = hashlib.sha256(content).hexdigest()
    row = ReportExport(
        id=export_id,
        run_id=run.id,
        workspace_id=run.workspace_id,
        report_version=version,
        report_digest=report.digest,
        approval_id=approval.id if approval and kind == "approved" else None,
        kind=kind,
        content_sha256=sha,
        object_key=key,
        created_by=user_id,
        details={"format": "markdown", "bytes": len(content)},
    )
    db.add(row)
    append_event(
        db, run.id, run.workspace_id, "report_exported", {"version": version, "kind": kind, "sha256": sha}
    )
    audit(
        db,
        "report.exported",
        actor_user_id=user_id,
        workspace_id=run.workspace_id,
        target=str(run.id),
        details={"version": version, "kind": kind, "sha256": sha},
    )
    db.commit()
    suffix = "approved" if kind == "approved" else "DRAFT"
    return ExportedReport(row, f"report-{str(run.id)[:8]}-v{version}-{suffix}.md", content)
