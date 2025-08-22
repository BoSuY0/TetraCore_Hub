"""
TetraCore StreamHub Task Router

Маршрутизатор завдань для StreamHub.
Відповідає за розподіл завдань між воркерами, балансування навантаження,
обробку результатів та управління чергами завдань.
"""

import asyncio
from datetime import datetime
from typing import Dict, Optional, Set, Callable, Any
from collections import defaultdict, deque
import structlog
import orjson
import os

from config import Settings
from models.task import Task, TaskStatus, TaskPriority, TaskQueue
from models.client import Client
from models.messages import MessageType, create_message


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

        # Завдання, призначені виконавцям (executor_id -> set of task_ids)
        self.executor_tasks: Dict[str, Set[str]] = defaultdict(set)

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

        # Overflow черги в пам'яті (на випадок тимчасового піку)
        self.overflow_queues: Dict[TaskPriority, deque] = {
            TaskPriority.CRITICAL: deque(),
            TaskPriority.HIGH: deque(),
            TaskPriority.NORMAL: deque(),
            TaskPriority.LOW: deque(),
        }
        # Ключі Redis overflow (персистентний буфер)
        self.redis_overflow_keys: Dict[TaskPriority, str] = {
            TaskPriority.CRITICAL: "overflow:critical",
            TaskPriority.HIGH: "overflow:high",
            TaskPriority.NORMAL: "overflow:normal",
            TaskPriority.LOW: "overflow:low",
        }

        # Streams overflow (опціонально через ENV)
        self.use_streams_overflow: bool = os.getenv(
            "REDIS_STREAMS_OVERFLOW", "false"
        ).lower() in ("1", "true", "yes")
        self.stream_overflow_keys: Dict[TaskPriority, str] = {
            TaskPriority.CRITICAL: "stream:overflow:critical",
            TaskPriority.HIGH: "stream:overflow:high",
            TaskPriority.NORMAL: "stream:overflow:normal",
            TaskPriority.LOW: "stream:overflow:low",
        }
        self.stream_overflow_maxlen: int = int(
            os.getenv("REDIS_STREAMS_OVERFLOW_MAXLEN", "50000")
        )

        # Стан маршрутизатора
        self.is_running = False
        self.timeout_task: Optional[asyncio.Task] = None
        self.cleanup_task: Optional[asyncio.Task] = None
        self.overflow_task: Optional[asyncio.Task] = None

        # Посилання на ClientManager (буде встановлено ззовні)
        self.client_manager = None

        # Ініціалізація Redis клієнта
        self.redis_manager = redis_manager
        if self.redis_manager and hasattr(self.redis_manager, "redis_client"):
            self.redis_client = self.redis_manager.redis_client
        elif settings.redis_enabled:
            # Redis увімкнений за замовчуванням; якщо менеджер не передано — залишаємо None, але не логуємо зайвого
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

            # Запуск фонових завдань з урахуванням тест-середовища
            import os

            disable_bg = bool(os.getenv("PYTEST_CURRENT_TEST")) or os.getenv(
                "DISABLE_BACKGROUND_TASKS", ""
            ).lower() in ("1", "true", "yes")
            if disable_bg:
                self.timeout_task = None
                self.cleanup_task = None
                self.logger.debug("TaskRouter background loops disabled (test env)")
            else:
                # Запускаємо фонового монітора таймаутів та очистки
                self.timeout_task = asyncio.create_task(self._timeout_monitor())
                self.cleanup_task = asyncio.create_task(self._cleanup_loop())
                self.overflow_task = asyncio.create_task(self._overflow_drain_loop())

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
        for task in [self.timeout_task, self.cleanup_task, self.overflow_task]:
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
        # Критична перевірка наявності ClientManager (не покладатися на __bool__)
        if self.client_manager is None:
            self.logger.error(
                "[TASK_ROUTER] ClientManager not initialized! Cannot submit tasks.",
                task_id=task.task_id,
            )
            # Для сумісності з тестом — піднімаємо виняток
            raise ValueError(
                "ClientManager is not set. Call set_client_manager() first."
            )
        try:

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

            # Ідемпотентність (опціонально через metadata.idempotency_key)
            try:
                idem = getattr(task, "metadata", None)
                idem_key = getattr(idem, "idempotency_key", None) if idem else None
                if idem_key and self.redis_client:
                    # Спроба поставити маркер з коротким TTL (наприклад 10 хв)
                    mark_key = f"idem:{idem_key}"
                    set_ok = await self.redis_client.set(
                        mark_key, task.task_id, ex=600, nx=True
                    )
                    if not set_ok:
                        # Дубль — не додаємо в чергу, вважаємо успіх (ідемпотентність)
                        self.logger.info(
                            "Idempotent task duplicate skipped",
                            idempotency_key=idem_key,
                            task_id=task.task_id,
                        )
                        return True
            except Exception as e:
                self.logger.debug(
                    "Idempotency check failed, continuing without it", error=str(e)
                )

            # Перевірка чи черга не переповнена
            queue = self.task_queues[task.priority]
            if queue.is_full():
                # Не відхиляємо таск, ставимо в overflow (Redis -> in-memory fallback)
                stored = task.to_storage()
                persisted = False
                try:
                    if self.redis_client:
                        if self.use_streams_overflow:
                            skey = self.stream_overflow_keys[task.priority]
                            # Streams із MAXLEN ~ для обмеження пам'яті
                            await self.redis_client.xadd(
                                skey,
                                fields={"task": orjson.dumps(stored)},
                                maxlen=self.stream_overflow_maxlen,
                                approximate=True,
                            )
                            persisted = True
                        else:
                            key = self.redis_overflow_keys[task.priority]
                            # LPUSH у Redis для черги (ліва вставка — як стек FIFO з RPOP)
                            await self.redis_client.lpush(key, orjson.dumps(stored))
                            persisted = True
                except Exception as e:
                    self.logger.warning(
                        "Failed to persist overflow to Redis, using in-memory",
                        error=str(e),
                    )
                if not persisted:
                    self.overflow_queues[task.priority].append(task)
                self.total_submitted += 1
                task.context.add_status_change(
                    TaskStatus.PENDING, "Queued in overflow (main queue full)"
                )
                self.logger.info(
                    "Task queued into overflow",
                    task_id=task.task_id,
                    priority=task.priority.value,
                    overflow_size=len(self.overflow_queues[task.priority]),
                )
                # Тригеримо негайне зливання overflow якщо є можливість
                await self._drain_overflow_for_priority(task.priority, max_per_cycle=1)
                return True

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
            if self.client_manager is None:
                self.logger.warning(
                    "[TASK_ROUTER] No client manager available", task_id=task.task_id
                )
                return False

            # Якщо таск вже призначено/в процесі, не повторюємо відправку
            if task.task_id in self.active_tasks or task.context.current_status in (
                TaskStatus.ASSIGNED,
                TaskStatus.PROCESSING,
            ):
                self.logger.debug(
                    "[TASK_ROUTER] Task already assigned or processing, skipping re-send",
                    task_id=task.task_id,
                    status=task.context.current_status.value,
                    worker_id=task.context.worker_id,
                )
                return True

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

            # Пошук найкращого виконавця
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
            assigned = await self._assign_task_to_worker(task, worker)
            return assigned

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
                        # Додаємо поле 'type' для сумісності з тестами/протоколом
                        payload = assignment_message.model_dump(mode="json")
                        if "type" not in payload:
                            payload["type"] = payload.get(
                                "message_type", MessageType.TASK_ASSIGN.value
                            )
                        await asyncio.wait_for(
                            worker.websocket.send_json(payload), timeout=5.0
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
            self.executor_tasks[worker_id].add(task.task_id)

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
                except Exception:
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
                task.mark_timeout()
                self.total_timeout += 1

            # Оновлення статистики воркера
            if self.client_manager:
                worker = self.client_manager.get_client(worker_id)
                if worker:
                    worker.complete_task(task_id, status, execution_time)

            # Видалення з активних завдань воркера
            self.executor_tasks[worker_id].discard(task_id)

            # Результати тепер відправляються тільки через WebSocket, не зберігаємо в Redis
            self.logger.info(
                "[WS_RESULT] Task result will be sent to client via WebSocket only",
                task_id=task_id,
                status=status.value,
                client_id=task.context.client_id,
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
            self.logger.info(
                "[WS_RESULT_SEND] Attempting to send result to client",
                task_id=task.task_id,
                client_id=task.context.client_id,
                has_client_manager=self.client_manager is not None,
            )

            if not task.context.client_id:
                self.logger.warning(
                    f"[WS_RESULT_SEND] No client_id for task {task.task_id}"
                )
                return

            if not self.client_manager:
                self.logger.warning("[WS_RESULT_SEND] No client_manager available")
                return

            client = self.client_manager.get_client(task.context.client_id)
            self.logger.info(
                "[WS_RESULT_SEND] Client lookup result",
                task_id=task.task_id,
                client_id=task.context.client_id,
                client_found=client is not None,
                has_websocket=client.websocket is not None if client else False,
            )

            if not client or not client.websocket:
                self.logger.warning(
                    "[WS_RESULT_SEND] Client not found or no websocket",
                    task_id=task.task_id,
                    client_id=task.context.client_id,
                )
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

            self.logger.info(
                "[WS_RESULT_SEND] Sending result message to client",
                task_id=task.task_id,
                client_id=task.context.client_id,
                message_type=result_message.message_type,
                has_result=task.context.result is not None,
            )

            await client.websocket.send_json(result_message.model_dump(mode="json"))

            self.logger.info(
                "[WS_RESULT_SEND] ✅ Result successfully sent to client",
                task_id=task.task_id,
                client_id=task.context.client_id,
            )

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
            # Пошук наступного завдання в черзі за пріоритетом
            for priority in [
                TaskPriority.CRITICAL,
                TaskPriority.HIGH,
                TaskPriority.NORMAL,
                TaskPriority.LOW,
            ]:
                queue = self.task_queues[priority]
                if queue.tasks:
                    # Беремо перше завдання
                    task_id = next(iter(queue.tasks))
                    task = queue.tasks[task_id]

                    # Спроба призначити завдання
                    if await self._try_assign_task(task):
                        # Завдання успішно призначено
                        break

        except Exception as e:
            self.logger.error("Error processing next task", error=str(e))

    async def _handle_task_update(
        self,
        task_id: str,
        status: TaskStatus,
        worker_id: str = None,
        error_message: str = None,
    ):
        """Оновлення стану таску (використовується у тестах)"""
        try:
            if task_id not in self.active_tasks:
                return False
            task = self.active_tasks[task_id]
            if status == TaskStatus.TIMEOUT:
                # Узгоджено з моделлю: позначаємо таймаут явно
                task.mark_timeout()
                self.total_timeout += 1
            elif status == TaskStatus.FAILED:
                task.fail(error_message or "Task failed")
                self.total_failed += 1
            elif status == TaskStatus.COMPLETED:
                task.complete({})
                self.total_completed += 1

            # Оновлюємо статистику воркера
            if worker_id and self.client_manager:
                worker = self.client_manager.get_client(worker_id)
                if worker:
                    worker.complete_task(task_id, status, None)

            # Прибираємо з мап та відправляємо результат
            _key = worker_id or task.context.worker_id
            if _key and _key in self.executor_tasks:
                self.executor_tasks[_key].discard(task_id)
            await self._send_result_to_client(task)
            del self.active_tasks[task_id]
            self._add_to_history(task)
            await self._invalidate_stats_cache()
            return True
        except Exception as e:
            self.logger.error(
                "_handle_task_update error", task_id=task_id, error=str(e)
            )
            return False

    async def process_pending_tasks_for_client(self, client: "Client") -> int:
        """
        Обробка pending tasks для нового клієнта

        Args:
            client: Новий клієнт, що з'єднався з хабом

        Returns:
            Кількість призначених завдань
        """
        try:
            assigned_count = 0
            client_id = client.info.client_id
            client_type = client.info.client_type.value

            self.logger.info(
                "Processing pending tasks for new client",
                client_id=client_id,
                client_type=client_type,
            )

            # Перевіряємо чи клієнт може виконувати завдання
            if client_type not in ["bot", "worker", "worker_api"]:
                self.logger.debug(
                    "Client type cannot execute tasks",
                    client_id=client_id,
                    client_type=client_type,
                )
                return 0

            # Проходимо по чергах за пріоритетом
            for priority in [
                TaskPriority.CRITICAL,
                TaskPriority.HIGH,
                TaskPriority.NORMAL,
                TaskPriority.LOW,
            ]:
                queue = self.task_queues[priority]

                if not queue.tasks:
                    continue

                # Копіюємо список task_id для безпечної ітерації
                task_ids = list(queue.tasks.keys())

                for task_id in task_ids:
                    task = queue.tasks.get(task_id)
                    if not task:
                        continue

                    # Перевіряємо чи цей клієнт може виконати завдання
                    if self._can_client_execute_task(client, task):
                        # Спробуємо призначити завдання
                        if await self._assign_task_to_worker(task, client):
                            assigned_count += 1
                            self.logger.info(
                                "Assigned pending task to new client",
                                task_id=task_id,
                                client_id=client_id,
                                priority=priority.value,
                            )

                            # Обмежуємо кількість одночасно призначених завдань
                            if assigned_count >= 5:  # Максимум 5 завдань за раз
                                break

                # Якщо досягли ліміту, зупиняємося
                if assigned_count >= 5:
                    break

            self.logger.info(
                "Completed processing pending tasks for new client",
                client_id=client_id,
                assigned_count=assigned_count,
            )

            return assigned_count

        except Exception as e:
            self.logger.error(
                "Error processing pending tasks for new client",
                client_id=client.info.client_id if client else "unknown",
                error=str(e),
            )
            return 0

    def _can_client_execute_task(self, client: "Client", task: Task) -> bool:
        """
        Перевіряє чи може клієнт виконати конкретне завдання

        Args:
            client: Клієнт для перевірки
            task: Завдання для перевірки

        Returns:
            True якщо клієнт може виконати завдання
        """
        try:
            # Перевірка типу клієнта
            client_type = client.info.client_type.value
            task_executor_type = (
                task.executor_type.value if hasattr(task, "executor_type") else "worker"
            )

            if client_type != task_executor_type:
                return False

            # Перевірка можливостей клієнта
            if hasattr(client.info, "capabilities") and client.info.capabilities:
                # Перевірка підтримуваних типів завдань
                if hasattr(client.info.capabilities, "supported_task_types"):
                    supported_types = client.info.capabilities.supported_task_types
                    if supported_types and task.task_type.value not in supported_types:
                        return False

                # Перевірка максимальної кількості одночасних завдань
                if hasattr(client.info.capabilities, "max_concurrent_tasks"):
                    max_tasks = client.info.capabilities.max_concurrent_tasks
                    current_tasks = (
                        client.info.stats.active_tasks
                        if hasattr(client.info, "stats")
                        else 0
                    )
                    if max_tasks and current_tasks >= max_tasks:
                        return False

            # Перевірка вимог до воркера
            if task.worker_requirements:
                # Тут можна додати додаткові перевірки вимог
                pass

            return True

        except Exception as e:
            self.logger.error(
                "Error checking if client can execute task",
                client_id=client.info.client_id if client else "unknown",
                task_id=task.task_id,
                error=str(e),
            )
            return False

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
                self.executor_tasks[task.context.worker_id].discard(task_id)

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

    async def reassign_executor_tasks(self, executor_id: str):
        """Переназначення завдань від відключеного виконавця"""
        try:
            if executor_id not in self.executor_tasks:
                return

            task_ids = list(self.executor_tasks[executor_id])
            self.executor_tasks[executor_id].clear()

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
                            TaskStatus.PENDING,
                            f"Reassigned from executor {executor_id}",
                        )

                        queue.add_task(task)

                        # Спроба призначити іншому воркеру
                        await self._try_assign_task(task)
                    else:
                        # Якщо черга переповнена, скасовуємо завдання
                        await self.cancel_task(
                            task_id,
                            f"Executor {executor_id} disconnected and queue is full",
                        )

            self.logger.info(
                "Executor tasks reassigned",
                executor_id=executor_id,
                task_count=len(task_ids),
            )

        except Exception as e:
            self.logger.error(
                "Failed to reassign executor tasks",
                executor_id=executor_id,
                error=str(e),
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

    async def _overflow_drain_loop(self):
        """Фоновий цикл, що переносить задачі з overflow у основні черги при наявності місця."""
        while self.is_running:
            try:
                # Порядок пріоритетів при зливанні
                for priority in [
                    TaskPriority.CRITICAL,
                    TaskPriority.HIGH,
                    TaskPriority.NORMAL,
                    TaskPriority.LOW,
                ]:
                    await self._drain_overflow_for_priority(priority, max_per_cycle=50)
                await asyncio.sleep(0.2)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in overflow drain loop", error=str(e))
                await asyncio.sleep(1.0)

    async def _drain_overflow_for_priority(
        self, priority: TaskPriority, max_per_cycle: int = 50
    ) -> int:
        """Переносить до max_per_cycle задач з overflow[priority] у основну чергу, якщо є місце."""
        moved = 0
        queue = self.task_queues[priority]
        overflow = self.overflow_queues[priority]
        # Спочатку пробуємо дістати з Redis overflow
        while moved < max_per_cycle and not queue.is_full():
            # 1) Redis джерело
            task = None
            if self.redis_client:
                try:
                    if self.use_streams_overflow:
                        skey = self.stream_overflow_keys[priority]
                        # Зчитуємо одну подію зі стріму (XREAD блокуючий з малим timeout)
                        items = await self.redis_client.xread(
                            {skey: "0-0"}, count=1, block=10
                        )
                        if items:
                            # items: [(stream, [(id, {field: value})])]
                            _, entries = items[0]
                            eid, fields = entries[0]
                            raw = fields.get("task")
                            if raw:
                                data = orjson.loads(raw)
                                task = Task.from_storage(data)
                            # Видаляємо запис, щоб не читати його повторно
                            try:
                                await self.redis_client.xdel(skey, eid)
                            except Exception:
                                pass
                    else:
                        key = self.redis_overflow_keys[priority]
                        raw = await self.redis_client.rpop(key)  # RPOP для FIFO
                        if raw:
                            data = orjson.loads(raw)
                            task = Task.from_storage(data)
                except Exception as e:
                    self.logger.warning("Failed to drain Redis overflow", error=str(e))
            # 2) In-memory fallback
            if task is None and overflow:
                task = overflow.popleft()

            if task is None:
                break  # Немає елементів у джерелах

            if queue.add_task(task):
                moved += 1
                self.logger.debug(
                    "Moved task from overflow to main queue",
                    task_id=task.task_id,
                    priority=priority.value,
                )
            else:
                # Якщо раптом не вдалося — повертаємо у початок та виходимо
                overflow.appendleft(task)
                break
        return moved

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
        include_tasks: bool = False,
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

            # Розподіл по виконавцях
            executor_distribution = {}
            for executor_id, task_ids in self.executor_tasks.items():
                if task_ids:
                    executor_distribution[executor_id] = len(task_ids)

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
                    td = task.to_dict()
                    # Маскуємо/обрізаємо task_data
                    if "task_data" in td and isinstance(td["task_data"], dict):
                        td["task_data_preview"] = list(td["task_data"].keys())[:10]
                        td["task_data"] = "<hidden>"
                    all_tasks.append(td)

                # Додаємо таски з черг
                queue_tasks_count = 0
                for priority_level in TaskPriority:
                    queue = self.task_queues.get(priority_level)
                    if queue:
                        queue_tasks_count += len(queue.tasks)
                        for task in queue.tasks.values():
                            task_dict = task.to_dict()
                            if "task_data" in task_dict and isinstance(
                                task_dict["task_data"], dict
                            ):
                                task_dict["task_data_preview"] = list(
                                    task_dict["task_data"].keys()
                                )[:10]
                                task_dict["task_data"] = "<hidden>"
                            all_tasks.append(task_dict)
                            # Мінімізоване логування без переліку всіх ключів у проді
                            if (
                                os.getenv("ENVIRONMENT", "development").lower()
                                != "production"
                            ):
                                self.logger.info(
                                    "[TASK_DEBUG] Added task to list",
                                    task_id=task.task_id,
                                    task_type=task.task_type.value,
                                    priority=task.priority.value,
                                    status=task.context.current_status.value,
                                )

                # Додаємо таски з історії (completed/failed/cancelled)
                history_tasks_count = len(self.task_history)
                for task in self.task_history.values():
                    td = task.to_dict()
                    if "task_data" in td and isinstance(td["task_data"], dict):
                        td["task_data_preview"] = list(td["task_data"].keys())[:10]
                        td["task_data"] = "<hidden>"
                    all_tasks.append(td)

                # Логування для діагностики
                if os.getenv("ENVIRONMENT", "development").lower() != "production":
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
                if os.getenv("ENVIRONMENT", "development").lower() != "production":
                    self.logger.info(
                        "[TASK_DEBUG] All collected tasks summary",
                        total_tasks_in_list=len(all_tasks),
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
                "executor_distribution": executor_distribution,
                "active_tasks": len(self.active_tasks),
                "executors_count": len(
                    [e for e in self.executor_tasks if self.executor_tasks[e]]
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
