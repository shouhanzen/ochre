from __future__ import annotations

from typing import Any, Optional


def debug_log(*, payload: dict[str, Any]) -> None:
    """
    No-op placeholder.

    This module existed only for interactive debugging sessions; it is kept as a stub
    so legacy imports don't crash in environments where debug-mode logging is disabled.
    """
    _ = payload


def mk_payload(
    *,
    runId: str,
    hypothesisId: str,
    location: str,
    message: str,
    data: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    return {
        "sessionId": "debug-session",
        "runId": runId,
        "hypothesisId": hypothesisId,
        "location": location,
        "message": message,
        "data": data or {},
        "timestamp": 0,
    }


