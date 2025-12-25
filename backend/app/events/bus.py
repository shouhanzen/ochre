from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, AsyncIterator, DefaultDict
from uuid import uuid4

from app.db import connect
from app.sessions.store import add_message
from app.ws.hub import send as ws_send


@dataclass
class Event:
    id: str
    session_id: str
    type: str
    payload: dict[str, Any]
    created_at: str


_subscribers: DefaultDict[str, set[asyncio.Queue[Event]]] = DefaultDict(set)
_lock = asyncio.Lock()


def _insert_event(session_id: str, type_: str, payload: dict[str, Any]) -> Event:
    eid = str(uuid4())
    payload_json = json.dumps(payload, ensure_ascii=False)
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO events(id, session_id, type, payload_json, created_at) "
            "VALUES(?, ?, ?, ?, datetime('now'))",
            (eid, session_id, type_, payload_json),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM events WHERE id=?", (eid,)).fetchone()
        assert row is not None
        return Event(
            id=row["id"],
            session_id=row["session_id"],
            type=row["type"],
            payload=json.loads(row["payload_json"]) if row["payload_json"] else {},
            created_at=row["created_at"],
        )
    finally:
        conn.close()


async def emit_event(session_id: str, type_: str, payload: dict[str, Any]) -> Event:
    """
    Persist event to SQLite and publish to live SSE subscribers.
    If payload includes `system_message`, also persists it as a role=system chat message for replay.
    """
    if "system_message" in payload and isinstance(payload["system_message"], str):
        add_message(
            session_id=session_id,
            role="system",
            content=payload["system_message"],
            meta={"type": type_},
        )

    ev = _insert_event(session_id, type_, payload)
    async with _lock:
        queues = list(_subscribers.get(session_id, set()))
    for q in queues:
        # best-effort, drop if backpressure
        try:
            q.put_nowait(ev)
        except asyncio.QueueFull:
            pass
    # best-effort WS broadcast
    try:
        await ws_send(
            session_id,
            {
                "type": "system.message" if "system_message" in payload else "event",
                "requestId": None,
                "payload": {"content": payload.get("system_message")} if "system_message" in payload else payload,
            },
        )
    except Exception:
        pass
    return ev


async def subscribe(session_id: str) -> AsyncIterator[Event]:
    q: asyncio.Queue[Event] = asyncio.Queue(maxsize=100)
    async with _lock:
        _subscribers[session_id].add(q)

    try:
        while True:
            ev = await q.get()
            yield ev
    finally:
        async with _lock:
            _subscribers[session_id].discard(q)


