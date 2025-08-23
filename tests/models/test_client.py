"""
Unit tests for the models.client module.
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime

from models.client import (
    Client,
    ClientInfo,
    ClientType,
    WorkerCapabilities,
    ConnectionStatus,
)
from models.task import Task, TaskType, TaskPriority, TaskStatus, ExecutorType
from core.task_router import TaskRouter, RedisErrorHandler
from core.client_manager import ClientManager
from config import Settings


class TestTaskSubmissionSystem:
    """Тести системи відправки тасків"""

    @pytest.fixture
    def mock_settings(self):
        """Mock settings"""
        settings = Mock(spec=Settings)
        settings.redis_enabled = False
        settings.max_connections = 100
        settings.websocket_timeout = 30
        return settings

    @pytest.fixture
    def mock_websocket(self):
        """Mock WebSocket connection"""
        ws = AsyncMock()
        ws.send_json = AsyncMock()
        ws.client_state = Mock()
        ws.client_state.name = "CONNECTED"
        return ws

    @pytest.fixture
    def test_client(self, mock_websocket):
        """Test client with mocked WebSocket"""
        info = ClientInfo(
            client_id="test-worker-1",
            client_type=ClientType.WORKER,
            client_name="Test Worker",
            capabilities=WorkerCapabilities(
                supported_task_types=["send_message", "test_task"],
                max_concurrent_tasks=5,
            ),
        )
        client = Client(info=info, websocket=mock_websocket)
        client.connect(mock_websocket)
        return client

    @pytest.fixture
    def task_router(self, mock_settings):
        """TaskRouter with mocked dependencies"""
        router = TaskRouter(mock_settings, redis_manager=None)
        router.redis_error_handler = RedisErrorHandler()
        return router

    @pytest.fixture
    def client_manager(self, mock_settings):
        """ClientManager with test setup"""
        manager = ClientManager(mock_settings)
        return manager

    @pytest.fixture
    def test_task(self):
        """Test task"""
        return Task.create(
            task_type=TaskType.SEND_MESSAGE,
            data={"chat_id": 123, "text": "Hello World"},
            priority=TaskPriority.NORMAL,
            executor_type=ExecutorType.WORKER,
            worker_requirements=["send_message"],
            timeout=300,  # 5 хвилин в секундах
        )

    @pytest.mark.asyncio
    async def test_task_submission_success(
        self, task_router, client_manager, test_client, test_task
    ):
        """Тест успішної подачі таску"""
        # Setup
        await client_manager.initialize()
        await client_manager.add_client(test_client)

        task_router.set_client_manager(client_manager)
        await task_router.initialize()

        # Submit task
        success = await task_router.submit_task(test_task)

        # Assertions
        assert success is True
        # Коли є доступний воркер, таск автоматично призначається, тому статус ASSIGNED
        assert test_task.context.current_status in [
            TaskStatus.PENDING,
            TaskStatus.ASSIGNED,
            TaskStatus.PROCESSING,
        ]
        # Перевіряємо що таск був переміщений з черги в активні після призначення
        if test_task.context.current_status in [
            TaskStatus.ASSIGNED,
            TaskStatus.PROCESSING,
        ]:
            assert test_task.task_id in task_router.active_tasks
        else:
            assert (
                test_task.task_id in task_router.task_queues[TaskPriority.NORMAL].tasks
            )

    @pytest.mark.asyncio
    async def test_task_assignment_success(
        self, task_router, client_manager, test_client, test_task, mock_websocket
    ):
        """Тест успішного призначення таску воркеру"""
        # Setup
        await client_manager.initialize()
        await client_manager.add_client(test_client)

        task_router.set_client_manager(client_manager)
        await task_router.initialize()

        # Submit and try to assign
        await task_router.submit_task(test_task)
        assignment_success = await task_router._try_assign_task(test_task)

        # Assertions
        assert assignment_success is True
        assert test_task.context.current_status == TaskStatus.PROCESSING
        assert test_task.context.worker_id == "test-worker-1"
        assert test_task.task_id in task_router.active_tasks

        # Verify WebSocket message was sent
        mock_websocket.send_json.assert_called_once()
        call_args = mock_websocket.send_json.call_args[0][0]
        assert call_args["type"] == "task_assign"
        assert call_args["task_id"] == test_task.task_id

    @pytest.mark.asyncio
    async def test_websocket_send_failure_rollback(
        self, task_router, client_manager, test_client, test_task, mock_websocket
    ):
        """Тест rollback при невдалому надсиланні через WebSocket"""
        # Setup WebSocket to fail
        mock_websocket.send_json.side_effect = Exception("WebSocket send failed")

        await client_manager.initialize()
        await client_manager.add_client(test_client)

        task_router.set_client_manager(client_manager)
        await task_router.initialize()

        # Submit and try to assign
        await task_router.submit_task(test_task)
        assignment_success = await task_router._try_assign_task(test_task)

        # Assertions - should fail and rollback
        assert assignment_success is False
        assert test_task.context.current_status == TaskStatus.PENDING  # Should be reset
        assert test_task.context.worker_id is None  # Should be reset
        assert test_task.task_id not in task_router.active_tasks

    @pytest.mark.asyncio
    async def test_redis_error_handling(self, task_router):
        """Тест обробки помилок Redis"""
        redis_handler = task_router.redis_error_handler

        # Mock operation that fails with Redis error
        async def failing_operation():
            raise Exception("too many connections")

        # Test retry logic
        result = await redis_handler.execute_with_retry(failing_operation)
        assert result is None
        assert redis_handler.connection_errors > 0

    @pytest.mark.asyncio
    async def test_queue_full_rejection(self, task_router, client_manager, test_task):
        """Тест відхилення таску при переповненні черги"""
        # Setup
        task_router.set_client_manager(client_manager)
        await task_router.initialize()

        # Mock queue as full
        queue = task_router.task_queues[TaskPriority.NORMAL]
        with patch.object(queue, "is_full", return_value=True):
            with patch.object(
                queue,
                "get_stats",
                return_value={
                    "total_tasks": 100,
                    "max_size": 100,
                    "utilization": 100.0,
                },
            ):
                success = await task_router.submit_task(test_task)

        # Assertions
        assert success is False
        assert len(test_task.context.errors) > 0
        assert test_task.context.errors[0]["error_type"] == "queue_full"

    @pytest.mark.asyncio
    async def test_client_manager_not_set_error(self, task_router, test_task):
        """Тест помилки при відсутності ClientManager"""
        # Don't set client manager
        await task_router.initialize()

        with pytest.raises(ValueError, match="ClientManager is not set"):
            await task_router.submit_task(test_task)

    @pytest.mark.asyncio
    async def test_fallback_worker_selection(self, client_manager, mock_settings):
        """Тест fallback логіки вибору воркера"""
        await client_manager.initialize()

        # Add client without specific capabilities
        info = ClientInfo(
            client_id="fallback-worker",
            client_type=ClientType.WORKER,
            client_name="Fallback Worker",
            capabilities=WorkerCapabilities(
                supported_task_types=["general"], max_concurrent_tasks=3
            ),
        )
        fallback_client = Client(info=info, websocket=AsyncMock())
        fallback_client.connect(AsyncMock())
        await client_manager.add_client(fallback_client)

        # Try to get worker with specific requirements
        worker = client_manager.get_best_worker(
            task_type="specific_task",
            worker_requirements=["specific_capability"],
            executor_type="worker",
        )

        # Should fall back to available worker
        assert worker is not None
        assert worker.info.client_id == "fallback-worker"

    @pytest.mark.asyncio
    async def test_executor_type_validation(self):
        """Тест валідації executor_type"""
        # Test string to enum mapping
        task = Task.create(
            task_type=TaskType.SEND_MESSAGE,
            data={"test": "data"},
            executor_type="bot",  # String instead of enum
        )
        assert task.executor_type == ExecutorType.BOT

        # Test unknown executor type
        task = Task.create(
            task_type=TaskType.SEND_MESSAGE,
            data={"test": "data"},
            executor_type="unknown_type",
        )
        assert task.executor_type == ExecutorType.WORKER  # Should default to WORKER

    @pytest.mark.asyncio
    async def test_task_timeout_handling(
        self, task_router, client_manager, test_client, test_task
    ):
        """Тест обробки таймауту таску"""
        # Setup
        await client_manager.initialize()
        await client_manager.add_client(test_client)

        task_router.set_client_manager(client_manager)
        await task_router.initialize()

        # Submit and assign task
        await task_router.submit_task(test_task)
        await task_router._try_assign_task(test_task)

        # Simulate timeout
        await task_router._handle_task_update(
            test_task.task_id,
            TaskStatus.TIMEOUT,
            worker_id="test-worker-1",
            error_message="Task timeout",
        )

        # Assertions
        assert test_task.context.current_status == TaskStatus.TIMEOUT
        assert test_task.task_id not in task_router.active_tasks
        assert test_task.task_id in task_router.task_history
