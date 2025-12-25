from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.sessions.store import create_session, get_session, list_messages, list_sessions


router = APIRouter()


class CreateSessionBody(BaseModel):
    title: str | None = None


@router.post("/api/sessions")
def post_create_session(body: CreateSessionBody) -> dict:
    s = create_session(title=body.title)
    return {"session": s.__dict__}


@router.get("/api/sessions")
def get_sessions(limit: int = Query(50)) -> dict:
    sessions = list_sessions(limit=limit)
    return {"sessions": [s.__dict__ for s in sessions]}


@router.get("/api/sessions/{session_id}")
def get_one_session(session_id: str, limit: int = Query(200)) -> dict:
    s = get_session(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    msgs = list_messages(session_id, limit=limit)
    return {"session": s.__dict__, "messages": [m.__dict__ for m in msgs]}


