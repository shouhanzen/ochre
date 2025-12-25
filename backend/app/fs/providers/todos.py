from __future__ import annotations

from typing import Any

from app.vfs import vfs_list, vfs_read, vfs_write


class TodosProvider:
    def can_handle(self, path: str) -> bool:
        return path.startswith("/fs/todos") or path == "/fs/todos"

    def list(self, path: str) -> dict[str, Any]:
        return vfs_list(path)

    def read(self, path: str, *, max_bytes: int = 512_000) -> dict[str, Any]:
        _ = max_bytes
        return vfs_read(path)

    def write(self, path: str, *, content: str) -> dict[str, Any]:
        return vfs_write(path, content=content)

    def move(self, from_path: str, to_path: str) -> dict[str, Any]:
        _ = (from_path, to_path)
        raise RuntimeError("Move not supported for todos")


