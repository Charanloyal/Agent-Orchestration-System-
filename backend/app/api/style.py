"""Writing Style Studio API: measured style metrics and a fact-locked rewrite of text a member
pastes or a document in their workspace. Nothing is stored; results are returned only."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from app.auth.deps import DbSession, WorkspaceAccess, workspace_access
from app.db.models import Upload, UploadChunk
from app.errors import NotFound, Unprocessable
from app.policy.permissions import Action
from app.services import style
from app.services.ratelimit import user_limit

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/style", tags=["style"])


class StyleSource(BaseModel):
    """Exactly one of `text` and `upload_id`."""

    text: str | None = Field(default=None, max_length=style.MAX_CHARS)
    upload_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _one_source(self) -> StyleSource:
        if (self.text is None) == (self.upload_id is None):
            raise ValueError("send either text or upload_id")
        return self


class RewriteIn(StyleSource):
    persona: Literal["journalist", "academic", "executive", "technical"] = "journalist"


class SentenceOut(BaseModel):
    text: str
    words: int
    phrases: list[str]


class BlockOut(BaseModel):
    kind: str
    prefix: str
    text: str
    first_sentence: int
    sentence_count: int


class ReportOut(BaseModel):
    words: int
    sentences: int
    paragraphs: int
    mean_sentence_words: float
    sentence_length_cv: float
    shortest_sentence: int
    longest_sentence: int
    vocabulary_mattr: float
    word_entropy_bits: float
    stock_phrases: int
    stock_phrases_per_1000_words: float
    paragraph_length_cv: float
    flagged: list[int]
    sentence_list: list[SentenceOut]
    blocks: list[BlockOut]


class ChangeOut(BaseModel):
    before: str
    after: str
    rules: list[str]
    accepted: bool


class FactLockOut(BaseModel):
    total: int
    preserved: int
    missing: list[str]


class AnalyzeOut(BaseModel):
    source: str
    text: str
    report: ReportOut


class RewriteOut(BaseModel):
    source: str
    persona: str
    original: str
    rewritten: str
    before: ReportOut
    after: ReportOut
    fact_lock: FactLockOut
    passes: int
    changed_sentences: int
    rejected_changes: int
    changes: list[ChangeOut]


def _report(report: style.StyleReport) -> ReportOut:
    return ReportOut(
        **{k: v for k, v in vars(report).items() if k not in {"flagged", "sentence_list", "blocks"}},
        flagged=list(report.flagged),
        sentence_list=[
            SentenceOut(text=s.text, words=s.words, phrases=list(s.phrases)) for s in report.sentence_list
        ],
        blocks=[BlockOut(**vars(b)) for b in report.blocks],
    )


def _text(db: DbSession, workspace_id: uuid.UUID, source: StyleSource) -> tuple[str, str]:
    if source.text is not None:
        if not source.text.strip():
            raise Unprocessable("The text is empty")
        return "pasted text", source.text
    upload = db.get(Upload, source.upload_id)
    if upload is None or upload.workspace_id != workspace_id:
        raise NotFound("Upload not found")
    passages = db.scalars(
        select(UploadChunk.text).where(UploadChunk.upload_id == upload.id).order_by(UploadChunk.chunk_index)
    )
    text = "\n\n".join(passages)[: style.MAX_CHARS]
    if not text.strip():
        raise Unprocessable("This document has no extracted text")
    return upload.filename, text


@router.post("/analyze", response_model=AnalyzeOut, dependencies=[Depends(user_limit("style"))])
def analyze(
    body: StyleSource,
    access: Annotated[WorkspaceAccess, Depends(workspace_access(Action.WORKSPACE_READ))],
    db: DbSession,
) -> AnalyzeOut:
    source, text = _text(db, access.workspace_id, body)
    return AnalyzeOut(source=source, text=text, report=_report(style.analyze(text)))


@router.post("/rewrite", response_model=RewriteOut, dependencies=[Depends(user_limit("style"))])
def rewrite(
    body: RewriteIn,
    access: Annotated[WorkspaceAccess, Depends(workspace_access(Action.WORKSPACE_READ))],
    db: DbSession,
) -> RewriteOut:
    source, text = _text(db, access.workspace_id, body)
    result = style.rewrite(text, body.persona)
    lock = style.fact_lock(text, result.text)
    return RewriteOut(
        source=source,
        persona=body.persona,
        original=text,
        rewritten=result.text,
        before=_report(style.analyze(text)),
        after=_report(style.analyze(result.text)),
        fact_lock=FactLockOut(total=lock.total, preserved=lock.preserved, missing=list(lock.missing)),
        passes=result.passes,
        changed_sentences=result.changed_sentences,
        rejected_changes=result.rejected_changes,
        changes=[
            ChangeOut(before=c.before, after=c.after, rules=list(c.rules), accepted=c.accepted)
            for c in result.changes
        ],
    )
