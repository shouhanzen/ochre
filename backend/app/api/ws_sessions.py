from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.conversation.hub import get_model
from app.sessions.store import get_session
from app.ws.hub import register, unregister
from app.logging.ndjson import log_event


router = APIRouter()


@router.websocket("/ws/sessions/{session_id}")
async def ws_session(session_id: str, ws: WebSocket) -> None:
    if not get_session(session_id):
        await ws.close(code=1008)
        return

    disconnect_code: int | None = None
    await ws.accept()
    await register(session_id, ws)
    model = await get_model(session_id)
    log_event(
        level="info",
        event="ws.connect",
        sessionId=session_id,
        data={
            "client": getattr(ws.client, "host", None),
            "headers": {
                "origin": ws.headers.get("origin"),
                "user_agent": ws.headers.get("user-agent"),
                "x_forwarded_for": ws.headers.get("x-forwarded-for"),
                "x_real_ip": ws.headers.get("x-real-ip"),
            },
        },
    )

    try:
        while True:
            try:
                msg = await ws.receive_json()
            except WebSocketDisconnect as e:
                disconnect_code = getattr(e, "code", None)
                raise
            except Exception as e:  # noqa: BLE001
                log_event(level="warn", event="ws.receive_error", sessionId=session_id, data={"error": str(e)})
                try:
                    await ws.close(code=1003)
                except Exception:
                    pass
                return
            mtype = msg.get("type")
            request_id = msg.get("requestId")
            payload = msg.get("payload") or {}

            if mtype == "hello":
                view = await model.snapshot_view()
                await ws.send_json({"type": "snapshot", "requestId": None, "payload": view})
                continue

            if mtype != "chat.send":
                await ws.send_json({"type": "chat.error", "requestId": request_id, "payload": {"message": "Unknown type"}})
                continue

            content = str(payload.get("content") or "").strip()
            if not content:
                continue
            rid = str(request_id or "").strip()
            if not rid:
                await ws.send_json({"type": "chat.error", "requestId": None, "payload": {"message": "Missing requestId"}})
                continue

            log_event(level="info", event="ws.chat.send", sessionId=session_id, requestId=rid, data={"contentLen": len(content)})
            await model.submit_user_message(request_id=rid, content=content)

    except WebSocketDisconnect as e:
        disconnect_code = getattr(e, "code", None)
        pass
    finally:
        await unregister(session_id, ws)
        log_event(
            level="info",
            event="ws.disconnect",
            sessionId=session_id,
            data={"code": disconnect_code, "client": getattr(ws.client, "host", None)},
        )


