from __future__ import annotations

import difflib
import json
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.events.bus import emit_event
from app.notion.cache import (
    DEFAULT_BOARD_ID,
    NotionCacheError,
    delete_overlay,
    get_card,
    get_overlay,
    list_boards,
    list_cards,
    list_pending_overlays,
    refresh_board_if_stale,
)
from app.notion.sync import enqueue_update_from_overlay, process_next_job


router = APIRouter()


class ApproveBody(BaseModel):
    sessionId: Optional[str] = None


class RejectBody(BaseModel):
    sessionId: Optional[str] = None


@router.get("/api/kanban/boards")
async def get_boards() -> dict:
    try:
        await refresh_board_if_stale(DEFAULT_BOARD_ID)
    except Exception:
        pass
    return {"boards": list_boards()}


@router.get("/api/kanban/boards/{board_id}")
async def get_board(board_id: str) -> dict:
    try:
        await refresh_board_if_stale(board_id)
    except Exception:
        pass
    return {"boardId": board_id, "cards": list_cards(board_id)}


@router.get("/api/kanban/pending")
def get_pending(boardId: Optional[str] = Query(None)) -> dict:
    return {"pending": list_pending_overlays(boardId)}


@router.get("/api/kanban/pending/{card_id}/diff")
def get_pending_diff(card_id: str) -> dict:
    ov = get_overlay(card_id)
    if not ov:
        raise HTTPException(status_code=404, detail="No pending overlay for card")
    board_id = ov["board_id"]
    card = get_card(board_id, card_id)
    before = ""
    if card:
        # before is the rendered snapshot doc as a best-effort (no body sync yet)
        before = json.dumps(card, ensure_ascii=False, indent=2)
    after = ov["content_md"]
    diff = "\n".join(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile="snapshot",
            tofile="overlay",
            lineterm="",
        )
    )
    return {"cardId": card_id, "boardId": board_id, "diff": diff}


@router.post("/api/kanban/pending/{card_id}/approve")
async def post_approve(card_id: str, body: ApproveBody) -> dict:
    ov = get_overlay(card_id)
    if not ov:
        raise HTTPException(status_code=404, detail="No pending overlay for card")
    board_id = ov["board_id"]
    try:
        job = enqueue_update_from_overlay(board_id=board_id, card_id=card_id, overlay_md=ov["content_md"])
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(e)) from e

    # Process one job immediately (best-effort) to keep localhost UX snappy.
    await process_next_job()

    # Clear overlay after enqueue (even if job fails, we have job record).
    delete_overlay(card_id)

    if body.sessionId:
        await emit_event(
            body.sessionId,
            "pending_approved",
            {
                "cardId": card_id,
                "boardId": board_id,
                "system_message": f"Pending change approved for card {card_id}. Sync job queued.",
            },
        )

    return {"ok": True, "job": job.__dict__}


@router.post("/api/kanban/pending/{card_id}/reject")
async def post_reject(card_id: str, body: RejectBody) -> dict:
    ov = get_overlay(card_id)
    if not ov:
        raise HTTPException(status_code=404, detail="No pending overlay for card")
    board_id = ov["board_id"]
    delete_overlay(card_id)

    if body.sessionId:
        await emit_event(
            body.sessionId,
            "pending_rejected",
            {
                "cardId": card_id,
                "boardId": board_id,
                "system_message": f"Pending change rejected for card {card_id}; reverted to cached version.",
            },
        )

    return {"ok": True}


