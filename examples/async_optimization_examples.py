#!/usr/bin/env python3
"""
Приклади використання асинхронних оптимізацій TetraCore Stream Hub

Цей файл містить практичні приклади використання AsyncOptimizer
та асинхронних хелперів для покращення продуктивності.
"""

import asyncio
import time
from datetime import datetime
from typing import List, Dict, Any
import random

# Імпорт необхідних модулів
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.async_optimization import (
    AsyncOptimizer, TaskPriority, async_cached, async_retry,
    run_in_background, AsyncBatcher
)
from utils.async_helpers import (
    async_json_dumps, async_json_loads, async_read_file,
    async_write_file, batch_process_async, AsyncTimer,
    gather_with_progress, async_timed
)


# === Приклад 1: Базове використання AsyncOptimizer ===

async def example_basic_usage():
    """Базовий приклад використання AsyncOptimizer"""
    print("\n=== Приклад 1: Базове використання AsyncOptimizer ===")

    # Створення та ініціалізація оптимізатора
    optimizer = AsyncOptimizer(max_workers=5, max_tasks=100)
    await optimizer.initialize()

    try:
        # Асинхронна серіалізація JSON
        data = {"users": [{"id": i, "name": f"User {i}"} for i in range(100)]}
        json_str = await optimizer.json_dumps(data)
        print(f"Серіалізовано {len(json_str)} байт")

        # Асинхронна десеріалізація
        parsed_data = await optimizer.json_loads(json_str)
        print(f"Десеріалізовано {len(parsed_data['users'])} користувачів")

        # Виконання блокуючої функції в потоці
        def blocking_calculation(n):
            """Симуляція блокуючої операції"""
            time.sleep(0.1)  # Симуляція важкої операції
            return sum(i ** 2 for i in range(n))

        result = await optimizer.run_in_thread(blocking_calculation, 1000)
        print(f"Результат обчислення: {result}")

    finally:
        await optimizer.shutdown()


# === Приклад 2: Фонові задачі з пріоритетами ===

async def example_background_tasks():
    """Приклад роботи з фоновими задачами"""
    print("\n=== Приклад 2: Фонові задачі з пріоритетами ===")

    optimizer = AsyncOptimizer(max_workers=3)
    await optimizer.initialize()

    try:
        # Функція для обробки даних
        async def process_data(data_id: int, size: int) -> Dict[str, Any]:
            """Симуляція обробки даних"""
            await asyncio.sleep(size * 0.1)  # Час залежить від розміру
            return {
                "data_id": data_id,
                "size": size,
                "processed_at": datetime.utcnow().isoformat(),
                "result": f"Processed {size} items"
            }

        # Створення задач з різними пріоритетами
        tasks = []

        # Критична задача
        task1 = await optimizer.create_background_task(
            "critical_processing",
            process_data,
            1, 5,
            priority=TaskPriority.CRITICAL
        )
        tasks.append(("Critical", task1))

        # Звичайні задачі
        for i in range(2, 5):
            task = await optimizer.create_background_task(
                f"normal_processing_{i}",
                process_data,
                i, 10,
                priority=TaskPriority.NORMAL
            )
            tasks.append((f"Normal {i}", task))

        # Низькопріоритетна задача
        task5 = await optimizer.create_background_task(
            "low_priority_processing",
            process_data,
            5, 15,
            priority=TaskPriority.LOW
        )
        tasks.append(("Low Priority", task5))

        # Очікування результатів
        print("Очікування виконання задач...")
        for name, task_id in tasks:
            try:
                result = await optimizer.get_task_result(task_id, timeout=10)
                print(f"{name}: {result}")
            except TimeoutError:
                print(f"{name}: Timeout!")

        # Статистика
        stats = optimizer.get_stats()
        print(f"\nСтатистика:")
        print(f"  Створено задач: {stats['tasks_created']}")
        print(f"  Виконано задач: {stats['tasks_completed']}")
        print(f"  Провалено задач: {stats['tasks_failed']}")

    finally:
        await optimizer.shutdown()


# === Приклад 3: Паралельна обробка даних ===

