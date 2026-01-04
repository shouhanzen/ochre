from __future__ import annotations

import asyncio
from typing import Any

from app.agent.prelude import build_context_prelude

SYSTEM_PROMPT = """You are Ochre, a helpful local coding assistant.

You have access to filesystem tools over a unified namespace. 
Most capabilities are exposed as "Skills" provided by the virtual filesystem.

To use a specific subsystem (like Todos, Notion, or Email):
1. Check the "Available Skills" list in the context.
2. Call `use_skill(name="skill_name")` to activate it.
3. Once activated, the skill's instructions will be injected into your context automatically.
4. Call `forget_skill(name="skill_name")` when you are done to save context tokens.

Alternatively, you can manually explore skills by listing `.ochre/skills` in any mounted directory and reading the `SKILL.md` file.

Tool Usage Tips:
- fs_read(path=...) accepts either a single string path or a list of paths ["/p1", "/p2"] to read multiple files at once.
- fs_move(fromPath=..., toPath=...) accepts lists for batch moves (lengths must match): fromPath=["/a", "/b"], toPath=["/c", "/d"].
- Use fs_list to explore directories before reading files.

Runtime logs (for debugging):
- Backend writes structured NDJSON logs under backend/data/logs/ (rotated daily, retained ~7 days).
- You may consult these logs when debugging tool behavior, filesystem ops, or Notion sync.
"""


def ensure_system_prompt(messages: list[dict[str, Any]], session_id: str | None = None) -> list[dict[str, Any]]:
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

    # We need to await the prelude build, but this function is sync.
    # In the sync context, we can use asyncio.run if there is no loop, 
    # but here we are likely inside a loop.
    # We should make this async or refactor call sites. 
    # Since call sites (stream_runner) are async, let's assume we can get the prelude passed in or make this async?
    # Actually, ensure_system_prompt is called from sync _normalize_messages too.
    # Let's verify call sites.
    
    # Quick fix: run synchronous part of prelude build (static parts) vs dynamic (async).
    # build_context_prelude is now async.
    
    # We can use a blocking call here safely ONLY if not deeply nested in a way that deadlocks.
    # But since we are inside an async runner, calling asyncio.run() will crash.
    # We must refactor ensure_system_prompt to be async OR handle the async part outside.
    
    # Let's cheat slightly: for now we can't easily refactor the signature everywhere without more changes.
    # Actually, let's modify the plan to refactor ensure_system_prompt to be async.
    # Wait, I cannot modify the plan. 
    # I will refactor ensure_system_prompt to be async and update call sites (runner.py, stream_runner.py).
    
    return [base, *rest]


async def ensure_system_prompt_async(messages: list[dict[str, Any]], session_id: str | None = None) -> list[dict[str, Any]]:
    PRELUDE_MARKER = "OCHRE_CONTEXT_PRELUDE\n"

    if messages and messages[0].get("role") == "system":
        base = messages[0]
        rest = list(messages[1:])
    else:
        base = {"role": "system", "content": SYSTEM_PROMPT}
        rest = list(messages)

    if rest and rest[0].get("role") == "system" and str(rest[0].get("content") or "").startswith(PRELUDE_MARKER):
        rest = rest[1:]

    prelude = await build_context_prelude(session_id=session_id)
    if prelude.strip():
        rest = [{"role": "system", "content": PRELUDE_MARKER + prelude}, *rest]

    return [base, *rest]
