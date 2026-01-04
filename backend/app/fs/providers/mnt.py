from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

import yaml
from app.fs.skills import Skill, SkillsMixin
from app.mounts import fs_delete, fs_list, fs_mkdir, fs_move, fs_read, fs_write, load_mounts


def _tree_lines(
    root: Path,
    *,
    max_depth: int = 4,
    max_entries: int = 500,
    ignore_names: Iterable[str] = (
        ".git",
        "node_modules",
        ".venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".cache",
        ".next",
        "dist",
        "build",
        ".turbo",
    ),
) -> list[str]:
    """
    Deterministic-ish tree view for agent context. Hard-capped by depth and entry count.
    """
    ignore = set(ignore_names)
    lines: list[str] = []
    emitted = 0

    def emit(s: str) -> None:
        nonlocal emitted
        if emitted >= max_entries:
            return
        lines.append(s)
        emitted += 1

    def walk(dir_path: Path, prefix: str, depth: int) -> None:
        if emitted >= max_entries or depth > max_depth:
            return
        try:
            children = list(dir_path.iterdir())
        except Exception:
            return

        # Skip ignored names; stable ordering: dirs first then files, case-insensitive.
        kept = [c for c in children if c.name not in ignore]
        kept.sort(key=lambda p: (not p.is_dir(), p.name.lower()))

        # Per-directory cap to avoid pathological wide dirs.
        per_dir_cap = 200
        shown = kept[:per_dir_cap]
        omitted = len(kept) - len(shown)

        for i, child in enumerate(shown):
            if emitted >= max_entries:
                return
            is_last = i == (len(shown) - 1) and omitted == 0
            branch = "└── " if is_last else "├── "
            next_prefix = prefix + ("    " if is_last else "│   ")
            name = child.name + ("/" if child.is_dir() else "")
            emit(prefix + branch + name)
            if child.is_dir() and depth < max_depth:
                walk(child, next_prefix, depth + 1)

        if omitted > 0 and emitted < max_entries:
            emit(prefix + f"... ({omitted} more entries omitted)")

    emit(f"{root.name}/")
    walk(root, "", 1)
    return lines


class MntProvider(SkillsMixin):
    def can_handle(self, path: str) -> bool:
        return path == "/fs/mnt" or path.startswith("/fs/mnt/")

    def get_skills(self) -> Iterable[Skill]:
        """
        Scan all mounts for .ochre/skills/*/SKILL.md
        """
        mounts = load_mounts()
        skills: list[Skill] = []
        for mount_name, m in mounts.items():
            # Look for <root>/.ochre/skills/
            skills_dir = m.root / ".ochre" / "skills"
            if not skills_dir.is_dir():
                continue
            
            try:
                for skill_folder in skills_dir.iterdir():
                    if not skill_folder.is_dir():
                        continue
                    
                    skill_md_path = skill_folder / "SKILL.md"
                    if not skill_md_path.is_file():
                        continue
                    
                    try:
                        content = skill_md_path.read_text(encoding="utf-8")
                        # Basic parsing of frontmatter to get name/desc
                        # ---
                        # name: foo
                        # description: bar
                        # ---
                        frontmatter = {}
                        parts = content.split("---", 2)
                        if len(parts) >= 3:
                            try:
                                frontmatter = yaml.safe_load(parts[1]) or {}
                            except Exception:
                                pass
                        
                        name = str(frontmatter.get("name") or skill_folder.name)
                        desc = str(frontmatter.get("description") or "(No description)")
                        
                        skills.append(Skill(name=name, description=desc, content=content))
                    except Exception:
                        continue
            except Exception:
                continue
        
        return skills

    def get_context_description(self) -> str | None:
        mounts = load_mounts()
        m = mounts.get("workspace")
        if m is None:
            return None
        root = m.root
        lines = _tree_lines(root, max_depth=4, max_entries=500)
        return "Worktree:\n" + "\n".join(lines)

    def list(self, path: str) -> dict[str, Any]:
        # Handle virtual skills listing first
        skills_res = self._handle_skills_list(path, self.get_skills())
        if skills_res:
            return skills_res

        if path.rstrip("/") == "/fs/mnt":
            mounts = load_mounts()
            entries = [
                {"name": name, "path": f"/fs/mnt/{name}", "kind": "dir", "size": None}
                for name in sorted(mounts.keys())
            ]
            return {"path": "/fs/mnt", "entries": entries}
        return fs_list(path)

    def read(self, path: str, *, max_bytes: int = 512_000) -> dict[str, Any]:
        # Handle virtual skills reading
        skills_res = self._handle_skills_read(path, self.get_skills())
        if skills_res:
            return skills_res

        return fs_read(path, max_bytes=max_bytes)

    def write(self, path: str, *, content: str) -> dict[str, Any]:
        return fs_write(path, content=content)

    def move(self, from_path: str, to_path: str) -> dict[str, Any]:
        return fs_move(from_path, to_path)

    # kept for future expansion (not used by toolspec currently)
    def mkdir(self, path: str) -> dict[str, Any]:
        return fs_mkdir(path)

    def delete(self, path: str, *, recursive: bool = False) -> dict[str, Any]:
        return fs_delete(path, recursive=recursive)
