import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient

# Import the hub launcher and settings for tests
from config import Settings


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_settings(monkeypatch):
    """
    Fixture to easily mock application settings in tests.
    """
    # Create a fresh Settings object for each test
    settings = Settings()
    
    return settings


class MockRedisManager:
    """
    A mock implementation of the RedisManager for testing purposes.
    It simulates the async methods without actual Redis connection.
    """
    def __init__(self):
        self._cache = {}
        self.publish = AsyncMock()
        self.subscribe = AsyncMock()

    async def get(self, key):
        return self._cache.get(key)

    async def set(self, key, value, ttl=None):
        self._cache[key] = value
        return True

    async def delete(self, key):
        if key in self._cache:
            del self._cache[key]
        return True

    async def hgetall(self, key):
        return self._cache.get(key, {})

    async def hset(self, name, key, value):
        if name not in self._cache:
            self._cache[name] = {}
        self._cache[name][key] = value
        return 1

    async def exists(self, key):
        return key in self._cache
        
    def get_redis_client(self):
        # Return a mock client
        return AsyncMock()

    def clear(self):
        self._cache.clear()


@pytest.fixture
def mock_redis_manager(monkeypatch):
    """
    Fixture that replaces the RedisManager with a mock version.
    """
    mock_instance = MockRedisManager()

    # The patch target depends on where RedisManager is imported.
    # Updated to the refactored path 'core.cache.redis.RedisManager'
    monkeypatch.setattr("core.cache.redis.RedisManager", lambda: mock_instance)
    
    # If there's a singleton getInstance pattern, we patch that.
    if hasattr(mock_instance, 'get_instance'):
        monkeypatch.setattr("core.cache.redis.RedisManager.get_instance", AsyncMock(return_value=mock_instance))
        
    return mock_instance 