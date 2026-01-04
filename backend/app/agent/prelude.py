from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.fs.router import _providers
from app.fs.skills import SkillsMixin

if TYPE_CHECKING:
    # Only import for type checking if needed, but actually we need it at runtime inside the function.
    pass

@dataclass(frozen=True)
class PreludePart:
    title: str
    content: str


async def build_context_prelude(session_id: str | None = None) -> str:
    """
    Returns the full collated prelude text (no marker).
    Dynamically queries all registered VFS providers for context and skills.
    
    If session_id is provided, filters displayed skills based on active list
    and injects full skill content for active skills.
    """
    # Import inside function to avoid circular dependency with hub -> model -> prompt -> prelude -> hub
    from app.conversation.hub import get_model

    parts: list[PreludePart] = []
    
    active_skills: set[str] = set()
    if session_id:
        try:
            model = await get_model(session_id)
            active_skills = model.active_skills
        except Exception:
            pass

    for provider in _providers:
        if not isinstance(provider, SkillsMixin):
            continue

        try:
            # 1. Dynamic Context
            context_desc = provider.get_context_description()
            if context_desc and context_desc.strip():
                parts.append(PreludePart(title=f"Context: {type(provider).__name__}", content=context_desc.strip()))

            # 2. Available Skills (Summary vs Detailed)
            skills = list(provider.get_skills())
            if skills:
                skill_lines = []
                # First, list ALL available skills briefly
                skill_lines.append("Available Skills (activate with use_skill):")
                for s in skills:
                    status = "[ACTIVE]" if s.name in active_skills else ""
                    skill_lines.append(f"- {s.name}: {s.description} {status}")
                
                parts.append(PreludePart(title=f"Skills: {type(provider).__name__}", content="\n".join(skill_lines)))
                
                # Then, inject FULL content for active skills
                for s in skills:
                    if s.name in active_skills:
                        parts.append(PreludePart(title=f"Active Skill: {s.name}", content=s.content))
        
        except Exception as e:
             logging.warning(f"Error building prelude for {type(provider).__name__}: {e}")
             parts.append(PreludePart(title=f"Error: {type(provider).__name__}", content=str(e)))

    if not parts:
        return ""

    lines: list[str] = [
        "This is auto-generated context. Use filesystem tools to verify before acting.",
        "",
    ]
    for part in parts:
        lines.append(f"## {part.title}")
        lines.append(part.content)
        lines.append("")
    return "\n".join(lines).rstrip()
