from __future__ import annotations

from typing import Any, Awaitable, Callable


ToolFunc = Callable[[dict[str, Any]], Awaitable[Any]]


class ToolNotFoundError(RuntimeError):
    pass


def tool_registry() -> dict[str, ToolFunc]:
    # Imported lazily so modules can import agent bits without cycles.
    from app.tools.mount_fs import tool_handlers as mount_handlers  # noqa: WPS433

    out: dict[str, ToolFunc] = {}
    out.update(mount_handlers())
    return out


async def dispatch_tool_call(name: str, args: dict[str, Any]) -> Any:
    tools = tool_registry()
    fn = tools.get(name)
    if fn is None:
        raise ToolNotFoundError(f"Unknown tool: {name}")
    return await fn(args)



