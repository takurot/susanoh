from __future__ import annotations

import logging
import os
from typing import Optional

import redis.asyncio as redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)


class RedisClient:
    def __init__(self, url: Optional[str] = None) -> None:
        self.url = url or os.environ.get("REDIS_URL")
        self.enabled = bool(self.url)
        self._client: Optional[redis.Redis] = None
        self._last_failure: Optional[float] = None

    def get_client(self) -> Optional[redis.Redis]:
        if not self.enabled:
            return None
        if self._client is None:
            self._client = redis.from_url(self.url, decode_responses=True, socket_timeout=2, socket_connect_timeout=2)
        return self._client

    async def ping(self) -> bool:
        client = self.get_client()
        if not client:
            return False
        try:
            return await client.ping()
        except RedisError:
            return False

    async def close(self) -> None:
        if self._client:
            await self._client.close()
            self._client = None
