from unittest.mock import AsyncMock, MagicMock

import pytest

import backend.main as main_module


@pytest.mark.asyncio
async def test_lifespan_skips_arq_pool_without_redis_url(monkeypatch):
    create_pool_mock = AsyncMock()
    redis_close_mock = AsyncMock()

    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setattr(main_module, "create_pool", create_pool_mock)
    monkeypatch.setattr(main_module.redis_client, "close", redis_close_mock)

    async with main_module.lifespan(main_module.app):
        assert main_module.app.state.arq_pool is None

    create_pool_mock.assert_not_awaited()
    redis_close_mock.assert_awaited_once()
    assert main_module.app.state.arq_pool is None


@pytest.mark.asyncio
async def test_lifespan_initializes_arq_pool_when_redis_url_is_configured(monkeypatch):
    pool = MagicMock()
    pool.close = AsyncMock()
    create_pool_mock = AsyncMock(return_value=pool)
    redis_settings_mock = MagicMock(return_value="redis-settings")
    redis_close_mock = AsyncMock()

    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setattr(main_module, "create_pool", create_pool_mock)
    monkeypatch.setattr(main_module.RedisSettings, "from_dsn", redis_settings_mock)
    monkeypatch.setattr(main_module.redis_client, "close", redis_close_mock)

    async with main_module.lifespan(main_module.app):
        assert main_module.app.state.arq_pool is pool

    redis_settings_mock.assert_called_once_with("redis://redis:6379/0")
    create_pool_mock.assert_awaited_once_with("redis-settings")
    pool.close.assert_awaited_once()
    redis_close_mock.assert_awaited_once()
    assert main_module.app.state.arq_pool is None
