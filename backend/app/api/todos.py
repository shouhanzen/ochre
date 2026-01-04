from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.todos.store import TodoError, add_task, delete_task, load_day, set_done, today_str


router = APIRouter()


class AddBody(BaseModel):
    text: str


class SetDoneBody(BaseModel):
    id: str = Field(..., description="Task id")
    done: bool


class DeleteBody(BaseModel):
    id: str


@router.get("/api/todos/today")
def get_today() -> dict:
    day = today_str()
    tasks, notes = load_day(day)
    return {"day": day, "tasks": [t.__dict__ for t in tasks], "notes": notes}


@router.post("/api/todos/today/add")
def post_add(body: AddBody) -> dict:
    day = today_str()
    try:
        tasks, notes = add_task(day, body.text)
        return {"day": day, "tasks": [t.__dict__ for t in tasks], "notes": notes}
    except TodoError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.patch("/api/todos/today/set_done")
def patch_set_done(body: SetDoneBody) -> dict:
    day = today_str()
    try:
        tasks, notes = set_done(day, body.id, body.done)
        return {"day": day, "tasks": [t.__dict__ for t in tasks], "notes": notes}
    except TodoError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/api/todos/today/delete")
def delete_today(body: DeleteBody) -> dict:
    day = today_str()
    try:
        tasks, notes = delete_task(day, body.id)
        return {"day": day, "tasks": [t.__dict__ for t in tasks], "notes": notes}
    except TodoError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
