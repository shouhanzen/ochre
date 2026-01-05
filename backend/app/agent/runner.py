from __future__ import annotations

import json
import time
from typing import Any, Optional

from app.agent.openrouter import chat_completions
from app.agent.prompt import ensure_system_prompt_async
from app.agent.tool_errors import ToolStructuredError
from app.agent.tool_dispatch import dispatch_tool_call
from app.agent.toolspecs import tool_specs


async def _normalize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # This now needs to be async or awaited
    processed = await ensure_system_prompt_async(messages)
    out: list[dict[str, Any]] = []
    for m in processed:
        role = m.get("role")
        if role not in ("user", "assistant", "tool", "system"):
            continue
        out.append(m)
    return out


async def run_agent(
    *,
    model: str,
    messages: list[dict[str, Any]],
    max_steps: int = 8,
) -> dict[str, Any]:
    """
    Runs a tool-calling loop until the model returns a message without tool calls.
    Returns the final OpenRouter response JSON, with internal steps applied to messages.
    """
    msgs = await _normalize_messages(messages)
    tools = tool_specs()

    last_resp: Optional[dict[str, Any]] = None
    for _ in range(max_steps):
        resp = await chat_completions(model=model, messages=msgs, tools=tools, tool_choice="auto")
        last_resp = resp
        choice = (resp.get("choices") or [{}])[0]
        message = choice.get("message") or {}

        # Always append assistant message (may contain tool_calls).
        msgs.append(message)

        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            break

        for tc in tool_calls:
            tc_id = tc.get("id")
            if not tc_id:
                tc_id = f"ochre-tc-{int(time.time() * 1000)}"
                tc["id"] = tc_id
            fn = (tc.get("function") or {})
            name = fn.get("name")
            raw_args = fn.get("arguments") or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except Exception:
                args = {"_raw": raw_args}

            try:
                result = await dispatch_tool_call(str(name), args if isinstance(args, dict) else {"args": args})
                content = json.dumps({"ok": True, "result": result}, ensure_ascii=False)
            except ToolStructuredError as e:
                content = json.dumps(e.payload, ensure_ascii=False)
            except Exception as e:  # noqa: BLE001
                content = json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

            msgs.append(
                {
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "name": name,
                    "content": content,
                    "args": raw_args,
                }
            )

    if last_resp is None:
        raise RuntimeError("Agent runner produced no response")

    # Attach the final message list for callers that want it.
    last_resp["_ochre_messages"] = msgs
    return last_resp
