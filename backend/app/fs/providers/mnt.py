from __future__ import annotations

from typing import Any

from app.mounts import fs_delete, fs_list, fs_mkdir, fs_move, fs_read, fs_write, load_mounts


class MntProvider:
    def can_handle(self, path: str) -> bool:
        return path == "/fs/mnt" or path.startswith("/fs/mnt/")

    def list(self, path: str) -> dict[str, Any]:
        if path.rstrip("/") == "/fs/mnt":
            mounts = load_mounts()
            entries = [
                {"name": name, "path": f"/fs/mnt/{name}", "kind": "dir", "size": None}
                for name in sorted(mounts.keys())
            ]
            return {"path": "/fs/mnt", "entries": entries}
        return fs_list(path)

    def read(self, path: str, *, max_bytes: int = 512_000) -> dict[str, Any]:
        return fs_read(path, max_bytes=max_bytes)

    def write(self, path: str, *, content: str) -> dict[str, Any]:
        return fs_write(path, content=content)

    def move(self, from_path: str, to_path: str) -> dict[str, Any]:
        return fs_move(from_path, to_path)

    # kept for future expansion (not used by toolspec currently)
    def mkdir(self, path: str) -> dict[str, Any]:
        return fs_mkdir(path)

    def delete(self, path: str, *, recursive: bool = False) -> dict[str, Any]:
        return fs_delete(path, recursive=recursive)


