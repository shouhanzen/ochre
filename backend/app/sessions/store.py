from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional
from uuid import uuid4

from app.db import connect


@dataclass
class SessionRow:
    id: str
    title: Optional[str]
    created_at: str
    last_active_at: str


@dataclass
class MessageRow:
    id: str
    session_id: str
    role: str
    content: Optional[str]
    created_at: str
    meta: dict[str, Any]


def create_session(*, title: Optional[str] = None) -> SessionRow:
    sid = str(uuid4())
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO sessions(id, title, created_at, last_active_at) VALUES(?, ?, datetime('now'), datetime('now'))",
            (sid, title),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
        assert row is not None
        return SessionRow(**dict(row))
    finally:
        conn.close()


def list_sessions(*, limit: int = 50) -> list[SessionRow]:
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT * FROM sessions ORDER BY last_active_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [SessionRow(**dict(r)) for r in rows]
    finally:
        conn.close()


def get_session(session_id: str) -> Optional[SessionRow]:
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        return SessionRow(**dict(row)) if row else None
    finally:
        conn.close()


def touch_session(session_id: str) -> None:
    conn = connect()
    try:
        conn.execute("UPDATE sessions SET last_active_at=datetime('now') WHERE id=?", (session_id,))
        conn.commit()
    finally:
        conn.close()


def add_message(
    *,
    session_id: str,
    role: str,
    content: Optional[str],
    meta: Optional[dict[str, Any]] = None,
) -> MessageRow:
    mid = str(uuid4())
    meta_json = json.dumps(meta or {}, ensure_ascii=False)
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO messages(id, session_id, role, content, created_at, meta_json) "
            "VALUES(?, ?, ?, ?, datetime('now'), ?)",
            (mid, session_id, role, content, meta_json),
        )
        conn.execute("UPDATE sessions SET last_active_at=datetime('now') WHERE id=?", (session_id,))
        conn.commit()
        row = conn.execute("SELECT * FROM messages WHERE id=?", (mid,)).fetchone()
        assert row is not None
        return _row_to_message(row)
    finally:
        conn.close()


def update_message_content(message_id: str, *, content: str, meta: Optional[dict[str, Any]] = None) -> None:
    """
    Update content (and optionally meta_json) for an existing message.
    Useful for persisting partial assistant output on cancellation.
    """
    conn = connect()
    try:
        if meta is None:
            conn.execute("UPDATE messages SET content=? WHERE id=?", (content, message_id))
        else:
            # Merge meta into existing meta_json rather than overwriting it.
            # This prevents accidental loss of fields like assistant tool_calls, which must stay linked to tool outputs.
            try:
                row = conn.execute("SELECT meta_json FROM messages WHERE id=?", (message_id,)).fetchone()
                existing_raw = (row["meta_json"] if row else None) or "{}"
                existing = json.loads(existing_raw)
                existing = existing if isinstance(existing, dict) else {"meta": existing}
            except Exception:
                existing = {}
            merged = {**existing, **(meta or {})}
            meta_json = json.dumps(merged, ensure_ascii=False)
            conn.execute("UPDATE messages SET content=?, meta_json=? WHERE id=?", (content, meta_json, message_id))
        conn.commit()
    finally:
        conn.close()


def list_messages(session_id: str, *, limit: int = 200) -> list[MessageRow]:
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT * FROM messages WHERE session_id=? ORDER BY created_at ASC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        return [_row_to_message(r) for r in rows]
    finally:
        conn.close()


def _row_to_message(row: Any) -> MessageRow:
    meta_raw = row["meta_json"] or "{}"
    try:
        meta = json.loads(meta_raw)
    except Exception:
        meta = {"_raw": meta_raw}
    return MessageRow(
        id=row["id"],
        session_id=row["session_id"],
        role=row["role"],
        content=row["content"],
        created_at=row["created_at"],
        meta=meta if isinstance(meta, dict) else {"meta": meta},
    )


def messages_for_llm(session_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
    msgs = list_messages(session_id, limit=limit)
    # Only include tool outputs that have a corresponding assistant tool_call id in the same history.
    # Providers reject tool outputs that can't be linked to a tool call ("No tool call found for ... call_id").
    valid_call_ids: set[str] = set()
    for m in msgs:
        if m.role != "assistant":
            continue
        tc = (m.meta or {}).get("tool_calls")
        if not isinstance(tc, list):
            continue
        for item in tc:
            if isinstance(item, dict):
                cid = item.get("id")
                if isinstance(cid, str) and cid:
                    valid_call_ids.add(cid)
    out: list[dict[str, Any]] = []
    for m in msgs:
        if m.role == "tool":
            tcid = (m.meta or {}).get("tool_call_id")
            if not (isinstance(tcid, str) and tcid and tcid in valid_call_ids):
                continue
        d: dict[str, Any] = {"role": m.role}
        if m.content is not None:
            d["content"] = m.content
        # carry through known tool fields if present
        for k in ("name", "tool_call_id", "tool_calls"):
            if k in m.meta:
                d[k] = m.meta[k]
        out.append(d)
    return out


