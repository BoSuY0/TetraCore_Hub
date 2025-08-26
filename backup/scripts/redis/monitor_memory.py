#!/usr/bin/env python3
"""
Redis Memory Monitor and Cleanup Service

Цей скрипт моніторить використання пам'яті Redis та автоматично очищує старі дані
для забезпечення оптимальної продуктивності.
"""

import asyncio
import sys
import os
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import structlog

# Додаємо шлях до кореневої директорії проекту
sys.path.append(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from config import Settings
from core.redis_manager import RedisManager


class RedisMemoryMonitor:
    """Монітор пам'яті Redis"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.logger = structlog.get_logger(__name__)
        self.redis_manager = RedisManager(settings)

        # Налаштування моніторингу
        self.check_interval = getattr(
            settings, "redis_cleanup_interval", 3600
        )  # 1 година
        self.memory_threshold = 80  # Поріг використання пам'яті у відсотках
        self.cleanup_patterns = [
            ("tetra:tasks:*", 7),  # Завдання - зберігати 7 днів
            ("tetra:results:*", 3),  # Результати - зберігати 3 дні
            ("tetra:metrics:*", 1),  # Метрики - зберігати 1 день
            ("tetra:temp:*", 0.25),  # Тимчасові дані - зберігати 6 годин
            ("session:*", 30),  # Сесії - зберігати 30 днів
        ]

        # Статистика
        self.cleanup_runs = 0
        self.total_keys_deleted = 0
        self.last_cleanup = None
        self.is_running = False

    async def initialize(self):
        """Ініціалізація монітора"""
        try:
            self.logger.info("Initializing Redis Memory Monitor")

            # Ініціалізація Redis менеджера
            await self.redis_manager.initialize()

            self.is_running = True
            self.logger.info("Redis Memory Monitor initialized successfully")

        except Exception as e:
            self.logger.error("Failed to initialize Redis Memory Monitor", error=str(e))
            raise

    async def shutdown(self):
        """Зупинка монітора"""
        self.logger.info("Shutting down Redis Memory Monitor")
        self.is_running = False

        # Зупинка Redis менеджера
        await self.redis_manager.shutdown()

        self.logger.info("Redis Memory Monitor shutdown complete")

    async def monitor_loop(self):
        """Основний цикл моніторингу"""
        while self.is_running:
            try:
                # Отримання статистики пам'яті
                memory_stats = await self.redis_manager.get_memory_usage()

                if memory_stats:
                    await self._log_memory_stats(memory_stats)

                    # Перевірка порогу пам'яті
                    if await self._check_memory_threshold(memory_stats):
                        self.logger.warning(
                            "Memory threshold exceeded, starting cleanup"
                        )
                        await self.cleanup_old_data()

                # Періодичне очищення незалежно від використання пам'яті
                if await self._should_run_periodic_cleanup():
                    self.logger.info("Running periodic cleanup")
                    await self.cleanup_old_data()

                # Очікування до наступної перевірки
                await asyncio.sleep(self.check_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in monitor loop", error=str(e))
                await asyncio.sleep(60)  # Коротша затримка при помилках

    async def cleanup_old_data(self):
        """Очищення старих даних за паттернами"""
        try:
            self.logger.info("Starting Redis cleanup")
            start_time = datetime.utcnow()
            keys_deleted = 0

            # Очищення за кожним паттерном
            for pattern, days in self.cleanup_patterns:
                try:
                    deleted = await self.redis_manager.cleanup_old_keys(pattern, days)
                    keys_deleted += deleted

                    if deleted > 0:
                        self.logger.info(
                            "Cleaned up keys",
                            pattern=pattern,
                            days=days,
                            deleted=deleted,
                        )

                except Exception as e:
                    self.logger.error(
                        "Failed to cleanup pattern", pattern=pattern, error=str(e)
                    )

            # Додаткове очищення ключів без TTL
            keys_without_ttl = await self._cleanup_keys_without_ttl()
            keys_deleted += keys_without_ttl

            # Оновлення статистики
            self.cleanup_runs += 1
            self.total_keys_deleted += keys_deleted
            self.last_cleanup = datetime.utcnow()

            duration = (datetime.utcnow() - start_time).total_seconds()

            self.logger.info(
                "Redis cleanup completed",
                keys_deleted=keys_deleted,
                duration_seconds=duration,
                total_runs=self.cleanup_runs,
                total_deleted=self.total_keys_deleted,
            )

        except Exception as e:
            self.logger.error("Failed to cleanup old data", error=str(e))

    async def _cleanup_keys_without_ttl(self) -> int:
        """Очищення ключів без TTL"""
        try:
            if not self.redis_manager.redis_client:
                return 0

            deleted = 0

            # Сканування всіх ключів
            async for key in self.redis_manager.redis_client.scan_iter():
                try:
                    ttl = await self.redis_manager.redis_client.ttl(key)

                    # Якщо ключ без TTL
                    if ttl == -1:
                        # Встановлюємо дефолтний TTL
                        await self.redis_manager.redis_client.expire(
                            key, self.redis_manager.default_ttl
                        )
                        deleted += 1

                        if deleted % 100 == 0:
                            self.logger.debug(
                                "Set TTL for keys without expiration", count=deleted
                            )

                except Exception as e:
                    self.logger.error(
                        "Failed to check/set TTL for key", key=key, error=str(e)
                    )

            if deleted > 0:
                self.logger.info("Set TTL for keys without expiration", total=deleted)

            return deleted

        except Exception as e:
            self.logger.error("Failed to cleanup keys without TTL", error=str(e))
            return 0

    async def _check_memory_threshold(self, memory_stats: Dict[str, Any]) -> bool:
        """Перевірка порогу використання пам'яті"""
        try:
            # Парсинг використаної пам'яті
            used_memory = memory_stats.get("used_memory", "0")
            if isinstance(used_memory, str):
                # Видалення суфіксів типу 'M', 'G'
                if used_memory.endswith("M"):
                    used_bytes = float(used_memory[:-1]) * 1024 * 1024
                elif used_memory.endswith("G"):
                    used_bytes = float(used_memory[:-1]) * 1024 * 1024 * 1024
                elif used_memory.endswith("K"):
                    used_bytes = float(used_memory[:-1]) * 1024
                else:
                    used_bytes = float(used_memory)
            else:
                used_bytes = float(used_memory)

            # Отримання максимальної пам'яті Redis
            info = await self.redis_manager.redis_client.config_get("maxmemory")
            max_memory = int(info.get("maxmemory", 0))

            if max_memory > 0:
                usage_percent = (used_bytes / max_memory) * 100

                if usage_percent > self.memory_threshold:
                    self.logger.warning(
                        "Memory usage above threshold",
                        usage_percent=usage_percent,
                        threshold=self.memory_threshold,
                    )
                    return True

            return False

        except Exception as e:
            self.logger.error("Failed to check memory threshold", error=str(e))
            return False

    async def _should_run_periodic_cleanup(self) -> bool:
        """Перевірка чи потрібно запускати періодичне очищення"""
        if not self.last_cleanup:
            return True

        time_since_cleanup = (datetime.utcnow() - self.last_cleanup).total_seconds()
        return time_since_cleanup >= self.check_interval

    async def _log_memory_stats(self, memory_stats: Dict[str, Any]):
        """Логування статистики пам'яті"""
        self.logger.info(
            "Redis memory statistics",
            used_memory=memory_stats.get("used_memory"),
            used_memory_peak=memory_stats.get("used_memory_peak"),
            fragmentation_ratio=memory_stats.get("mem_fragmentation_ratio"),
            evicted_keys=memory_stats.get("evicted_keys"),
        )

    def get_stats(self) -> Dict[str, Any]:
        """Отримання статистики монітора"""
        return {
            "is_running": self.is_running,
            "cleanup_runs": self.cleanup_runs,
            "total_keys_deleted": self.total_keys_deleted,
            "last_cleanup": (
                self.last_cleanup.isoformat() if self.last_cleanup else None
            ),
            "check_interval": self.check_interval,
            "memory_threshold": self.memory_threshold,
            "cleanup_patterns": self.cleanup_patterns,
        }


async def main():
    """Головна функція"""
    # Ініціалізація налаштувань
    settings = Settings()

    # Створення та ініціалізація монітора
    monitor = RedisMemoryMonitor(settings)

    try:
        await monitor.initialize()

        # Запуск моніторингу
        await monitor.monitor_loop()

    except KeyboardInterrupt:
        print("\nShutdown requested...")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await monitor.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
