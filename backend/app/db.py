from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Iterator


def db_path() -> Path:
    backend_dir = Path(__file__).resolve().parents[1]
    data_dir = backend_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return Path(os.environ.get("OCHRE_DB_PATH", str(data_dir / "ochre.db")))


def connect() -> sqlite3.Connection:
    p = db_path()
    conn = sqlite3.connect(p, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Good defaults for a local single-user app.
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db() -> None:
    conn = connect()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
              id TEXT PRIMARY KEY,
              applied_at TEXT NOT NULL
            );
            """
        )
        _apply_migrations(conn)
        conn.commit()
    finally:
        conn.close()


def _apply_migrations(conn: sqlite3.Connection) -> None:
    migrations: list[tuple[str, str]] = [
        ("001_initial", _MIG_001_INITIAL),
        ("002_settings", _MIG_002_SETTINGS),
    ]
    applied = {row["id"] for row in conn.execute("SELECT id FROM schema_migrations")}
    for mid, sql in migrations:
        if mid in applied:
            continue
        conn.executescript(sql)
        conn.execute(
            "INSERT INTO schema_migrations(id, applied_at) VALUES(?, datetime('now'))",
            (mid,),
        )


_MIG_001_INITIAL = r"""
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  title TEXT,
  created_at TEXT NOT NULL,
  last_active_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  role TEXT NOT NULL,
  content TEXT,
  created_at TEXT NOT NULL,
  meta_json TEXT,
  FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_session_created
ON messages(session_id, created_at);

CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_events_session_created
ON events(session_id, created_at);

CREATE INDEX IF NOT EXISTS idx_sessions_last_active
ON sessions(last_active_at);

-- Notion cache + overlays + sync jobs
CREATE TABLE IF NOT EXISTS notion_boards (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  database_id TEXT NOT NULL,
  status_property TEXT NOT NULL,
  updated_at TEXT,
  last_sync_at TEXT
);

CREATE TABLE IF NOT EXISTS notion_cards (
  id TEXT PRIMARY KEY,
  board_id TEXT NOT NULL,
  title TEXT NOT NULL,
  status TEXT,
  tags_json TEXT,
  body_md TEXT,
  notion_updated_at TEXT,
  cached_at TEXT NOT NULL,
  FOREIGN KEY(board_id) REFERENCES notion_boards(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_notion_cards_board_status
ON notion_cards(board_id, status);

CREATE TABLE IF NOT EXISTS notion_overlays (
  card_id TEXT PRIMARY KEY,
  board_id TEXT NOT NULL,
  content_md TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(board_id) REFERENCES notion_boards(id) ON DELETE CASCADE,
  FOREIGN KEY(card_id) REFERENCES notion_cards(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_notion_overlays_board_updated
ON notion_overlays(board_id, updated_at);

CREATE TABLE IF NOT EXISTS notion_sync_jobs (
  id TEXT PRIMARY KEY,
  board_id TEXT NOT NULL,
  card_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  error TEXT,
  FOREIGN KEY(board_id) REFERENCES notion_boards(id) ON DELETE CASCADE,
  FOREIGN KEY(card_id) REFERENCES notion_cards(id) ON DELETE CASCADE
);
"""

_MIG_002_SETTINGS = r"""
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""


