from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncGenerator, Optional

if TYPE_CHECKING:
    from redis.asyncio import Redis


class LockManager:
    """
    Abstracts per-user concurrency locks. 
    Uses Redis distributed locks when Redis is available.
    Falls back to asyncio.Lock for in-memory, single-process execution.
    """

    def __init__(self, redis_client: Optional[Redis] = None) -> None:
        self.redis = redis_client
        self._local_locks: dict[str, asyncio.Lock] = {}

    @asynccontextmanager
    async def acquire_user_lock(self, user_id: str, timeout: float = 10.0) -> AsyncGenerator[None, None]:
        """
        Acquire an exclusive lock for a specific user to prevent race conditions
        in L1 Sliding Windows and State Machine transitions.
        """
        if self.redis:
            # redis.lock returns an async context manager in redis-py asyncio
            lock = self.redis.lock(f"susanoh:lock:{user_id}", timeout=timeout)
            async with lock:
                yield
        else:
            # Use setdefault to avoid race where two coroutines both create
            # separate Lock instances for the same user_id.
            lock = self._local_locks.setdefault(user_id, asyncio.Lock())
            async with lock:
                yield
