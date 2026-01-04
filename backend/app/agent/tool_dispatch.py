from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from app.agent.tool_errors import ToolStructuredError
# from app.conversation.hub import get_model  # Moved to inside functions to avoid circular import
from app.fs.router import fs_grep, fs_list, fs_move, fs_patch, fs_read, fs_write

ToolFunc = Callable[[dict[str, Any]], Awaitable[Any]]


class ToolNotFoundError(RuntimeError):
    pass


def tool_registry() -> dict[str, ToolFunc]:
    # Imported lazily so modules can import agent bits without cycles.
    return {
        "fs_list": _wrap_sync(fs_list),
        "fs_read": _wrap_sync(fs_read),
        "fs_write": _wrap_sync(fs_write),
        "fs_move": _wrap_sync(fs_move),
        "fs_grep": _wrap_sync(fs_grep),
        "fs_patch": _wrap_sync(fs_patch),
        "use_skill": use_skill,
        "forget_skill": forget_skill,
    }


def _wrap_sync(fn) -> ToolFunc:
    async def wrapper(args: dict[str, Any]) -> Any:
        # In a real app, might want active threadpool for fs ops
        # Here we just run sync for simplicity/safety
        return fn(**args)

    return wrapper


async def dispatch_tool_call(name: str, args: dict[str, Any], session_id: str | None = None) -> Any:
    reg = tool_registry()
    fn = reg.get(name)
    if not fn:
        raise ToolNotFoundError(f"Tool '{name}' not found")
    
    # Special case: skill tools need session context
    if name in ("use_skill", "forget_skill"):
        if not session_id:
             raise ToolStructuredError({"error": "Skill tools require a session context"})
        # Inject session_id into args for these specific tools
        # We copy args to avoid mutating the original dict passed by runner
        call_args = dict(args)
        call_args["_session_id"] = session_id
        return await fn(call_args)

    return await fn(args)


async def use_skill(args: dict[str, Any]) -> dict[str, Any]:
    from app.conversation.hub import get_model

    name = str(args.get("name") or "").strip()
    session_id = args.get("_session_id")
    if not name:
        return {"error": "Skill name required"}
    if not session_id:
        return {"error": "Session context required"}

    model = await get_model(session_id)
    # We don't strictly validate existence here because skills are dynamic.
    # The agent is responsible for using valid names from the prelude.
    # However, we could validate if we wanted to be strict.
    # For now, just track it.
    
    # Check if already active
    if name in model.active_skills:
        return {"ok": True, "status": "already_active", "msg": f"Skill '{name}' is already active."}

    model.active_skills.add(name)
    return {
        "ok": True, 
        "status": "activated", 
        "msg": f"Skill '{name}' activated. Instructions will be injected into context on next turn."
    }


async def forget_skill(args: dict[str, Any]) -> dict[str, Any]:
    from app.conversation.hub import get_model

    name = str(args.get("name") or "").strip()
    session_id = args.get("_session_id")
    if not name:
        return {"error": "Skill name required"}
    if not session_id:
        return {"error": "Session context required"}

    model = await get_model(session_id)
    if name not in model.active_skills:
        return {"ok": True, "status": "not_active", "msg": f"Skill '{name}' was not active."}

    model.active_skills.remove(name)
    return {
        "ok": True, 
        "status": "deactivated", 
        "msg": f"Skill '{name}' deactivated."
    }
