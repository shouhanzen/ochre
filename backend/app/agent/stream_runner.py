from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from app.agent.openrouter import chat_completions_stream
from app.agent.tool_errors import ToolStructuredError
from app.agent.tool_dispatch import dispatch_tool_call
from app.agent.toolspecs import tool_specs


@dataclass
class StreamResult:
    assistant_text: str
    tool_calls: list[dict[str, Any]]
    finish_reason: Optional[str]


async def stream_once(
    *,
    model: str,
    messages: list[dict[str, Any]],
    on_delta: Callable[[str], Any],
    cancel_event: asyncio.Event,
) -> StreamResult:
    """
    Streams a single OpenRouter response until DONE or tool_calls finish.
    Returns accumulated assistant_text and any tool_calls.
    """
    buf: list[str] = []
    tool_calls: dict[int, dict[str, Any]] = {}
    finish_reason: Optional[str] = None

    async for frame in chat_completions_stream(model=model, messages=messages, tools=tool_specs(), tool_choice="auto"):
        if cancel_event.is_set():
            break
        choice = (frame.get("choices") or [{}])[0]
        delta = choice.get("delta") or {}
        finish_reason = choice.get("finish_reason") or finish_reason

        if "content" in delta and delta["content"]:
            text = str(delta["content"])
            buf.append(text)
            on_delta(text)

        # tool_calls can come as incremental deltas: list with indexes
        if "tool_calls" in delta and isinstance(delta["tool_calls"], list):
            for tc in delta["tool_calls"]:
                idx = tc.get("index")
                if idx is None:
                    continue
                slot = tool_calls.setdefault(int(idx), {"id": None, "type": "function", "function": {"name": None, "arguments": ""}})
                if "id" in tc and tc["id"]:
                    slot["id"] = tc["id"]
                fn = tc.get("function") or {}
                if "name" in fn and fn["name"]:
                    slot["function"]["name"] = fn["name"]
                if "arguments" in fn and fn["arguments"]:
                    slot["function"]["arguments"] += fn["arguments"]

    ordered = [tool_calls[k] for k in sorted(tool_calls.keys())]
    return StreamResult(assistant_text="".join(buf), tool_calls=ordered, finish_reason=finish_reason)


async def run_tool_loop_streaming(
    *,
    model: str,
    base_messages: list[dict[str, Any]],
    on_event: Callable[[dict[str, Any]], Any],
    cancel_event: asyncio.Event,
    max_steps: int = 8,
) -> tuple[str, list[dict[str, Any]]]:
    """
    Streaming tool loop. Emits events via on_event:
    - chat.delta
    - tool.start/tool.end
    Returns final assistant text and the full message list (including tool messages) for persistence.
    """
    msgs = list(base_messages)
    accumulated_final: list[str] = []

    for _ in range(max_steps):
        result = await stream_once(
            model=model,
            messages=msgs,
            on_delta=lambda t: (accumulated_final.append(t), on_event({"type": "chat.delta", "payload": {"text": t}})),
            cancel_event=cancel_event,
        )

        # If cancelled mid-stream, stop immediately.
        if cancel_event.is_set():
            break

        if result.tool_calls:
            # Append assistant message with tool_calls
            assistant_msg: dict[str, Any] = {"role": "assistant", "content": result.assistant_text, "tool_calls": result.tool_calls}
            msgs.append(assistant_msg)

            for tc in result.tool_calls:
                tc_id = tc.get("id")
                fn = tc.get("function") or {}
                name = str(fn.get("name") or "")
                raw_args = fn.get("arguments") or "{}"
                args: dict[str, Any]
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except Exception:
                    args = {"_raw": raw_args}

                on_event({"type": "tool.start", "payload": {"tool": name, "argsPreview": raw_args[:200]}})
                t0 = time.time()
                ok = True
                try:
                    tool_res = await dispatch_tool_call(name, args if isinstance(args, dict) else {"args": args})
                    content = json.dumps({"ok": True, "result": tool_res}, ensure_ascii=False)
                except ToolStructuredError as e:
                    ok = False
                    content = json.dumps(e.payload, ensure_ascii=False)
                except Exception as e:  # noqa: BLE001
                    ok = False
                    content = json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)
                ms = int((time.time() - t0) * 1000)
                on_event({"type": "tool.end", "payload": {"tool": name, "ok": ok, "durationMs": ms}})

                msgs.append({"role": "tool", "tool_call_id": tc_id, "name": name, "content": content})

            continue

        # No tool calls: normal completion
        msgs.append({"role": "assistant", "content": result.assistant_text})
        break

    return ("".join(accumulated_final), msgs)


