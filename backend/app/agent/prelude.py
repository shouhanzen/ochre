from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import quote

from app.mounts import load_mounts
from app.notion.cache import DEFAULT_BOARD_ID, get_overlay, list_boards, list_cards
from app.notion.markdown import parse_card_doc
from app.todos.store import Task, ensure_day, today_str


@dataclass(frozen=True)
class PreludePart:
    title: str
    content: str


class PreludeProvider:
    """
    Service-level "context prelude" provider.
    Returns None to omit itself from the prelude.
    """

    title: str

    def build(self) -> Optional[str]:  # pragma: no cover - interface
        raise NotImplementedError


def _truncate_lines(lines: list[str], *, max_lines: int) -> list[str]:
    if max_lines <= 0:
        return []
    if len(lines) <= max_lines:
        return lines
    return [*lines[: max_lines - 1], f"... ({len(lines) - (max_lines - 1)} more lines omitted)"]


def _safe_json_loads(s: str, default):
    try:
        return json.loads(s)
    except Exception:
        return default


def _tree_lines(
    root: Path,
    *,
    max_depth: int = 4,
    max_entries: int = 500,
    ignore_names: Iterable[str] = (
        ".git",
        "node_modules",
        ".venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".cache",
        ".next",
        "dist",
        "build",
        ".turbo",
    ),
) -> list[str]:
    """
    Deterministic-ish tree view for agent context. Hard-capped by depth and entry count.
    """
    ignore = set(ignore_names)
    lines: list[str] = []
    emitted = 0

    def emit(s: str) -> None:
        nonlocal emitted
        if emitted >= max_entries:
            return
        lines.append(s)
        emitted += 1

    def walk(dir_path: Path, prefix: str, depth: int) -> None:
        if emitted >= max_entries or depth > max_depth:
            return
        try:
            children = list(dir_path.iterdir())
        except Exception:
            return

        # Skip ignored names; stable ordering: dirs first then files, case-insensitive.
        kept = [c for c in children if c.name not in ignore]
        kept.sort(key=lambda p: (not p.is_dir(), p.name.lower()))

        # Per-directory cap to avoid pathological wide dirs.
        per_dir_cap = 200
        shown = kept[:per_dir_cap]
        omitted = len(kept) - len(shown)

        for i, child in enumerate(shown):
            if emitted >= max_entries:
                return
            is_last = i == (len(shown) - 1) and omitted == 0
            branch = "└── " if is_last else "├── "
            next_prefix = prefix + ("    " if is_last else "│   ")
            name = child.name + ("/" if child.is_dir() else "")
            emit(prefix + branch + name)
            if child.is_dir() and depth < max_depth:
                walk(child, next_prefix, depth + 1)

        if omitted > 0 and emitted < max_entries:
            emit(prefix + f"... ({omitted} more entries omitted)")

    emit(f"{root.name}/")
    walk(root, "", 1)
    return lines


class VfsWorktreePrelude(PreludeProvider):
    title = "VFS worktree"

    def build(self) -> Optional[str]:
        mounts = load_mounts()
        m = mounts.get("workspace")
        if m is None:
            return None
        root = m.root
        lines = _tree_lines(root, max_depth=4, max_entries=500)
        return "\n".join(lines)


class TodosPrelude(PreludeProvider):
    title = "Todos (today)"

    def build(self) -> Optional[str]:
        day = today_str()
        tasks: list[Task] = ensure_day(day)
        if not tasks:
            return f"{day}: (no tasks)"

        done = [t for t in tasks if t.done]
        pending = [t for t in tasks if not t.done]

        def fmt(t: Task) -> str:
            box = "x" if t.done else " "
            return f"- [{box}] {t.text} (id:{t.id})"

        lines: list[str] = [f"Day: {day}", f"Pending: {len(pending)}  Done: {len(done)}", ""]
        if pending:
            lines.append("Pending:")
            for t in pending[:50]:
                lines.append(fmt(t))
            if len(pending) > 50:
                lines.append(f"... ({len(pending) - 50} more pending omitted)")
            lines.append("")
        if done:
            lines.append("Done:")
            # done list can get long; keep it shorter by default
            for t in done[:30]:
                lines.append(fmt(t))
            if len(done) > 30:
                lines.append(f"... ({len(done) - 30} more done omitted)")
        return "\n".join(lines).rstrip()


