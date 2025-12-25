from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


MountKind = Literal["file", "dir"]


@dataclass(frozen=True)
class Mount:
    name: str
    root: Path
    read_only: bool


class MountError(RuntimeError):
    pass


def _repo_relative(path: str) -> Path:
    # backend/app/mounts.py -> backend/
    here = Path(__file__).resolve()
    backend_dir = here.parents[1]
    return (backend_dir / path).resolve()


def load_mounts() -> dict[str, Mount]:
    cfg_path = _repo_relative("config/mounts.json")
    if not cfg_path.exists():
        return {}
    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    mounts = raw.get("mounts") or []
    out: dict[str, Mount] = {}
    for m in mounts:
        name = str(m.get("name") or "").strip()
        if not name:
            continue
        root = Path(str(m.get("path") or "")).expanduser()
        if not root.is_absolute():
            root = (cfg_path.parent / root).resolve()
        else:
            root = root.resolve()
        read_only = bool(m.get("readOnly", False))
        out[name] = Mount(name=name, root=root, read_only=read_only)
    return out


def _split_mnt_path(path: str) -> tuple[str, str]:
    # "/fs/mnt/<mountName>/rest/of/path"
    if not path.startswith("/fs/mnt/"):
        raise MountError("Path must start with /fs/mnt/")
    rest = path[len("/fs/mnt/") :]
    parts = rest.split("/", 1)
    mount_name = parts[0]
    subpath = parts[1] if len(parts) == 2 else ""
    if not mount_name:
        raise MountError("Missing mount name in /mnt/<mountName>/...")
    return mount_name, subpath


def _safe_join(root: Path, subpath: str) -> Path:
    candidate = (root / subpath).resolve()
    try:
        common = os.path.commonpath([str(root), str(candidate)])
    except ValueError as e:
        raise MountError(f"Invalid path: {e}") from e
    if Path(common).resolve() != root.resolve():
        raise MountError("Path escapes mount root")
    return candidate


def resolve_mount_path(path: str) -> tuple[Mount, Path]:
    mounts = load_mounts()
    mount_name, subpath = _split_mnt_path(path)
    mount = mounts.get(mount_name)
    if mount is None:
        raise MountError(f"Unknown mount: {mount_name}")
    p = _safe_join(mount.root, subpath)
    return mount, p


def fs_move(from_path: str, to_path: str) -> dict[str, Any]:
    src_mount, src = resolve_mount_path(from_path)
    dst_mount, dst = resolve_mount_path(to_path)
    if src_mount.name != dst_mount.name:
        raise MountError("Cannot move across mounts")
    if src_mount.read_only or dst_mount.read_only:
        raise MountError("Mount is read-only")
    if not src.exists():
        raise MountError("Source does not exist")
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)
    return {"fromPath": from_path, "toPath": to_path, "ok": True}


def fs_list(path: str) -> dict[str, Any]:
    mount, p = resolve_mount_path(path)
    if not p.exists():
        raise MountError("Path does not exist")
    if p.is_file():
        raise MountError("Path is a file; expected directory")

    entries: list[dict[str, Any]] = []
    for child in sorted(p.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower())):
        kind: MountKind = "dir" if child.is_dir() else "file"
        entries.append(
            {
                "name": child.name,
                "path": f"/fs/mnt/{mount.name}/" + str(child.relative_to(mount.root)).replace("\\", "/"),
                "kind": kind,
                "size": child.stat().st_size if child.is_file() else None,
            }
        )
    return {"path": path, "entries": entries}


def fs_read(path: str, *, max_bytes: int = 512_000) -> dict[str, Any]:
    _mount, p = resolve_mount_path(path)
    if not p.exists() or not p.is_file():
        raise MountError("File does not exist")
    size = p.stat().st_size
    if size > max_bytes:
        raise MountError(f"File too large ({size} bytes > {max_bytes})")
    content = p.read_text(encoding="utf-8")
    return {"path": path, "content": content}


def fs_write(path: str, *, content: str) -> dict[str, Any]:
    mount, p = resolve_mount_path(path)
    if mount.read_only:
        raise MountError("Mount is read-only")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return {"path": path, "ok": True}


def fs_mkdir(path: str) -> dict[str, Any]:
    mount, p = resolve_mount_path(path)
    if mount.read_only:
        raise MountError("Mount is read-only")
    p.mkdir(parents=True, exist_ok=True)
    return {"path": path, "ok": True}


def fs_delete(path: str, *, recursive: bool = False) -> dict[str, Any]:
    mount, p = resolve_mount_path(path)
    if mount.read_only:
        raise MountError("Mount is read-only")
    if not p.exists():
        return {"path": path, "ok": True}
    if p.is_dir():
        if recursive:
            shutil.rmtree(p)
        else:
            p.rmdir()
    else:
        p.unlink()
    return {"path": path, "ok": True}


