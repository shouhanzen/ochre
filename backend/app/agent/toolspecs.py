from __future__ import annotations

from typing import Any


def tool_specs() -> list[dict[str, Any]]:
    # OpenAI-compatible tools schema, used by OpenRouter.
    return [
        {
            "type": "function",
            "function": {
                "name": "use_skill",
                "description": "Activate a skill by name to add its instructions to your context.",
                "parameters": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "forget_skill",
                "description": "Deactivate a skill by name to remove its instructions from your context.",
                "parameters": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            },
        },
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
                "description": "Read a UTF-8 text file (or list of files) from unified filesystem paths.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]
                        },
                        "max_bytes": {"type": "integer"},
                    },
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
                "description": "Move/rename a path (or list of paths) in the unified filesystem.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "fromPath": {
                            "anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]
                        },
                        "toPath": {
                            "anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]
                        }
                    },
                    "required": ["fromPath", "toPath"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "fs_grep",
                "description": "Recursively search for a string/regex under a unified filesystem directory (e.g. /fs, /fs/mnt/<mountName>, /fs/todos).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "dir": {"type": "string"},
                        "query": {"type": "string"},
                        "regex": {"type": "boolean"},
                        "case_sensitive": {"type": "boolean"},
                        "include_globs": {"type": "array", "items": {"type": "string"}},
                        "exclude_globs": {"type": "array", "items": {"type": "string"}},
                        "max_files": {"type": "integer"},
                        "max_matches": {"type": "integer"},
                        "max_file_bytes": {"type": "integer"},
                        "context_before": {"type": "integer"},
                        "context_after": {"type": "integer"},
                    },
                    "required": ["dir", "query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "fs_patch",
                "description": "Apply targeted, unambiguous edits to a UTF-8 text file in the unified filesystem. Rejects invalid/ambiguous edits and returns a capped unified diff.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "max_file_bytes": {"type": "integer"},
                        "max_total_delta_bytes": {"type": "integer"},
                        "diff_cap_bytes": {"type": "integer"},
                        "edits": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "op": {"type": "string"},
                                    "expected_matches": {"type": "integer"},
                                    "old": {"type": "string"},
                                    "new": {"type": "string"},
                                    "anchor": {"type": "string"},
                                    "insert": {"type": "string"},
                                },
                                "required": ["op", "expected_matches"],
                            },
                        },
                    },
                    "required": ["path", "edits"],
                },
            },
        },
    ]


