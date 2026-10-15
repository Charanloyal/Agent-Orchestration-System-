"""Uploads API: ingest permitted documents into a workspace and search them (FR-05)."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select

from app.auth.deps import AppSettings, DbSession, WorkspaceAccess, workspace_access
from app.db.models import Upload, UploadChunk, User
from app.errors import Forbidden, NotFound
from app.policy.permissions import Action, is_allowed
from app.services.audit import audit
from app.services.ratelimit import user_limit
from app.services.uploads import ingest_upload, search_chunks
from app.storage import get_object_store

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/uploads", tags=["uploads"])


class UploadOut(BaseModel):
    id: uuid.UUID
    filename: str
    title: str | None
    media_type: str
    size_bytes: int
    sha256: str
    pages: int | None
    text_chars: int
    chunks: int
    uploaded_by: str
    uploaded_by_id: uuid.UUID
    created_at: datetime


class ChunkHitOut(BaseModel):
    upload_id: uuid.UUID
    filename: str
    locator: str | None
    text: str
    rank: float


def _out(db: DbSession, upload: Upload) -> UploadOut:
    chunks = db.scalar(
        select(func.count()).select_from(UploadChunk).where(UploadChunk.upload_id == upload.id)
    )
    creator = db.get(User, upload.created_by)
    return UploadOut(
        id=upload.id,
        filename=upload.filename,
        title=upload.title,
        media_type=upload.media_type,
        size_bytes=upload.size_bytes,
        sha256=upload.sha256,
        pages=upload.pages,
        text_chars=upload.text_chars,
        chunks=chunks or 0,
        uploaded_by=creator.display_name if creator else "unknown",
        uploaded_by_id=upload.created_by,
        created_at=upload.created_at,
    )


@router.post("", response_model=UploadOut, status_code=201, dependencies=[Depends(user_limit("upload"))])
async def create_upload(
    access: Annotated[WorkspaceAccess, Depends(workspace_access(Action.UPLOAD_CREATE))],
    db: DbSession,
    settings: AppSettings,
    response: Response,
    file: Annotated[UploadFile, File(description="Text-based PDF, .txt, or .md")],
) -> UploadOut:
    data = await file.read(settings.upload_max_bytes + 1)
    result = ingest_upload(
        db,
        get_object_store(),
        access.principal,
        access.workspace_id,
        filename=file.filename,
        data=data,
        max_bytes=settings.upload_max_bytes,
    )
    if not result.created:
        response.status_code = 200
    return _out(db, result.upload)


@router.get("", response_model=list[UploadOut])
def list_uploads(
    access: Annotated[WorkspaceAccess, Depends(workspace_access(Action.WORKSPACE_READ))], db: DbSession
) -> list[UploadOut]:
    uploads = db.scalars(
        select(Upload).where(Upload.workspace_id == access.workspace_id).order_by(Upload.created_at.desc())
    )
    return [_out(db, u) for u in uploads]


@router.get("/search", response_model=list[ChunkHitOut])
def search_uploads(
    access: Annotated[WorkspaceAccess, Depends(workspace_access(Action.WORKSPACE_READ))],
    db: DbSession,
    q: Annotated[str, Query(min_length=2, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=20)] = 10,
) -> list[ChunkHitOut]:
    return [
        ChunkHitOut(upload_id=h.upload_id, filename=h.filename, locator=h.locator, text=h.text, rank=h.rank)
        for h in search_chunks(db, access.workspace_id, q, limit)
    ]


def _get(db: DbSession, workspace_id: uuid.UUID, upload_id: uuid.UUID) -> Upload:
    upload = db.get(Upload, upload_id)
    if upload is None or upload.workspace_id != workspace_id:
        raise NotFound("Upload not found")
    return upload


@router.get("/{upload_id}", response_model=UploadOut)
def get_upload(
    upload_id: uuid.UUID,
    access: Annotated[WorkspaceAccess, Depends(workspace_access(Action.WORKSPACE_READ))],
    db: DbSession,
) -> UploadOut:
    return _out(db, _get(db, access.workspace_id, upload_id))


@router.delete("/{upload_id}", status_code=204)
def delete_upload(
    upload_id: uuid.UUID,
    access: Annotated[WorkspaceAccess, Depends(workspace_access(Action.WORKSPACE_READ))],
    db: DbSession,
) -> Response:
    """Removes the stored file and its searchable chunks. Passages already copied into run
    evidence stay with those runs as an immutable record (see the retention policy)."""
    upload = _get(db, access.workspace_id, upload_id)
    if upload.created_by != access.principal.user_id and not is_allowed(access.role, Action.DATA_DELETE):
        raise Forbidden("Only the uploader or an admin can delete this upload")
    get_object_store().delete(upload.object_key)
    db.delete(upload)
    audit(
        db,
        "upload.delete",
        actor_user_id=access.principal.user_id,
        workspace_id=access.workspace_id,
        target=str(upload_id),
    )
    db.commit()
    return Response(status_code=204)
