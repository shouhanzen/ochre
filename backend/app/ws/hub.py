from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, DefaultDict

from fastapi import WebSocket


_lock = asyncio.Lock()
_conns: DefaultDict[str, set[WebSocket]] = defaultdict(set)


async def register(session_id: str, ws: WebSocket) -> None:
    async with _lock:
        _conns[session_id].add(ws)


async def unregister(session_id: str, ws: WebSocket) -> None:
    async with _lock:
        _conns[session_id].discard(ws)


async def send(session_id: str, msg: dict[str, Any]) -> None:
    async with _lock:
        targets = list(_conns.get(session_id, set()))
    for ws in targets:
        try:
            await ws.send_json(msg)
        except Exception:
            # Best-effort; caller can prune on disconnect path.
            pass


