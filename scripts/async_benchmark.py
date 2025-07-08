#!/usr/bin/env python3
"""
Бенчмарк для асинхронних оптимізацій TetraCore Stream Hub

Цей скрипт порівнює продуктивність синхронних та асинхронних операцій
для демонстрації ефективності впроваджених оптимізацій.
"""

import asyncio
import json
import time
import sys
import os
from typing import List, Dict, Any, Callable
import statistics
from datetime import datetime
import tempfile
import random
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor

# Додаємо шлях до проекту
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.async_optimization import AsyncOptimizer, TaskPriority
from utils.async_helpers import (
    async_json_dumps, async_json_loads,
    async_read_file, async_write_file,
    batch_process_async, AsyncTimer
)


class AsyncBenchmark:
    """Клас для бенчмаркінгу асинхронних операцій"""

    def __init__(self):
        self.results = {}
        self.optimizer = AsyncOptimizer(max_workers=10)

    async def initialize(self):
        """Ініціалізація бенчмарку"""
        await self.optimizer.initialize()
        print("=== Асинхронний бенчмарк TetraCore Stream Hub ===\n")

    async def shutdown(self):
        """Завершення бенчмарку"""
        await self.optimizer.shutdown()

    def measure_time(self, func: Callable, *args, **kwargs):
        """Вимірювання часу синхронної функції"""
        start = time.time()
        result = func(*args, **kwargs)
        end = time.time()
        return result, end - start

    async def measure_async_time(self, coro):
        """Вимірювання часу асинхронної функції"""
        start = time.time()
        result = await coro
        end = time.time()
        return result, end - start

    # === JSON бенчмарки ===

    async def benchmark_json_operations(self, size: int = 10000):
        """Порівняння JSON операцій"""
        print(f"📊 JSON операції (розмір: {size} елементів)")

        # Генерація тестових даних
        data = {
            "users": [
                {
                    "id": i,
                    "name": f"User {i}",
                    "email": f"user{i}@example.com",
                    "metadata": {"score": random.randint(0, 1000)}
                }
                for i in range(size)
            ]
        }

        # Синхронна серіалізація
        _, sync_dumps_time = self.measure_time(json.dumps, data)

        # Асинхронна серіалізація
        _, async_dumps_time = await self.measure_async_time(
            async_json_dumps(data)
        )

        # Серіалізуємо для тесту десеріалізації
        json_str = json.dumps(data)

        # Синхронна десеріалізація
        _, sync_loads_time = self.measure_time(json.loads, json_str)

        # Асинхронна десеріалізація
        _, async_loads_time = await self.measure_async_time(
            async_json_loads(json_str)
        )

        # Результати
        print(f"  Серіалізація:")
        print(f"    Синхронна:  {sync_dumps_time:.4f}с")
        print(f"    Асинхронна: {async_dumps_time:.4f}с")
        print(f"    Покращення: {sync_dumps_time/async_dumps_time:.2f}x")

        print(f"  Десеріалізація:")
        print(f"    Синхронна:  {sync_loads_time:.4f}с")
        print(f"    Асинхронна: {async_loads_time:.4f}с")
        print(f"    Покращення: {sync_loads_time/async_loads_time:.2f}x\n")

        self.results["json"] = {
            "dumps": {"sync": sync_dumps_time, "async": async_dumps_time},
            "loads": {"sync": sync_loads_time, "async": async_loads_time}
        }

    # === Файлові операції ===

    async def benchmark_file_operations(self, size_mb: int = 10):
        """Порівняння файлових операцій"""
        print(f"📁 Файлові операції (розмір: {size_mb}MB)")

        # Генерація тестових даних
        content = "x" * (size_mb * 1024 * 1024)

        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            temp_file = f.name
            f.write(content)

        try:
            # Синхронне читання
            def sync_read():
                with open(temp_file, 'r') as f:
                    return f.read()

            _, sync_read_time = self.measure_time(sync_read)

            # Асинхронне читання
            _, async_read_time = await self.measure_async_time(
                async_read_file(temp_file)
            )

            # Синхронний запис
            def sync_write():
                with open(temp_file + ".copy", 'w') as f:
                    f.write(content)

            _, sync_write_time = self.measure_time(sync_write)

            # Асинхронний запис
            _, async_write_time = await self.measure_async_time(
                async_write_file(temp_file + ".async", content)
            )

            # Результати
            print(f"  Читання:")
            print(f"    Синхронне:  {sync_read_time:.4f}с")
            print(f"    Асинхронне: {async_read_time:.4f}с")
            print(f"    Покращення: {sync_read_time/async_read_time:.2f}x")

            print(f"  Запис:")
            print(f"    Синхронний:  {sync_write_time:.4f}с")
            print(f"    Асинхронний: {async_write_time:.4f}с")
            print(f"    Покращення: {sync_write_time/async_write_time:.2f}x\n")

            self.results["file"] = {
                "read": {"sync": sync_read_time, "async": async_read_time},
                "write": {"sync": sync_write_time, "async": async_write_time}
            }

        finally:
            # Очищення
            for file in [temp_file, temp_file + ".copy", temp_file + ".async"]:
                try:
                    os.remove(file)
                except:
                    pass

    # === Конкурентні операції ===

    async def benchmark_concurrent_operations(self, num_tasks: int = 100):
        """Порівняння конкурентних операцій"""
        print(f"⚡ Конкурентні операції ({num_tasks} задач)")

        # Симуляція I/O операції
        def blocking_io_operation(n: int):
            time.sleep(0.01)  # Симуляція I/O
            return n ** 2

        async def async_io_operation(n: int):
            await asyncio.sleep(0.01)  # Симуляція I/O
            return n ** 2

        # Синхронне виконання
        start = time.time()
        sync_results = []
        for i in range(num_tasks):
            result = blocking_io_operation(i)
            sync_results.append(result)
        sync_time = time.time() - start

        # Асинхронне виконання (послідовно)
        start = time.time()
        async_seq_results = []
        for i in range(num_tasks):
            result = await async_io_operation(i)
            async_seq_results.append(result)
        async_seq_time = time.time() - start

        # Асинхронне виконання (паралельно)
        start = time.time()
        async_par_results = await asyncio.gather(*[
            async_io_operation(i) for i in range(num_tasks)
        ])
        async_par_time = time.time() - start

        # Використання AsyncOptimizer
        start = time.time()
        optimizer_results = await self.optimizer.map_async(
            async_io_operation,
            list(range(num_tasks)),
            max_concurrent=10
        )
        optimizer_time = time.time() - start

        # Результати
        print(f"  Синхронне виконання:       {sync_time:.4f}с")
        print(f"  Асинхронне (послідовно):   {async_seq_time:.4f}с")
        print(f"  Асинхронне (паралельно):   {async_par_time:.4f}с")
        print(f"  AsyncOptimizer:            {optimizer_time:.4f}с")
        print(f"  Покращення:                {sync_time/async_par_time:.2f}x\n")

        self.results["concurrent"] = {
            "sync": sync_time,
            "async_sequential": async_seq_time,
            "async_parallel": async_par_time,
            "optimizer": optimizer_time
        }

    # === Фонові задачі ===

    async def benchmark_background_tasks(self, num_tasks: int = 50):
        """Бенчмарк фонових задач"""
        print(f"🔧 Фонові задачі ({num_tasks} задач)")

        # CPU-інтенсивна функція
        def cpu_intensive_task(n: int):
            result = 0
            for i in range(n * 1000):
                result += i ** 2
            return result

        # Створення задач з різними пріоритетами
        start = time.time()
        task_ids = []

        # Критичні задачі
        for i in range(num_tasks // 3):
            task_id = await self.optimizer.create_background_task(
                f"critical_{i}",
                cpu_intensive_task,
                10,
                priority=TaskPriority.CRITICAL
            )
            task_ids.append(task_id)

        # Звичайні задачі
        for i in range(num_tasks // 3):
            task_id = await self.optimizer.create_background_task(
                f"normal_{i}",
                cpu_intensive_task,
                10,
                priority=TaskPriority.NORMAL
            )
            task_ids.append(task_id)

        # Низькопріоритетні задачі
        for i in range(num_tasks // 3):
            task_id = await self.optimizer.create_background_task(
                f"low_{i}",
                cpu_intensive_task,
                10,
                priority=TaskPriority.LOW
            )
            task_ids.append(task_id)

        creation_time = time.time() - start

        # Очікування виконання
        start = time.time()
        results = []
        for task_id in task_ids:
            try:
                result = await self.optimizer.get_task_result(task_id, timeout=30)
                results.append(result)
            except TimeoutError:
                pass

        execution_time = time.time() - start

        # Статистика
        stats = self.optimizer.get_stats()

        print(f"  Час створення задач:       {creation_time:.4f}с")
        print(f"  Час виконання:             {execution_time:.4f}с")
        print(f"  Загальний час:             {creation_time + execution_time:.4f}с")
        print(f"  Виконано задач:            {stats['tasks_completed']}")
        print(f"  Cache hits:                {stats['cache_hits']}")
        print(f"  Cache misses:              {stats['cache_misses']}\n")

        self.results["background_tasks"] = {
            "creation_time": creation_time,
            "execution_time": execution_time,
            "total_time": creation_time + execution_time,
            "stats": stats
        }

    # === Батчування ===

    async def benchmark_batching(self, num_items: int = 1000):
        """Бенчмарк батчування операцій"""
        print(f"📦 Батчування операцій ({num_items} елементів)")

        results_storage = []

        # Функція збереження
        async def save_items(items: List[Dict]):
            await asyncio.sleep(0.05)  # Симуляція I/O
            results_storage.extend(items)
            return len(items)

        # Без батчування
        start = time.time()
        for i in range(num_items):
            await save_items([{"id": i, "value": i * 2}])
        no_batch_time = time.time() - start

        results_storage.clear()

        # З батчуванням
        start = time.time()
        items = [{"id": i, "value": i * 2} for i in range(num_items)]
        await batch_process_async(
            items,
            lambda batch: save_items(batch),
            batch_size=50
        )
        batch_time = time.time() - start

        print(f"  Без батчування:    {no_batch_time:.4f}с")
        print(f"  З батчуванням:     {batch_time:.4f}с")
        print(f"  Покращення:        {no_batch_time/batch_time:.2f}x\n")

        self.results["batching"] = {
            "no_batch": no_batch_time,
            "with_batch": batch_time
        }

    # === Фінальний звіт ===

    def print_summary(self):
        """Виведення підсумкового звіту"""
        print("="*60)
        print("📈 ПІДСУМОК БЕНЧМАРКУ")
        print("="*60)

        total_improvements = []

        for category, data in self.results.items():
            print(f"\n{category.upper()}:")

            if category in ["json", "file"]:
                for operation, times in data.items():
                    if "sync" in times and "async" in times:
                        improvement = times["sync"] / times["async"]
                        total_improvements.append(improvement)
                        print(f"  {operation}: {improvement:.2f}x покращення")

            elif category == "concurrent":
                improvement = data["sync"] / data["async_parallel"]
                total_improvements.append(improvement)
                print(f"  Паралельне виконання: {improvement:.2f}x покращення")

            elif category == "batching":
                improvement = data["no_batch"] / data["with_batch"]
                total_improvements.append(improvement)
                print(f"  Батчування: {improvement:.2f}x покращення")

        if total_improvements:
            avg_improvement = statistics.mean(total_improvements)
            print(f"\n🎯 Середнє покращення продуктивності: {avg_improvement:.2f}x")

        print("\n" + "="*60)


async def main():
    """Головна функція бенчмарку"""
    benchmark = AsyncBenchmark()

    try:
        await benchmark.initialize()

        # Запуск всіх бенчмарків
        await benchmark.benchmark_json_operations(size=10000)
        await benchmark.benchmark_file_operations(size_mb=5)
        await benchmark.benchmark_concurrent_operations(num_tasks=50)
        await benchmark.benchmark_background_tasks(num_tasks=30)
        await benchmark.benchmark_batching(num_items=100)

        # Підсумок
        benchmark.print_summary()

    finally:
        await benchmark.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
