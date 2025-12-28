from __future__ import annotations

from typing import Any

import hashlib
import json
import re
import unicodedata
from urllib.parse import quote, unquote

from app.notion.cache import (
    DEFAULT_BOARD_ID,
    get_card,
    get_overlay,
    list_boards,
    list_cards,
    refresh_board_if_stale,
    upsert_overlay,
)
from app.notion.markdown import parse_card_doc, render_card_doc


_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
_TOKEN_RE = re.compile(r"^[0-9a-f]{6,64}$", re.IGNORECASE)


def _snake_slug(s: str, *, cap: int = 64) -> str:
    """
    Turn an arbitrary title into a stable-ish snake_case filename segment.
    - ASCII fold (NFKD) to avoid platform/path oddities in UIs
    - lowercase, [a-z0-9_]
    """
    s = (s or "").strip()
    if not s:
        return "task"
    s = unicodedata.normalize("NFKD", s)
    s = s.encode("ascii", "ignore").decode("ascii")
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    s = re.sub(r"_+", "_", s)
    if not s:
        return "task"
    if cap and len(s) > cap:
        s = s[:cap].rstrip("_")
    return s or "task"


def _card_token(card_id: str, *, n: int = 12) -> str:
    # Stable, non-reversible-ish token so we don't expose Notion page IDs in filenames.
    return hashlib.sha256(card_id.encode("utf-8")).hexdigest()[:n]


def _card_filename(*, card_id: str, title: str) -> str:
    return f"{_snake_slug(title)}--{_card_token(card_id)}.task.md"


def _resolve_card_id(*, board_id: str, filename: str) -> str:
    """
    Resolve a filename to the underlying Notion card/page id.

    Supports:
    - legacy: <uuid>.task.md
    - pretty: <slug>--<token>.task.md (token = sha256(card_id)[:n])
    """
    base = filename
    if base.endswith(".task.md"):
        base = base[: -len(".task.md")]

    if _UUID_RE.match(base):
        return base

    if "--" in base:
        token = base.split("--")[-1].strip().lower()
        if not _TOKEN_RE.match(token):
            raise RuntimeError("Invalid card token in filename")
        cards = list_cards(board_id)
        hits: list[str] = []
        for c in cards:
            cid = c.get("id")
            if not cid:
                continue
            if _card_token(str(cid)).startswith(token):
                hits.append(str(cid))
        if len(hits) == 1:
            return hits[0]
        if len(hits) == 0:
            raise RuntimeError("Card not found for token (try refreshing)")
        raise RuntimeError("Ambiguous card token (multiple matches)")

    raise RuntimeError("Unsupported card filename")


