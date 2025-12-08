"""
Unit tests for the core.client_manager module.
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timedelta

from core.client_manager import ClientManager
from models.client import Client, ClientInfo, WorkerCapabilities, WorkerStatus
from models.messages import ClientType
from config import Settings


@pytest.fixture()
def manager():
    settings = Settings()
    settings.max_connections = 100
    settings.websocket_timeout = 5
    return ClientManager(settings)


def make_worker(client_id: str, task_types=None, max_tasks=1, active_tasks=0):
    caps = WorkerCapabilities(
        supported_task_types=task_types or ["generic"],
        max_concurrent_tasks=max_tasks,
    )
    client = Client.create_worker(
        client_id=client_id,
        client_name=f"Worker {client_id}",
        capabilities=caps,
    )
    client.info.connection_status = client.info.connection_status.CONNECTED
    client.info.stats.active_tasks = active_tasks
    return client


@pytest.mark.anyio
async def test_add_and_remove_client(manager: ClientManager):
    worker = make_worker("w1")
    ok = await manager.add_client(worker)
    assert ok is True
    assert manager.get_client("w1") is not None

    ok2 = await manager.remove_client("w1")
    assert ok2 is True
    assert manager.get_client("w1") is None


@pytest.mark.anyio
async def test_available_workers_filter_by_type_and_capability(manager: ClientManager):
    w1 = make_worker("w1", task_types=["a", "b"], active_tasks=0)
    w2 = make_worker("w2", task_types=["b", "c"], active_tasks=1)
    await manager.add_client(w1)
    await manager.add_client(w2)

    # Only workers, capability 'b' => only workers that are available (not at full capacity)
    available = manager.get_available_workers(task_type="b", executor_type="worker")
    assert [c.info.client_id for c in available] == ["w1"]

    # Capability 'c' => w2 matches capability but is at full capacity => not available
    available_c = manager.get_available_workers(task_type="c", executor_type="worker")
    assert [c.info.client_id for c in available_c] == []


@pytest.mark.anyio
async def test_get_best_worker_prefers_low_load(manager: ClientManager):
    w1 = make_worker("w1", task_types=["x"], max_tasks=5, active_tasks=4)
    w2 = make_worker("w2", task_types=["x"], max_tasks=5, active_tasks=1)
    await manager.add_client(w1)
    await manager.add_client(w2)

    best = manager.get_best_worker(task_type="x", executor_type="worker")
    assert best is not None
    assert best.info.client_id == "w2"


@pytest.mark.anyio
async def test_get_best_worker_with_requirements_and_fallbacks(manager: ClientManager):
    w1 = make_worker("w1", task_types=["x"], max_tasks=3, active_tasks=0)
    w2 = make_worker("w2", task_types=["y"], max_tasks=3, active_tasks=0)
    await manager.add_client(w1)
    await manager.add_client(w2)

    # Strict requirements that none matches => fallback to any executor_type
    best = manager.get_best_worker(
        task_type="x", worker_requirements=["z"], executor_type="worker"
    )
    assert best is not None
    assert best.info.client_id in ("w1", "w2")
