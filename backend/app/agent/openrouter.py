from __future__ import annotations

import os
import json
from typing import Any, AsyncIterator, Literal, Optional

import httpx


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterError(RuntimeError):
    pass


def _api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise OpenRouterError("Missing OPENROUTER_API_KEY")
    return key


async def chat_completions(
    *,
    model: str,
    messages: list[dict[str, Any]],
    tools: Optional[list[dict[str, Any]]] = None,
    tool_choice: Optional[Literal["auto", "none"]] = "auto",
    temperature: float = 0.2,
) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if tools is not None:
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        r = await client.post(f"{OPENROUTER_BASE_URL}/chat/completions", headers=headers, json=payload)
        if r.status_code >= 400:
            raise OpenRouterError(f"OpenRouter error {r.status_code}: {r.text}")
        return r.json()


async def chat_completions_stream(
    *,
    model: str,
    messages: list[dict[str, Any]],
    tools: Optional[list[dict[str, Any]]] = None,
    tool_choice: Optional[Literal["auto", "none"]] = "auto",
    temperature: float = 0.2,
) -> AsyncIterator[dict[str, Any]]:
    """
    OpenAI-compatible SSE stream. Yields parsed JSON payloads from `data: {...}` lines.
    """
    headers = {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if tools is not None:
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        async with client.stream(
            "POST",
            f"{OPENROUTER_BASE_URL}/chat/completions",
            headers=headers,
            json=payload,
        ) as r:
            if r.status_code >= 400:
                text = await r.aread()
                raise OpenRouterError(f"OpenRouter error {r.status_code}: {text.decode('utf-8', 'ignore')}")

            async for line in r.aiter_lines():
                if not line:
                    continue
                if not line.startswith("data:"):
                    continue
                data = line[len("data:") :].strip()
                if data == "[DONE]":
                    break
                try:
                    yield json.loads(data)
                except Exception:
                    # Skip malformed frames rather than killing the whole stream.
                    continue



