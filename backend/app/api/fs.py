from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.fs.router import FsError, fs_list, fs_move, fs_read, fs_write, fs_tree


router = APIRouter()


class WriteBody(BaseModel):
    path: str
    content: str


class MoveBody(BaseModel):
    fromPath: str
    toPath: str


@router.get("/api/fs/list")
def api_fs_list(path: str = Query(...)) -> dict:
    try:
        return fs_list(path)
    except FsError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/api/fs/tree")
def api_fs_tree(path: str = Query(...)) -> dict:
    try:
        return {"tree": fs_tree(path)}
    except FsError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/api/fs/read")
def api_fs_read(path: str = Query(...), max_bytes: int = Query(512_000)) -> dict:
    try:
        return fs_read(path, max_bytes=max_bytes)
    except FsError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.put("/api/fs/write")
def api_fs_write(body: WriteBody) -> dict:
    try:
        return fs_write(body.path, content=body.content)
    except FsError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/api/fs/move")
def api_fs_move(body: MoveBody) -> dict:
    try:
        return fs_move(body.fromPath, body.toPath)
    except FsError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e



