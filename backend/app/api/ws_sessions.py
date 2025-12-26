from __future__ import annotations

import asyncio
from typing import Any, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.agent.stream_runner import run_tool_loop_streaming
from app.api.settings import DEFAULT_MODEL_FALLBACK, DEFAULT_MODEL_KEY
from app.sessions.store import add_message, get_session, messages_for_llm, update_message_content
from app.settings.store import get_setting
from app.ws.hub import register, send, unregister
from app.logging.ndjson import log_event


router = APIRouter()


class InFlight:
    def __init__(self) -> None:
        self.task: Optional[asyncio.Task] = None
        self.cancel_event = asyncio.Event()
        self.assistant_message_id: Optional[str] = None
        self.assistant_text: str = ""
        self.lock = asyncio.Lock()


_inflight: dict[str, InFlight] = {}


def _get_state(session_id: str) -> InFlight:
    st = _inflight.get(session_id)
    if st is None:
        st = InFlight()
        _inflight[session_id] = st
    return st


@router.websocket("/ws/sessions/{session_id}")
async def ws_session(session_id: str, ws: WebSocket) -> None:
    if not get_session(session_id):
        await ws.close(code=1008)
        return

    await ws.accept()
    await register(session_id, ws)
    st = _get_state(session_id)

    try:
        while True:
            msg = await ws.receive_json()
            mtype = msg.get("type")
            request_id = msg.get("requestId")
            payload = msg.get("payload") or {}

            if mtype != "chat.send":
                await ws.send_json({"type": "chat.error", "requestId": request_id, "payload": {"message": "Unknown type"}})
                continue

            content = str(payload.get("content") or "").strip()
            if not content:
                continue

            async with st.lock:
                log_event(
                    level="info",
                    event="ws.chat.send",
                    sessionId=session_id,
                    requestId=str(request_id or ""),
                    data={"contentLen": len(content)},
                )
                # cancel any inflight
                if st.task and not st.task.done():
                    st.cancel_event.set()
                    st.task.cancel()
                    try:
                        await st.task
                    except Exception:
                        pass
                    # persist partial assistant
                    if st.assistant_message_id is not None:
                        update_message_content(
                            st.assistant_message_id,
                            content=st.assistant_text,
                            meta={"cancelled": True},
                        )
                    add_message(
                        session_id=session_id,
                        role="system",
                        content="Generation cancelled (new user message).",
                        meta={"type": "cancel"},
                    )
                    log_event(
                        level="info",
                        event="ws.chat.cancel",
                        sessionId=session_id,
                        requestId=str(request_id or ""),
                        data={"reason": "new_message"},
                    )
                    await send(
                        session_id,
                        {"type": "chat.cancelled", "requestId": request_id, "payload": {"reason": "new_message"}},
                    )

                st.cancel_event = asyncio.Event()
                st.assistant_message_id = None
                st.assistant_text = ""

                # Persist user message
                add_message(session_id=session_id, role="user", content=content, meta={})

                # Create assistant message placeholder for partial persistence
                assistant_row = add_message(session_id=session_id, role="assistant", content="", meta={"streaming": True})
                st.assistant_message_id = assistant_row.id

                model = get_setting(DEFAULT_MODEL_KEY, DEFAULT_MODEL_FALLBACK) or DEFAULT_MODEL_FALLBACK

                await ws.send_json({"type": "chat.started", "requestId": request_id, "payload": {"messageId": assistant_row.id}})
                log_event(
                    level="info",
                    event="ws.chat.started",
                    sessionId=session_id,
                    requestId=str(request_id or ""),
                    data={"messageId": assistant_row.id, "model": model},
                )

                async def run_generation() -> None:
                    try:
                        llm_msgs = messages_for_llm(session_id)

                        def on_event(ev: dict[str, Any]) -> None:
                            # ev is like {type:'chat.delta', payload:{text}}
                            et = str(ev.get("type") or "")
                            if et and et != "chat.delta":
                                log_event(
                                    level="info",
                                    event=f"agent.event.{et}",
                                    sessionId=session_id,
                                    requestId=str(request_id or ""),
                                    data=ev.get("payload") if isinstance(ev.get("payload"), dict) else {"payload": ev.get("payload")},
                                )
                            asyncio.create_task(send(session_id, {"type": ev["type"], "requestId": request_id, "payload": ev.get("payload", {})}))

                        text, full_msgs = await run_tool_loop_streaming(
                            model=model,
                            base_messages=llm_msgs,
                            on_event=on_event,
                            cancel_event=st.cancel_event,
                        )
                        st.assistant_text = text

                        if st.cancel_event.is_set():
                            # cancel handled by caller, but ensure persisted partial
                            if st.assistant_message_id is not None:
                                update_message_content(st.assistant_message_id, content=st.assistant_text, meta={"cancelled": True})
                            return

                        # Persist tool messages and final assistant message content/meta
                        # Note: we already inserted an assistant placeholder; update it with final content.
                        if st.assistant_message_id is not None:
                            update_message_content(st.assistant_message_id, content=st.assistant_text, meta={"streaming": False})

                        # Persist tool messages and any additional assistant messages (tool-call wrappers)
                        for m in full_msgs[len(llm_msgs) :]:
                            role = m.get("role")
                            if role == "tool":
                                add_message(
                                    session_id=session_id,
                                    role="tool",
                                    content=m.get("content"),
                                    meta={"name": m.get("name"), "tool_call_id": m.get("tool_call_id")},
                                )
                                log_event(
                                    level="info",
                                    event="agent.tool.result",
                                    sessionId=session_id,
                                    requestId=str(request_id or ""),
                                    toolCallId=str(m.get("tool_call_id") or ""),
                                    data={"name": m.get("name"), "contentLen": len(str(m.get("content") or ""))},
                                )
                            elif role == "assistant" and m.get("tool_calls"):
                                add_message(
                                    session_id=session_id,
                                    role="assistant",
                                    content=m.get("content"),
                                    meta={"tool_calls": m.get("tool_calls")},
                                )

                        await send(session_id, {"type": "chat.done", "requestId": request_id, "payload": {"ok": True}})
                        log_event(
                            level="info",
                            event="ws.chat.done",
                            sessionId=session_id,
                            requestId=str(request_id or ""),
                            data={"ok": True, "assistantChars": len(st.assistant_text)},
                        )
                    except asyncio.CancelledError:
                        # Persist partial and exit
                        if st.assistant_message_id is not None:
                            update_message_content(
                                st.assistant_message_id,
                                content=st.assistant_text,
                                meta={"cancelled": True, "streaming": False},
                            )
                        add_message(
                            session_id=session_id,
                            role="system",
                            content="Generation cancelled.",
                            meta={"type": "cancel"},
                        )
                        log_event(
                            level="info",
                            event="ws.chat.cancel",
                            sessionId=session_id,
                            requestId=str(request_id or ""),
                            data={"reason": "cancelled"},
                        )
                    except Exception as e:  # noqa: BLE001
                        log_event(
                            level="error",
                            event="ws.chat.error",
                            sessionId=session_id,
                            requestId=str(request_id or ""),
                            data={"error": str(e)},
                        )
                        await send(session_id, {"type": "chat.error", "requestId": request_id, "payload": {"message": str(e)}})

                st.task = asyncio.create_task(run_generation())

    except WebSocketDisconnect:
        pass
    finally:
        await unregister(session_id, ws)


