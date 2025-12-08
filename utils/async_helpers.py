"""
TetraCore StreamHub Async Helpers

Утиліти для міграції блокуючих операцій на асинхронні версії.
Надає зручні функції та декоратори для покращення асинхронної продуктивності.
"""

import asyncio
import json
import time
import functools
import atexit
from typing import Any, List, Optional, Callable, TypeVar, Coroutine, Union
from pathlib import Path
import aiofiles
import structlog
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# Type definitions
T = TypeVar("T")
AsyncFunc = Callable[..., Coroutine[Any, Any, T]]

# Глобальний thread pool для блокуючих операцій
_thread_pool = ThreadPoolExecutor(max_workers=10)

logger = structlog.get_logger(__name__)


# === JSON операції ===


async def async_json_dumps(obj: Any, **kwargs) -> str:
    """
    Асинхронна серіалізація JSON.

    Args:
        obj: Об'єкт для серіалізації
        **kwargs: Додаткові параметри для json.dumps

    Returns:
        JSON рядок
    """
    loop = asyncio.get_event_loop()
    kwargs.setdefault("ensure_ascii", False)
    kwargs.setdefault("default", str)

    return await loop.run_in_executor(
        _thread_pool, functools.partial(json.dumps, obj, **kwargs)
    )


async def async_json_loads(s: Union[str, bytes]) -> Any:
    """
    Асинхронна десеріалізація JSON.

    Args:
        s: JSON рядок або байти

    Returns:
        Десеріалізований об'єкт
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_thread_pool, json.loads, s)


# === Файлові операції ===


async def async_read_file(
    path: Union[str, Path], mode: str = "r", encoding: str = "utf-8"
) -> str:
    """
    Асинхронне читання файлу.

    Args:
        path: Шлях до файлу
        mode: Режим відкриття
        encoding: Кодування

    Returns:
        Вміст файлу
    """
    async with aiofiles.open(path, mode=mode, encoding=encoding) as f:
        return await f.read()


async def async_write_file(
    path: Union[str, Path], content: str, mode: str = "w", encoding: str = "utf-8"
):
    """
    Асинхронний запис у файл.

    Args:
        path: Шлях до файлу
        content: Вміст для запису
        mode: Режим відкриття
        encoding: Кодування
    """
    async with aiofiles.open(path, mode=mode, encoding=encoding) as f:
        await f.write(content)


async def async_read_json(path: Union[str, Path]) -> Any:
    """
    Асинхронне читання та парсинг JSON файлу.

    Args:
        path: Шлях до JSON файлу

    Returns:
        Десеріалізований об'єкт
    """
    content = await async_read_file(path)
    return await async_json_loads(content)


async def async_write_json(path: Union[str, Path], obj: Any, **kwargs):
    """
    Асинхронна серіалізація та запис JSON у файл.

    Args:
        path: Шлях до файлу
        obj: Об'єкт для серіалізації
        **kwargs: Додаткові параметри для json.dumps
    """
    content = await async_json_dumps(obj, **kwargs)
    await async_write_file(path, content)


# === Загальні блокуючі операції ===


async def run_blocking(func: Callable[..., T], *args, **kwargs) -> T:
    """
    Виконання блокуючої функції в окремому потоці.

    Args:
        func: Функція для виконання
        *args: Позиційні аргументи
        **kwargs: Іменовані аргументи

    Returns:
        Результат виконання функції
    """
    loop = asyncio.get_event_loop()
    if args or kwargs:
        return await loop.run_in_executor(
            _thread_pool, functools.partial(func, *args, **kwargs)
        )
    else:
        return await loop.run_in_executor(_thread_pool, func)


# === Datetime операції ===


async def async_datetime_now() -> datetime:
    """Асинхронне отримання поточного часу"""
    return await run_blocking(datetime.utcnow)


async def async_time_time() -> float:
    """Асинхронне отримання timestamp"""
    return await run_blocking(time.time)


# === Batch операції ===


async def batch_process_async(
    items: List[Any],
    processor: AsyncFunc,
    batch_size: int = 100,
    max_concurrent: int = 10,
) -> List[Any]:
    """
    Обробка елементів батчами з обмеженням конкурентності.

    Args:
        items: Список елементів для обробки
        processor: Асинхронна функція обробки
        batch_size: Розмір батчу
        max_concurrent: Максимальна кількість конкурентних операцій

    Returns:
        Список результатів
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    results = []

    async def limited_processor(item):
        async with semaphore:
            return await processor(item)

    # Обробка батчами
    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        batch_results = await asyncio.gather(
            *[limited_processor(item) for item in batch], return_exceptions=False
        )
        results.extend(batch_results)

        # Короткий sleep між батчами для уникнення перевантаження
        if i + batch_size < len(items):
            await asyncio.sleep(0.01)

    return results


