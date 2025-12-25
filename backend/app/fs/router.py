from __future__ import annotations

from typing import Any

from app.fs.providers.kanban_notion import KanbanNotionProvider
from app.fs.providers.kanban_root import KanbanRootProvider
from app.fs.providers.mnt import MntProvider
from app.fs.providers.root import RootProvider
from app.fs.providers.todos import TodosProvider
from app.logging.ndjson import log_event


class FsError(RuntimeError):
    pass


_providers = [
    RootProvider(),
    KanbanRootProvider(),
    MntProvider(),
    TodosProvider(),
    KanbanNotionProvider(),  # stubbed initially; filled in later in plan
]


def _provider_for(path: str):
    for p in _providers:
        if p.can_handle(path):
            return p
    raise FsError("Unknown /fs path")


def fs_list(path: str) -> dict[str, Any]:
    p = _provider_for(path)
    res = p.list(path)
    try:
        log_event(
            level="info",
            event="fs.list",
            data={"path": path, "provider": type(p).__name__, "entries": len((res.get("entries") or []))},
        )
    except Exception:
        pass
    return res


def fs_read(path: str, *, max_bytes: int = 512_000) -> dict[str, Any]:
    p = _provider_for(path)
    res = p.read(path, max_bytes=max_bytes)
    try:
        content = res.get("content")
        log_event(
            level="info",
            event="fs.read",
            data={
                "path": path,
                "provider": type(p).__name__,
                "maxBytes": max_bytes,
                "contentLen": len(content) if isinstance(content, str) else None,
            },
        )
    except Exception:
        pass
    return res


def fs_write(path: str, *, content: str) -> dict[str, Any]:
    p = _provider_for(path)
    res = p.write(path, content=content)
    try:
        log_event(
            level="info",
            event="fs.write",
            data={"path": path, "provider": type(p).__name__, "contentLen": len(content)},
        )
    except Exception:
        pass
    return res


def fs_move(from_path: str, to_path: str) -> dict[str, Any]:
    src = _provider_for(from_path)
    dst = _provider_for(to_path)
    if type(src) is not type(dst):
        raise FsError("Cannot move between different filesystem providers")
    if not hasattr(src, "move"):
        raise FsError("Move not supported for this provider")
    res = getattr(src, "move")(from_path, to_path)
    try:
        log_event(
            level="info",
            event="fs.move",
            data={"fromPath": from_path, "toPath": to_path, "provider": type(src).__name__},
        )
    except Exception:
        pass
    return res
