"""
TetraCore StreamHub Task Router

Маршрутизатор завдань для StreamHub.
Відповідає за розподіл завдань між воркерами, балансування навантаження,
обробку результатів та управління чергами завдань.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Callable, Any
from collections import defaultdict
import structlog

from config import Settings
from models.task import Task, TaskType, TaskStatus, TaskPriority, TaskQueue
from models.client import Client, ClientType
from models.messages import BaseMessage, MessageType, create_message


class TaskRouter:
    """Маршрутизатор завдань StreamHub"""

    def __init__(self, settings: Settings, redis_manager=None):
        """Ініціалізація маршрутизатора завдань"""
        self.settings = settings
        self.redis_manager = redis_manager
        self.logger = structlog.get_logger(__name__)

        # Черги завдань за пріоритетами
        self.task_queues: Dict[TaskPriority, TaskQueue] = {
            TaskPriority.CRITICAL: TaskQueue(name="critical", max_size=1000),
            TaskPriority.HIGH: TaskQueue(name="high", max_size=5000),
            TaskPriority.NORMAL: TaskQueue(name="normal", max_size=10000),
            TaskPriority.LOW: TaskQueue(name="low", max_size=20000)
        }

        # Активні завдання (task_id -> task)
        self.active_tasks: Dict[str, Task] = {}

        # Завдання, призначені воркерам (worker_id -> set of task_ids)
        self.worker_tasks: Dict[str, Set[str]] = defaultdict(set)

        # Завдання, що очікують результату (task_id -> client_websocket)
        self.pending_results: Dict[str, Any] = {}

        # Статистика
        self.total_submitted = 0
        self.total_completed = 0
        self.total_failed = 0
        self.total_timeout = 0
        self.total_cancelled = 0

        # Event handlers
        self.on_task_assigned: Optional[Callable] = None
        self.on_task_completed: Optional[Callable] = None
        self.on_task_failed: Optional[Callable] = None

        # Стан маршрутизатора
        self.is_running = False
        self.timeout_task: Optional[asyncio.Task] = None
        self.cleanup_task: Optional[asyncio.Task] = None

        # Посилання на ClientManager (буде встановлено ззовні)
        self.client_manager = None

    async def initialize(self):
        """Ініціалізація маршрутизатора"""
        try:
            self.logger.info("Initializing TaskRouter")

            # Запуск фонових задач
            self.timeout_task = asyncio.create_task(self._timeout_monitor())
            self.cleanup_task = asyncio.create_task(self._cleanup_loop())

            self.is_running = True
            self.logger.info("TaskRouter initialized successfully")

        except Exception as e:
            self.logger.error("Failed to initialize TaskRouter", error=str(e))
            raise

    async def shutdown(self):
        """Зупинка маршрутизатора"""
        self.logger.info("Shutting down TaskRouter")

        self.is_running = False

        # Зупинка фонових задач
        for task in [self.timeout_task, self.cleanup_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Скасування всіх активних завдань
        for task_id in list(self.active_tasks.keys()):
            await self.cancel_task(task_id, "System shutdown")

        self.logger.info("TaskRouter shutdown complete")

    async def submit_task(self, task: Task) -> bool:
        """Подання нового завдання"""
        try:
            # Перевірка чи черга не переповнена
            queue = self.task_queues[task.priority]
            if queue.is_full():
                self.logger.warning("Task queue is full",
                                  priority=task.priority.value,
                                  task_id=task.task_id)
                return False

            # Додавання до черги
            if not queue.add_task(task):
                self.logger.error("Failed to add task to queue",
                                task_id=task.task_id,
                                priority=task.priority.value)
                return False

            # Додавання до активних завдань
            self.active_tasks[task.task_id] = task

            # Оновлення статистики
            self.total_submitted += 1

            # Спроба призначити завдання негайно
            await self._try_assign_task(task)

            self.logger.info("Task submitted successfully",
                           task_id=task.task_id,
                           priority=task.priority.value,
                           task_type=task.task_type.value)

            return True

        except Exception as e:
            self.logger.error("Failed to submit task",
                            task_id=task.task_id,
                            error=str(e))
            return False

    async def _try_assign_task(self, task: Task) -> bool:
        """Спроба призначити завдання воркеру"""
        try:
            if not self.client_manager:
                return False

            # Пошук найкращого воркера
            worker = self.client_manager.get_best_worker(
                task_type=task.task_type.value,
                worker_requirements=task.worker_requirements
            )

            if not worker:
                self.logger.debug("No available worker found",
                                task_id=task.task_id,
                                task_type=task.task_type.value)
                return False

            # Призначення завдання
            return await self._assign_task_to_worker(task, worker)

        except Exception as e:
            self.logger.error("Error trying to assign task",
                            task_id=task.task_id,
                            error=str(e))
            return False

    async def _assign_task_to_worker(self, task: Task, worker: 'Client') -> bool:
        """Призначення завдання конкретному воркеру"""
        try:
            worker_id = worker.info.client_id

            # Призначення завдання
            task.assign_to_worker(worker_id)
            task.start_execution()

            # Оновлення внутрішніх структур
            self.worker_tasks[worker_id].add(task.task_id)

            # Призначення завдання в клієнта
            if not worker.assign_task(task.task_id):
                self.logger.error("Worker rejected task assignment",
                                task_id=task.task_id,
                                worker_id=worker_id)
                return False

            # Видалення з черги
            queue = self.task_queues[task.priority]
            queue.remove_task(task.task_id)

            # Створення повідомлення для воркера
            assignment_message = create_message(
                MessageType.TASK_ASSIGN,
                task_id=task.task_id,
                worker_id=worker_id,
                task_type=task.task_type.value,
                task_data=task.data,
                priority=task.priority.value,
                timeout=task.timeout,
                assigned_at=datetime.utcnow()
            )

            # Відправка завдання воркеру
            if worker.websocket:
                await worker.websocket.send_json(assignment_message.model_dump(mode='json'))

            # Виклик callback
            if self.on_task_assigned:
                await self.on_task_assigned(task, worker_id)

            self.logger.info("Task assigned successfully",
                           task_id=task.task_id,
                           worker_id=worker_id,
                           task_type=task.task_type.value)

            return True

        except Exception as e:
            self.logger.error("Failed to assign task to worker",
                            task_id=task.task_id,
                            worker_id=worker.info.client_id,
                            error=str(e))
            return False

    async def handle_task_result(self, task_id: str, worker_id: str,
                                status: TaskStatus, result: Dict[str, Any] = None,
                                error_message: str = None, execution_time: int = None):
        """Обробка результату завдання від воркера"""
        try:
            # Перевірка наявності завдання
            if task_id not in self.active_tasks:
                self.logger.warning("Received result for unknown task",
                                  task_id=task_id,
                                  worker_id=worker_id)
                return

            task = self.active_tasks[task_id]

            # Оновлення статусу завдання
            if status == TaskStatus.COMPLETED:
                task.complete(result or {})
                self.total_completed += 1
            elif status == TaskStatus.FAILED:
                task.fail(error_message or "Task failed", "")
                self.total_failed += 1
            elif status == TaskStatus.TIMEOUT:
                task.timeout()
                self.total_timeout += 1

            # Оновлення статистики воркера
            if self.client_manager:
                worker = self.client_manager.get_client(worker_id)
                if worker:
                    worker.complete_task(task_id, status, execution_time)

            # Видалення з активних завдань воркера
            self.worker_tasks[worker_id].discard(task_id)

            # Відправка результату боту
            await self._send_result_to_client(task)

            # Видалення з активних завдань
            del self.active_tasks[task_id]

            # Виклик callbacks
            if status == TaskStatus.COMPLETED and self.on_task_completed:
                await self.on_task_completed(task)
            elif status in [TaskStatus.FAILED, TaskStatus.TIMEOUT] and self.on_task_failed:
                await self.on_task_failed(task, error_message or "Task failed")

            # Спроба призначити наступне завдання з черги
            await self._process_next_task()

            self.logger.info("Task result processed",
                           task_id=task_id,
                           worker_id=worker_id,
                           status=status.value,
                           execution_time=execution_time)

        except Exception as e:
            self.logger.error("Failed to handle task result",
                            task_id=task_id,
                            worker_id=worker_id,
                            error=str(e))

    async def _send_result_to_client(self, task: Task):
        """Відправка результату завдання клієнту"""
        try:
            if not task.context.client_id:
                return

            if not self.client_manager:
                return

            client = self.client_manager.get_client(task.context.client_id)
            if not client or not client.websocket:
                return

            # Створення повідомлення з результатом
            result_message = create_message(
                MessageType.TASK_RESULT,
                task_id=task.task_id,
                status=task.context.current_status.value,
                result=task.context.result,
                error_message=task.context.errors[-1]["error_message"] if task.context.errors else None,
                execution_time=int(task.context.get_execution_time() * 1000) if task.context.get_execution_time() else None,
                correlation_id=task.context.correlation_id,
                completed_at=datetime.utcnow()
            )

            await client.websocket.send_json(result_message.model_dump(mode='json'))

        except Exception as e:
            self.logger.error("Failed to send result to client",
                            task_id=task.task_id,
                            client_id=task.context.client_id,
                            error=str(e))

    async def _process_next_task(self):
        """Обробка наступного завдання з черги"""
        try:
            if not self.client_manager:
                return

            # Пошук завдання в порядку пріоритету
            for priority in [TaskPriority.CRITICAL, TaskPriority.HIGH, TaskPriority.NORMAL, TaskPriority.LOW]:
                queue = self.task_queues[priority]

                if queue.is_empty():
                    continue

                # Пошук доступного воркера
                available_workers = self.client_manager.get_available_workers()
                if not available_workers:
                    break

                # Отримання наступного завдання
                next_task = queue.get_next_task()
                if next_task:
                    await self._try_assign_task(next_task)
                    break

        except Exception as e:
            self.logger.error("Error processing next task", error=str(e))

    async def cancel_task(self, task_id: str, reason: str = "Cancelled by user") -> bool:
        """Скасування завдання"""
        try:
            if task_id not in self.active_tasks:
                # Спроба знайти в чергах
                for queue in self.task_queues.values():
                    task = queue.remove_task(task_id)
                    if task:
                        task.cancel(reason)
                        self.total_cancelled += 1
                        return True
                return False

            task = self.active_tasks[task_id]

            # Якщо завдання призначене воркеру, сповістити його
            if task.context.worker_id and self.client_manager:
                worker = self.client_manager.get_client(task.context.worker_id)
                if worker and worker.websocket:
                    if worker.websocket:
                        cancel_message = create_message(
                            MessageType.TASK_CANCEL,
                            task_id=task_id,
                            reason=reason
                        )
                        await worker.websocket.send_json(cancel_message.model_dump(mode='json'))

                # Видалення з завдань воркера
                self.worker_tasks[task.context.worker_id].discard(task_id)

            # Скасування завдання
            task.cancel(reason)

            # Відправка результату клієнту
            await self._send_result_to_client(task)

            # Видалення з активних завдань
            del self.active_tasks[task_id]

            self.total_cancelled += 1

            self.logger.info("Task cancelled",
                           task_id=task_id,
                           reason=reason)

            return True

        except Exception as e:
            self.logger.error("Failed to cancel task",
                            task_id=task_id,
                            error=str(e))
            return False

    async def reassign_worker_tasks(self, worker_id: str):
        """Переназначення завдань від відключеного воркера"""
        try:
            if worker_id not in self.worker_tasks:
                return

            task_ids = list(self.worker_tasks[worker_id])
            self.worker_tasks[worker_id].clear()

            for task_id in task_ids:
                if task_id in self.active_tasks:
                    task = self.active_tasks[task_id]

                    # Повернення завдання в чергу
                    queue = self.task_queues[task.priority]
                    if not queue.is_full():
                        task.context.worker_id = None
                        task.context.assigned_at = None
                        task.context.add_status_change(TaskStatus.PENDING, f"Reassigned from worker {worker_id}")

                        queue.add_task(task)

                        # Спроба призначити іншому воркеру
                        await self._try_assign_task(task)
                    else:
                        # Якщо черга переповнена, скасовуємо завдання
                        await self.cancel_task(task_id, f"Worker {worker_id} disconnected and queue is full")

            self.logger.info("Worker tasks reassigned",
                           worker_id=worker_id,
                           task_count=len(task_ids))

        except Exception as e:
            self.logger.error("Failed to reassign worker tasks",
                            worker_id=worker_id,
                            error=str(e))

    async def get_queue_stats(self) -> Dict[str, Any]:
        """Отримання статистики черг"""
        try:
            stats = {
                "queue_sizes": {},
                "total_active": len(self.active_tasks),
                "total_submitted": self.total_submitted,
                "total_completed": self.total_completed,
                "total_failed": self.total_failed,
                "total_timeout": self.total_timeout,
                "total_cancelled": self.total_cancelled,
                "worker_assignments": {
                    worker_id: len(task_ids)
                    for worker_id, task_ids in self.worker_tasks.items()
                    if task_ids
                }
            }

            # Статистика черг
            for priority, queue in self.task_queues.items():
                queue_stats = queue.get_stats()
                stats["queue_sizes"][priority.value] = queue_stats["total_tasks"]

            return stats

        except Exception as e:
            self.logger.error("Failed to get queue stats", error=str(e))
            return {}

    def is_healthy(self) -> bool:
        """Перевірка здоров'я маршрутизатора"""
        return self.is_running

    async def _timeout_monitor(self):
        """Моніторинг таймаутів завдань"""
        while self.is_running:
            try:
                now = datetime.utcnow()
                timeout_tasks = []

                for task_id, task in self.active_tasks.items():
                    if (task.context.started_at and
                        (now - task.context.started_at).total_seconds() > task.timeout):
                        timeout_tasks.append(task_id)

                for task_id in timeout_tasks:
                    task = self.active_tasks.get(task_id)
                    if task:
                        await self.handle_task_result(
                            task_id=task_id,
                            worker_id=task.context.worker_id or "unknown",
                            status=TaskStatus.TIMEOUT,
                            error_message="Task execution timeout"
                        )

                await asyncio.sleep(10)  # Перевірка кожні 10 секунд

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in timeout monitor", error=str(e))
                await asyncio.sleep(5)

    async def _cleanup_loop(self):
        """Фонова задача очищення"""
        while self.is_running:
            try:
                # Очищення прострочених завдань з черг
                for queue in self.task_queues.values():
                    expired_count = queue.clear_expired_tasks()
                    if expired_count > 0:
                        self.logger.info("Cleared expired tasks",
                                       queue=queue.name,
                                       count=expired_count)

                await asyncio.sleep(300)  # Очищення кожні 5 хвилин

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in cleanup loop", error=str(e))
                await asyncio.sleep(60)

    def set_client_manager(self, client_manager):
        """Встановлення посилання на ClientManager"""
        self.client_manager = client_manager
