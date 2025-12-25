from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4


_TASK_LINE_RE = re.compile(
    r"^\s*-\s*\[(?P<done>[ xX])\]\s*(?P<text>.*?)\s*(?:<!--\s*id:(?P<id>[A-Za-z0-9_-]+)\s*-->)?\s*$"
)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class Task:
    id: str
    text: str
    done: bool
    created_at: str
    updated_at: str


class TodoError(RuntimeError):
    pass


def data_dir() -> Path:
    # backend/app/todos/store.py -> backend/
    backend_dir = Path(__file__).resolve().parents[2]
    return backend_dir / "data" / "todos"


def template_path() -> Path:
    return data_dir() / "template.md"


def day_json_path(day: str) -> Path:
    return data_dir() / f"{day}.json"


def today_str() -> str:
    return date.today().isoformat()


def _ensure_dirs() -> None:
    data_dir().mkdir(parents=True, exist_ok=True)


def ensure_template_exists() -> None:
    _ensure_dirs()
    p = template_path()
    if p.exists():
        return
    p.write_text(
        "# Template\n\n- [ ] Review today’s priorities\n- [ ] Triage inbox\n- [ ] One meaningful task\n",
        encoding="utf-8",
    )


def parse_markdown_tasks(md: str) -> list[tuple[Optional[str], str, bool]]:
    """
    Returns tuples: (id|None, text, done).
    Only lines that look like task checkboxes are parsed.
    """
    out: list[tuple[Optional[str], str, bool]] = []
    for line in md.splitlines():
        m = _TASK_LINE_RE.match(line)
        if not m:
            continue
        text = (m.group("text") or "").strip()
        if not text:
            continue
        done = (m.group("done") or " ").lower() == "x"
        out.append((m.group("id"), text, done))
    return out


def render_markdown(day: str, tasks: list[Task]) -> str:
    lines = [f"# Todos: {day}", ""]
    for t in tasks:
        box = "x" if t.done else " "
        lines.append(f"- [{box}] {t.text} <!-- id:{t.id} -->")
    lines.append("")
    return "\n".join(lines)


def load_day(day: str) -> list[Task]:
    _ensure_dirs()
    p = day_json_path(day)
    if not p.exists():
        ensure_day(day)
    raw = json.loads(p.read_text(encoding="utf-8"))
    tasks_raw = raw.get("tasks") or []
    tasks: list[Task] = []
    for t in tasks_raw:
        tasks.append(
            Task(
                id=str(t["id"]),
                text=str(t["text"]),
                done=bool(t.get("done", False)),
                created_at=str(t.get("created_at") or _now_iso()),
                updated_at=str(t.get("updated_at") or _now_iso()),
            )
        )
    return tasks


def save_day(day: str, tasks: list[Task]) -> None:
    _ensure_dirs()
    payload = {"day": day, "tasks": [asdict(t) for t in tasks]}
    day_json_path(day).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_day(day: str) -> list[Task]:
    ensure_template_exists()
    _ensure_dirs()
    p = day_json_path(day)
    if p.exists():
        return load_day(day)

    tpl = template_path().read_text(encoding="utf-8")
    parsed = parse_markdown_tasks(tpl)
    now = _now_iso()
    tasks: list[Task] = [
        Task(id=str(uuid4()), text=text, done=False, created_at=now, updated_at=now)
        for (_id, text, _done) in parsed
    ]
    save_day(day, tasks)
    return tasks


def apply_markdown_edit(day: str, new_md: str) -> list[Task]:
    """
    Apply edits from a markdown file into canonical JSON for the given day.
    - Stable identity: if <!-- id:... --> is present, we keep that ID.
    - If missing, we try to match by text (first match), otherwise create a new task.
    - Any tasks not present in the edited markdown are deleted.
    """
    existing = load_day(day)
    by_id = {t.id: t for t in existing}
    used_existing_ids: set[str] = set()

    parsed = parse_markdown_tasks(new_md)
    now = _now_iso()
    out: list[Task] = []

    # Simple text index for fallback matching (first available).
    by_text: dict[str, list[Task]] = {}
    for t in existing:
        by_text.setdefault(t.text.strip(), []).append(t)

    for maybe_id, text, done in parsed:
        text = text.strip()
        if not text:
            continue

        t: Optional[Task] = None
        if maybe_id and maybe_id in by_id:
            t = by_id[maybe_id]
        else:
            candidates = by_text.get(text) or []
            while candidates:
                cand = candidates.pop(0)
                if cand.id not in used_existing_ids:
                    t = cand
                    break

        if t is None:
            out.append(Task(id=str(uuid4()), text=text, done=done, created_at=now, updated_at=now))
        else:
            used_existing_ids.add(t.id)
            out.append(
                Task(
                    id=t.id,
                    text=text,
                    done=done,
                    created_at=t.created_at,
                    updated_at=now,
                )
            )

    save_day(day, out)
    return out


def set_done(day: str, task_id: str, done: bool) -> list[Task]:
    tasks = load_day(day)
    now = _now_iso()
    found = False
    out: list[Task] = []
    for t in tasks:
        if t.id == task_id:
            found = True
            out.append(Task(id=t.id, text=t.text, done=done, created_at=t.created_at, updated_at=now))
        else:
            out.append(t)
    if not found:
        raise TodoError("Task not found")
    save_day(day, out)
    return out


def add_task(day: str, text: str) -> list[Task]:
    text = text.strip()
    if not text:
        raise TodoError("Task text is empty")
    tasks = load_day(day)
    now = _now_iso()
    tasks.append(Task(id=str(uuid4()), text=text, done=False, created_at=now, updated_at=now))
    save_day(day, tasks)
    return tasks


def delete_task(day: str, task_id: str) -> list[Task]:
    tasks = load_day(day)
    out = [t for t in tasks if t.id != task_id]
    if len(out) == len(tasks):
        raise TodoError("Task not found")
    save_day(day, out)
    return out


