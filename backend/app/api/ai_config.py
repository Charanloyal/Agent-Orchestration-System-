"""A workspace's model engine (ADR 0029): which engine runs, and the admin's own provider key.

Members see the engine; workspace admins save, test or remove the key. The key is encrypted
at rest, never returned, and never logged; responses show only its last 4 characters.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field, model_validator

from app.auth.deps import AppSettings, DbSession, WorkspaceAccess, workspace_access
from app.db.models import WorkspaceAiConfig
from app.errors import Conflict, Unprocessable
from app.policy.permissions import Action
from app.services import ai_engine
from app.services.audit import audit
from app.services.ratelimit import user_limit

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/ai-config", tags=["ai-config"])


class ProviderOut(BaseModel):
    id: str
    label: str
    models: list[str]


class EngineOut(BaseModel):
    source: Literal["workspace", "environment", "demo"]
    live: bool
    label: str
    provider: str | None
    model: str | None
    key_hint: str | None
    problem: str | None
    providers: list[ProviderOut]


class ConfigIn(BaseModel):
    provider: Literal["gemini", "groq", "openai"]
    model: str = Field(min_length=1, max_length=100)
    # Empty keeps the saved key (changing only the model); required the first time.
    api_key: str | None = Field(default=None, max_length=400)

    @model_validator(mode="after")
    def _known_model(self) -> ConfigIn:
        if self.model not in ai_engine.PROVIDERS[self.provider].models:
            raise ValueError(f"{self.model} is not offered for {self.provider}")
        if self.api_key is not None:
            self.api_key = self.api_key.strip() or None
        return self


class TestIn(BaseModel):
    """Test a key before saving it, or the saved engine when nothing is sent."""

    provider: Literal["gemini", "groq", "openai"] | None = None
    model: str | None = Field(default=None, max_length=100)
    api_key: str | None = Field(default=None, max_length=400)


class TestOut(BaseModel):
    ok: bool
    latency_ms: int
    model: str
    detail: str


def _engine_out(engine: ai_engine.Engine) -> EngineOut:
    return EngineOut(
        source=engine.source,
        live=engine.live,
        label=engine.label,
        provider=engine.provider,
        model=engine.model,
        key_hint=engine.key_hint,
        problem=engine.problem,
        providers=[
            ProviderOut(id=k, label=v.label, models=list(v.models)) for k, v in ai_engine.PROVIDERS.items()
        ],
    )


@router.get("", response_model=EngineOut)
def get_engine(
    access: Annotated[WorkspaceAccess, Depends(workspace_access(Action.WORKSPACE_READ))],
    db: DbSession,
    settings: AppSettings,
) -> EngineOut:
    return _engine_out(ai_engine.resolve(db, settings, access.workspace_id))


@router.put("", response_model=EngineOut)
def save_engine(
    body: ConfigIn,
    access: Annotated[WorkspaceAccess, Depends(workspace_access(Action.WORKSPACE_MANAGE))],
    db: DbSession,
    settings: AppSettings,
) -> EngineOut:
    config = db.get(WorkspaceAiConfig, access.workspace_id, with_for_update=True)
    if body.api_key is None and (config is None or config.provider != body.provider):
        raise Unprocessable("Paste the API key for this provider")
    try:
        ciphertext = ai_engine.encrypt_key(settings, body.api_key) if body.api_key else None
    except ai_engine.SecretsUnavailable as exc:
        raise Conflict(str(exc)) from exc
    if config is None:
        assert ciphertext is not None
        assert body.api_key is not None
        config = WorkspaceAiConfig(
            workspace_id=access.workspace_id,
            provider=body.provider,
            model=body.model,
            key_ciphertext=ciphertext,
            key_hint=body.api_key[-4:],
            updated_by=access.principal.user_id,
        )
        db.add(config)
    else:
        config.provider, config.model, config.updated_by = body.provider, body.model, access.principal.user_id
        if ciphertext is not None and body.api_key is not None:
            config.key_ciphertext, config.key_hint = ciphertext, body.api_key[-4:]
    audit(
        db,
        "workspace.ai_engine.save",
        actor_user_id=access.principal.user_id,
        workspace_id=access.workspace_id,
        details={"provider": body.provider, "model": body.model, "key_changed": body.api_key is not None},
    )
    db.commit()
    return _engine_out(ai_engine.resolve(db, settings, access.workspace_id))


@router.delete("", status_code=204)
def remove_engine(
    access: Annotated[WorkspaceAccess, Depends(workspace_access(Action.WORKSPACE_MANAGE))],
    db: DbSession,
) -> Response:
    config = db.get(WorkspaceAiConfig, access.workspace_id)
    if config is not None:
        db.delete(config)
        audit(
            db,
            "workspace.ai_engine.remove",
            actor_user_id=access.principal.user_id,
            workspace_id=access.workspace_id,
        )
        db.commit()
    return Response(status_code=204)


@router.post("/test", response_model=TestOut, dependencies=[Depends(user_limit("ai_test"))])
def test_engine(
    body: TestIn,
    access: Annotated[WorkspaceAccess, Depends(workspace_access(Action.WORKSPACE_MANAGE))],
    db: DbSession,
    settings: AppSettings,
) -> TestOut:
    """One small live request, timed: the key and model work, or the provider's reason."""
    if body.api_key and body.provider:
        model = body.model or ai_engine.PROVIDERS[body.provider].models[0]
        llm = ai_engine.build_llm(settings, body.provider, model, body.api_key.strip())
    else:
        found = ai_engine.engine_llm(db, settings, access.workspace_id)
        if found is None:
            raise Unprocessable("No model is configured: paste a key first")
        llm = found
    result = ai_engine.ping(llm)
    return TestOut(ok=result.ok, latency_ms=result.latency_ms, model=result.model, detail=result.detail)
