from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from app.agent.stream_runner import run_tool_loop_streaming
from app.api.settings import DEFAULT_MODEL_FALLBACK, DEFAULT_MODEL_KEY
from app.sessions.store import add_message, list_messages, messages_for_llm, update_message_content
from app.settings.store import get_setting
from app.ws.hub import send


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _truncate(s: str, *, max_chars: int) -> tuple[str, bool]:
    if len(s) <= max_chars:
        return s, False
    return s[:max_chars] + f"\n... (truncated, {len(s) - max_chars} chars omitted)", True


@dataclass
class OpenAssistant:
    message_id: str
    buffer_text: str


@dataclass
class ActiveRun:
    request_id: str
    model: str
    status: str  # running|done|error|cancelled
    started_at: str
    ended_at: Optional[str]
    cancel_event: asyncio.Event
    task: Optional[asyncio.Task]
    open_assistant: Optional[OpenAssistant]


class ConversationModel:
    """
    Single source of truth for a session's in-flight run + transcript persistence.
    """

    def __init__(self, *, session_id: str) -> None:
        self.session_id = session_id
        self.lock = asyncio.Lock()
        self.active_run: Optional[ActiveRun] = None
        self._seen_request_ids: dict[str, str] = {}  # requestId -> status

    async def snapshot_view(self) -> dict[str, Any]:
        """
        Render-ready view for reconnect/resync.
        """
        async with self.lock:
            ar = self.active_run
            overlays: dict[str, Any] = {}
            active_run_view: Optional[dict[str, Any]] = None
            if ar is not None:
                active_run_view = {
                    "requestId": ar.request_id,
                    "status": ar.status,
                    "startedAt": ar.started_at,
                    "endedAt": ar.ended_at,
                    "model": ar.model,
                }
                if ar.open_assistant is not None:
                    overlays["assistant"] = {
                        "messageId": ar.open_assistant.message_id,
                        "content": ar.open_assistant.buffer_text,
                    }

        msgs = list_messages(self.session_id, limit=400)
        return {
            "sessionId": self.session_id,
            "messages": [m.__dict__ for m in msgs],
            "activeRun": active_run_view,
            "overlays": overlays or None,
        }

    async def submit_user_message(self, *, request_id: str, content: str, model: Optional[str] = None) -> None:
        """
        Idempotent submit; starts (or re-acks) a run.
        """
        content = (content or "").strip()
        if not content:
            return

        async with self.lock:
            # Idempotency: if we've seen this requestId, just re-emit a started signal.
            if request_id in self._seen_request_ids and (self.active_run is None or self.active_run.request_id != request_id):
                asyncio.create_task(
                    send(self.session_id, {"type": "chat.started", "requestId": request_id, "payload": {"messageId": None}})
                )
                return

            # Cancel in-flight run (if any) for a different requestId.
            if self.active_run is not None and self.active_run.status == "running" and self.active_run.request_id != request_id:
                await self._cancel_inflight_locked(reason="new_message")

            chosen_model = model or get_setting(DEFAULT_MODEL_KEY, DEFAULT_MODEL_FALLBACK) or DEFAULT_MODEL_FALLBACK

            add_message(session_id=self.session_id, role="user", content=content, meta={"requestId": request_id})

            self.active_run = ActiveRun(
                request_id=request_id,
                model=chosen_model,
                status="running",
                started_at=_now_iso(),
                ended_at=None,
                cancel_event=asyncio.Event(),
                task=None,
                open_assistant=None,
            )
            self._seen_request_ids[request_id] = "running"

            # Ack acceptance (assistant segment messageId is created on first token).
            asyncio.create_task(send(self.session_id, {"type": "chat.started", "requestId": request_id, "payload": {"messageId": None}}))

            cancel_event = self.active_run.cancel_event
            self.active_run.task = asyncio.create_task(self._run_generation(request_id=request_id, model=chosen_model, cancel_event=cancel_event))

    async def _cancel_inflight_locked(self, *, reason: str) -> None:
        ar = self.active_run
        if ar is None or ar.status != "running":
            return
        ar.cancel_event.set()
        if ar.task and not ar.task.done():
            ar.task.cancel()
            try:
                await ar.task
            except Exception:
                pass

        # Flush any open assistant segment to DB as cancelled.
        await self._flush_open_assistant_locked(meta={"cancelled": True, "streaming": False})

        ar.status = "cancelled"
        ar.ended_at = _now_iso()
        self._seen_request_ids[ar.request_id] = "cancelled"

        add_message(
            session_id=self.session_id,
            role="system",
            content="Generation cancelled (new user message).",
            meta={"type": "cancel", "requestId": ar.request_id, "reason": reason},
        )
        asyncio.create_task(
            send(
                self.session_id,
                {"type": "system.message", "requestId": ar.request_id, "payload": {"content": "Generation cancelled (new user message)."}},
            )
        )
        asyncio.create_task(send(self.session_id, {"type": "chat.cancelled", "requestId": ar.request_id, "payload": {"reason": reason}}))

        self.active_run = None

    async def _run_generation(self, *, request_id: str, model: str, cancel_event: asyncio.Event) -> None:
        try:
            llm_msgs = messages_for_llm(self.session_id)

            def on_event(ev: dict[str, Any]) -> None:
                et = str(ev.get("type") or "")
                payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {"payload": ev.get("payload")}
                if et == "chat.delta":
                    self._on_chat_delta(request_id=request_id, text=str(payload.get("text") or ""))
                    return
                if et == "tool.start":
                    self._on_tool_start(request_id=request_id, tool=str(payload.get("tool") or ""), args_preview=str(payload.get("argsPreview") or ""))
                    return
                if et == "tool.end":
                    self._on_tool_end(
                        request_id=request_id,
                        tool=str(payload.get("tool") or ""),
                        ok=bool(payload.get("ok", True)),
                        duration_ms=int(payload.get("durationMs") or 0),
                    )
                    return
                if et == "tool.output":
                    self._on_tool_output(request_id=request_id, tool=str(payload.get("tool") or ""), content=str(payload.get("content") or ""))
                    return
                # forward unknown events as-is
                asyncio.create_task(send(self.session_id, {"type": et, "requestId": request_id, "payload": payload}))

            text, _full_msgs = await run_tool_loop_streaming(
                model=model,
                base_messages=llm_msgs,
                on_event=on_event,
                cancel_event=cancel_event,
            )
            _ = text

            async with self.lock:
                # If a new run started, ignore completion from stale task.
                if not self.active_run or self.active_run.request_id != request_id:
                    return
                if self.active_run.cancel_event.is_set():
                    return
                await self._flush_open_assistant_locked(meta={"streaming": False})
                self.active_run.status = "done"
                self.active_run.ended_at = _now_iso()
                self._seen_request_ids[request_id] = "done"
                asyncio.create_task(send(self.session_id, {"type": "chat.done", "requestId": request_id, "payload": {"ok": True}}))
                self.active_run = None
        except asyncio.CancelledError:
            # Cancellation is handled by the canceller (new user message path).
            return
        except Exception as e:  # noqa: BLE001
            async with self.lock:
                if self.active_run and self.active_run.request_id == request_id:
                    await self._flush_open_assistant_locked(meta={"streaming": False, "error": True})
                    self.active_run.status = "error"
                    self.active_run.ended_at = _now_iso()
                    self._seen_request_ids[request_id] = "error"
                    add_message(
                        session_id=self.session_id,
                        role="system",
                        content=f"Chat error: {e}",
                        meta={"type": "error", "requestId": request_id},
                    )
                    asyncio.create_task(
                        send(
                            self.session_id,
                            {"type": "system.message", "requestId": request_id, "payload": {"content": f"Chat error: {e}"}},
                        )
                    )
                    asyncio.create_task(send(self.session_id, {"type": "chat.error", "requestId": request_id, "payload": {"message": str(e)}}))
                    self.active_run = None

    def _ensure_open_assistant(self, *, request_id: str) -> Optional[str]:
        """
        Create assistant segment message row on first token.
        Must only be called from the streaming task.
        """
        ar = self.active_run
        if ar is None or ar.request_id != request_id or ar.status != "running":
            return None
        if ar.open_assistant is not None:
            return ar.open_assistant.message_id
        row = add_message(
            session_id=self.session_id,
            role="assistant",
            content="",
            meta={"streaming": True, "requestId": request_id, "segment": True},
        )
        ar.open_assistant = OpenAssistant(message_id=row.id, buffer_text="")
        asyncio.create_task(send(self.session_id, {"type": "assistant.segment.started", "requestId": request_id, "payload": {"messageId": row.id}}))
        return row.id

    def _on_chat_delta(self, *, request_id: str, text: str) -> None:
        if not text:
            return
        # Best-effort: mutate state without awaiting; cancels/flushes happen under lock elsewhere.
        ar = self.active_run
        if ar is None or ar.request_id != request_id or ar.status != "running":
            return
        mid = self._ensure_open_assistant(request_id=request_id)
        if mid is None or ar.open_assistant is None:
            return
        ar.open_assistant.buffer_text += text
        asyncio.create_task(
            send(self.session_id, {"type": "chat.delta", "requestId": request_id, "payload": {"text": text, "messageId": mid}})
        )

    def _on_tool_start(self, *, request_id: str, tool: str, args_preview: str) -> None:
        ar = self.active_run
        if ar is None or ar.request_id != request_id or ar.status != "running":
            return
        # Tool boundary closes any open assistant segment.
        if ar.open_assistant is not None:
            try:
                update_message_content(
                    ar.open_assistant.message_id,
                    content=ar.open_assistant.buffer_text,
                    meta={"streaming": False, "requestId": request_id, "segment": True},
                )
            except Exception:
                pass
            ar.open_assistant = None

        line = f"▶ {tool} {args_preview}".rstrip() if args_preview else f"▶ {tool}"
        add_message(session_id=self.session_id, role="tool", content=line, meta={"name": tool, "requestId": request_id})
        asyncio.create_task(send(self.session_id, {"type": "tool.start", "requestId": request_id, "payload": {"tool": tool, "argsPreview": args_preview}}))

    def _on_tool_end(self, *, request_id: str, tool: str, ok: bool, duration_ms: int) -> None:
        ar = self.active_run
        if ar is None or ar.request_id != request_id or ar.status != "running":
            return
        line = f"■ {tool} {'ok' if ok else 'error'} ({duration_ms}ms)"
        add_message(session_id=self.session_id, role="tool", content=line, meta={"name": tool, "requestId": request_id})
        asyncio.create_task(
            send(
                self.session_id,
                {"type": "tool.end", "requestId": request_id, "payload": {"tool": tool, "ok": ok, "durationMs": duration_ms}},
            )
        )

    def _on_tool_output(self, *, request_id: str, tool: str, content: str) -> None:
        ar = self.active_run
        if ar is None or ar.request_id != request_id or ar.status != "running":
            return
        # Persist full tool output to DB (may be large).
        add_message(session_id=self.session_id, role="tool", content=content, meta={"name": tool, "requestId": request_id})

        preview, truncated = _truncate(content, max_chars=20_000)
        asyncio.create_task(
            send(
                self.session_id,
                {"type": "tool.output", "requestId": request_id, "payload": {"tool": tool, "content": preview, "truncated": truncated}},
            )
        )

    async def _flush_open_assistant_locked(self, *, meta: dict[str, Any]) -> None:
        ar = self.active_run
        if ar is None or ar.open_assistant is None:
            return
        try:
            update_message_content(
                ar.open_assistant.message_id,
                content=ar.open_assistant.buffer_text,
                meta={**meta, "requestId": ar.request_id, "segment": True},
            )
        except Exception:
            pass
        ar.open_assistant = None

