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
import orjson
import uuid

from config import Settings
from models.task import Task, TaskType, TaskStatus, TaskPriority, TaskQueue
from models.client import Client, ClientType
from models.messages import BaseMessage, MessageType, create_message


class RedisErrorHandler:
    """Обробник помилок Redis з exponential backoff"""

    def __init__(self, max_retries: int = 3, base_delay: float = 0.5):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.connection_errors = 0
        self.last_error_time = None
        self.logger = structlog.get_logger(__name__)

    async def execute_with_retry(self, operation, *args, **kwargs):
        """Виконання Redis операції з retry логікою"""
        last_exception = None

        for attempt in range(self.max_retries + 1):
            try:
                return await operation(*args, **kwargs)

            except Exception as e:
                last_exception = e
                error_str = str(e).lower()

                # Перевіряємо тип помилки
                if "too many connections" in error_str:
                    self.connection_errors += 1
                    self.last_error_time = datetime.utcnow()

                    if attempt < self.max_retries:
                        delay = self.base_delay * (2**attempt)  # Exponential backoff
                        self.logger.warning(
                            "Redis connection limit reached, retrying",
                            attempt=attempt + 1,
                            delay=delay,
                            error=str(e),
                        )
                        await asyncio.sleep(delay)
                        continue

                elif "connection" in error_str or "timeout" in error_str:
                    if attempt < self.max_retries:
                        delay = self.base_delay * (2**attempt)
                        self.logger.warning(
                            "Redis connection error, retrying",
                            attempt=attempt + 1,
                            delay=delay,
                            error=str(e),
                        )
                        await asyncio.sleep(delay)
                        continue

                # Інші помилки не retry
                break

        # Якщо всі спроби невдалі
        self.logger.error(
            "Redis operation failed after all retries",
            attempts=self.max_retries + 1,
            error=str(last_exception),
        )
        return None

    def should_skip_redis(self) -> bool:
        """Перевірка чи слід пропустити Redis операції"""
        if self.connection_errors > 10 and self.last_error_time:
            # Пропускаємо Redis на 5 хвилин після багатьох помилок
            if (datetime.utcnow() - self.last_error_time).total_seconds() < 300:
                return True
        return False


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
            TaskPriority.LOW: TaskQueue(name="low", max_size=20000),
        }

        # Активні завдання (task_id -> task)
        self.active_tasks: Dict[str, Task] = {}

        # Історія всіх завдань (task_id -> task) - зберігає completed/failed/cancelled tasks
        self.task_history: Dict[str, Task] = {}

        # Максимальний розмір історії (для уникнення переповнення пам'яті)
        self.max_history_size = 10000

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

        # Ініціалізація Redis клієнта
        self.redis_manager = redis_manager
        if self.redis_manager and hasattr(self.redis_manager, "redis_client"):
            self.redis_client = self.redis_manager.redis_client
        elif settings.redis_enabled:
            self.logger.warning(
                "Redis enabled in settings but no Redis manager provided"
            )
            self.redis_client = None
        else:
            self.redis_client = None

        # Redis error handler
        self.redis_error_handler = RedisErrorHandler(max_retries=3, base_delay=0.5)

    async def initialize(self):
        """Ініціалізація роутера"""
        try:
            # Ініціалізація Redis клієнта
            try:
                # Використовуємо існуючий redis_manager або створюємо новий
                if self.redis_manager:
                    self.redis_client = self.redis_manager.redis_client
                    self.logger.info("Redis клієнт отримано з існуючого redis_manager")
                else:
                    self.logger.info(
                        "Redis manager не доступний, пропускаємо ініціалізацію Redis"
                    )
                    self.redis_client = None
            except Exception as e:
                self.logger.warning(f"Не вдалося ініціалізувати Redis: {e}")
                self.redis_client = None

            # Запуск фонових завдань
            self._timeout_task = asyncio.create_task(self._timeout_monitor())
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

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
            # Критична перевірка наявності ClientManager
            if not self.client_manager:
                self.logger.error(
                    "[TASK_ROUTER] ClientManager not initialized! Cannot submit tasks.",
                    task_id=task.task_id,
                )
                raise ValueError(
                    "ClientManager is not set. Call set_client_manager() first."
                )

            self.logger.info(
                "[TASK_ROUTER] Received task submission",
                task_id=task.task_id,
                task_type=(
                    task.task_type.value
                    if hasattr(task.task_type, "value")
                    else task.task_type
                ),
                executor_type=(
                    task.executor_type.value
                    if hasattr(task, "executor_type")
                    else "unknown"
                ),
                priority=task.priority.value,
            )

            # Перевірка чи черга не переповнена
            queue = self.task_queues[task.priority]
            if queue.is_full():
                queue_stats = queue.get_stats()
                self.logger.warning(
                    "Task queue is full - rejecting task",
                    priority=task.priority.value,
                    task_id=task.task_id,
                    queue_size=queue_stats["total_tasks"],
                    max_size=queue_stats["max_size"],
                    utilization=f"{queue_stats['utilization']:.1f}%",
                )

                # Додаємо помилку до контексту таску для кращої діагностики
                task.context.add_error(
                    "queue_full",
                    f"Task queue '{queue.name}' is full ({queue_stats['total_tasks']}/{queue_stats['max_size']})",
                    None,
                )
                return False

            # Додавання до черги
            if not queue.add_task(task):
                self.logger.error(
                    "Failed to add task to queue - internal error",
                    task_id=task.task_id,
                    priority=task.priority.value,
                )
                task.context.add_error(
                    "queue_add_failed", "Internal error adding task to queue", None
                )
                return False

            self.logger.info(
                "[TASK_ROUTER] Task added to queue successfully",
                task_id=task.task_id,
                priority=task.priority.value,
                executor_type=(
                    task.executor_type.value
                    if hasattr(task, "executor_type")
                    else "unknown"
                ),
                queue_size=len(queue.tasks),
                active_tasks_count=len(self.active_tasks),
            )

            # Логування стану таску
            self.logger.info(
                "[TASK_STATE] ✅ Таск прийнято і поставлено в чергу",
                task_id=task.task_id,
                task_type=(
                    task.task_type.value
                    if hasattr(task.task_type, "value")
                    else task.task_type
                ),
                state="PENDING",
                priority=task.priority.value,
                executor_type=(
                    task.executor_type.value
                    if hasattr(task, "executor_type")
                    else "unknown"
                ),
                status="В очікуванні доступного виконавця",
                queue_position=len(queue.tasks),
                in_active_tasks=False,
            )

            # Оновлення статистики
            self.total_submitted += 1

            # Очищаємо кеш статистики при додаванні нового таску
            await self._invalidate_stats_cache()

            # Спроба призначити завдання негайно
            assigned = await self._try_assign_task(task)

            # Додавання до активних завдань тільки якщо таск було призначено
            # Інакше він залишається тільки в черзі як PENDING
            if assigned:
                self.active_tasks[task.task_id] = task

            self.logger.debug(
                "[TASK_ROUTER] Task assignment attempt",
                task_id=task.task_id,
                assigned=assigned,
                executor_type=(
                    task.executor_type.value
                    if hasattr(task, "executor_type")
                    else "unknown"
                ),
            )

            if not assigned:
                executor_desc = {
                    "bot": "бота",
                    "worker": "воркера",
                    "worker_api": "API воркера",
                }
                exec_type = (
                    task.executor_type.value
                    if hasattr(task, "executor_type")
                    else "unknown"
                )
                self.logger.info(
                    "[TASK_STATE] ⏳ Таск залишається в черзі",
                    task_id=task.task_id,
                    state="PENDING",
                    reason="Немає доступних виконавців",
                    status=f"Очікує вільного {executor_desc.get(exec_type, 'виконавця')}",
                )

            self.logger.info(
                "Task submitted successfully",
                task_id=task.task_id,
                priority=task.priority.value,
                task_type=task.task_type.value,
            )

            return True

        except Exception as e:
            self.logger.error(
                "Failed to submit task", task_id=task.task_id, error=str(e)
            )
            return False

    async def _try_assign_task(self, task: Task) -> bool:
        """Спроба призначити завдання воркеру"""
        try:
            if not self.client_manager:
                self.logger.warning(
                    "[TASK_ROUTER] No client manager available", task_id=task.task_id
                )
                return False

            executor_desc = {
                "bot": "bot",
                "worker": "worker",
                "worker_api": "API worker",
            }
            exec_type = (
                task.executor_type.value
                if hasattr(task, "executor_type")
                else "unknown"
            )
            self.logger.debug(
                f"[TASK_ROUTER] Looking for {executor_desc.get(exec_type, 'executor')}",
                task_id=task.task_id,
                task_type=task.task_type.value,
                executor_type=exec_type,
                worker_requirements=task.worker_requirements,
            )

            # Пошук найкращого воркера
            worker = self.client_manager.get_best_worker(
                task_type=task.task_type.value,
                worker_requirements=task.worker_requirements,
                executor_type=task.executor_type.value,
            )

            if not worker:
                executor_desc = {
                    "bot": "bot",
                    "worker": "worker",
                    "worker_api": "API worker",
                }
                exec_type = (
                    task.executor_type.value
                    if hasattr(task, "executor_type")
                    else "unknown"
                )
                self.logger.debug(
                    f"[TASK_ROUTER] No available {executor_desc.get(exec_type, 'executor')} found",
                    task_id=task.task_id,
                    task_type=task.task_type.value,
                    executor_type=exec_type,
                    worker_requirements=task.worker_requirements,
                )
                return False

            # Призначення завдання
            return await self._assign_task_to_worker(task, worker)

        except Exception as e:
            self.logger.error(
                "Error trying to assign task", task_id=task.task_id, error=str(e)
            )
            return False

    async def _assign_task_to_worker(self, task: Task, worker: "Client") -> bool:
        """Призначення завдання конкретному воркеру"""
        try:
            worker_id = worker.info.client_id

            # Призначення завдання БЕЗ зміни статусу на PROCESSING (тільки ASSIGNED)
            task.assign_to_worker(worker_id)

            # Перевірка можливості воркера прийняти завдання
            if not worker.assign_task(task.task_id):
                self.logger.error(
                    "Worker rejected task assignment",
                    task_id=task.task_id,
                    worker_id=worker_id,
                )
                # Додати більше логування
                self.logger.error(
                    f"Worker details: type={worker.info.client_type}, capabilities={worker.info.capabilities}, active_tasks={worker.info.stats.active_tasks}, max_tasks={worker.info.capabilities.max_concurrent_tasks if worker.info.capabilities else 0}"
                )

                # Скидання призначення
                task.context.reset_assignment()
                return False

            # Створення повідомлення для воркера
            assignment_message = create_message(
                MessageType.TASK_ASSIGN,
                task_id=task.task_id,
                worker_id=worker_id,
                task_type=task.task_type.value,
                task_data=task.data,
                priority=task.priority.value,
                timeout=task.timeout,
                assigned_at=datetime.utcnow(),
            )

            # Відправка завдання воркеру з обробкою помилок та ретраями
            send_success = False
            max_send_attempts = 3
            send_attempt = 0

            while send_attempt < max_send_attempts and not send_success:
                send_attempt += 1
                try:
                    if worker.websocket and worker.websocket.client_state.name in [
                        "CONNECTED",
                        "CONNECTING",
                    ]:
                        # Відправка з таймаутом
                        await asyncio.wait_for(
                            worker.websocket.send_json(
                                assignment_message.model_dump(mode="json")
                            ),
                            timeout=5.0,  # 5 секунд таймаут
                        )
                        send_success = True
                        self.logger.info(
                            "Task message sent successfully",
                            task_id=task.task_id,
                            worker_id=worker_id,
                            attempt=send_attempt,
                        )
                    else:
                        self.logger.warning(
                            "Worker websocket not available",
                            task_id=task.task_id,
                            worker_id=worker_id,
                            websocket_state=(
                                worker.websocket.client_state.name
                                if worker.websocket
                                else "None"
                            ),
                        )
                        break

                except asyncio.TimeoutError:
                    self.logger.warning(
                        "WebSocket send timeout",
                        task_id=task.task_id,
                        worker_id=worker_id,
                        attempt=send_attempt,
                    )
                    if send_attempt < max_send_attempts:
                        await asyncio.sleep(0.5 * send_attempt)  # Exponential backoff

                except Exception as e:
                    self.logger.error(
                        "WebSocket send error",
                        task_id=task.task_id,
                        worker_id=worker_id,
                        attempt=send_attempt,
                        error=str(e),
                    )
                    if send_attempt < max_send_attempts:
                        await asyncio.sleep(0.5 * send_attempt)  # Exponential backoff

            # Якщо надсилання не вдалося після всіх спроб
            if not send_success:
                self.logger.error(
                    "Failed to send task after all attempts",
                    task_id=task.task_id,
                    worker_id=worker_id,
                    attempts=max_send_attempts,
                )

                # Скидання призначення та повернення таску в чергу
                worker.release_task(task.task_id)
                task.context.reset_assignment()
                return False

            # ТІЛЬКИ ТЕПЕР встановлюємо статус PROCESSING після успішного надсилання
            task.start_execution()

            # Оновлення внутрішніх структур після успішного надсилання
            self.worker_tasks[worker_id].add(task.task_id)

            # Видалення з черги
            queue = self.task_queues[task.priority]
            queue.remove_task(task.task_id)

            # Додавання до активних завдань після успішного призначення
            self.active_tasks[task.task_id] = task

            # Логування додавання в active_tasks
            self.logger.info(
                "[TASK_STATE] ✅ Таск додано в active_tasks після успішного надсилання",
                task_id=task.task_id,
                worker_id=worker_id,
                active_tasks_count=len(self.active_tasks),
            )

            # Виклик callback
            if self.on_task_assigned:
                await self.on_task_assigned(task, worker_id)

            self.logger.info(
                "Task assigned successfully",
                task_id=task.task_id,
                worker_id=worker_id,
                task_type=task.task_type.value,
            )

            return True

        except Exception as e:
            self.logger.error(
                "Failed to assign task to worker",
                task_id=task.task_id,
                worker_id=worker.info.client_id if "worker" in locals() else "unknown",
                error=str(e),
            )

            # Скидання призначення при будь-якій помилці
            if "worker" in locals() and "task" in locals():
                try:
                    worker.release_task(task.task_id)
                    task.context.reset_assignment()
                except:
                    pass
            return False

    async def handle_task_result(
        self,
        task_id: str,
        worker_id: str,
        status: TaskStatus,
        result: Dict[str, Any] = None,
        error_message: str = None,
        execution_time: int = None,
    ):
        """Обробка результату завдання від воркера"""
        try:
            # Перевірка наявності завдання
            if task_id not in self.active_tasks:
                self.logger.warning(
                    "Received result for unknown task",
                    task_id=task_id,
                    worker_id=worker_id,
                )
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

            # Збереження результату в Redis для API воркера або бота
            if self.redis_client and not self.redis_error_handler.should_skip_redis():

                async def _save_result():
                    result_key = f"task_result:{task_id}"
                    result_data = {
                        "success": status == TaskStatus.COMPLETED,
                        "result": result,
                        "error": error_message,
                        "status": status.value,
                        "worker_id": worker_id,
                        "execution_time": execution_time,
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                    # Зберігаємо результат на 5 хвилин
                    await self.redis_client.set(
                        result_key, orjson.dumps(result_data), ex=300
                    )
                    return True

                success = await self.redis_error_handler.execute_with_retry(
                    _save_result
                )
                if success:
                    self.logger.debug(f"Результат завдання {task_id} збережено в Redis")
                else:
                    self.logger.warning(
                        f"Не вдалося зберегти результат в Redis після спроб: {task_id}"
                    )

            # Відправка результату боту
            await self._send_result_to_client(task)

            # Переміщення з активних завдань в історію
            del self.active_tasks[task_id]
            self._add_to_history(task)

            # Очищаємо кеш статистики при зміні статусу таску
            await self._invalidate_stats_cache()

            # Виклик callbacks
            if status == TaskStatus.COMPLETED and self.on_task_completed:
                await self.on_task_completed(task)
            elif (
                status in [TaskStatus.FAILED, TaskStatus.TIMEOUT]
                and self.on_task_failed
            ):
                await self.on_task_failed(task, error_message or "Task failed")

            # Спроба призначити наступне завдання з черги
            await self._process_next_task()

            self.logger.info(
                "Task result processed",
                task_id=task_id,
                worker_id=worker_id,
                status=status.value if hasattr(status, "value") else str(status),
                execution_time=execution_time,
            )

        except Exception as e:
            self.logger.error(
                "Failed to handle task result",
                task_id=task_id,
                worker_id=worker_id,
                error=str(e),
            )

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
                error_message=(
                    task.context.errors[-1]["error_message"]
                    if task.context.errors
                    else None
                ),
                execution_time=(
                    int(task.context.get_execution_time() * 1000)
                    if task.context.get_execution_time()
                    else None
                ),
                correlation_id=task.context.correlation_id,
                completed_at=datetime.utcnow(),
            )

            await client.websocket.send_json(result_message.model_dump(mode="json"))

        except Exception as e:
            self.logger.error(
                "Failed to send result to client",
                task_id=task.task_id,
                client_id=task.context.client_id,
                error=str(e),
            )

    async def _process_next_task(self):
        """Обробка наступного завдання з черги"""
        try:
            if not self.client_manager:
                return

            # Пошук завдання в порядку пріоритету
            for priority in [
                TaskPriority.CRITICAL,
                TaskPriority.HIGH,
                TaskPriority.NORMAL,
                TaskPriority.LOW,
            ]:
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

    async def cancel_task(
        self, task_id: str, reason: str = "Cancelled by user"
    ) -> bool:
        """Скасування завдання"""
        try:
            if task_id not in self.active_tasks:
                # Спроба знайти в чергах
                for queue in self.task_queues.values():
                    task = queue.remove_task(task_id)
                    if task:
                        task.cancel(reason)
                        self._add_to_history(task)
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
                            MessageType.TASK_CANCEL, task_id=task_id, reason=reason
                        )
                        await worker.websocket.send_json(
                            cancel_message.model_dump(mode="json")
                        )

                # Видалення з завдань воркера
                self.worker_tasks[task.context.worker_id].discard(task_id)

            # Скасування завдання
            task.cancel(reason)

            # Відправка результату клієнту
            await self._send_result_to_client(task)

            # Переміщення з активних завдань в історію
            del self.active_tasks[task_id]
            self._add_to_history(task)

            self.total_cancelled += 1

            self.logger.info("Task cancelled", task_id=task_id, reason=reason)

            return True

        except Exception as e:
            self.logger.error("Failed to cancel task", task_id=task_id, error=str(e))
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

                    # Видалення з активних завдань
                    del self.active_tasks[task_id]

                    # Повернення завдання в чергу
                    queue = self.task_queues[task.priority]
                    if not queue.is_full():
                        task.context.worker_id = None
                        task.context.assigned_at = None
                        task.context.add_status_change(
                            TaskStatus.PENDING, f"Reassigned from worker {worker_id}"
                        )

                        queue.add_task(task)

                        # Спроба призначити іншому воркеру
                        await self._try_assign_task(task)
                    else:
                        # Якщо черга переповнена, скасовуємо завдання
                        await self.cancel_task(
                            task_id,
                            f"Worker {worker_id} disconnected and queue is full",
                        )

            self.logger.info(
                "Worker tasks reassigned", worker_id=worker_id, task_count=len(task_ids)
            )

        except Exception as e:
            self.logger.error(
                "Failed to reassign worker tasks", worker_id=worker_id, error=str(e)
            )

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
                    if (
                        task.context.started_at
                        and (now - task.context.started_at).total_seconds()
                        > task.timeout
                    ):
                        timeout_tasks.append(task_id)

                for task_id in timeout_tasks:
                    task = self.active_tasks.get(task_id)
                    if task:
                        await self.handle_task_result(
                            task_id=task_id,
                            worker_id=task.context.worker_id or "unknown",
                            status=TaskStatus.TIMEOUT,
                            error_message="Task execution timeout",
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
                        self.logger.info(
                            "Cleared expired tasks",
                            queue=queue.name,
                            count=expired_count,
                        )

                await asyncio.sleep(300)  # Очищення кожні 5 хвилин

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in cleanup loop", error=str(e))
                await asyncio.sleep(60)

    async def _invalidate_stats_cache(self):
        """Очищення кешу статистики при зміні тасків"""
        if not self.redis_client or self.redis_error_handler.should_skip_redis():
            return

        async def _clear_cache():
            # Очищаємо всі ключі статистики
            pattern = "task_stats:*"
            keys = []
            async for key in self.redis_client.scan_iter(match=pattern):
                keys.append(key)

            if keys:
                await self.redis_client.delete(*keys)
                return len(keys)
            return 0

        keys_count = await self.redis_error_handler.execute_with_retry(_clear_cache)
        if keys_count is not None:
            self.logger.debug("Stats cache invalidated", keys_count=keys_count)
        else:
            self.logger.warning("Failed to invalidate stats cache after retries")

    def _add_to_history(self, task: Task):
        """Додавання завершеного завдання до історії"""
        self.task_history[task.task_id] = task

        # Обмеження розміру історії
        if len(self.task_history) > self.max_history_size:
            # Видаляємо найстаріші tasks (за created_at)
            sorted_tasks = sorted(
                self.task_history.items(), key=lambda x: x[1].context.created_at
            )
            # Видаляємо 10% найстаріших tasks
            to_remove = int(self.max_history_size * 0.1)
            for i in range(to_remove):
                task_id, _ = sorted_tasks[i]
                del self.task_history[task_id]

            self.logger.debug(
                "Task history cleaned up",
                removed_count=to_remove,
                current_size=len(self.task_history),
            )

    def set_client_manager(self, client_manager):
        """Встановлення посилання на ClientManager"""
        self.logger.info(
            "[TASK_ROUTER] Setting client_manager",
            client_manager_exists=client_manager is not None,
            client_manager_type=(
                type(client_manager).__name__ if client_manager else None
            ),
        )
        self.client_manager = client_manager
        self.logger.info(
            "[TASK_ROUTER] Client manager set successfully",
            has_client_manager=self.client_manager is not None,
        )

    async def get_queue_stats(
        self,
        sort: str = "created_at",
        order: str = "desc",
        status: Optional[str] = None,
        priority: Optional[str] = None,
        task_type: Optional[str] = None,
        search: Optional[str] = None,
        worker: Optional[str] = None,
        include_tasks: bool = True,
        use_cache: bool = True,
    ) -> Dict[str, Any]:
        """Отримання статистики черг завдань з підтримкою фільтрації та сортування"""
        try:
            # Генеруємо ключ кешу на основі параметрів
            cache_key = None
            if (
                use_cache
                and self.redis_client
                and not self.redis_error_handler.should_skip_redis()
            ):
                cache_params = {
                    "sort": sort,
                    "order": order,
                    "status": status,
                    "priority": priority,
                    "task_type": task_type,
                    "search": search,
                    "worker": worker,
                    "include_tasks": include_tasks,
                }
                cache_key = f"task_stats:{hash(str(sorted(cache_params.items())))}"

                # Спробуємо отримати з кешу з retry логікою
                async def _get_cached():
                    cached_data = await self.redis_client.get(cache_key)
                    if cached_data:
                        return orjson.loads(cached_data)
                    return None

                cached_result = await self.redis_error_handler.execute_with_retry(
                    _get_cached
                )
                if cached_result:
                    self.logger.debug(
                        "Queue stats retrieved from cache", cache_key=cache_key
                    )
                    return cached_result
            # Підрахунок завдань в чергах
            queue_sizes = {}
            pending_count = 0

            for priority in TaskPriority:
                queue = self.task_queues.get(priority)
                if queue:
                    size = len(queue.tasks)
                    queue_sizes[priority.value] = size
                    pending_count += size
                else:
                    queue_sizes[priority.value] = 0

            # Підрахунок активних завдань
            processing_count = 0
            for task in self.active_tasks.values():
                if task.context.current_status == TaskStatus.PROCESSING:
                    processing_count += 1

            # Розподіл по воркерах
            worker_distribution = {}
            for worker_id, task_ids in self.worker_tasks.items():
                if task_ids:
                    worker_distribution[worker_id] = len(task_ids)

            # Розрахунок середнього часу обробки
            avg_processing_time = 0
            completed_tasks = [
                task
                for task in self.active_tasks.values()
                if task.context.current_status == TaskStatus.COMPLETED
            ]

            if completed_tasks:
                total_time = sum(
                    task.context.get_execution_time() or 0 for task in completed_tasks
                )
                avg_processing_time = (
                    total_time / len(completed_tasks) if completed_tasks else 0
                )

            # Додаємо список всіх тасків для фронтенду (якщо потрібно)
            all_tasks = []

            if include_tasks:
                # Додаємо активні таски
                active_tasks_count = len(self.active_tasks)
                for task in self.active_tasks.values():
                    all_tasks.append(task.to_dict())

                # Додаємо таски з черг
                queue_tasks_count = 0
                for priority_level in TaskPriority:
                    queue = self.task_queues.get(priority_level)
                    if queue:
                        queue_tasks_count += len(queue.tasks)
                        for task in queue.tasks.values():
                            task_dict = task.to_dict()
                            all_tasks.append(task_dict)
                            # Додаткове логування для діагностики
                            self.logger.info(
                                "[TASK_DEBUG] Adding task from queue to list",
                                task_id=task.task_id,
                                task_type=task.task_type.value,
                                priority=task.priority.value,
                                status=task.context.current_status.value,
                                task_dict_keys=list(task_dict.keys()),
                            )

                # Додаємо таски з історії (completed/failed/cancelled)
                history_tasks_count = len(self.task_history)
                for task in self.task_history.values():
                    all_tasks.append(task.to_dict())

                # Логування для діагностики
                self.logger.info(
                    "[QUEUE_STATS] Task collection summary",
                    active_tasks_count=active_tasks_count,
                    queue_tasks_count=queue_tasks_count,
                    history_tasks_count=history_tasks_count,
                    total_collected=len(all_tasks),
                    pending_count=pending_count,
                    processing_count=processing_count,
                )

                # Додаткове логування списку всіх зібраних завдань
                self.logger.info(
                    "[TASK_DEBUG] All collected tasks summary",
                    total_tasks_in_list=len(all_tasks),
                    task_ids=[t.get("task_id", "NO_ID") for t in all_tasks],
                    task_statuses=[t.get("status", "NO_STATUS") for t in all_tasks],
                )

                # Застосовуємо фільтри
                # ТИМЧАСОВО ВІДКЛЮЧЕНО ДЛЯ ДІАГНОСТИКИ
                if False and status and status != "all":
                    before_filter = len(all_tasks)
                    all_tasks = [t for t in all_tasks if t.get("status") == status]
                    self.logger.info(
                        "[FILTER_DEBUG] Status filter applied",
                        filter_status=status,
                        before_count=before_filter,
                        after_count=len(all_tasks),
                    )

                if False and priority and priority != "all":
                    before_filter = len(all_tasks)
                    all_tasks = [t for t in all_tasks if t.get("priority") == priority]
                    self.logger.info(
                        "[FILTER_DEBUG] Priority filter applied",
                        filter_priority=priority,
                        before_count=before_filter,
                        after_count=len(all_tasks),
                    )

                if False and task_type and task_type != "all":
                    all_tasks = [
                        t for t in all_tasks if t.get("task_type") == task_type
                    ]

                if False and worker and worker != "all":
                    all_tasks = [t for t in all_tasks if t.get("worker_id") == worker]

                # Застосовуємо пошук
                if False and search:
                    search_lower = search.lower()
                    all_tasks = [
                        t
                        for t in all_tasks
                        if search_lower in t.get("task_id", "").lower()
                        or search_lower in t.get("task_type", "").lower()
                    ]

                # Застосовуємо сортування
                if sort in [
                    "created_at",
                    "priority",
                    "status",
                    "task_type",
                    "started_at",
                    "completed_at",
                ]:
                    reverse_order = order.lower() == "desc"

                    if sort == "priority":
                        # Сортування за пріоритетом: critical > high > normal > low
                        priority_order = {
                            "critical": 4,
                            "high": 3,
                            "normal": 2,
                            "low": 1,
                        }
                        all_tasks.sort(
                            key=lambda t: priority_order.get(
                                t.get("priority", "normal"), 2
                            ),
                            reverse=reverse_order,
                        )
                    elif sort in ["created_at", "started_at", "completed_at"]:
                        # Сортування за датою з правильним парсингом
                        from datetime import datetime

                        def parse_date(date_str):
                            if not date_str:
                                return datetime.min
                            try:
                                return datetime.fromisoformat(
                                    date_str.replace("Z", "+00:00")
                                )
                            except (ValueError, AttributeError):
                                return datetime.min

                        all_tasks.sort(
                            key=lambda t: parse_date(t.get(sort)), reverse=reverse_order
                        )
                    else:
                        # Сортування за строковими полями
                        all_tasks.sort(
                            key=lambda t: t.get(sort, ""), reverse=reverse_order
                        )

            result = {
                "total_tasks": self.total_submitted,
                "pending_tasks": pending_count,
                "processing_tasks": processing_count,
                "completed_tasks": self.total_completed,
                "failed_tasks": self.total_failed,
                "average_processing_time": avg_processing_time,
                "queue_sizes": queue_sizes,
                "worker_distribution": worker_distribution,
                "active_tasks": len(self.active_tasks),
                "workers_count": len(
                    [w for w in self.worker_tasks if self.worker_tasks[w]]
                ),
                "tasks": all_tasks,
            }

            # Зберігаємо в кеш (на 60 секунд для статистики з тасками, 30 секунд для статистики без тасків)
            if (
                cache_key
                and self.redis_client
                and not self.redis_error_handler.should_skip_redis()
            ):

                async def _save_to_cache():
                    cache_ttl = 30 if not include_tasks else 60
                    # Конвертуємо всі множини в списки для JSON серіалізації
                    serializable_result = self._convert_sets_to_lists(result)
                    await self.redis_client.set(
                        cache_key, orjson.dumps(serializable_result), ex=cache_ttl
                    )
                    return cache_ttl

                ttl = await self.redis_error_handler.execute_with_retry(_save_to_cache)
                if ttl:
                    self.logger.debug(
                        "Queue stats cached", cache_key=cache_key, ttl=ttl
                    )
                else:
                    self.logger.warning("Failed to cache queue stats after retries")

            return result
        except Exception as e:
            self.logger.error("Error getting queue stats", error=str(e))
            return {"error": str(e)}

    def _convert_sets_to_lists(self, obj):
        """Рекурсивно конвертує всі множини (set) в списки для JSON серіалізації"""
        if isinstance(obj, set):
            return list(obj)
        elif isinstance(obj, dict):
            return {
                key: self._convert_sets_to_lists(value) for key, value in obj.items()
            }
        elif isinstance(obj, (list, tuple)):
            return [self._convert_sets_to_lists(item) for item in obj]
        else:
            return obj

    def _add_to_history(self, task: Task):
        """Додавання завдання до історії"""
        # Обмежуємо розмір історії
        if len(self.task_history) >= 1000:
            # Видаляємо найстарші 100 завдань
            oldest_tasks = sorted(
                self.task_history.keys(),
                key=lambda tid: self.task_history[tid].context.created_at,
            )[:100]
            for tid in oldest_tasks:
                del self.task_history[tid]

        self.task_history[task.task_id] = task
