from __future__ import annotations

from typing import Any


def tool_specs() -> list[dict[str, Any]]:
    # OpenAI-compatible tools schema, used by OpenRouter.
    return [
        {
            "type": "function",
            "function": {
                "name": "fs_list",
                "description": "List files/directories under unified filesystem paths like /fs/mnt/<mountName>/... or /fs/todos/...",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "fs_read",
                "description": "Read a UTF-8 text file from a unified filesystem path.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}, "max_bytes": {"type": "integer"}},
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "fs_write",
                "description": "Write a UTF-8 text file to a unified filesystem path.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                    "required": ["path", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "fs_move",
                "description": "Move/rename a path in the unified filesystem (used for e.g. moving Notion cards between status folders).",
                "parameters": {
                    "type": "object",
                    "properties": {"fromPath": {"type": "string"}, "toPath": {"type": "string"}},
                    "required": ["fromPath", "toPath"],
                },
            },
        },
    ]



