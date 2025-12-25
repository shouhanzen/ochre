from __future__ import annotations

import os


def notion_api_key() -> str:
    return os.environ.get("NOTION_API_KEY", "").strip()


def notion_database_id() -> str:
    return os.environ.get("NOTION_DATABASE_ID", "").strip()


def notion_status_property() -> str:
    return os.environ.get("NOTION_STATUS_PROPERTY", "Status").strip() or "Status"


def notion_tags_property() -> str:
    # Optional, common default.
    return os.environ.get("NOTION_TAGS_PROPERTY", "Tags").strip() or "Tags"


def is_configured() -> bool:
    return bool(notion_api_key() and notion_database_id())


