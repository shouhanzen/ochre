from __future__ import annotations

import asyncio
from typing import Dict

from app.conversation.model import ConversationModel


_lock = asyncio.Lock()
_models: Dict[str, ConversationModel] = {}


async def get_model(session_id: str) -> ConversationModel:
    async with _lock:
        m = _models.get(session_id)
        if m is None:
            m = ConversationModel(session_id=session_id)
            _models[session_id] = m
        return m

