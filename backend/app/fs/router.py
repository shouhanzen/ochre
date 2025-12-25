from __future__ import annotations

from typing import Any

from app.fs.providers.kanban_notion import KanbanNotionProvider
from app.fs.providers.kanban_root import KanbanRootProvider
from app.fs.providers.mnt import MntProvider
from app.fs.providers.root import RootProvider
from app.fs.providers.todos import TodosProvider


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
    return _provider_for(path).list(path)


def fs_read(path: str, *, max_bytes: int = 512_000) -> dict[str, Any]:
    return _provider_for(path).read(path, max_bytes=max_bytes)


def fs_write(path: str, *, content: str) -> dict[str, Any]:
    return _provider_for(path).write(path, content=content)


def fs_move(from_path: str, to_path: str) -> dict[str, Any]:
    src = _provider_for(from_path)
    dst = _provider_for(to_path)
    if type(src) is not type(dst):
        raise FsError("Cannot move between different filesystem providers")
    if not hasattr(src, "move"):
        raise FsError("Move not supported for this provider")
    return getattr(src, "move")(from_path, to_path)
