from __future__ import annotations

from typing import Any


class KanbanRootProvider:
    def can_handle(self, path: str) -> bool:
        return path == "/fs/kanban" or path == "/fs/kanban/"

    def list(self, path: str) -> dict[str, Any]:
        _ = path
        return {
            "path": "/fs/kanban",
            "entries": [{"name": "notion", "path": "/fs/kanban/notion", "kind": "dir", "size": None}],
        }

    def read(self, path: str, *, max_bytes: int = 512_000) -> dict[str, Any]:
        _ = (path, max_bytes)
        raise RuntimeError("Cannot read a directory")

    def write(self, path: str, *, content: str) -> dict[str, Any]:
        _ = (path, content)
        raise RuntimeError("Cannot write a directory")


