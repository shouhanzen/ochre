from __future__ import annotations

from typing import Any, Awaitable, Callable

from app.fs.router import fs_list, fs_move, fs_read, fs_write


ToolFunc = Callable[[dict[str, Any]], Awaitable[Any]]

async def _fs_list(args: dict[str, Any]) -> Any:
    return fs_list(str(args.get("path", "")))


async def _fs_read(args: dict[str, Any]) -> Any:
    return fs_read(str(args.get("path", "")), max_bytes=int(args.get("max_bytes", 512_000)))


async def _fs_write(args: dict[str, Any]) -> Any:
    return fs_write(str(args.get("path", "")), content=str(args.get("content", "")))

async def _fs_move(args: dict[str, Any]) -> Any:
    return fs_move(str(args.get("fromPath", "")), str(args.get("toPath", "")))


def tool_handlers() -> dict[str, ToolFunc]:
    return {
        "fs_list": _fs_list,
        "fs_read": _fs_read,
        "fs_write": _fs_write,
        "fs_move": _fs_move,
    }