class KanbanNotionProvider:
    def can_handle(self, path: str) -> bool:
        return path == "/fs/kanban/notion" or path.startswith("/fs/kanban/notion/")

    def list(self, path: str) -> dict[str, Any]:
        if path.rstrip("/") == "/fs/kanban/notion":
            return {
                "path": path,
                "entries": [{"name": "boards", "path": "/fs/kanban/notion/boards", "kind": "dir", "size": None}],
            }

        if path.rstrip("/") == "/fs/kanban/notion/boards":
            boards = list_boards()
            entries = [
                {"name": b["id"], "path": f"/fs/kanban/notion/boards/{b['id']}", "kind": "dir", "size": None}
                for b in boards
            ]
            if not entries:
                entries.append({"name": "default", "path": "/fs/kanban/notion/boards/default", "kind": "dir", "size": None})
            return {"path": path, "entries": entries}

        if path.startswith("/fs/kanban/notion/boards/") and "/status" not in path:
            board_id = path.split("/")[5]
            if path.rstrip("/") == f"/fs/kanban/notion/boards/{board_id}":
                return {
                    "path": path,
                    "entries": [
                        {"name": "board.json", "path": f"/fs/kanban/notion/boards/{board_id}/board.json", "kind": "file", "size": None},
                        {"name": "columns.json", "path": f"/fs/kanban/notion/boards/{board_id}/columns.json", "kind": "file", "size": None},
                        {"name": "status", "path": f"/fs/kanban/notion/boards/{board_id}/status", "kind": "dir", "size": None},
                    ],
                }

        if path.endswith("/status"):
            board_id = path.split("/")[5]
            cards = list_cards(board_id)
            # Determine effective statuses, overlay-first.
            statuses: set[str] = set()
            for c in cards:
                st = c.get("status") or "Uncategorized"
                ov = get_overlay(c["id"])
                if ov and ov.get("content_md"):
                    try:
                        doc = parse_card_doc(ov["content_md"])
                        if doc.status:
                            st = doc.status
                    except Exception:
                        pass
                statuses.add(st)
            entries = []
            for st in sorted(statuses):
                seg = quote(st, safe="")
                entries.append(
                    {
                        "name": st,
                        "path": f"/fs/kanban/notion/boards/{board_id}/status/{seg}",
                        "kind": "dir",
                        "size": None,
                    }
                )
            return {"path": path, "entries": entries}

        if "/status/" in path and path.count("/") == 7:
            # /fs/kanban/notion/boards/<boardId>/status/<statusSeg>
            parts = path.split("/")
            board_id = parts[5]
            status_seg = parts[7]
            status_name = unquote(status_seg)
            cards = list_cards(board_id)
            entries = []
            for c in cards:
                st = c.get("status") or "Uncategorized"
                ov = get_overlay(c["id"])
                if ov and ov.get("content_md"):
                    try:
                        doc = parse_card_doc(ov["content_md"])
                        if doc.status:
                            st = doc.status
                        # Prefer overlay title if present (keeps filename stable with local edits).
                        if doc.title:
                            c = dict(c)
                            c["title"] = doc.title
                    except Exception:
                        pass
                if st == status_name:
                    title = str(c.get("title") or "")
                    entries.append(
                        {
                            "name": _card_filename(card_id=str(c["id"]), title=title),
                            "path": f"/fs/kanban/notion/boards/{board_id}/status/{status_seg}/{_card_filename(card_id=str(c['id']), title=title)}",
                            "kind": "file",
                            "size": None,
                        }
                    )
            return {"path": path, "entries": entries}

        raise RuntimeError("Unknown Notion kanban directory")

    def read(self, path: str, *, max_bytes: int = 512_000) -> dict[str, Any]:
        _ = max_bytes
        if path == "/fs/kanban/notion/boards/default/board.json":
            # best-effort refresh (if configured) and return board list snapshot
            try:
                import asyncio

                asyncio.run(refresh_board_if_stale(DEFAULT_BOARD_ID))
            except Exception:
                pass
            boards = list_boards()
            return {"path": path, "content": json.dumps({"boards": boards}, ensure_ascii=False, indent=2)}

        if path.endswith("/columns.json"):
            board_id = path.split("/")[5]
            cards = list_cards(board_id)
            statuses = sorted({c.get("status") for c in cards if c.get("status")})
            return {
                "path": path,
                "content": json.dumps({"boardId": board_id, "columns": statuses}, ensure_ascii=False, indent=2),
            }

        if path.endswith("/board.json"):
            board_id = path.split("/")[5]
            try:
                import asyncio

                asyncio.run(refresh_board_if_stale(board_id))
            except Exception:
                pass
            boards = {b["id"]: b for b in list_boards()}
            return {"path": path, "content": json.dumps({"board": boards.get(board_id)}, ensure_ascii=False, indent=2)}

        if "/cards/" in path and (path.endswith(".md") or path.endswith(".task.md")):
            # legacy path removed
            raise RuntimeError("Card path has moved; use /status/<status>/<cardId>.task.md")

        if "/status/" in path and path.endswith(".task.md"):
            parts = path.split("/")
            board_id = parts[5]
            card_id = _resolve_card_id(board_id=board_id, filename=parts[-1])
            ov = get_overlay(card_id)
            if ov and ov.get("content_md"):
                return {"path": path, "content": ov["content_md"]}
            c = get_card(board_id, card_id)
            if not c:
                raise RuntimeError("Card not found in cache (try refreshing)")
            tags = []
            try:
                tags = json.loads(c.get("tags_json") or "[]")
            except Exception:
                tags = []
            md = render_card_doc(
                page_id=c["id"],
                board_id=board_id,
                title=c["title"],
                status=c.get("status"),
                tags=tags if isinstance(tags, list) else [],
                body=c.get("body_md") or "",
            )
            return {"path": path, "content": md}

        raise RuntimeError("Unknown Notion kanban file")

    def write(self, path: str, *, content: str) -> dict[str, Any]:
        if "/status/" in path and path.endswith(".task.md"):
            parts = path.split("/")
            board_id = parts[5]
            card_id = _resolve_card_id(board_id=board_id, filename=parts[-1])
            upsert_overlay(board_id=board_id, card_id=card_id, content_md=content)
            return {"path": path, "ok": True, "overlay": True}
        raise RuntimeError("Writes only supported for card markdown docs")

    def move(self, from_path: str, to_path: str) -> dict[str, Any]:
        """
        Interpret moving a card between status folders as a status change overlay update.
        """
        if not (
            "/status/" in from_path
            and from_path.endswith(".task.md")
            and "/status/" in to_path
            and to_path.endswith(".task.md")
        ):
            raise RuntimeError("Notion move only supported for status folder card moves")

        fp = from_path.split("/")
        tp = to_path.split("/")
        from_board = fp[5]
        to_board = tp[5]
        if from_board != to_board:
            raise RuntimeError("Cannot move card across boards")
        from_status = unquote(fp[7])
        to_status = unquote(tp[7])
        card_id = _resolve_card_id(board_id=from_board, filename=fp[-1])
        to_card_id = _resolve_card_id(board_id=from_board, filename=tp[-1])
        if card_id != to_card_id:
            raise RuntimeError("Move must reference the same card")
        if from_status == to_status:
            return {"fromPath": from_path, "toPath": to_path, "ok": True, "changed": False}

        ov = get_overlay(card_id)
        if ov and ov.get("content_md"):
            try:
                doc = parse_card_doc(ov["content_md"])
                new_md = render_card_doc(
                    page_id=doc.page_id,
                    board_id=doc.board_id,
                    title=doc.title,
                    status=to_status,
                    tags=doc.tags,
                    body=doc.body,
                )
            except Exception:
                new_md = ov["content_md"]
        else:
            c = get_card(from_board, card_id)
            if not c:
                raise RuntimeError("Card not found in cache")
            tags = []
            try:
                tags = json.loads(c.get("tags_json") or "[]")
            except Exception:
                tags = []
            new_md = render_card_doc(
                page_id=c["id"],
                board_id=from_board,
                title=c["title"],
                status=to_status,
                tags=tags if isinstance(tags, list) else [],
                body=c.get("body_md") or "",
            )

        upsert_overlay(board_id=from_board, card_id=card_id, content_md=new_md)
        return {"fromPath": from_path, "toPath": to_path, "ok": True, "changed": True}