async def example_parallel_processing():
    """Приклад паралельної обробки даних"""
    print("\n=== Приклад 3: Паралельна обробка даних ===")

    optimizer = AsyncOptimizer()
    await optimizer.initialize()

    try:
        # Симуляція API запитів
        async def fetch_user_data(user_id: int) -> Dict[str, Any]:
            """Симуляція запиту до API"""
            await asyncio.sleep(random.uniform(0.1, 0.3))
            return {
                "id": user_id,
                "name": f"User {user_id}",
                "email": f"user{user_id}@example.com",
                "score": random.randint(0, 100)
            }

        # Паралельне отримання даних для 20 користувачів
        user_ids = list(range(1, 21))

        async with AsyncTimer("Parallel fetch"):
            users = await optimizer.map_async(
                fetch_user_data,
                user_ids,
                max_concurrent=5  # Максимум 5 одночасних запитів
            )

        print(f"Отримано даних для {len(users)} користувачів")

        # Обробка батчами
        async def process_user_batch(users: List[Dict]) -> Dict[str, Any]:
            """Обробка батчу користувачів"""
            await asyncio.sleep(0.2)
            total_score = sum(u['score'] for u in users)
            return {
                "batch_size": len(users),
                "average_score": total_score / len(users),
                "processed_at": datetime.utcnow().isoformat()
            }

        # Розбиваємо на батчі по 5 користувачів
        batches = [users[i:i+5] for i in range(0, len(users), 5)]

        async with AsyncTimer("Batch processing"):
            results = await asyncio.gather(*[
                process_user_batch(batch) for batch in batches
            ])

        for i, result in enumerate(results):
            print(f"Batch {i+1}: {result}")

    finally:
        await optimizer.shutdown()


# === Приклад 4: Кешування результатів ===

@async_cached(ttl=5)  # Кеш на 5 секунд
async def expensive_calculation(n: int) -> int:
    """Дорога операція з кешуванням"""
    print(f"Виконується складне обчислення для n={n}")
    await asyncio.sleep(2)  # Симуляція важкої операції
    return n ** 3


async def example_caching():
    """Приклад використання кешування"""
    print("\n=== Приклад 4: Кешування результатів ===")

    # Перший виклик - виконується повністю
    start = time.time()
    result1 = await expensive_calculation(10)
    duration1 = time.time() - start
    print(f"Перший виклик: результат={result1}, час={duration1:.2f}с")

    # Другий виклик - береться з кешу
    start = time.time()
    result2 = await expensive_calculation(10)
    duration2 = time.time() - start
    print(f"Другий виклик (з кешу): результат={result2}, час={duration2:.2f}с")

    # Очікуємо експірації кешу
    print("Очікування експірації кешу...")
    await asyncio.sleep(6)

    # Третій виклик - знову виконується
    start = time.time()
    result3 = await expensive_calculation(10)
    duration3 = time.time() - start
    print(f"Третій виклик (після експірації): результат={result3}, час={duration3:.2f}с")


# === Приклад 5: Батчування операцій ===

async def example_batching():
    """Приклад батчування операцій для оптимізації"""
    print("\n=== Приклад 5: Батчування операцій ===")

    # Функція для збереження батчу
    async def save_batch_to_db(records: List[Dict[str, Any]]):
        """Симуляція збереження батчу в БД"""
        print(f"Зберігаємо батч з {len(records)} записів")
        await asyncio.sleep(0.5)  # Симуляція I/O операції
        return f"Saved {len(records)} records"

    # Використання AsyncBatcher
    async with AsyncBatcher(save_batch_to_db, batch_size=5, flush_interval=2.0) as batcher:
        # Генерація записів
        for i in range(12):
            record = {
                "id": i,
                "timestamp": datetime.utcnow().isoformat(),
                "value": random.randint(1, 100)
            }
            await batcher.add(record)
            print(f"Додано запис {i}")
            await asyncio.sleep(0.1)

    print("Батчування завершено")


# === Приклад 6: Обробка помилок з retry ===

@async_retry(max_attempts=3, delay=1.0)
async def unreliable_operation():
    """Операція, яка може завершитися помилкою"""
    if random.random() < 0.7:  # 70% шанс помилки
        raise Exception("Операція провалилась")
    return "Успіх!"


