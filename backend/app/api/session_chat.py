from __future__ import annotations

import json
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agent.openrouter import OpenRouterError
from app.agent.runner import run_agent
from app.sessions.store import add_message, get_session, messages_for_llm


router = APIRouter()


class ChatBody(BaseModel):
    content: str = Field(..., description="User message content")
    model: str | None = Field(default=None, description="Optional model override")


def _sse(event: str, data: Any) -> bytes:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")


@router.post("/api/sessions/{session_id}/chat")
async def post_chat(session_id: str, body: ChatBody) -> StreamingResponse:
    if not get_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")

    async def gen() -> AsyncIterator[bytes]:
        # Persist user message first.
        add_message(session_id=session_id, role="user", content=body.content, meta={})

        llm_msgs = messages_for_llm(session_id)
        try:
            from app.api.settings import DEFAULT_MODEL_FALLBACK, DEFAULT_MODEL_KEY  # noqa: WPS433
            from app.settings.store import get_setting  # noqa: WPS433

            model = body.model or get_setting(DEFAULT_MODEL_KEY, DEFAULT_MODEL_FALLBACK) or DEFAULT_MODEL_FALLBACK
        except Exception:
            model = body.model or "openai/gpt-4o-mini"
        yield _sse("meta", {"model": model, "sessionId": session_id})

        try:
            resp = await run_agent(model=model, messages=llm_msgs)
        except OpenRouterError as e:
            add_message(session_id=session_id, role="system", content=f"OpenRouter error: {e}", meta={"type": "error"})
            yield _sse("error", {"message": str(e)})
            return
        except Exception as e:  # noqa: BLE001
            add_message(session_id=session_id, role="system", content=f"Server error: {e}", meta={"type": "error"})
            yield _sse("error", {"message": f"Server error: {e}"})
            return

        # Persist new messages since last user message: easiest is to persist the final assistant content only for now,
        # plus any tool messages from the runner's internal message list.
        msgs_all = resp.get("_ochre_messages") or []
        # Find the index of the last user message we just inserted (best-effort: last role=user).
        last_user_idx = -1
        for i in range(len(msgs_all) - 1, -1, -1):
            if msgs_all[i].get("role") == "user":
                last_user_idx = i
                break

        new_msgs = msgs_all[last_user_idx + 1 :] if last_user_idx >= 0 else msgs_all
        for m in new_msgs:
            role = m.get("role")
            if role not in ("assistant", "tool", "system"):
                continue
            content = m.get("content")
            meta: dict[str, Any] = {}
            for k in ("name", "tool_call_id", "tool_calls"):
                if k in m:
                    meta[k] = m[k]
            
            if "args" in m:
                meta["argsPreview"] = str(m["args"])

            add_message(session_id=session_id, role=role, content=content, meta=meta)

        # Stream final assistant content in chunks.
        choice = (resp.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        content = msg.get("content") or ""
        for i in range(0, len(content), 120):
            yield _sse("delta", {"text": content[i : i + 120]})
        yield _sse("done", {"ok": True})

    return StreamingResponse(gen(), media_type="text/event-stream")


