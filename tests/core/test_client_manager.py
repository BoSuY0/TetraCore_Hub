"""
Unit tests for the core.client_manager module.
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timedelta

from core.client_manager import ClientManager
from models.client import ClientInfo, ClientType, ClientStats
from config import Settings


@pytest.fixture
def settings():
    """Тестові налаштування"""
    settings = Mock(spec=Settings)
    settings.max_clients = 1000
    settings.websocket_timeout = 60
    settings.cleanup_interval = 30
    settings.is_production.return_value = False
    return settings


@pytest.fixture
def async_optimizer_mock():
    """Mock для AsyncOptimizer"""
    optimizer = Mock()
    optimizer.create_background_task = AsyncMock()
    optimizer.get_task_result = AsyncMock()
    return optimizer


@pytest.fixture
async def client_manager(settings, async_optimizer_mock):
    """Створення ClientManager для тестів"""
    manager = ClientManager(settings)
    manager.async_optimizer = async_optimizer_mock
    await manager.start()
    yield manager
    await manager.stop()


@pytest.mark.asyncio
async def test_cleanup_loop_direct_execution(client_manager):
    """
    Тест що cleanup_loop викликає _cleanup_unhealthy_clients напряму,
    без використання AsyncOptimizer
    """
    # Mock для _cleanup_unhealthy_clients
    client_manager._cleanup_unhealthy_clients = AsyncMock()
    
    # Створюємо cleanup loop task
    cleanup_task = asyncio.create_task(client_manager._cleanup_loop())
    
    # Даємо час на один цикл
    await asyncio.sleep(0.1)
    
    # Зупиняємо manager
    client_manager.is_running = False
    cleanup_task.cancel()
    
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    
    # Перевіряємо що _cleanup_unhealthy_clients був викликаний
    client_manager._cleanup_unhealthy_clients.assert_called()
    
    # Перевіряємо що AsyncOptimizer НЕ використовувався
    client_manager.async_optimizer.create_background_task.assert_not_called()


@pytest.mark.asyncio 
async def test_cleanup_unhealthy_clients(client_manager):
    """Тест видалення неактивних клієнтів"""
    # Створюємо тестових клієнтів
    active_client = Mock()
    active_client.info = ClientInfo(
        client_id="active-1",
        client_type=ClientType.WORKER,
        stats=ClientStats(last_activity=datetime.utcnow())
    )
    
    inactive_client = Mock()
    inactive_client.info = ClientInfo(
        client_id="inactive-1", 
        client_type=ClientType.WORKER,
        stats=ClientStats(last_activity=datetime.utcnow() - timedelta(minutes=5))
    )
    inactive_client.websocket = Mock()
    
    # Додаємо клієнтів
    client_manager.clients["active-1"] = active_client
    client_manager.clients["inactive-1"] = inactive_client
    
    # Mock для get_unhealthy_clients
    client_manager.get_unhealthy_clients = Mock(return_value=[inactive_client])
    
    # Викликаємо cleanup
    await client_manager._cleanup_unhealthy_clients()
    
    # Перевіряємо що неактивний клієнт був видалений
    assert "active-1" in client_manager.clients
    assert "inactive-1" not in client_manager.clients


def test_placeholder():
    """
    A placeholder test.
    TODO: Replace this with actual tests for the module.
    """
    assert True
