from __future__ import annotations

from typing import Any, Iterable

from app.fs.skills import Skill, SkillsMixin
from app.todos.store import Task, ensure_day, today_str
from app.vfs import vfs_list, vfs_read, vfs_write


class TodosProvider(SkillsMixin):
    def can_handle(self, path: str) -> bool:
        return path.startswith("/fs/todos") or path == "/fs/todos"

    def get_skills(self) -> Iterable[Skill]:
        return [
            Skill(
                name="manage_todos",
                description="Manage daily tasks and notes. Use when user asks to add, complete, or list tasks.",
                content="""---
name: manage_todos
description: Manage daily tasks and notes.
---

# Manage Todos

You can manage daily tasks by reading and writing markdown files in `/fs/todos/`.

## Structure
- `/fs/todos/today.md`: The current day's tasks.
- `/fs/todos/YYYY-MM-DD.md`: Past or future days.
- `/fs/todos/template.md`: Template for new days.

## Format
Tasks use markdown checkboxes:
- `- [ ] Task text`: Pending task
- `- [x] Task text`: Completed task

## Instructions
1. **Interactive UI**: When the user asks to see their todos, ALWAYS display the interactive widget:
   ```widget:file
   { "path": "/fs/todos/today.todo.md" }
   ```
2. **Read**: Use `fs_read` to check content programmatically if you need to summarize or search.
3. **Update**: Use `fs_write` with the full file content to update checkboxes or add items programmatically.
4. **Notes**: You can add notes under a `## Notes` section at the bottom.
""",
            )
        ]

    def get_context_description(self) -> str | None:
        day = today_str()
        tasks, notes = ensure_day(day)
        if not tasks and not notes:
            return f"Todos ({day}): (no tasks or notes)"

        done = [t for t in tasks if t.done]
        pending = [t for t in tasks if not t.done]

        def fmt(t: Task) -> str:
            box = "x" if t.done else " "
            return f"- [{box}] {t.text} (id:{t.id})"

        lines: list[str] = [f"Todos ({day}): Pending: {len(pending)}  Done: {len(done)}"]
        
        if pending:
            lines.append("Pending:")
            for t in pending[:50]:
                lines.append(fmt(t))
            if len(pending) > 50:
                lines.append(f"... ({len(pending) - 50} more pending omitted)")
        
        if done:
            # Short summary for done
            if len(done) <= 5:
                 lines.append("Done: " + ", ".join(t.text for t in done))
            else:
                 lines.append(f"Done: {len(done)} tasks (use fs_read to see)")

        if notes:
            lines.append(f"Notes: {len(notes)} chars")

        return "\n".join(lines)

    def list(self, path: str) -> dict[str, Any]:
        # Check for virtual skills path
        skills_res = self._handle_skills_list(path, self.get_skills())
        if skills_res:
            return skills_res
            
        return vfs_list(path)

    def read(self, path: str, *, max_bytes: int = 512_000) -> dict[str, Any]:
        skills_res = self._handle_skills_read(path, self.get_skills())
        if skills_res:
            return skills_res

        _ = max_bytes
        return vfs_read(path)

    def write(self, path: str, *, content: str) -> dict[str, Any]:
        return vfs_write(path, content=content)

    def move(self, from_path: str, to_path: str) -> dict[str, Any]:
        _ = (from_path, to_path)
        raise RuntimeError("Move not supported for todos")
