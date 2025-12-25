from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Optional

from app.db import connect
from app.notion.client import NotionClient, NotionError
from app.notion.config import is_configured, notion_database_id, notion_status_property, notion_tags_property


DEFAULT_BOARD_ID = "default"


class NotionCacheError(RuntimeError):
    pass


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


async def ensure_default_board() -> None:
    if not is_configured():
        return
    conn = connect()
    try:
        row = conn.execute("SELECT id FROM notion_boards WHERE id=?", (DEFAULT_BOARD_ID,)).fetchone()
        if row:
            return
        # best-effort fetch name
        client = NotionClient()
        db = await client.retrieve_database(notion_database_id())
        name = _extract_db_title(db) or "Notion Board"
        conn.execute(
            "INSERT INTO notion_boards(id, name, database_id, status_property, updated_at, last_sync_at) "
            "VALUES(?, ?, ?, ?, ?, ?)",
            (DEFAULT_BOARD_ID, name, notion_database_id(), notion_status_property(), None, None),
        )
        conn.commit()
    finally:
        conn.close()


def list_boards() -> list[dict[str, Any]]:
    conn = connect()
    try:
        rows = conn.execute("SELECT * FROM notion_boards ORDER BY name ASC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_board(board_id: str) -> Optional[dict[str, Any]]:
    conn = connect()
    try:
        r = conn.execute("SELECT * FROM notion_boards WHERE id=?", (board_id,)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def list_cards(board_id: str) -> list[dict[str, Any]]:
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT * FROM notion_cards WHERE board_id=? ORDER BY cached_at DESC",
            (board_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_card(board_id: str, card_id: str) -> Optional[dict[str, Any]]:
    conn = connect()
    try:
        r = conn.execute(
            "SELECT * FROM notion_cards WHERE board_id=? AND id=?",
            (board_id, card_id),
        ).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def get_overlay(card_id: str) -> Optional[dict[str, Any]]:
    conn = connect()
    try:
        r = conn.execute("SELECT * FROM notion_overlays WHERE card_id=?", (card_id,)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def upsert_overlay(*, board_id: str, card_id: str, content_md: str) -> None:
    conn = connect()
    try:
        now = _now_iso()
        conn.execute(
            "INSERT INTO notion_overlays(card_id, board_id, content_md, created_at, updated_at) "
            "VALUES(?, ?, ?, ?, ?) "
            "ON CONFLICT(card_id) DO UPDATE SET content_md=excluded.content_md, updated_at=excluded.updated_at",
            (card_id, board_id, content_md, now, now),
        )
        conn.commit()
    finally:
        conn.close()


def delete_overlay(card_id: str) -> None:
    conn = connect()
    try:
        conn.execute("DELETE FROM notion_overlays WHERE card_id=?", (card_id,))
        conn.commit()
    finally:
        conn.close()


def list_pending_overlays(board_id: Optional[str] = None) -> list[dict[str, Any]]:
    conn = connect()
    try:
        if board_id:
            rows = conn.execute(
                "SELECT * FROM notion_overlays WHERE board_id=? ORDER BY updated_at DESC",
                (board_id,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM notion_overlays ORDER BY updated_at DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _is_stale(last_sync_at: Optional[str], *, max_age_seconds: int) -> bool:
    if not last_sync_at:
        return True
    try:
        dt = datetime.fromisoformat(last_sync_at)
    except Exception:
        return True
    return datetime.now() - dt > timedelta(seconds=max_age_seconds)


async def refresh_board_if_stale(board_id: str, *, max_age_seconds: int = 90) -> dict[str, Any]:
    if not is_configured():
        raise NotionCacheError("Notion is not configured (set NOTION_API_KEY and NOTION_DATABASE_ID)")

    await ensure_default_board()
    board = get_board(board_id)
    if not board:
        raise NotionCacheError("Board not found")
    if not _is_stale(board.get("last_sync_at"), max_age_seconds=max_age_seconds):
        return {"ok": True, "refreshed": False, "boardId": board_id}
    await refresh_board(board_id)
    return {"ok": True, "refreshed": True, "boardId": board_id}


async def refresh_board(board_id: str) -> None:
    if not is_configured():
        raise NotionCacheError("Notion is not configured")
    await ensure_default_board()
    board = get_board(board_id)
    if not board:
        raise NotionCacheError("Board not found")

    client = NotionClient()
    dbid = board["database_id"]
    status_prop = board["status_property"]
    tags_prop = notion_tags_property()

    cursor: Optional[str] = None
    pages: list[dict[str, Any]] = []
    while True:
        res = await client.query_database(dbid, start_cursor=cursor)
        pages.extend(res.get("results") or [])
        if not res.get("has_more"):
            break
        cursor = res.get("next_cursor")

    now = _now_iso()
    conn = connect()
    try:
        for p in pages:
            page_id = p.get("id")
            props = p.get("properties") or {}
            title = _extract_title(props) or f"Untitled ({page_id})"
            status = _extract_status(props, status_prop)
            tags = _extract_tags(props, tags_prop)
            notion_updated_at = p.get("last_edited_time")
            conn.execute(
                "INSERT INTO notion_cards(id, board_id, title, status, tags_json, body_md, notion_updated_at, cached_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET "
                "board_id=excluded.board_id, title=excluded.title, status=excluded.status, tags_json=excluded.tags_json, "
                "notion_updated_at=excluded.notion_updated_at, cached_at=excluded.cached_at",
                (
                    page_id,
                    board_id,
                    title,
                    status,
                    json.dumps(tags, ensure_ascii=False),
                    None,
                    notion_updated_at,
                    now,
                ),
            )
        conn.execute("UPDATE notion_boards SET last_sync_at=? WHERE id=?", (now, board_id))
        conn.commit()
    finally:
        conn.close()


def _extract_db_title(db: dict[str, Any]) -> Optional[str]:
    title = db.get("title") or []
    if isinstance(title, list) and title:
        t0 = title[0]
        if isinstance(t0, dict):
            return t0.get("plain_text")
    return None


def _extract_title(props: dict[str, Any]) -> Optional[str]:
    # Find a property of type "title"
    for v in props.values():
        if isinstance(v, dict) and v.get("type") == "title":
            arr = v.get("title") or []
            return "".join([x.get("plain_text", "") for x in arr if isinstance(x, dict)]).strip() or None
    return None


def _extract_status(props: dict[str, Any], status_prop: str) -> Optional[str]:
    v = props.get(status_prop)
    if not isinstance(v, dict):
        return None
    if v.get("type") == "status":
        s = v.get("status") or {}
        return s.get("name")
    if v.get("type") == "select":
        s = v.get("select") or {}
        return s.get("name")
    return None


def _extract_tags(props: dict[str, Any], tags_prop: str) -> list[str]:
    v = props.get(tags_prop)
    if not isinstance(v, dict):
        return []
    if v.get("type") == "multi_select":
        arr = v.get("multi_select") or []
        return [x.get("name") for x in arr if isinstance(x, dict) and x.get("name")]
    return []


