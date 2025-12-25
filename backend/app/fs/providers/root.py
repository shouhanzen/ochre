from __future__ import annotations

from typing import Any


class RootProvider:
    """
    Lists top-level filesystem namespaces under /fs.
    """

    def can_handle(self, path: str) -> bool:
        return path == "/fs" or path == "/fs/"

    def list(self, path: str) -> dict[str, Any]:
        _ = path
        return {
            "path": "/fs",
            "entries": [
                {"name": "mnt", "path": "/fs/mnt", "kind": "dir", "size": None},
                {"name": "todos", "path": "/fs/todos", "kind": "dir", "size": None},
                {"name": "kanban", "path": "/fs/kanban", "kind": "dir", "size": None},
            ],
        }

    def read(self, path: str, *, max_bytes: int = 512_000) -> dict[str, Any]:
        _ = (path, max_bytes)
        raise RuntimeError("Cannot read a directory")

    def write(self, path: str, *, content: str) -> dict[str, Any]:
        _ = (path, content)
        raise RuntimeError("Cannot write a directory")


