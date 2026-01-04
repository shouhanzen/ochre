from __future__ import annotations

from typing import Any

from app.fs.providers.kanban_notion import KanbanNotionProvider
from app.fs.providers.kanban_root import KanbanRootProvider
from app.fs.providers.mnt import MntProvider
from app.fs.providers.email_gmail import EmailGmailProvider
from app.fs.providers.root import RootProvider
from app.fs.providers.shortcuts import ShortcutsProvider
from app.fs.providers.todos import TodosProvider
from app.logging.ndjson import log_event


class FsError(RuntimeError):
    pass


_providers = [
    RootProvider(),
    ShortcutsProvider(),
    KanbanRootProvider(),
    MntProvider(),
    TodosProvider(),
    EmailGmailProvider(),
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


def fs_read(path: str | list[str], *, max_bytes: int = 512_000) -> dict[str, Any] | list[dict[str, Any]]:
    # Support bulk read
    if isinstance(path, list):
        results = []
        for p_item in path:
            try:
                results.append(fs_read(p_item, max_bytes=max_bytes))
            except Exception as e:
                 results.append({"path": p_item, "error": str(e)})
        return results

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


def fs_tree(path: str) -> str:
    lines = []
    root_name = path.rstrip("/").split("/")[-1] or path
    lines.append(root_name)

    def _walk(current_path: str, prefix: str):
        try:
            listing = fs_list(current_path)
            entries = listing.get("entries", [])
            entries.sort(key=lambda x: x["name"])
        except Exception:
            return

        for i, entry in enumerate(entries):
            is_last = (i == len(entries) - 1)
            marker = "└── " if is_last else "├── "
            lines.append(f"{prefix}{marker}{entry['name']}")

            if entry.get("kind") == "dir":
                extension = "    " if is_last else "│   "
                _walk(entry["path"], prefix + extension)

    _walk(path, "")
    return "\n".join(lines)


def fs_move(from_path: str | list[str], to_path: str | list[str]) -> dict[str, Any] | list[dict[str, Any]]:
    # Support bulk move
    # 1. from_path=list, to_path=list (parallel zip)
    # 2. from_path=list, to_path=str (move all to directory) -> IMPL: simplified, just support 1:1 zip for now
    
    if isinstance(from_path, list) and isinstance(to_path, list):
        if len(from_path) != len(to_path):
             raise FsError("Batch move requires equal length from_path and to_path lists")
        
        results = []
        for f, t in zip(from_path, to_path):
            try:
                results.append(fs_move(f, t))
            except Exception as e:
                results.append({"from": f, "to": t, "error": str(e)})
        return results

    if isinstance(from_path, list) or isinstance(to_path, list):
         raise FsError("Batch move requires both fromPath and toPath to be lists of equal length")

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


def fs_grep(
    dir: str,
    query: str,
    regex: bool = False,
    case_sensitive: bool = False,
    include_globs: list[str] | None = None,
    exclude_globs: list[str] | None = None,
    max_files: int = 100,
    max_matches: int = 100,
    max_file_bytes: int = 512_000,
    context_before: int = 0,
    context_after: int = 0,
) -> dict[str, Any]:
    # Currently only supported by MntProvider and potentially others if they implement `grep`.
    # We delegate to the provider.
    p = _provider_for(dir)
    if not hasattr(p, "grep"):
        raise FsError(f"Grep not supported for this provider ({type(p).__name__})")
    
    return getattr(p, "grep")(
        dir,
        query=query,
        regex=regex,
        case_sensitive=case_sensitive,
        include_globs=include_globs,
        exclude_globs=exclude_globs,
        max_files=max_files,
        max_matches=max_matches,
        max_file_bytes=max_file_bytes,
        context_before=context_before,
        context_after=context_after
    )


def fs_patch(
    path: str,
    edits: list[dict[str, Any]],
    max_file_bytes: int = 2_000_000,
    max_total_delta_bytes: int = 500_000,
    diff_cap_bytes: int = 20_000
) -> dict[str, Any]:
    p = _provider_for(path)
    # Check if provider has patch support (often delegated to vfs_patch utility, 
    # but the provider must expose it or we can try a default implementation via read/write).
    
    # Ideally providers implement 'patch'.
    if hasattr(p, "patch"):
        return getattr(p, "patch")(
            path, 
            edits=edits, 
            max_file_bytes=max_file_bytes, 
            max_total_delta_bytes=max_total_delta_bytes, 
            diff_cap_bytes=diff_cap_bytes
        )
        
    # Fallback: Read-Modify-Write if not natively supported? 
    # Actually, fs_patch is complex (fuzzy matching), so we probably want a shared utility 
    # that providers call. But for now, let's assume if the provider doesn't support it, we fail.
    # MntProvider should support it.
    raise FsError(f"Patch not supported for this provider ({type(p).__name__})")
