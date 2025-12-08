#!/usr/bin/env python3
"""
Redis Performance Benchmark Script

Цей скрипт виконує бенчмаркінг продуктивності Redis для різних конфігурацій
та операцій, щоб оптимізувати налаштування StreamHub.
"""

import asyncio
import sys
import os
import time
import json
import statistics
from datetime import datetime
from typing import Dict, List, Any, Tuple
from dataclasses import dataclass, asdict
import structlog
from typing import Any
import click

# Додаємо шлях до кореневої директорії проекту
sys.path.append(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from config import Settings

# Кастомне логування для заміни print
logger = structlog.get_logger(__name__)


def print(*args: Any, **kwargs: Any):  # type: ignore[override]
    try:
        msg = " ".join(str(a) for a in args)
    except Exception:
        msg = "".join(map(str, args))
    logger.info(msg)


from core.redis_manager import RedisManager


@dataclass
class BenchmarkResult:
    """Результат бенчмарку"""

    operation: str
    total_operations: int
    total_time: float
    operations_per_second: float
    avg_latency_ms: float
    min_latency_ms: float
    max_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    errors: int = 0


class RedisBenchmark:
    """Бенчмарк Redis продуктивності"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.logger = structlog.get_logger(__name__)
        self.redis_manager = RedisManager(settings)
        self.results: List[BenchmarkResult] = []

    async def initialize(self):
        """Ініціалізація бенчмарку"""
        self.logger.info("Initializing Redis Benchmark")
        await self.redis_manager.initialize()

    async def shutdown(self):
        """Завершення бенчмарку"""
        await self.redis_manager.shutdown()

    async def run_benchmarks(self, operations: int = 10000, data_size: int = 1024):
        """Запуск всіх бенчмарків"""
        self.logger.info(
            "Starting Redis benchmarks", operations=operations, data_size=data_size
        )

        # Генерація тестових даних
        test_data = self._generate_test_data(data_size)

        # SET/GET операції
        await self._benchmark_set_get(operations, test_data)

        # Pipeline операції
        await self._benchmark_pipeline(operations, test_data)

        # Pub/Sub операції
        await self._benchmark_pubsub(operations, test_data)

        # Concurrent операції
        await self._benchmark_concurrent(operations, test_data)

        # TTL операції
        await self._benchmark_ttl_operations(operations)

        # Scan операції
        await self._benchmark_scan_operations(operations)

        # Виведення результатів
        self._print_results()

    async def _benchmark_set_get(self, operations: int, data: str):
        """Бенчмарк SET/GET операцій"""
        self.logger.info("Running SET/GET benchmark")

        # SET операції
        latencies = []
        errors = 0
        start_time = time.time()

        for i in range(operations):
            key = f"bench:set:{i}"
            op_start = time.time()

            try:
                await self.redis_manager.set_key(key, data)
                latencies.append((time.time() - op_start) * 1000)
            except Exception as e:
                errors += 1
                self.logger.error("SET operation failed", error=str(e))

        set_result = self._calculate_result(
            "SET", operations, start_time, latencies, errors
        )
        self.results.append(set_result)

        # GET операції
        latencies = []
        errors = 0
        start_time = time.time()

        for i in range(operations):
            key = f"bench:set:{i}"
            op_start = time.time()

            try:
                await self.redis_manager.get_key(key)
                latencies.append((time.time() - op_start) * 1000)
            except Exception as e:
                errors += 1
                self.logger.error("GET operation failed", error=str(e))

        get_result = self._calculate_result(
            "GET", operations, start_time, latencies, errors
        )
        self.results.append(get_result)

        # Очищення
        await self._cleanup_keys("bench:set:*")

    async def _benchmark_pipeline(self, operations: int, data: str):
        """Бенчмарк Pipeline операцій"""
        self.logger.info("Running Pipeline benchmark")

        # Збереження оригінальних налаштувань
        original_enabled = self.redis_manager.pipeline_enabled
        original_batch_size = self.redis_manager.pipeline_batch_size

        batch_sizes = [10, 50, 100, 500]

        for batch_size in batch_sizes:
            self.redis_manager.pipeline_enabled = True
            self.redis_manager.pipeline_batch_size = batch_size

            latencies = []
            errors = 0
            start_time = time.time()

            # Публікація повідомлень через pipeline
            for i in range(operations):
                op_start = time.time()

                try:
                    message = {
                        "message_id": f"bench_{i}",
                        "data": data,
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                    await self.redis_manager.publish("bench:pipeline", message)
                    latencies.append((time.time() - op_start) * 1000)
                except Exception as e:
                    errors += 1
                    self.logger.error("Pipeline operation failed", error=str(e))

            # Flush залишкових операцій
            await self.redis_manager._flush_pipeline()

            result = self._calculate_result(
                f"Pipeline (batch={batch_size})",
                operations,
                start_time,
                latencies,
                errors,
            )
            self.results.append(result)

        # Відновлення налаштувань
        self.redis_manager.pipeline_enabled = original_enabled
        self.redis_manager.pipeline_batch_size = original_batch_size

    async def _benchmark_pubsub(self, operations: int, data: str):
        """Бенчмарк Pub/Sub операцій"""
        self.logger.info("Running Pub/Sub benchmark")

        # Підписка на канал
        received_messages = []

        async def message_handler(channel: str, message: Dict[str, Any]):
            received_messages.append(message)

        self.redis_manager.on_message_received = message_handler
        await self.redis_manager.subscribe(["bench:pubsub"])

        # Публікація повідомлень
        latencies = []
        errors = 0
        start_time = time.time()

        for i in range(operations):
            op_start = time.time()

            try:
                message = {
                    "message_id": f"pubsub_{i}",
                    "data": data,
                    "timestamp": datetime.utcnow().isoformat(),
                }
                await self.redis_manager.publish("bench:pubsub", message)
                latencies.append((time.time() - op_start) * 1000)
            except Exception as e:
                errors += 1
                self.logger.error("Pub/Sub operation failed", error=str(e))

        # Очікування отримання всіх повідомлень
        await asyncio.sleep(1)

        result = self._calculate_result(
            "Pub/Sub", operations, start_time, latencies, errors
        )
        self.results.append(result)

        self.logger.info(
            "Pub/Sub results", sent=operations, received=len(received_messages)
        )

        # Відписка
        await self.redis_manager.unsubscribe(["bench:pubsub"])

    async def _benchmark_concurrent(self, operations: int, data: str):
        """Бенчмарк конкурентних операцій"""
        self.logger.info("Running Concurrent operations benchmark")

        concurrency_levels = [10, 50, 100]

        for concurrency in concurrency_levels:
            latencies = []
            errors = 0
            start_time = time.time()

            # Створення завдань
            tasks = []
            operations_per_task = operations // concurrency

            for i in range(concurrency):
                task = self._concurrent_operations(
                    i * operations_per_task, operations_per_task, data
                )
                tasks.append(task)

            # Виконання конкурентно
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Обробка результатів
            for result in results:
                if isinstance(result, Exception):
                    errors += operations_per_task
                    self.logger.error("Concurrent task failed", error=str(result))
                else:
                    latencies.extend(result)

            result = self._calculate_result(
                f"Concurrent (workers={concurrency})",
                operations,
                start_time,
                latencies,
                errors,
            )
            self.results.append(result)

    async def _concurrent_operations(
        self, start_idx: int, count: int, data: str
    ) -> List[float]:
        """Виконання операцій для конкурентного тесту"""
        latencies = []

        for i in range(count):
            key = f"bench:concurrent:{start_idx + i}"
            op_start = time.time()

            try:
                await self.redis_manager.set_key(key, data)
                latencies.append((time.time() - op_start) * 1000)
            except Exception:
                latencies.append(0)

        return latencies

    async def _benchmark_ttl_operations(self, operations: int):
        """Бенчмарк операцій з TTL"""
        self.logger.info("Running TTL operations benchmark")

        ttl_values = [60, 300, 3600, 86400]  # 1 хв, 5 хв, 1 год, 1 день

        for ttl in ttl_values:
            latencies = []
            errors = 0
            start_time = time.time()

            for i in range(operations // len(ttl_values)):
                key = f"bench:ttl:{ttl}:{i}"
                op_start = time.time()

                try:
                    await self.redis_manager.set_key(key, "test_data", expire=ttl)
                    latencies.append((time.time() - op_start) * 1000)
                except Exception as e:
                    errors += 1
                    self.logger.error("TTL operation failed", error=str(e))

            result = self._calculate_result(
                f"SET with TTL={ttl}s", len(latencies), start_time, latencies, errors
            )
            self.results.append(result)

        # Очищення
        await self._cleanup_keys("bench:ttl:*")

    async def _benchmark_scan_operations(self, operations: int):
        """Бенчмарк SCAN операцій"""
        self.logger.info("Running SCAN operations benchmark")

        # Створення тестових ключів
        for i in range(1000):
            await self.redis_manager.set_key(f"bench:scan:{i}", f"value_{i}")

        patterns = ["bench:scan:*", "bench:scan:1*", "bench:scan:5*"]

        for pattern in patterns:
            latencies = []
            errors = 0
            start_time = time.time()
            keys_found = 0

            for _ in range(operations // len(patterns)):
                op_start = time.time()

                try:
                    count = 0
                    async for key in self.redis_manager.redis_client.scan_iter(
                        match=pattern
                    ):
                        count += 1
                    keys_found = count
                    latencies.append((time.time() - op_start) * 1000)
                except Exception as e:
                    errors += 1
                    self.logger.error("SCAN operation failed", error=str(e))

            result = self._calculate_result(
                f"SCAN (pattern={pattern}, keys={keys_found})",
                len(latencies),
                start_time,
                latencies,
                errors,
            )
            self.results.append(result)

        # Очищення
        await self._cleanup_keys("bench:scan:*")

    def _generate_test_data(self, size: int) -> str:
        """Генерація тестових даних"""
        return json.dumps(
            {
                "data": "x" * size,
                "timestamp": datetime.utcnow().isoformat(),
                "metadata": {"test": True, "size": size},
            }
        )

    async def _cleanup_keys(self, pattern: str):
        """Очищення тестових ключів"""
        try:
            count = 0
            async for key in self.redis_manager.redis_client.scan_iter(match=pattern):
                await self.redis_manager.redis_client.delete(key)
                count += 1

            self.logger.debug("Cleaned up test keys", pattern=pattern, count=count)
        except Exception as e:
            self.logger.error("Failed to cleanup keys", pattern=pattern, error=str(e))

    def _calculate_result(
        self,
        operation: str,
        total_ops: int,
        start_time: float,
        latencies: List[float],
        errors: int,
    ) -> BenchmarkResult:
        """Розрахунок результатів бенчмарку"""
        total_time = time.time() - start_time
        valid_latencies = [l for l in latencies if l > 0]

        if not valid_latencies:
            return BenchmarkResult(
                operation=operation,
                total_operations=total_ops,
                total_time=total_time,
                operations_per_second=0,
                avg_latency_ms=0,
                min_latency_ms=0,
                max_latency_ms=0,
                p50_latency_ms=0,
                p95_latency_ms=0,
                p99_latency_ms=0,
                errors=errors,
            )

        sorted_latencies = sorted(valid_latencies)

        return BenchmarkResult(
            operation=operation,
            total_operations=total_ops,
            total_time=total_time,
            operations_per_second=total_ops / total_time,
            avg_latency_ms=statistics.mean(valid_latencies),
            min_latency_ms=min(valid_latencies),
            max_latency_ms=max(valid_latencies),
            p50_latency_ms=sorted_latencies[len(sorted_latencies) // 2],
            p95_latency_ms=sorted_latencies[int(len(sorted_latencies) * 0.95)],
            p99_latency_ms=sorted_latencies[int(len(sorted_latencies) * 0.99)],
            errors=errors,
        )

    def _print_results(self):
        """Виведення результатів бенчмарку"""
        print("\n" + "=" * 100)
        print("REDIS BENCHMARK RESULTS")
        print("=" * 100)
        print(f"Redis Mode: {self.redis_manager.redis_mode}")
        # Маскуємо можливий пароль у URL
        safe_url = self.settings.redis_url
        try:
            if safe_url and "@" in safe_url:
                safe_url = safe_url.split("://")[0] + "://***@" + safe_url.split("@")[1]
        except Exception:
            safe_url = "<hidden>"
        print(f"Redis URL: {safe_url}")
        print(f"Pipeline Enabled: {self.redis_manager.pipeline_enabled}")
        print("=" * 100)

        # Заголовки таблиці
        headers = [
            "Operation",
            "Total Ops",
            "Time (s)",
            "Ops/sec",
            "Avg (ms)",
            "Min (ms)",
            "Max (ms)",
            "P50 (ms)",
            "P95 (ms)",
            "P99 (ms)",
            "Errors",
        ]

        # Форматування заголовків
        header_format = "{:<35} {:>10} {:>10} {:>10} {:>10} {:>10} {:>10} {:>10} {:>10} {:>10} {:>8}"
        print(header_format.format(*headers))
        print("-" * 150)

        # Виведення результатів
        row_format = "{:<35} {:>10} {:>10.2f} {:>10.0f} {:>10.2f} {:>10.2f} {:>10.2f} {:>10.2f} {:>10.2f} {:>10.2f} {:>8}"

        for result in self.results:
            print(
                row_format.format(
                    result.operation,
                    result.total_operations,
                    result.total_time,
                    result.operations_per_second,
                    result.avg_latency_ms,
                    result.min_latency_ms,
                    result.max_latency_ms,
                    result.p50_latency_ms,
                    result.p95_latency_ms,
                    result.p99_latency_ms,
                    result.errors,
                )
            )

        print("=" * 150)

        # Збереження результатів у файл
        self._save_results()

    def _save_results(self):
        """Збереження результатів у JSON файл"""
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"redis_benchmark_{timestamp}.json"

        data = {
            "timestamp": datetime.utcnow().isoformat(),
            "redis_mode": self.redis_manager.redis_mode,
            "redis_url": safe_url,
            "pipeline_enabled": self.redis_manager.pipeline_enabled,
            "results": [asdict(r) for r in self.results],
        }

        with open(filename, "w") as f:
            json.dump(data, f, indent=2)

        print(f"\nResults saved to: {filename}")


@click.command()
@click.option(
    "--operations", "-o", default=10000, help="Number of operations to perform"
)
@click.option("--data-size", "-s", default=1024, help="Size of test data in bytes")
@click.option("--redis-url", "-r", help="Redis URL (overrides config)")
@click.option(
    "--mode",
    "-m",
    type=click.Choice(["standalone", "sentinel", "cluster"]),
    help="Redis mode to test",
)
async def main(operations: int, data_size: int, redis_url: str, mode: str):
    """Redis Performance Benchmark"""
    # Ініціалізація налаштувань
    settings = Settings()

    # Перевизначення налаштувань якщо потрібно
    if redis_url:
        settings.redis_url = redis_url

    if mode:
        if mode == "sentinel":
            # Для тестування Sentinel потрібно задати URLs
            sentinel_urls = os.getenv("REDIS_SENTINEL_URLS")
            if sentinel_urls:
                settings.redis_sentinel_urls = sentinel_urls.split(",")
        elif mode == "cluster":
            # Для тестування Cluster потрібно задати nodes
            cluster_nodes = os.getenv("REDIS_CLUSTER_NODES")
            if cluster_nodes:
                settings.redis_cluster_nodes = cluster_nodes.split(",")

    # Створення та запуск бенчмарку
    benchmark = RedisBenchmark(settings)

    try:
        await benchmark.initialize()
        await benchmark.run_benchmarks(operations, data_size)
    except Exception as e:
        print(f"Benchmark failed: {e}")
    finally:
        await benchmark.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
