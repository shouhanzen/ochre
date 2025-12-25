from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.settings.store import get_setting, set_setting


router = APIRouter()


DEFAULT_MODEL_KEY = "defaultModel"
DEFAULT_MODEL_FALLBACK = "openai/gpt-4o-mini"


class SettingsResponse(BaseModel):
    defaultModel: str = Field(..., description="Global default LLM model")


class UpdateSettingsBody(BaseModel):
    defaultModel: str


@router.get("/api/settings")
def get_settings() -> SettingsResponse:
    model = get_setting(DEFAULT_MODEL_KEY, DEFAULT_MODEL_FALLBACK) or DEFAULT_MODEL_FALLBACK
    return SettingsResponse(defaultModel=model)


@router.put("/api/settings")
def put_settings(body: UpdateSettingsBody) -> SettingsResponse:
    model = body.defaultModel.strip() or DEFAULT_MODEL_FALLBACK
    set_setting(DEFAULT_MODEL_KEY, model)
    return SettingsResponse(defaultModel=model)


