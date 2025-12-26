from __future__ import annotations

from typing import Any


class ToolStructuredError(RuntimeError):
    """
    Raise this from a tool handler to return a structured JSON payload.

    The agent runners will serialize `payload` directly into the tool message content
    (instead of collapsing into a plain string error), while still marking the tool
    invocation as failed for UI/status purposes.
    """

    def __init__(self, payload: dict[str, Any]):
        self.payload = payload
        super().__init__(payload.get("error", {}).get("message") if isinstance(payload.get("error"), dict) else None)

