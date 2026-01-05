from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

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
    return s[:max_chars] + "...", True


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
    open_assistant: Optional[OpenAssistant] = None
    tool_meta: dict[str, dict[str, Any]] = None

    def __post_init__(self):
        if self.tool_meta is None:
            self.tool_meta = {}


class ConversationModel:
    """
    Single source of truth for a session's in-flight run + transcript persistence.
    """

    def __init__(self, *, session_id: str) -> None:
        self.session_id = session_id
        self.lock = asyncio.Lock()
        self.active_run: Optional[ActiveRun] = None
        self._seen_request_ids: dict[str, str] = {}  # requestId -> status
        # In-memory set of active skills for this session.
        self.active_skills: set[str] = set()

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

            active_skills_list = sorted(list(self.active_skills))

        msgs = list_messages(self.session_id, limit=400)
        return {
            "sessionId": self.session_id,
            "messages": [m.__dict__ for m in msgs],
            "activeRun": active_run_view,
            "overlays": overlays or None,
            "activeSkills": active_skills_list,
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
                tool_meta={},
            )
            self._seen_request_ids[request_id] = "running"

            # Ack acceptance (assistant segment messageId is created on first token).
            asyncio.create_task(send(self.session_id, {"type": "chat.started", "requestId": request_id, "payload": {"messageId": None}}))

            cancel_event = self.active_run.cancel_event
            self.active_run.task = asyncio.create_task(self._run_generation(request_id=request_id, model=chosen_model, cancel_event=cancel_event))

    async def _cancel_inflight_locked(self, *, reason: str) -> None:
        if self.active_run is None:
            return
        
        # Don't overwrite 'done' status if it finished naturally just now.
        if self.active_run.status == "running":
            self.active_run.status = "cancelled"
            self.active_run.ended_at = _now_iso()
            self.active_run.cancel_event.set()
            
            # Persist partial assistant output if any.
            if self.active_run.open_assistant:
                oa = self.active_run.open_assistant
                if oa.message_id and oa.buffer_text:
                     # Mark it as cancelled in meta if desired, but content update is main thing.
                     update_message_content(oa.message_id, content=oa.buffer_text)

        # Notify clients
        asyncio.create_task(send(self.session_id, {"type": "run.cancelled", "requestId": self.active_run.request_id, "payload": {"reason": reason}}))

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
                if et == "assistant.tool_calls":
                    self._on_assistant_tool_calls(request_id=request_id, tool_calls=payload.get("toolCalls"))
                    return
                if et == "chat.usage":
                    self._on_chat_usage(request_id=request_id, usage=payload)
                    return
                if et == "tool.start":
                    self._on_tool_start(
                        request_id=request_id,
                        tool=str(payload.get("tool") or ""),
                        tc_id=str(payload.get("tcId") or ""),
                        args_preview=str(payload.get("argsPreview") or ""),
                    )
                    return
                if et == "tool.end":
                    self._on_tool_end(
                        request_id=request_id,
                        tool=str(payload.get("tool") or ""),
                        tc_id=str(payload.get("tcId") or ""),
                        ok=bool(payload.get("ok", True)),
                        duration_ms=int(payload.get("durationMs") or 0),
                    )
                    return
                if et == "tool.output":
                    self._on_tool_output(
                        request_id=request_id,
                        tool=str(payload.get("tool") or ""),
                        tc_id=str(payload.get("tcId") or ""),
                        output=payload.get("output") or payload.get("content"),
                    )
                    return

            # Run the tool loop
            # Pass session context so tools can read active_skills
            final_text, final_msgs = await run_tool_loop_streaming(
                model=model,
                base_messages=llm_msgs,
                on_event=on_event,
                cancel_event=cancel_event,
                max_steps=10,
                session_id=self.session_id, # Pass session ID down
            )

            # Done. Persist the final assistant message (if not already done via delta updates or if we want to be sure).
            # The runner emits deltas, so the DB should be up to date if we handled deltas correctly.
            # But we might need to close out the run status.

            async with self.lock:
                if self.active_run and self.active_run.request_id == request_id:
                     self.active_run.status = "done"
                     self.active_run.ended_at = _now_iso()
                     # If we have a buffered assistant message, ensure it's finalized in DB
                     if self.active_run.open_assistant:
                         oa = self.active_run.open_assistant
                         update_message_content(oa.message_id, content=oa.buffer_text)
                         # Also emit chat.done
                         asyncio.create_task(send(self.session_id, {"type": "chat.done", "requestId": request_id, "payload": {"messageId": oa.message_id}}))
                     else:
                         # No assistant output (maybe just tools?), rare but possible.
                         asyncio.create_task(send(self.session_id, {"type": "chat.done", "requestId": request_id, "payload": {"messageId": None}}))
                     
                     self.active_run = None

        except asyncio.CancelledError:
             # Already handled in _cancel_inflight_locked usually, but if task cancelled externally:
             async with self.lock:
                 if self.active_run and self.active_run.request_id == request_id:
                     await self._cancel_inflight_locked(reason="task_cancelled")
        except Exception as e:
            # Error state
            import traceback
            traceback.print_exc()
            async with self.lock:
                if self.active_run and self.active_run.request_id == request_id:
                     self.active_run.status = "error"
                     self.active_run.ended_at = _now_iso()
                     asyncio.create_task(send(self.session_id, {"type": "run.error", "requestId": request_id, "payload": {"error": str(e)}}))
                     self.active_run = None

    def _on_chat_delta(self, *, request_id: str, text: str) -> None:
        # We need to append to the active run's buffer AND persist periodically (or on finish).
        # For responsiveness, we don't write DB on every token. We write on finish/cancel.
        # But we DO emit WS events.
        
        # NOTE: This runs in the task loop, so we need to be careful with lock if we modify self.active_run.
        # However, active_run object itself is mutable and owned by this task effectively.
        if not self.active_run or self.active_run.request_id != request_id:
            return

        if not self.active_run.open_assistant:
            # First token -> create message row
            oa_id = str(uuid4())
            # We insert directly to DB to get an ID
            add_message(session_id=self.session_id, role="assistant", content="", meta={"requestId": request_id})
            self.active_run.open_assistant = OpenAssistant(message_id=oa_id, buffer_text="")
            # Notify frontend of the message ID
            asyncio.create_task(send(self.session_id, {"type": "chat.started", "requestId": request_id, "payload": {"messageId": oa_id}}))
            # Also correct the previous message meta if needed? No, add_message returned a new row.
            # Wait, add_message generates its own ID. We need that ID.
            # Rework: add_message returns the row.
            # Let's fix this slightly: add_message was called above but we didn't capture ID?
            # actually add_message is synchronous DB call.
            # Let's do it properly:
            row = add_message(session_id=self.session_id, role="assistant", content="", meta={"requestId": request_id})
            self.active_run.open_assistant = OpenAssistant(message_id=row.id, buffer_text="")
            asyncio.create_task(send(self.session_id, {"type": "chat.started", "requestId": request_id, "payload": {"messageId": row.id}}))

        self.active_run.open_assistant.buffer_text += text
        asyncio.create_task(send(self.session_id, {"type": "chat.delta", "requestId": request_id, "payload": {"text": text, "messageId": self.active_run.open_assistant.message_id}}))

    def _on_assistant_tool_calls(self, *, request_id: str, tool_calls: list[dict[str, Any]]) -> None:
        if not self.active_run or self.active_run.request_id != request_id:
            return
        # We should persist these into the assistant message meta so they are preserved.
        if self.active_run.open_assistant:
             mid = self.active_run.open_assistant.message_id
             # We might get partials? usually tool_calls come in a chunk or final block.
             # For now, just update the DB meta.
             update_message_content(mid, content=self.active_run.open_assistant.buffer_text, meta={"tool_calls": tool_calls})

    def _on_chat_usage(self, *, request_id: str, usage: dict[str, Any]) -> None:
         asyncio.create_task(send(self.session_id, {"type": "chat.usage", "requestId": request_id, "payload": usage}))

    def _on_tool_start(self, *, request_id: str, tool: str, tc_id: str, args_preview: str) -> None:
         # Persist tool invocation as a message? 
         # The standard is usually: User -> Assistant (calls tool) -> Tool (output) -> Assistant.
         # The tool call itself is part of Assistant message.
         # The output is a separate message.
         # Here we just emit event for UI.
         if self.active_run and self.active_run.request_id == request_id:
             self.active_run.tool_meta[tc_id] = {"argsPreview": args_preview}
         
         asyncio.create_task(send(self.session_id, {"type": "tool.start", "requestId": request_id, "payload": {"tool": tool, "tcId": tc_id, "argsPreview": args_preview}}))

    def _on_tool_end(self, *, request_id: str, tool: str, tc_id: str, ok: bool, duration_ms: int) -> None:
         asyncio.create_task(send(self.session_id, {"type": "tool.end", "requestId": request_id, "payload": {"tool": tool, "tcId": tc_id, "ok": ok, "durationMs": duration_ms}}))

    def _on_tool_output(self, *, request_id: str, tool: str, tc_id: str, output: Any) -> None:
        # Create a tool message in the transcript
        import json
        content = json.dumps(output, ensure_ascii=False) if not isinstance(output, str) else output
        
        meta = {"requestId": request_id, "tool_call_id": tc_id, "name": tool}
        if self.active_run and self.active_run.request_id == request_id:
            tm = self.active_run.tool_meta.get(tc_id)
            if tm and "argsPreview" in tm:
                meta["argsPreview"] = tm["argsPreview"]

        add_message(session_id=self.session_id, role="tool", content=content, meta=meta)
        asyncio.create_task(send(self.session_id, {"type": "tool.output", "requestId": request_id, "payload": {"tool": tool, "tcId": tc_id, "output": output}}))
