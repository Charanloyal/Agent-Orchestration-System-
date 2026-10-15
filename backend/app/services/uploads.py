"""Upload ingestion: validate, extract, chunk, index, and store (FR-05, threat model T8)."""

import hashlib
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.auth.deps import Principal
from app.db.models import Upload, UploadChunk
from app.errors import AppError
from app.services.audit import audit
from app.storage import ObjectStore
from app.tools.chunking import split_passages
from app.tools.extract import ExtractedDocument, ExtractionError, extract_pdf, extract_plain

TEXT_SUFFIXES = (".txt", ".md", ".markdown")


class PayloadTooLarge(AppError):
    status_code = 413
    code = "payload_too_large"


class UnsupportedMediaType(AppError):
    status_code = 415
    code = "unsupported_media_type"


class UnreadableDocument(AppError):
    status_code = 422
    code = "unreadable_document"


def safe_filename(name: str | None) -> str:
    base = re.split(r"[\\/]", name or "upload")[-1]
    cleaned = re.sub(r"[^A-Za-z0-9._ -]", "_", base).strip(" .") or "upload"
    return cleaned[:255]


def sniff(data: bytes, filename: str) -> str:
    """Decide the type from content, not from the client's declared Content-Type."""
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if filename.lower().endswith(TEXT_SUFFIXES) and b"\x00" not in data:
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            pass
        else:
            return "text/plain"
    raise UnsupportedMediaType("Only text-based PDF, .txt, and .md files are supported")


@dataclass(frozen=True)
class IngestResult:
    upload: Upload
    created: bool


def ingest_upload(
    db: Session,
    store: ObjectStore,
    principal: Principal,
    workspace_id: uuid.UUID,
    *,
    filename: str | None,
    data: bytes,
    max_bytes: int,
) -> IngestResult:
    if len(data) > max_bytes:
        raise PayloadTooLarge(f"Uploads are limited to {max_bytes // 1_000_000} MB")
    if not data:
        raise UnreadableDocument("The file is empty")
    name = safe_filename(filename)
    media_type = sniff(data, name)
    digest = hashlib.sha256(data).hexdigest()

    existing = db.scalar(select(Upload).where(Upload.workspace_id == workspace_id, Upload.sha256 == digest))
    if existing is not None:
        return IngestResult(existing, created=False)

    try:
        document: ExtractedDocument = (
            extract_pdf(data) if media_type == "application/pdf" else extract_plain(data.decode("utf-8"))
        )
    except ExtractionError as exc:
        audit(
            db,
            "upload.rejected",
            actor_user_id=principal.user_id,
            workspace_id=workspace_id,
            details={"reason": exc.reason, "sha256": digest},
        )
        db.commit()
        raise UnreadableDocument(f"Document rejected: {exc.reason.replace('_', ' ')}") from exc

    upload = Upload(
        workspace_id=workspace_id,
        created_by=principal.user_id,
        filename=name,
        title=document.title,
        media_type=media_type,
        size_bytes=len(data),
        sha256=digest,
        object_key=f"uploads/{workspace_id}/{digest}",
        pages=document.pages,
        text_chars=len(document.text),
    )
    db.add(upload)
    db.flush()
    index = 0
    for segment in document.segments:
        for number, passage in enumerate(split_passages(segment.text, limit=None), 1):
            locator = f"{segment.locator}, passage {number}" if segment.locator else f"passage {number}"
            db.add(
                UploadChunk(
                    upload_id=upload.id,
                    chunk_index=index,
                    workspace_id=workspace_id,
                    locator=locator,
                    text=passage,
                )
            )
            index += 1
    store.put(upload.object_key, data)
    audit(
        db,
        "upload.create",
        actor_user_id=principal.user_id,
        workspace_id=workspace_id,
        target=str(upload.id),
        details={"bytes": len(data), "chunks": index},
    )
    db.commit()
    return IngestResult(upload, created=True)


@dataclass(frozen=True)
class ChunkHit:
    upload_id: uuid.UUID
    chunk_index: int
    filename: str
    title: str | None
    locator: str | None
    text: str
    rank: float


def search_chunks(
    db: Session, workspace_id: uuid.UUID, query: str, limit: int = 5, *, match_any: bool = False
) -> list[ChunkHit]:
    """Workspace-scoped full-text search. The workspace filter is applied in SQL before
    ranking, so other workspaces' documents are never candidates (FR-01).

    `match_any` ORs the query's words (for natural-language research questions, where
    requiring every word would miss relevant passages); ranking still favours passages that
    match more of them. User searches keep web-search semantics (all words)."""
    if match_any:
        words = re.findall(r"[A-Za-z0-9]+", query)[:32]
        if not words:
            return []
        query = " or ".join(words)
    tsquery = func.websearch_to_tsquery(text("'english'"), query)
    rank = func.ts_rank_cd(UploadChunk.tsv, tsquery)
    rows = db.execute(
        select(UploadChunk, Upload.filename, Upload.title, rank.label("rank"))
        .join(Upload, Upload.id == UploadChunk.upload_id)
        .where(UploadChunk.workspace_id == workspace_id, UploadChunk.tsv.op("@@")(tsquery))
        .order_by(rank.desc(), UploadChunk.upload_id, UploadChunk.chunk_index)
        .limit(limit)
    ).all()
    return [
        ChunkHit(c.upload_id, c.chunk_index, filename, title, c.locator, c.text, float(r))
        for c, filename, title, r in rows
    ]
