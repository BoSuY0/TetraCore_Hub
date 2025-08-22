"""
TetraCore StreamHub Async Task Handler

Заглушка для обробника задач. Усі завдання тепер перенаправляються 
на tetra-core-api воркери через HTTP API.
"""

import asyncio
import json
from datetime import datetime
from typing import Dict, Any, Optional
from enum import Enum
import structlog
import httpx

from models.messages import BaseMessage, MessageType, create_message
from models.client import Client
from models.task import Task, TaskPriority, TaskType
# Celery імпорти видалено - завдання тепер обробляються через tetra-core-api


class TaskProcessingMode(Enum):
    """Режими обробки задач"""
    API_REDIRECT = "api_redirect"  # Перенаправлення на tetra-core-api
    DIRECT = "direct"              # Пряма обробка через WebSocket


class AsyncTaskHandler:
    """Обробник задач - перенаправляє завдання на tetra-core-api воркери"""

    def __init__(self, stream_hub):
        self.hub = stream_hub
        self.logger = structlog.get_logger(__name__)
        self.async_optimizer = stream_hub.async_optimizer

        # Налаштування API для tetra-core-api
        self.api_base_url = "http://localhost:8081"  # Можна зробити конфігурабельним
        self.http_client = httpx.AsyncClient(timeout=30.0)

        # Налаштування режиму обробки
        self.processing_mode = TaskProcessingMode.API_REDIRECT

        # Статистика
        self.stats = {
            "api_redirected_tasks": 0,
            "direct_tasks": 0,
            "failed_tasks": 0
        }

    async def handle_task_submission(self, client: Client, message: BaseMessage):
        """Обробка подання завдання - перенаправлення на tetra-core-api"""

        # Валідація клієнта
        if not client.info.is_bot():
            await self._send_error(client, "UNAUTHORIZED", "Only bots can submit tasks")
            return

        try:
            # Створення завдання
            task = await self._create_task_from_message(message, client)

            # Визначення режиму обробки
            processing_mode = await self._determine_processing_mode(task)

            # Обробка залежно від режиму
            if processing_mode == TaskProcessingMode.API_REDIRECT:
                await self._handle_api_redirect(task, client)
            else:  # DIRECT
                await self._handle_direct_processing(task, client)

            # Оновлення статистики
            if processing_mode == TaskProcessingMode.API_REDIRECT:
                self.stats["api_redirected_tasks"] += 1
            else:
                self.stats["direct_tasks"] += 1

        except Exception as e:
            self.logger.error("Error handling task submission",
                            client_id=client.info.client_id,
                            error=str(e))
            self.stats["failed_tasks"] += 1
            await self._send_error(client, "TASK_SUBMISSION_ERROR", str(e))

    async def _create_task_from_message(self, message: BaseMessage, client: Client) -> Task:
        """Створення задачі з повідомлення"""
        task_type_str = getattr(message, 'task_type', 'custom')
        task_type = TaskType.CUSTOM if isinstance(task_type_str, str) else task_type_str

        task = Task.create(
            task_type=task_type,
            data=getattr(message, 'task_data', {}),
            priority=getattr(message, 'priority', TaskPriority.NORMAL),
            timeout=getattr(message, 'timeout', 300),
            max_retries=getattr(message, 'max_retries', 3),
            worker_requirements=getattr(message, 'worker_requirements', [])
        )

        task.context.client_id = client.info.client_id
        task.context.correlation_id = getattr(message, 'correlation_id', None)

        return task

    async def _determine_processing_mode(self, task: Task) -> TaskProcessingMode:
        """Визначення оптимального режиму обробки задачі"""

        # За замовчуванням перенаправляємо на API
        if self.processing_mode == TaskProcessingMode.API_REDIRECT:
            return TaskProcessingMode.API_REDIRECT

        # Критичні завдання з маленьким розміром можна обробити локально
        is_high_priority = task.priority == TaskPriority.CRITICAL
        data_size = len(json.dumps(task.data))
        is_lightweight = data_size < 1024  # < 1KB

        if is_high_priority and is_lightweight:
            return TaskProcessingMode.DIRECT

        # Все інше перенаправляємо на API
        return TaskProcessingMode.API_REDIRECT

    async def _handle_api_redirect(self, task: Task, client: Client):
        """Перенаправлення завдання на tetra-core-api воркери"""
        self.logger.info("Redirecting task to tetra-core-api",
                        task_id=task.task_id,
                        mode="api_redirect")

        try:
            # Підготовка даних для API запиту
            task_payload = {
                "action": task.task_type.value.lower(),
                "params": {
                    "task_id": task.task_id,
                    "task_data": task.data,
                    "client_id": client.info.client_id,
                    "correlation_id": task.context.correlation_id,
                    "priority": task.priority.value,
                    "timeout": task.timeout,
                    "max_retries": task.max_retries,
                    "submitted_at": datetime.utcnow().isoformat()
                }
            }

            # Відправка завдання на tetra-core-api
            response = await self.http_client.post(
                f"{self.api_base_url}/api/v1/tasks",
                json=task_payload,
                headers={"Content-Type": "application/json"}
            )

            if response.status_code == 202:  # Accepted
                result = response.json()
                api_task_id = result.get("task_id")
                
                # Відправка підтвердження клієнту
                await self._send_task_accepted(client, task, api_task_id)
                
                # Запуск моніторингу статусу
                asyncio.create_task(self._monitor_api_task(
                    task.task_id, api_task_id, client
                ))

            else:
                error_msg = f"API returned status {response.status_code}"
                await self._send_error(client, "API_ERROR", error_msg)

        except httpx.TimeoutException:
            await self._send_error(client, "API_TIMEOUT", "API request timed out")
        except httpx.ConnectError:
            await self._send_error(client, "API_UNAVAILABLE", "Cannot connect to tetra-core-api")
        except Exception as e:
            self.logger.error("Failed to redirect task to API",
                            task_id=task.task_id,
                            error=str(e))
            await self._send_error(client, "API_REDIRECT_ERROR", str(e))

    async def _handle_direct_processing(self, task: Task, client: Client):
        """Пряма обробка через WebSocket (legacy mode)"""
        self.logger.info("Processing task directly",
                        task_id=task.task_id,
                        mode="direct")

        # Використання існуючого task router
        success = await self.hub.task_router.submit_task(task)

        if success:
            await self._send_task_accepted(client, task)
        else:
            await self._send_error(client, "TASK_REJECTED",
                                 "Task queue is full or task rejected")

    async def _monitor_api_task(self, task_id: str, api_task_id: str,
                               client: Client, max_wait: int = 300):
        """Моніторинг статусу API завдання"""
        start_time = datetime.utcnow()
        last_status = None

        while (datetime.utcnow() - start_time).total_seconds() < max_wait:
            try:
                # Перевірка статусу через API
                response = await self.http_client.get(
                    f"{self.api_base_url}/api/v1/tasks/{api_task_id}"
                )

                if response.status_code == 200:
                    task_result = response.json()
                    current_status = task_result.get("status")

                    if current_status != last_status:
                        last_status = current_status

                        # Відправка оновлення статусу клієнту
                        await self._send_task_status_update(
                            client, task_id, task_result
                        )

                        # Якщо завдання завершено
                        if current_status in ["completed", "failed"]:
                            if current_status == "completed" and "result" in task_result:
                                await self._send_task_result(client, task_id, task_result["result"])
                            break

                elif response.status_code == 404:
                    # Завдання не знайдено
                    await self._send_error(client, "TASK_NOT_FOUND", f"Task {api_task_id} not found")
                    break

                await asyncio.sleep(2)  # Перевірка кожні 2 секунди

            except Exception as e:
                self.logger.error("Error monitoring API task",
                                task_id=task_id,
                                api_task_id=api_task_id,
                                error=str(e))
                break

    # === Видалено всі Celery методи - завдання тепер обробляються через tetra-core-api ===

    async def _send_task_accepted(self, client: Client, task: Task,
                                  api_task_id: Optional[str] = None):
        """Відправка підтвердження прийняття задачі"""
        response = create_message(
            MessageType.TASK_ACCEPTED,
            task_id=task.task_id,
            api_task_id=api_task_id,
            status="accepted",
            timestamp=datetime.utcnow().isoformat()
        )

        await client.websocket.send_json(response.model_dump(mode='json'))

    async def _send_task_status_update(self, client: Client, task_id: str,
                                       task_result):
        """Відправка оновлення статусу задачі"""
        response = create_message(
            MessageType.TASK_STATUS,
            task_id=task_id,
            status=task_result.status.value,
            progress=getattr(task_result, 'progress', None),
            timestamp=datetime.utcnow().isoformat()
        )

        await client.websocket.send_json(response.model_dump(mode='json'))

    async def _send_task_result(self, client: Client, task_id: str, result: Any):
        """Відправка результату задачі"""
        response = create_message(
            MessageType.TASK_RESULT,
            task_id=task_id,
            result=result,
            timestamp=datetime.utcnow().isoformat()
        )

        await client.websocket.send_json(response.model_dump(mode='json'))

    async def _send_error(self, client: Client, error_code: str,
                          error_message: str):
        """Відправка повідомлення про помилку"""
        response = create_message(
            MessageType.ERROR,
            error_code=error_code,
            error_message=error_message,
            timestamp=datetime.utcnow().isoformat()
        )

        await client.websocket.send_json(response.model_dump(mode='json'))

    def get_stats(self) -> Dict[str, Any]:
        """Отримання статистики обробки"""
        total_tasks = sum(self.stats.values())

        return {
            **self.stats,
            'total_tasks': total_tasks,
            'api_base_url': self.api_base_url,
            'processing_mode': self.processing_mode.value
        }

    async def shutdown(self):
        """Завершення роботи обробника"""
        if hasattr(self, 'http_client'):
            await self.http_client.aclose()
