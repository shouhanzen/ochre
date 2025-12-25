import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.events import router as events_router
from app.api.fs import router as fs_router
from app.api.kanban import router as kanban_router
from app.api.logs import router as logs_router
from app.api.session_chat import router as session_chat_router
from app.api.sessions import router as sessions_router
from app.api.settings import router as settings_router
from app.api.todos import router as todos_router
from app.api.ws_sessions import router as ws_sessions_router
from app.logging.ndjson import init_logging, log_event


def _load_dotenvs() -> None:
    """
    Load environment variables from:
    - backend/.env
    - repo-root/.env
    """
    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:  # noqa: BLE001
        return

    backend_dir = Path(__file__).resolve().parents[1]
    repo_root = backend_dir.parent

    load_dotenv(backend_dir / ".env")
    load_dotenv(repo_root / ".env")


def create_app() -> FastAPI:
    _load_dotenvs()
    try:
        from app.db import init_db  # noqa: WPS433

        init_db()
    except Exception:  # noqa: BLE001
        # If DB init fails we still want the process to start so errors can be surfaced via endpoints/logs.
        pass
    try:
        init_logging()
    except Exception:
        pass
    app = FastAPI(title="Ochre API", version="0.1.0")

    cors_origins = os.environ.get("OCHRE_CORS_ORIGINS", "http://localhost:5173").split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in cors_origins if o.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    @app.middleware("http")
    async def log_exceptions(request, call_next):  # type: ignore[no-untyped-def]
        try:
            return await call_next(request)
        except Exception as e:  # noqa: BLE001
            log_event(
                level="error",
                event="api.exception",
                data={"method": request.method, "path": str(request.url.path), "error": str(e)},
            )
            raise

    @app.on_event("startup")
    async def startup_tasks() -> None:
        # Best-effort: seed Notion board + refresh cache once on boot if configured.
        try:
            from app.notion.cache import ensure_default_board, refresh_board_if_stale  # noqa: WPS433

            await ensure_default_board()
            await refresh_board_if_stale("default")
        except Exception:
            pass
        log_event(level="info", event="app.startup", data={"ok": True})

    app.include_router(fs_router)
    app.include_router(sessions_router)
    app.include_router(session_chat_router)
    app.include_router(events_router)
    app.include_router(kanban_router)
    app.include_router(logs_router)
    app.include_router(settings_router)
    app.include_router(todos_router)
    app.include_router(ws_sessions_router)
    return app


app = create_app()


