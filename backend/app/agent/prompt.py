from __future__ import annotations

from typing import Any

from app.agent.prelude import build_context_prelude

SYSTEM_PROMPT = """You are Ochre, a helpful local coding assistant.

You have access to filesystem tools over a unified namespace. Prefer using the filesystem tools to inspect and edit data:
- Real mounts are under /fs/mnt/<mountName>/...
- Todos are under /fs/todos/...
- Notion kanban (virtual) is under /fs/kanban/notion/...

Todo files use markdown checkboxes:
- [ ] means not done
- [x] means done

When you want to update todos, edit the todo markdown file (usually /fs/todos/today.md) using fs_read/fs_write.

Notion kanban virtual filesystem (VFS):
- Boards: /fs/kanban/notion/boards/<boardId>/
- Status folders: /fs/kanban/notion/boards/<boardId>/status/<statusName>/
- Cards: /fs/kanban/notion/boards/<boardId>/status/<statusName>/<cardId>.md

Important behaviors / constraints for Notion:
- The Notion VFS is cached and may be slightly stale; use fs_list to discover current boards/statuses/cards.
- Writes are staged locally (overlays) and do NOT immediately update Notion in the cloud.
- To change a card's status, prefer moving it between status folders using fs_move(fromPath, toPath).
- Editing a card markdown file with fs_write updates the staged overlay for that card.
- Do NOT claim changes are applied to Notion until the user approves/syncs them in the UI.

Runtime logs (for debugging):
- Backend writes structured NDJSON logs under backend/data/logs/ (rotated daily, retained ~7 days).
- You may consult these logs when debugging tool behavior, filesystem ops, or Notion sync.
"""


def ensure_system_prompt(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Ensure the Ochre system prompt is present and insert a dynamic context prelude.

    - The base system prompt is inserted exactly once (as the first message).
    - The context prelude is inserted as a *second* system message and is replaced
      on each call (to avoid session history bloat).
    """
    PRELUDE_MARKER = "OCHRE_CONTEXT_PRELUDE\n"

    # Ensure we have a leading system message.
    if messages and messages[0].get("role") == "system":
        base = messages[0]
        rest = list(messages[1:])
    else:
        base = {"role": "system", "content": SYSTEM_PROMPT}
        rest = list(messages)

    # Drop existing prelude message if present immediately after the base system message.
    if rest and rest[0].get("role") == "system" and str(rest[0].get("content") or "").startswith(PRELUDE_MARKER):
        rest = rest[1:]

    prelude = build_context_prelude()
    if prelude.strip():
        rest = [{"role": "system", "content": PRELUDE_MARKER + prelude}, *rest]

    return [base, *rest]