async def example_error_handling():
    """Приклад обробки помилок з автоматичним повтором"""
    print("\n=== Приклад 6: Обробка помилок з retry ===")

    try:
        result = await unreliable_operation()
        print(f"Результат: {result}")
    except Exception as e:
        print(f"Операція провалилась після всіх спроб: {e}")


# === Приклад 7: Комплексний сценарій ===

async def example_complex_scenario():
    """Комплексний приклад використання всіх можливостей"""
    print("\n=== Приклад 7: Комплексний сценарій ===")

    optimizer = AsyncOptimizer(max_workers=5)
    await optimizer.initialize()

    try:
        # 1. Читання конфігурації
        config = {
            "api_urls": [f"https://api{i}.example.com" for i in range(1, 4)],
            "batch_size": 10,
            "timeout": 5
        }

        # 2. Збереження конфігурації асинхронно
        await async_write_file(
            "config_example.json",
            await async_json_dumps(config, indent=2)
        )
        print("Конфігурація збережена")

        # 3. Симуляція отримання даних з API
        async def fetch_from_api(url: str) -> List[Dict]:
            """Симуляція API запиту"""
            await asyncio.sleep(random.uniform(0.5, 1.5))
            return [
                {"url": url, "item": i, "value": random.randint(100, 1000)}
                for i in range(5)
            ]

        # 4. Паралельне отримання даних з progress callback
        def progress_callback(completed: int, total: int):
            print(f"Прогрес: {completed}/{total} ({completed/total*100:.1f}%)")

        async with AsyncTimer("Fetching data from APIs"):
            api_results = await gather_with_progress(
                *[fetch_from_api(url) for url in config["api_urls"]],
                callback=progress_callback
            )

        # 5. Об'єднання результатів
        all_items = []
        for result in api_results:
            if not isinstance(result, Exception):
                all_items.extend(result)

        print(f"Отримано {len(all_items)} елементів")

        # 6. CPU-інтенсивна обробка в процесі
        def calculate_statistics(items: List[Dict]) -> Dict[str, float]:
            """Розрахунок статистики"""
            values = [item["value"] for item in items]
            return {
                "count": len(values),
                "sum": sum(values),
                "avg": sum(values) / len(values),
                "min": min(values),
                "max": max(values)
            }

        stats = await optimizer.run_in_process(calculate_statistics, all_items)
        print(f"Статистика: {stats}")

        # 7. Збереження результатів батчами
        async def save_results(batch: List[Dict]):
            """Збереження батчу результатів"""
            filename = f"results_batch_{len(batch)}_{time.time()}.json"
            await async_write_file(
                filename,
                await async_json_dumps(batch)
            )
            print(f"Збережено батч в {filename}")
            return filename

        # Обробка батчами
        saved_files = await batch_process_async(
            all_items,
            lambda items: save_results(items),
            batch_size=5
        )

        print(f"Збережено {len(saved_files)} файлів")

        # 8. Фінальна статистика
        final_stats = optimizer.get_stats()
        print(f"\nФінальна статистика:")
        print(f"  Задач створено: {final_stats['tasks_created']}")
        print(f"  Задач виконано: {final_stats['tasks_completed']}")
        print(f"  Cache hits: {final_stats['cache_hits']}")
        print(f"  Cache misses: {final_stats['cache_misses']}")

    finally:
        await optimizer.shutdown()

        # Очищення тестових файлів
        import glob
        for file in glob.glob("results_batch_*.json") + ["config_example.json"]:
            try:
                os.remove(file)
            except:
                pass


# === Головна функція ===

async def main():
    """Запуск всіх прикладів"""
    print("=== Приклади асинхронних оптимізацій TetraCore Stream Hub ===")

    examples = [
        example_basic_usage,
        example_background_tasks,
        example_parallel_processing,
        example_caching,
        example_batching,
        example_error_handling,
        example_complex_scenario
    ]

    for example in examples:
        try:
            await example()
        except Exception as e:
            print(f"Помилка в {example.__name__}: {e}")

        print("\n" + "="*60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
