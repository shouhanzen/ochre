from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query

from app.logging.ndjson import log_dir

router = APIRouter()


def _read_tail_lines(path: Path, *, max_lines: int) -> list[str]:
    """
    Best-effort tail without external deps. Reads a chunk from the end and splits lines.
    """
    if not path.exists():
        return []
    try:
        size = path.stat().st_size
        # Read up to last 512KB per file.
        read_bytes = min(size, 512 * 1024)
        with open(path, "rb") as f:
            f.seek(max(0, size - read_bytes))
            buf = f.read(read_bytes)
        text = buf.decode("utf-8", errors="ignore")
        lines = [ln for ln in text.splitlines() if ln.strip()]
        return lines[-max_lines:]
    except Exception:
        return []


@router.get("/api/logs/tail")
def get_logs_tail(lines: int = Query(200, ge=1, le=2000)) -> dict[str, Any]:
    d = log_dir()
    files = sorted(d.glob("ochre-*.ndjson"), key=lambda p: p.name, reverse=True)
    out_lines: list[str] = []
    remaining = int(lines)
    for p in files:
        if remaining <= 0:
            break
        chunk = _read_tail_lines(p, max_lines=remaining)
        # prepend older chunks so ordering is chronological overall
        out_lines = chunk + out_lines
        remaining = int(lines) - len(out_lines)
    return {"dir": str(d), "lines": out_lines[-int(lines) :], "count": len(out_lines[-int(lines) :])}


