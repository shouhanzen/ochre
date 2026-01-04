from __future__ import annotations

import dataclasses
from typing import Any, Iterable

@dataclasses.dataclass(frozen=True)
class Skill:
    name: str
    description: str
    content: str


class SkillsMixin:
    """
    Mixin for VFS providers to expose skills under a virtual .ochre/skills/ directory.
    """

    def get_skills(self) -> Iterable[Skill]:
        """
        Return a list of skills provided by this VFS.
        """
        return []

    def get_context_description(self) -> str | None:
        """
        Return a dynamic context description for the agent prelude.
        """
        return None

    def _handle_skills_list(self, path: str, skills: Iterable[Skill]) -> dict[str, Any] | None:
        """
        Helper to handle fs_list calls for .ochre/skills/
        Returns None if the path doesn't match skills logic.
        """
        # We expect path to be relative to the VFS root or absolute.
        # But providers usually get the full absolute path.
        # Let's assume the provider calls this with the full path, and we check suffixes.
        
        # normalize: remove trailing slash
        clean_path = path.rstrip("/")
        
        # Check if we are listing the skills root
        if clean_path.endswith("/.ochre/skills"):
            entries = []
            for s in skills:
                entries.append({
                    "name": s.name,
                    "path": f"{clean_path}/{s.name}",
                    "kind": "dir",
                    "size": None
                })
            return {"path": path, "entries": entries}

        # Check if we are listing a specific skill directory
        for s in skills:
            skill_path = f"/.ochre/skills/{s.name}"
            if clean_path.endswith(skill_path):
                return {
                    "path": path,
                    "entries": [
                        {
                            "name": "SKILL.md",
                            "path": f"{clean_path}/SKILL.md",
                            "kind": "file",
                            "size": len(s.content)
                        }
                    ]
                }
        
        # Also handle listing .ochre root if it exists purely virtually
        if clean_path.endswith("/.ochre"):
             return {
                "path": path,
                "entries": [
                    {"name": "skills", "path": f"{clean_path}/skills", "kind": "dir", "size": None}
                ]
            }

        return None

    def _handle_skills_read(self, path: str, skills: Iterable[Skill]) -> dict[str, Any] | None:
        """
        Helper to handle fs_read calls for .ochre/skills/.../SKILL.md
        """
        clean_path = path
        
        for s in skills:
            # We look for .../.ochre/skills/<name>/SKILL.md
            suffix = f"/.ochre/skills/{s.name}/SKILL.md"
            if clean_path.endswith(suffix):
                return {"path": path, "content": s.content}
        
        return None

