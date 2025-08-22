"""
TetraCore StreamHub Async Optimization Module

Модуль для покращення асинхронної продуктивності StreamHub.
Надає інструменти для заміни блокуючих операцій на асинхронні,
управління фоновими задачами та оптимізації використання asyncio.
"""

import asyncio
import os
import json
import aiofiles
import time
import functools
from typing import Dict, List, Any, Optional, Callable, TypeVar, Coroutine, Tuple
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
import structlog
from collections import deque
import hashlib

# Type definitions
T = TypeVar('T')
AsyncFunc = Callable[..., Coroutine[Any, Any, T]]


class TaskPriority(Enum):
    """Пріоритети задач"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class BackgroundTask:
    """Модель фонової задачі"""
    id: str
    name: str
    func: Callable
    args: tuple
    kwargs: dict
    priority: TaskPriority = TaskPriority.NORMAL
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    result: Any = None
    error: Optional[Exception] = None
    retries: int = 0
    max_retries: int = 3


class AsyncOptimizer:
    """Головний клас для асинхронних оптимізацій"""

    def __init__(self, max_workers: int = 10, max_tasks: int = 1000):
        self.logger = structlog.get_logger(__name__)
        self.max_workers = max_workers
        self.max_tasks = max_tasks
        # Відключення фон-петель у тест-середовищі або за прапором
        self.disable_background_tasks = bool(os.getenv("PYTEST_CURRENT_TEST")) or os.getenv("DISABLE_BACKGROUND_TASKS", "").lower() in ("1", "true", "yes")

        # Пули для виконання задач
        self.thread_pool = ThreadPoolExecutor(max_workers=max_workers)
        self.process_pool = ProcessPoolExecutor(max_workers=max_workers // 2)

        # Черги задач за пріоритетами
        self.task_queues: Dict[TaskPriority, deque] = {
            priority: deque() for priority in TaskPriority
        }

        # Активні задачі
        self.active_tasks: Dict[str, asyncio.Task] = {}
        self.completed_tasks: Dict[str, BackgroundTask] = {}

        # Семафор для обмеження конкурентних задач
        self.task_semaphore = asyncio.Semaphore(max_workers)

        # Кеш результатів
        self.result_cache: Dict[str, Any] = {}
        self.cache_ttl = 300  # 5 хвилин

        # Статистика
        self.stats = {
            "tasks_created": 0,
            "tasks_completed": 0,
            "tasks_failed": 0,
            "cache_hits": 0,
            "cache_misses": 0
        }

    async def initialize(self):
        """Ініціалізація оптимізатора"""
        self.logger.info("Initializing AsyncOptimizer",
                        max_workers=self.max_workers,
                        max_tasks=self.max_tasks)

        if self.disable_background_tasks:
            self.logger.debug("AsyncOptimizer background tasks disabled (test env)")
            self.worker_task = None
            self.cache_cleanup_task = None
        else:
            # Запуск обробника задач
            self.worker_task = asyncio.create_task(self._worker_loop())
            # Запуск очищення кешу
            self.cache_cleanup_task = asyncio.create_task(self._cache_cleanup_loop())

    async def shutdown(self):
        """Завершення роботи оптимізатора"""
        self.logger.info("Shutting down AsyncOptimizer")

        # Зупинка воркерів
        if hasattr(self, 'worker_task'):
            self.worker_task.cancel()
            try:
                await self.worker_task
            except asyncio.CancelledError:
                pass

        if hasattr(self, 'cache_cleanup_task'):
            self.cache_cleanup_task.cancel()
            try:
                await self.cache_cleanup_task
            except asyncio.CancelledError:
                pass

        # Очікування завершення активних задач
        if self.active_tasks:
            await asyncio.gather(*self.active_tasks.values(), return_exceptions=True)

        # Закриття пулів
        self.thread_pool.shutdown(wait=True)
        self.process_pool.shutdown(wait=True)

    # === Асинхронні версії блокуючих операцій ===

    async def json_dumps(self, obj: Any, **kwargs) -> str:
        """Асинхронна серіалізація JSON"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.thread_pool,
            functools.partial(json.dumps, obj, **kwargs)
        )

    async def json_loads(self, s: str) -> Any:
        """Асинхронна десеріалізація JSON"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.thread_pool,
            json.loads,
            s
        )

    async def read_file(self, path: str, mode: str = 'r', encoding: str = 'utf-8') -> str:
        """Асинхронне читання файлу"""
        async with aiofiles.open(path, mode=mode, encoding=encoding) as f:
            return await f.read()

    async def write_file(self, path: str, content: str, mode: str = 'w', encoding: str = 'utf-8'):
        """Асинхронний запис у файл"""
        async with aiofiles.open(path, mode=mode, encoding=encoding) as f:
            await f.write(content)

    async def run_in_thread(self, func: Callable, *args, **kwargs) -> Any:
        """Виконання блокуючої функції в окремому потоці"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.thread_pool,
            functools.partial(func, *args, **kwargs)
        )

    async def run_in_process(self, func: Callable, *args, **kwargs) -> Any:
        """Виконання CPU-інтенсивної функції в окремому процесі"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.process_pool,
            functools.partial(func, *args, **kwargs)
        )

    # === Управління фоновими задачами ===

    async def create_background_task(self,
                                   name: str,
                                   func: Callable,
                                   *args,
                                   priority: TaskPriority = TaskPriority.NORMAL,
                                   use_cache: bool = True,
                                   **kwargs) -> str:
        """Створення фонової задачі"""
        # Генерація ID задачі
        task_id = self._generate_task_id(name, args, kwargs)

        # Перевірка кешу
        if use_cache and task_id in self.result_cache:
            self.stats["cache_hits"] += 1
            self.logger.debug("Task result found in cache", task_id=task_id)
            return task_id

        self.stats["cache_misses"] += 1

        # Якщо фон-петлі вимкнені (тести) — виконуємо відразу, без воркера
        if self.disable_background_tasks:
            try:
                if asyncio.iscoroutinefunction(func):
                    result = await func(*args, **kwargs)
                else:
                    # Виконати в thread pool, щоб не блокувати
                    result = await self.run_in_thread(func, *args, **kwargs)
                bt = BackgroundTask(
                    id=task_id,
                    name=name,
                    func=func,
                    args=args,
                    kwargs=kwargs,
                    priority=priority,
                    started_at=time.time(),
                    completed_at=time.time(),
                    result=result
                )
                self.completed_tasks[task_id] = bt
                self.result_cache[task_id] = result
                self.stats["tasks_completed"] += 1
                self.logger.debug("Background task executed inline (test mode)", task_id=task_id)
                return task_id
            except Exception as e:
                bt = BackgroundTask(
                    id=task_id,
                    name=name,
                    func=func,
                    args=args,
                    kwargs=kwargs,
                    priority=priority,
                    started_at=time.time(),
                    completed_at=time.time(),
                    error=e
                )
                self.completed_tasks[task_id] = bt
                self.stats["tasks_failed"] += 1
                self.logger.error("Inline background task failed (test mode)", task_id=task_id, error=str(e))
                return task_id

        # Інакше — звичайний шлях через чергу та воркер
        task = BackgroundTask(
            id=task_id,
            name=name,
            func=func,
            args=args,
            kwargs=kwargs,
            priority=priority
        )
        self.task_queues[priority].append(task)
        self.stats["tasks_created"] += 1
        self.logger.info("Background task created",
                        task_id=task_id,
                        name=name,
                        priority=priority.name)
        return task_id

    async def get_task_result(self, task_id: str, timeout: float = None) -> Any:
        """Отримання результату задачі"""
        # Перевірка кешу
        if task_id in self.result_cache:
            return self.result_cache[task_id]

        # Перевірка виконаних задач
        if task_id in self.completed_tasks:
            task = self.completed_tasks[task_id]
            if task.error:
                raise task.error
            return task.result

        # Очікування виконання
        if task_id in self.active_tasks:
            try:
                await asyncio.wait_for(
                    self.active_tasks[task_id],
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                raise TimeoutError(f"Task {task_id} timeout")

            # Повторна перевірка результату
            if task_id in self.completed_tasks:
                task = self.completed_tasks[task_id]
                if task.error:
                    raise task.error
                return task.result

        raise ValueError(f"Task {task_id} not found")

    async def cancel_task(self, task_id: str) -> bool:
        """Скасування задачі"""
        if task_id in self.active_tasks:
            self.active_tasks[task_id].cancel()
            del self.active_tasks[task_id]
            self.logger.info("Task cancelled", task_id=task_id)
            return True

        # Видалення з черги
        for queue in self.task_queues.values():
            for i, task in enumerate(queue):
                if task.id == task_id:
                    del queue[i]
                    self.logger.info("Task removed from queue", task_id=task_id)
                    return True

        return False

    # === Паралельне виконання ===

    async def gather_with_timeout(self,
                                *coroutines: Coroutine,
                                timeout: float = None,
                                return_exceptions: bool = True) -> List[Any]:
        """Виконання кількох корутин паралельно з таймаутом"""
        try:
            return await asyncio.wait_for(
                asyncio.gather(*coroutines, return_exceptions=return_exceptions),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            self.logger.warning("Gather operation timeout", count=len(coroutines))
            # Скасування незавершених задач
            for coro in coroutines:
                if asyncio.iscoroutine(coro):
                    coro.close()
            raise

    async def map_async(self,
                       func: AsyncFunc,
                       items: List[Any],
                       max_concurrent: int = 10) -> List[Any]:
        """Асинхронний map з обмеженням конкурентності"""
        semaphore = asyncio.Semaphore(max_concurrent)

        async def limited_func(item):
            async with semaphore:
                return await func(item)

        return await asyncio.gather(
            *[limited_func(item) for item in items],
            return_exceptions=False
        )

    async def batch_process(self,
                          func: AsyncFunc,
                          items: List[Any],
                          batch_size: int = 100) -> List[Any]:
        """Обробка елементів батчами"""
        results = []

        for i in range(0, len(items), batch_size):
            batch = items[i:i + batch_size]
            batch_results = await asyncio.gather(
                *[func(item) for item in batch],
                return_exceptions=False
            )
            results.extend(batch_results)

        return results

    # === Внутрішні методи ===

    async def _worker_loop(self):
        """Основний цикл обробки задач"""
        while True:
            try:
                # Вибір задачі з найвищим пріоритетом
                task = None
                for priority in reversed(list(TaskPriority)):
                    if self.task_queues[priority]:
                        task = self.task_queues[priority].popleft()
                        break

                if not task:
                    await asyncio.sleep(0.1)
                    continue

                # Виконання задачі
                async with self.task_semaphore:
                    await self._execute_task(task)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in worker loop", error=str(e))

    async def _execute_task(self, task: BackgroundTask):
        """Виконання окремої задачі"""
        task.started_at = time.time()

        try:
            # Створення asyncio задачі
            if asyncio.iscoroutinefunction(task.func):
                coro = task.func(*task.args, **task.kwargs)
            else:
                # Виконання синхронної функції в thread pool
                coro = self.run_in_thread(task.func, *task.args, **task.kwargs)

            async_task = asyncio.create_task(coro)
            self.active_tasks[task.id] = async_task

            # Виконання
            result = await async_task
            task.result = result
            task.completed_at = time.time()

            # Збереження в кеш
            self.result_cache[task.id] = result

            # Переміщення в виконані
            self.completed_tasks[task.id] = task
            self.stats["tasks_completed"] += 1

            self.logger.info("Task completed",
                           task_id=task.id,
                           duration=task.completed_at - task.started_at)

        except Exception as e:
            task.error = e
            task.completed_at = time.time()
            self.completed_tasks[task.id] = task
            self.stats["tasks_failed"] += 1

            self.logger.error("Task failed",
                            task_id=task.id,
                            error=str(e))

            # Retry логіка
            if task.retries < task.max_retries:
                task.retries += 1
                task.error = None
                self.task_queues[task.priority].append(task)
                self.logger.info("Task retry scheduled",
                               task_id=task.id,
                               retry=task.retries)

        finally:
            # Видалення з активних
            if task.id in self.active_tasks:
                del self.active_tasks[task.id]

    async def _cache_cleanup_loop(self):
        """Періодичне очищення кешу"""
        while True:
            try:
                await asyncio.sleep(60)  # Кожну хвилину

                now = time.time()
                expired_keys = [
                    key for key, value in self.completed_tasks.items()
                    if now - value.completed_at > self.cache_ttl
                ]

                for key in expired_keys:
                    if key in self.result_cache:
                        del self.result_cache[key]
                    if key in self.completed_tasks:
                        del self.completed_tasks[key]

                if expired_keys:
                    self.logger.debug("Cache cleaned", removed=len(expired_keys))

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in cache cleanup", error=str(e))

    def _generate_task_id(self, name: str, args: tuple, kwargs: dict) -> str:
        """Генерація унікального ID для задачі"""
        # Створення хешу з параметрів (уникаємо MD5 через колізії)
        data = f"{name}:{args}:{sorted(kwargs.items())}"
        return hashlib.sha256(data.encode()).hexdigest()

    def get_stats(self) -> Dict[str, Any]:
        """Отримання статистики"""
        return {
            **self.stats,
            "active_tasks": len(self.active_tasks),
            "queued_tasks": sum(len(q) for q in self.task_queues.values()),
            "completed_tasks": len(self.completed_tasks),
            "cache_size": len(self.result_cache)
        }


# === Декоратори для оптимізації ===

def async_cached(ttl: int = 300):
    """Декоратор для кешування результатів асинхронних функцій"""
    def decorator(func: AsyncFunc) -> AsyncFunc:
        cache = {}
        cache_times = {}

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Генерація ключа кешу
            key = f"{args}:{sorted(kwargs.items())}"
            now = time.time()

            # Перевірка кешу
            if key in cache and now - cache_times[key] < ttl:
                return cache[key]

            # Виконання функції
            result = await func(*args, **kwargs)

            # Збереження в кеш
            cache[key] = result
            cache_times[key] = now

            return result

        return wrapper
    return decorator


def async_retry(max_attempts: int = 3, delay: float = 1.0):
    """Декоратор для автоматичного повтору асинхронних операцій"""
    def decorator(func: AsyncFunc) -> AsyncFunc:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_attempts - 1:
                        await asyncio.sleep(delay * (attempt + 1))

            raise last_exception

        return wrapper
    return decorator


def run_in_background(optimizer: AsyncOptimizer, priority: TaskPriority = TaskPriority.NORMAL):
    """Декоратор для автоматичного виконання функції у фоні"""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            task_id = await optimizer.create_background_task(
                name=func.__name__,
                func=func,
                *args,
                priority=priority,
                **kwargs
            )
            return task_id

        return wrapper
    return decorator


# === Утиліти для міграції коду ===

class AsyncContextManager:
    """Базовий клас для асинхронних контекстних менеджерів"""

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.release()

    async def acquire(self):
        """Отримання ресурсу"""
        pass

    async def release(self):
        """Звільнення ресурсу"""
        pass


class AsyncBatcher:
    """Утиліта для батчування асинхронних операцій"""

    def __init__(self, batch_size: int = 100, flush_interval: float = 1.0):
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.buffer: List[Tuple[Callable, Any]] = []
        self.flush_task: Optional[asyncio.Task] = None

    async def add(self, func: Callable, data: Any):
        """Додавання елементу до батчу"""
        self.buffer.append((func, data))

        if len(self.buffer) >= self.batch_size:
            await self.flush()
        elif not self.flush_task or self.flush_task.done():
            self.flush_task = asyncio.create_task(self._auto_flush())

    async def flush(self):
        """Виконання накопичених операцій"""
        if not self.buffer:
            return

        batch = self.buffer[:]
        self.buffer.clear()

        # Групування за функціями
        grouped = {}
        for func, data in batch:
            if func not in grouped:
                grouped[func] = []
            grouped[func].append(data)

        # Виконання батчами
        for func, items in grouped.items():
            if asyncio.iscoroutinefunction(func):
                await asyncio.gather(*[func(item) for item in items])
            else:
                # Виконання в thread pool
                loop = asyncio.get_event_loop()
                await asyncio.gather(*[
                    loop.run_in_executor(None, func, item)
                    for item in items
                ])

    async def _auto_flush(self):
        """Автоматичне виконання через інтервал"""
        await asyncio.sleep(self.flush_interval)
        await self.flush()


# Глобальний екземпляр оптимізатора
_global_optimizer: Optional[AsyncOptimizer] = None


def get_async_optimizer() -> AsyncOptimizer:
    """Отримання глобального екземпляру оптимізатора"""
    global _global_optimizer
    if _global_optimizer is None:
        _global_optimizer = AsyncOptimizer()
    return _global_optimizer
