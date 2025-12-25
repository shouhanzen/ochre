from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from app.db import connect
from app.notion.client import NotionClient, NotionError
from app.notion.config import notion_status_property, notion_tags_property
from app.notion.markdown import parse_card_doc
from app.logging.ndjson import log_event


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


async def _list_all_children(client: NotionClient, block_id: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    cursor: Optional[str] = None
    while True:
        res = await client.list_block_children(block_id, start_cursor=cursor)
        out.extend(res.get("results") or [])
        if not res.get("has_more"):
            break
        cursor = res.get("next_cursor")
    return out


def _rt_plain(text: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": {"content": text}}]


async def _ensure_ochre_body_section(*, client: NotionClient, page_id: str, body_md: str) -> dict[str, Any]:
    """
    Ensure a dedicated 'Ochre Body' section exists, and overwrite its children with a single markdown code block.

    We store the body as plaintext inside a code block (language: markdown) to avoid full markdown->Notion mapping.
    """
    children = await _list_all_children(client, page_id)

    ochre_toggle_id: Optional[str] = None
    for b in children:
        if not isinstance(b, dict):
            continue
        if b.get("type") != "toggle":
            continue
        t = (b.get("toggle") or {}).get("rich_text") or []
        plain = "".join([x.get("plain_text", "") for x in t if isinstance(x, dict)])
        if plain.strip().lower().startswith("ochre body"):
            ochre_toggle_id = b.get("id")
            break

    if not ochre_toggle_id:
        created = await client.append_block_children(
            page_id,
            children=[
                {
                    "type": "toggle",
                    "toggle": {
                        "rich_text": _rt_plain("Ochre Body"),
                        "children": [],
                    },
                }
            ],
        )
        # Find the created block id by re-listing last page children.
        children2 = await _list_all_children(client, page_id)
        for b in reversed(children2):
            if isinstance(b, dict) and b.get("type") == "toggle":
                t = (b.get("toggle") or {}).get("rich_text") or []
                plain = "".join([x.get("plain_text", "") for x in t if isinstance(x, dict)])
                if plain.strip() == "Ochre Body":
                    ochre_toggle_id = b.get("id")
                    break

    if not ochre_toggle_id:
        raise RuntimeError("Failed to create/find Ochre Body section")

    # Delete existing children under the toggle.
    existing = await _list_all_children(client, ochre_toggle_id)
    deleted = 0
    for ch in existing:
        cid = ch.get("id") if isinstance(ch, dict) else None
        if cid:
            try:
                await client.delete_block(cid)
                deleted += 1
            except Exception:
                pass

    # Append a single code block containing the markdown body.
    await client.append_block_children(
        ochre_toggle_id,
        children=[
            {
                "type": "code",
                "code": {
                    "rich_text": _rt_plain(body_md or ""),
                    "language": "markdown",
                },
            }
        ],
    )
    return {"toggleId": ochre_toggle_id, "deleted": deleted}


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
    log_event(
        level="info",
        event="notion.sync.enqueue",
        jobId=None,
        data={
            "boardId": board_id,
            "cardId": card_id,
            "pageId": doc.page_id,
            "titleLen": len(doc.title or ""),
            "status": doc.status,
            "tagsCount": len(doc.tags or []),
            "bodyLen": len(doc.body or ""),
        },
    )
    payload = {
        "pageId": doc.page_id,
        "title": doc.title,
        "status": doc.status,
        "tags": doc.tags,
        "body": doc.body,
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
        log_event(level="info", event="notion.sync.job.picked", jobId=job.id, data={"boardId": job.board_id, "cardId": job.card_id, "kind": job.kind})
        conn.execute(
            "UPDATE notion_sync_jobs SET status='running', updated_at=? WHERE id=?",
            (_now_iso(), job.id),
        )
        conn.commit()
    finally:
        conn.close()

    try:
        log_event(level="info", event="notion.sync.job.apply.start", jobId=job.id, data={"boardId": job.board_id, "cardId": job.card_id})
        await _apply_job(job)
        log_event(level="info", event="notion.sync.job.apply.ok", jobId=job.id, data={"boardId": job.board_id, "cardId": job.card_id})
        _mark_job_done(job.id)
        return job
    except Exception as e:  # noqa: BLE001
        log_event(level="error", event="notion.sync.job.apply.failed", jobId=job.id, data={"boardId": job.board_id, "cardId": job.card_id, "error": str(e)})
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
    body = payload.get("body") or ""

    props: dict[str, Any] = {}
    # Title property: best effort, Notion requires the DB title property name; we can’t infer cheaply here.
    # We'll set the first title property by using the special 'title' key only if Notion accepts it per DB schema.
    # More reliably, users can set NOTION_TITLE_PROPERTY later; for now we use 'Name'.
    title_prop = "Name"
    props[title_prop] = {"title": [{"type": "text", "text": {"content": title}}]}

    if status is not None:
        # Most Notion DBs use "select" for status-like fields; prefer select first.
        props[notion_status_property()] = {"select": {"name": status}}

    if isinstance(tags, list):
        props[notion_tags_property()] = {"multi_select": [{"name": str(t)} for t in tags if str(t).strip()]}

    client = NotionClient()
    try:
        await client.update_page_properties(page_id, properties=props)
    except NotionError as e:
        # If the DB uses the newer "status" type, Notion may reject select payloads.
        msg = str(e)
        if status is not None and "expected to be status" in msg:
            props2 = dict(props)
            props2[notion_status_property()] = {"status": {"name": status}}
            await client.update_page_properties(page_id, properties=props2)
        else:
            raise

    # Write body into the dedicated "Ochre Body" section.
    try:
        await _ensure_ochre_body_section(client=client, page_id=page_id, body_md=str(body))
    except Exception as e:  # noqa: BLE001
        log_event(level="error", event="notion.sync.body.failed", jobId=job.id, data={"pageId": page_id, "error": str(e)})
        raise

    # Update cache snapshot fields optimistically.
    conn = connect()
    try:
        conn.execute(
            "UPDATE notion_cards SET title=?, status=?, tags_json=?, cached_at=? WHERE id=? AND board_id=?",
            (title, status, json.dumps(tags, ensure_ascii=False), _now_iso(), job.card_id, job.board_id),
        )
        conn.execute(
            "UPDATE notion_cards SET body_md=? WHERE id=? AND board_id=?",
            (str(body), job.card_id, job.board_id),
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


