from __future__ import annotations

from typing import Any, Optional

import httpx

from app.notion.config import notion_api_key


NOTION_BASE_URL = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


class NotionError(RuntimeError):
    pass


class NotionClient:
    def __init__(self) -> None:
        key = notion_api_key()
        if not key:
            raise NotionError("Missing NOTION_API_KEY")
        self._headers = {
            "Authorization": f"Bearer {key}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    async def query_database(self, database_id: str, *, start_cursor: Optional[str] = None) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if start_cursor:
            payload["start_cursor"] = start_cursor
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            r = await client.post(
                f"{NOTION_BASE_URL}/databases/{database_id}/query",
                headers=self._headers,
                json=payload,
            )
            if r.status_code >= 400:
                raise NotionError(f"Notion error {r.status_code}: {r.text}")
            return r.json()

    async def retrieve_database(self, database_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            r = await client.get(f"{NOTION_BASE_URL}/databases/{database_id}", headers=self._headers)
            if r.status_code >= 400:
                raise NotionError(f"Notion error {r.status_code}: {r.text}")
            return r.json()

    async def update_page_properties(self, page_id: str, *, properties: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            r = await client.patch(
                f"{NOTION_BASE_URL}/pages/{page_id}",
                headers=self._headers,
                json={"properties": properties},
            )
            if r.status_code >= 400:
                raise NotionError(f"Notion error {r.status_code}: {r.text}")
            return r.json()


