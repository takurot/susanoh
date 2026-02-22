from __future__ import annotations

import os
from typing import Optional

import redis.asyncio as redis


class RedisClient:
    def __init__(self, url: Optional[str] = None) -> None:
        self.url = url or os.environ.get("REDIS_URL")
        self.enabled = bool(self.url)
        self._client: Optional[redis.Redis] = None

    def get_client(self) -> Optional[redis.Redis]:
        if not self.enabled:
            return None
        if self._client is None:
            self._client = redis.from_url(self.url, decode_responses=True)
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.close()
            self._client = None
