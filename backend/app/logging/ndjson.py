from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

_lock = threading.Lock()


def _backend_dir() -> Path:
    # backend/app/logging/ndjson.py -> backend/
    return Path(__file__).resolve().parents[2]


def log_dir() -> Path:
    p = os.environ.get("OCHRE_LOG_DIR")
    if p:
        return Path(p)
    return _backend_dir() / "data" / "logs"


def _today_prefix(ts: Optional[float] = None) -> str:
    dt = datetime.fromtimestamp(ts or time.time())
    return dt.strftime("ochre-%Y-%m-%d")


def _max_bytes() -> int:
    try:
        return int(os.environ.get("OCHRE_LOG_MAX_BYTES", str(50 * 1024 * 1024)))
    except Exception:
        return 50 * 1024 * 1024


def _retention_days() -> int:
    try:
        return int(os.environ.get("OCHRE_LOG_RETENTION_DAYS", "7"))
    except Exception:
        return 7


def _truncate(v: Any, *, max_len: int = 600) -> Any:
    if v is None:
        return None
    if isinstance(v, str):
        if len(v) <= max_len:
            return v
        return v[:max_len] + f"...(+{len(v) - max_len} chars)"
    if isinstance(v, (int, float, bool)):
        return v
    if isinstance(v, dict):
        out: dict[str, Any] = {}
        for k, vv in list(v.items())[:80]:
            out[str(k)] = _truncate(vv, max_len=max_len)
        if len(v) > 80:
            out["_truncated_keys"] = len(v) - 80
        return out
    if isinstance(v, list):
        out = [_truncate(x, max_len=max_len) for x in v[:80]]
        if len(v) > 80:
            out.append({"_truncated_items": len(v) - 80})
        return out
    return _truncate(str(v), max_len=max_len)


def _pick_log_file(*, ts: Optional[float] = None) -> Path:
    d = log_dir()
    d.mkdir(parents=True, exist_ok=True)
    prefix = _today_prefix(ts)
    base = d / f"{prefix}.ndjson"
    max_b = _max_bytes()

    if not base.exists():
        return base
    try:
        if base.stat().st_size < max_b:
            return base
    except Exception:
        return base

    # Size exceeded; pick next suffix.
    for i in range(1, 1000):
        p = d / f"{prefix}.{i}.ndjson"
        if not p.exists():
            return p
        try:
            if p.stat().st_size < max_b:
                return p
        except Exception:
            return p
    return base


def _prune_old_files() -> None:
    d = log_dir()
    if not d.exists():
        return
    cutoff = datetime.now() - timedelta(days=_retention_days())
    for p in d.glob("ochre-*.ndjson"):
        try:
            mtime = datetime.fromtimestamp(p.stat().st_mtime)
            if mtime < cutoff:
                p.unlink(missing_ok=True)  # type: ignore[arg-type]
        except Exception:
            continue
    for p in d.glob("ochre-*.?.ndjson"):
        try:
            mtime = datetime.fromtimestamp(p.stat().st_mtime)
            if mtime < cutoff:
                p.unlink(missing_ok=True)  # type: ignore[arg-type]
        except Exception:
            continue


def init_logging() -> None:
    """
    Best-effort init: ensure log dir exists and prune old files.
    """
    with _lock:
        log_dir().mkdir(parents=True, exist_ok=True)
        _prune_old_files()


def log_event(
    *,
    level: str,
    event: str,
    data: Optional[dict[str, Any]] = None,
    sessionId: Optional[str] = None,
    requestId: Optional[str] = None,
    jobId: Optional[str] = None,
    toolCallId: Optional[str] = None,
) -> None:
    """
    Append a single structured NDJSON record.
    Never include secrets; callers should pass sizes/previews, not full content.
    """
    ts_ms = int(time.time() * 1000)
    rec: dict[str, Any] = {
        "ts": ts_ms,
        "level": level,
        "event": event,
    }
    if sessionId:
        rec["sessionId"] = sessionId
    if requestId:
        rec["requestId"] = requestId
    if jobId:
        rec["jobId"] = jobId
    if toolCallId:
        rec["toolCallId"] = toolCallId
    if data:
        rec["data"] = _truncate(data)

    line = json.dumps(rec, ensure_ascii=False)
    with _lock:
        try:
            _prune_old_files()
            p = _pick_log_file()
            with open(p, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            # Best-effort: never crash the app due to logging.
            pass


