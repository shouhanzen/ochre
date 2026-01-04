from __future__ import annotations

from typing import Any


class ShortcutsProvider:
    def can_handle(self, path: str) -> bool:
        return path == "/fs/shortcuts" or path == "/fs/shortcuts/"

    def list(self, path: str) -> dict[str, Any]:
        return {
            "path": "/fs/shortcuts",
            "entries": [
                {
                    "name": "today.todo.md",
                    "path": "/fs/todos/today.todo.md",
                    "kind": "file",
                    "size": None,
                }
            ],
        }

    def read(self, path: str, *, max_bytes: int = 512_000) -> dict[str, Any]:
        _ = (path, max_bytes)
        raise RuntimeError("Shortcuts is a directory-only provider. Use the target path.")

    def write(self, path: str, *, content: str) -> dict[str, Any]:
        _ = (path, content)
        raise RuntimeError("Shortcuts is read-only")

