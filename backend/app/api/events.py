from __future__ import annotations

import json
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.events.bus import subscribe
from app.sessions.store import get_session


router = APIRouter()


def _sse(event: str, data: Any) -> bytes:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")


@router.get("/api/sessions/{session_id}/events")
async def get_events(session_id: str) -> StreamingResponse:
    if not get_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")

    async def gen() -> AsyncIterator[bytes]:
        yield _sse("ready", {"sessionId": session_id})
        async for ev in subscribe(session_id):
            yield _sse(
                "event",
                {
                    "id": ev.id,
                    "type": ev.type,
                    "payload": ev.payload,
                    "createdAt": ev.created_at,
                },
            )

    return StreamingResponse(gen(), media_type="text/event-stream")