async def gather_with_progress(
    *coroutines: Coroutine,
    callback: Optional[Callable[[int, int], None]] = None,
    return_exceptions: bool = True,
) -> List[Any]:
    """
    Виконання кількох корутин з відстеженням прогресу.

    Args:
        *coroutines: Корутини для виконання
        callback: Функція зворотнього виклику (completed, total)
        return_exceptions: Чи повертати винятки як результати

    Returns:
        Список результатів
    """
    total = len(coroutines)
    completed = 0

    async def wrapped_coro(index: int, coro: Coroutine):
        nonlocal completed
        try:
            result = await coro
            completed += 1
            if callback:
                callback(completed, total)
            return index, result
        except Exception as e:
            completed += 1
            if callback:
                callback(completed, total)
            if return_exceptions:
                return index, e
            raise

    # Виконання з індексами для збереження порядку
    indexed_results = await asyncio.gather(
        *[wrapped_coro(i, coro) for i, coro in enumerate(coroutines)],
        return_exceptions=return_exceptions,
    )

    # Сортування за індексами
    indexed_results.sort(key=lambda x: x[0])

    return [result for _, result in indexed_results]


# === Декоратори ===


def async_timed(func: AsyncFunc) -> AsyncFunc:
    """
    Декоратор для вимірювання часу виконання асинхронної функції.
    """

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = await func(*args, **kwargs)
            elapsed = time.time() - start_time
            logger.debug(
                f"{func.__name__} completed",
                duration=elapsed,
                args_count=len(args),
                kwargs_keys=list(kwargs.keys()),
            )
            return result
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"{func.__name__} failed", duration=elapsed, error=str(e))
            raise

    return wrapper


def ensure_async(func: Union[Callable, AsyncFunc]) -> AsyncFunc:
    """
    Декоратор для перетворення синхронної функції на асинхронну.
    """
    if asyncio.iscoroutinefunction(func):
        return func

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        return await run_blocking(func, *args, **kwargs)

    return wrapper


def async_lru_cache(maxsize: int = 128):
    """
    LRU кеш для асинхронних функцій.
    """

    def decorator(func: AsyncFunc) -> AsyncFunc:
        cache = {}
        cache_order = []

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Створення ключа кешу
            key = str(args) + str(sorted(kwargs.items()))

            # Перевірка кешу
            if key in cache:
                # Переміщення в кінець (найновіший)
                cache_order.remove(key)
                cache_order.append(key)
                return cache[key]

            # Виконання функції
            result = await func(*args, **kwargs)

            # Додавання в кеш
            cache[key] = result
            cache_order.append(key)

            # Видалення найстаріших якщо перевищено розмір
            while len(cache) > maxsize:
                oldest_key = cache_order.pop(0)
                del cache[oldest_key]

            return result

        # Додаткові методи для управління кешем
        wrapper.cache_clear = lambda: (cache.clear(), cache_order.clear())
        wrapper.cache_info = lambda: {"size": len(cache), "maxsize": maxsize}

        return wrapper

    return decorator


# === Контекстні менеджери ===


class AsyncTimer:
    """Контекстний менеджер для вимірювання часу асинхронних операцій"""

    def __init__(self, name: str = "Operation"):
        self.name = name
        self.start_time = None
        self.end_time = None

    async def __aenter__(self):
        self.start_time = time.time()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.end_time = time.time()
        elapsed = self.end_time - self.start_time

        if exc_type is None:
            logger.info(f"{self.name} completed", duration=elapsed)
        else:
            logger.error(f"{self.name} failed", duration=elapsed, error=str(exc_val))

    @property
    def elapsed(self) -> float:
        """Час виконання в секундах"""
        if self.start_time is None:
            return 0
        if self.end_time is None:
            return time.time() - self.start_time
        return self.end_time - self.start_time


class AsyncBatcher:
    """Контекстний менеджер для батчування операцій"""

    def __init__(
        self, flush_func: AsyncFunc, batch_size: int = 100, flush_interval: float = 1.0
    ):
        self.flush_func = flush_func
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.buffer = []
        self.flush_task = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # Flush залишкових даних
        if self.buffer:
            await self.flush()

        # Скасування flush задачі
        if self.flush_task and not self.flush_task.done():
            self.flush_task.cancel()
            try:
                await self.flush_task
            except asyncio.CancelledError:
                pass

    async def add(self, item: Any):
        """Додавання елементу до батчу"""
        self.buffer.append(item)

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

        await self.flush_func(batch)

    async def _auto_flush(self):
        """Автоматичне виконання через інтервал"""
        await asyncio.sleep(self.flush_interval)
        await self.flush()


# === Утиліти для конвертації ===


def make_async(sync_class: type) -> type:
    """
    Перетворює синхронний клас на асинхронний.
    Замінює всі методи на асинхронні версії.
    """

    class AsyncWrapper(sync_class):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)

            # Обгортання всіх методів
            for name in dir(self):
                if name.startswith("_"):
                    continue

                attr = getattr(self, name)
                if callable(attr) and not asyncio.iscoroutinefunction(attr):
                    setattr(self, name, ensure_async(attr))

    AsyncWrapper.__name__ = f"Async{sync_class.__name__}"
    return AsyncWrapper


# === Cleanup при завершенні ===


def cleanup_thread_pool():
    """Очищення thread pool при завершенні"""
    _thread_pool.shutdown(wait=True)


# Реєстрація cleanup
atexit.register(cleanup_thread_pool)