class NotionKanbanPrelude(PreludeProvider):
    title = "Notion kanban"

    def build(self) -> Optional[str]:
        boards = list_boards()
        board_ids = [str(b.get("id")) for b in boards if b.get("id")]
        if not board_ids:
            board_ids = [DEFAULT_BOARD_ID]

        out_lines: list[str] = []
        for board_id in board_ids[:3]:
            cards = list_cards(board_id)
            if not cards:
                out_lines.append(f"Board: {board_id} (no cached cards)")
                out_lines.append("")
                continue

            # Effective (overlay-first) title/status/tags.
            eff: list[dict[str, object]] = []
            for c in cards:
                cid = str(c.get("id") or "")
                if not cid:
                    continue
                title = str(c.get("title") or "")
                status = str(c.get("status") or "Uncategorized")
                tags = _safe_json_loads(str(c.get("tags_json") or "[]"), [])
                if not isinstance(tags, list):
                    tags = []

                ov = get_overlay(cid)
                if ov and ov.get("content_md"):
                    try:
                        doc = parse_card_doc(str(ov["content_md"]))
                        if doc.title:
                            title = doc.title
                        if doc.status:
                            status = doc.status
                        if doc.tags:
                            tags = list(doc.tags)
                    except Exception:
                        pass

                eff.append({"id": cid, "title": title, "status": status, "tags": tags})

            # Top-of-mind heuristic: active-ish status or active-ish tags.
            active_status_terms = ("doing", "in progress", "today", "now", "next", "urgent", "focus")
            active_tag_terms = ("urgent", "top", "focus", "now", "today", "next")

            def is_top(item: dict[str, object]) -> bool:
                st = str(item.get("status") or "").lower()
                if any(t in st for t in active_status_terms):
                    return True
                tags = item.get("tags") or []
                if isinstance(tags, list):
                    joined = " ".join([str(x).lower() for x in tags])
                    if any(t in joined for t in active_tag_terms):
                        return True
                return False

            top = [x for x in eff if is_top(x)]
            # Stable presentation: status then title.
            top.sort(key=lambda x: (str(x.get("status") or "").lower(), str(x.get("title") or "").lower()))

            out_lines.append(f"Board: {board_id}")
            if top:
                out_lines.append("Top of mind:")
                for x in top[:12]:
                    out_lines.append(f"- {x.get('title')} (id:{x.get('id')}) [{x.get('status')}]")
            else:
                out_lines.append("Top of mind: (none matched heuristics)")

            # Full board by status (titles only, linked with id)
            out_lines.append("")
            out_lines.append("By status:")
            by_status: dict[str, list[dict[str, object]]] = {}
            for x in eff:
                by_status.setdefault(str(x.get("status") or "Uncategorized"), []).append(x)
            for st in sorted(by_status.keys(), key=lambda s: s.lower()):
                out_lines.append(f"- {st}:")
                items = by_status[st]
                items.sort(key=lambda x: str(x.get("title") or "").lower())
                for x in items[:80]:
                    # Include a vfs hint that can be navigated by the agent/user.
                    st_seg = quote(st, safe="")
                    out_lines.append(f"  - {x.get('title')} (id:{x.get('id')})  vfs:/fs/kanban/notion/boards/{board_id}/status/{st_seg}/…")
                if len(items) > 80:
                    out_lines.append(f"  ... ({len(items) - 80} more in '{st}' omitted)")
            out_lines.append("")

        return "\n".join(_truncate_lines(out_lines, max_lines=900)).rstrip()


def build_context_prelude() -> str:
    """
    Returns the full collated prelude text (no marker).
    Kept sync so it can be used in session message normalization.
    """
    providers: list[PreludeProvider] = [
        NotionKanbanPrelude(),
        TodosPrelude(),
        VfsWorktreePrelude(),
    ]

    parts: list[PreludePart] = []
    for p in providers:
        try:
            txt = p.build()
        except Exception as e:  # noqa: BLE001
            txt = f"(error building prelude: {type(e).__name__}: {e})"
        if txt and txt.strip():
            parts.append(PreludePart(title=p.title, content=txt.strip()))

    if not parts:
        return ""

    lines: list[str] = [
        "This is auto-generated context (may be stale). Use filesystem tools to verify before acting.",
        "",
    ]
    for part in parts:
        lines.append(f"## {part.title}")
        lines.append(part.content)
        lines.append("")
    return "\n".join(lines).rstrip()

