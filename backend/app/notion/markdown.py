from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


_FM_START_RE = re.compile(r"^\s*---\s*$")
_KV_RE = re.compile(r"^\s*(?P<key>[A-Za-z0-9_]+)\s*:\s*(?P<val>.*)\s*$")


@dataclass
class CardDoc:
    page_id: str
    board_id: str
    title: str
    status: str | None
    tags: list[str]
    body: str


def render_card_doc(*, page_id: str, board_id: str, title: str, status: str | None, tags: list[str], body: str) -> str:
    lines = [
        "---",
        f"pageId: {json.dumps(page_id)}",
        f"boardId: {json.dumps(board_id)}",
        f"title: {json.dumps(title)}",
    ]
    if status is not None:
        lines.append(f"status: {json.dumps(status)}")
    lines.append(f"tags: {json.dumps(tags)}")
    lines.append("---")
    lines.append("")
    if body:
        lines.append(body.rstrip() + "\n")
    return "\n".join(lines)


def parse_card_doc(md: str) -> CardDoc:
    """
    Minimal frontmatter parser:
    - Requires starting `---` and ending `---`
    - Supports key: "string" and tags: ["a","b"] (JSON-ish list) or tags: [a,b]
    """
    lines = md.splitlines()
    if not lines or not _FM_START_RE.match(lines[0]):
        raise ValueError("Missing frontmatter start (---)")
    end_idx = None
    for i in range(1, len(lines)):
        if _FM_START_RE.match(lines[i]):
            end_idx = i
            break
    if end_idx is None:
        raise ValueError("Missing frontmatter end (---)")

    fm_lines = lines[1:end_idx]
    body = "\n".join(lines[end_idx + 1 :]).lstrip("\n")
    data: dict[str, Any] = {}
    for l in fm_lines:
        m = _KV_RE.match(l)
        if not m:
            continue
        key = m.group("key")
        val = (m.group("val") or "").strip()
        data[key] = _parse_value(val)

    page_id = str(data.get("pageId") or data.get("page_id") or "").strip()
    board_id = str(data.get("boardId") or data.get("board_id") or "default").strip() or "default"
    title = str(data.get("title") or "").strip()
    status = data.get("status")
    status_str = str(status).strip() if status is not None and str(status).strip() else None
    tags_raw = data.get("tags") or []
    tags: list[str] = []
    if isinstance(tags_raw, list):
        tags = [str(t).strip() for t in tags_raw if str(t).strip()]
    elif isinstance(tags_raw, str) and tags_raw.strip():
        tags = [tags_raw.strip()]

    if not page_id:
        raise ValueError("Missing pageId in frontmatter")
    if not title:
        raise ValueError("Missing title in frontmatter")

    return CardDoc(page_id=page_id, board_id=board_id, title=title, status=status_str, tags=tags, body=body)


def _parse_value(val: str) -> Any:
    # quoted string
    if len(val) >= 2 and ((val[0] == '"' and val[-1] == '"') or (val[0] == "'" and val[-1] == "'")):
        return val[1:-1]

    # list form: [a,b] or ["a","b"]
    if val.startswith("[") and val.endswith("]"):
        inner = val[1:-1].strip()
        if not inner:
            return []
        parts = [p.strip() for p in inner.split(",")]
        out: list[str] = []
        for p in parts:
            if not p:
                continue
            if len(p) >= 2 and ((p[0] == '"' and p[-1] == '"') or (p[0] == "'" and p[-1] == "'")):
                out.append(p[1:-1])
            else:
                out.append(p)
        return out

    return val


