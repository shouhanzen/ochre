from __future__ import annotations

from pathlib import Path
from typing import Any

from app.todos.store import (
    TodoError,
    apply_markdown_edit,
    data_dir,
    ensure_day,
    render_markdown,
    template_path,
    today_str,
)


class VfsError(RuntimeError):
    pass


def _normalize(path: str) -> str:
    if not path.startswith("/"):
        path = "/" + path
    # normalize trailing slash except for root
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return path


def _list_todo_files() -> list[str]:
    root = data_dir()
    if not root.exists():
        return []
    days: list[str] = []
    for p in root.glob("*.json"):
        day = p.stem
        # naive validation: YYYY-MM-DD length
        if len(day) == 10 and day[4] == "-" and day[7] == "-":
            days.append(day)
    return sorted(days, reverse=True)


def vfs_list(path: str) -> dict[str, Any]:
    path = _normalize(path)
    if path in ("/fs/todos",):
        days = _list_todo_files()
        entries = [
            {"name": "template.todo.md", "path": "/fs/todos/template.todo.md", "kind": "file", "size": None},
            {"name": "today.todo.md", "path": "/fs/todos/today.todo.md", "kind": "file", "size": None},
        ]
        for day in days:
            entries.append({"name": f"{day}.todo.md", "path": f"/fs/todos/{day}.todo.md", "kind": "file", "size": None})
        return {"path": path, "entries": entries}

    raise VfsError("Unknown virtual directory")


def _day_from_todo_md_path(path: str) -> str:
    if path == "/fs/todos/today.todo.md":
        return today_str()
    if path.startswith("/fs/todos/") and path.endswith(".todo.md"):
        name = path.split("/")[-1]
        day = name[:-8]  # remove .todo.md
        if len(day) == 10 and day[4] == "-" and day[7] == "-":
            return day
    raise VfsError("Unsupported todo file path")


def vfs_read(path: str) -> dict[str, Any]:
    path = _normalize(path)
    if path == "/fs/todos/template.todo.md":
        # allow reading template directly from disk
        if not template_path().exists():
            ensure_day(today_str())
        return {"path": path, "content": template_path().read_text(encoding="utf-8")}

    if path.startswith("/fs/todos/") and path.endswith(".todo.md"):
        day = _day_from_todo_md_path(path)
        tasks, notes = ensure_day(day)
        return {"path": path, "content": render_markdown(day, tasks, notes)}

    raise VfsError("Unknown virtual file")


def vfs_write(path: str, *, content: str) -> dict[str, Any]:
    path = _normalize(path)
    if path == "/fs/todos/template.todo.md":
        template_path().parent.mkdir(parents=True, exist_ok=True)
        template_path().write_text(content, encoding="utf-8")
        return {"path": path, "ok": True}

    if path.startswith("/fs/todos/") and path.endswith(".todo.md"):
        day = _day_from_todo_md_path(path)
        try:
            tasks, _notes = apply_markdown_edit(day, content)
        except TodoError as e:
            raise VfsError(str(e)) from e
        return {"path": path, "ok": True, "task_count": len(tasks)}

    raise VfsError("Unknown virtual file")
