from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from app.db import connect
from app.notion.client import NotionClient
from app.notion.config import notion_status_property, notion_tags_property
from app.notion.markdown import parse_card_doc


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class SyncJob:
    id: str
    board_id: str
    card_id: str
    kind: str
    payload: dict[str, Any]
    status: str
    created_at: str
    updated_at: str
    error: Optional[str]


def enqueue_update_from_overlay(*, board_id: str, card_id: str, overlay_md: str) -> SyncJob:
    doc = parse_card_doc(overlay_md)
    payload = {
        "pageId": doc.page_id,
        "title": doc.title,
        "status": doc.status,
        "tags": doc.tags,
    }
    jid = str(uuid4())
    now = _now_iso()
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO notion_sync_jobs(id, board_id, card_id, kind, payload_json, status, created_at, updated_at, error) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, NULL)",
            (jid, board_id, card_id, "update_properties", json.dumps(payload, ensure_ascii=False), "queued", now, now),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM notion_sync_jobs WHERE id=?", (jid,)).fetchone()
        assert row is not None
        return _row_to_job(row)
    finally:
        conn.close()


async def process_next_job() -> Optional[SyncJob]:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM notion_sync_jobs WHERE status='queued' ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        job = _row_to_job(row)
        conn.execute(
            "UPDATE notion_sync_jobs SET status='running', updated_at=? WHERE id=?",
            (_now_iso(), job.id),
        )
        conn.commit()
    finally:
        conn.close()

    try:
        await _apply_job(job)
        _mark_job_done(job.id)
        return job
    except Exception as e:  # noqa: BLE001
        _mark_job_failed(job.id, str(e))
        return job


async def _apply_job(job: SyncJob) -> None:
    if job.kind != "update_properties":
        raise RuntimeError("Unknown sync job kind")
    payload = job.payload
    page_id = payload["pageId"]
    title = payload["title"]
    status = payload.get("status")
    tags = payload.get("tags") or []

    props: dict[str, Any] = {}
    # Title property: best effort, Notion requires the DB title property name; we can’t infer cheaply here.
    # We'll set the first title property by using the special 'title' key only if Notion accepts it per DB schema.
    # More reliably, users can set NOTION_TITLE_PROPERTY later; for now we use 'Name'.
    title_prop = "Name"
    props[title_prop] = {"title": [{"type": "text", "text": {"content": title}}]}

    if status is not None:
        props[notion_status_property()] = {"status": {"name": status}}

    if isinstance(tags, list):
        props[notion_tags_property()] = {"multi_select": [{"name": str(t)} for t in tags if str(t).strip()]}

    client = NotionClient()
    await client.update_page_properties(page_id, properties=props)

    # Update cache snapshot fields optimistically.
    conn = connect()
    try:
        conn.execute(
            "UPDATE notion_cards SET title=?, status=?, tags_json=?, cached_at=? WHERE id=? AND board_id=?",
            (title, status, json.dumps(tags, ensure_ascii=False), _now_iso(), job.card_id, job.board_id),
        )
        conn.commit()
    finally:
        conn.close()


def _mark_job_done(job_id: str) -> None:
    conn = connect()
    try:
        conn.execute(
            "UPDATE notion_sync_jobs SET status='done', updated_at=?, error=NULL WHERE id=?",
            (_now_iso(), job_id),
        )
        conn.commit()
    finally:
        conn.close()


def _mark_job_failed(job_id: str, error: str) -> None:
    conn = connect()
    try:
        conn.execute(
            "UPDATE notion_sync_jobs SET status='failed', updated_at=?, error=? WHERE id=?",
            (_now_iso(), error, job_id),
        )
        conn.commit()
    finally:
        conn.close()


def _row_to_job(row: Any) -> SyncJob:
    payload_raw = row["payload_json"] or "{}"
    try:
        payload = json.loads(payload_raw)
    except Exception:
        payload = {"_raw": payload_raw}
    return SyncJob(
        id=row["id"],
        board_id=row["board_id"],
        card_id=row["card_id"],
        kind=row["kind"],
        payload=payload if isinstance(payload, dict) else {"payload": payload},
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        error=row["error"],
    )


