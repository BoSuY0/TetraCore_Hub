"""
TetraCore StreamHub Redis Manager

Менеджер для роботи з Redis Pub/Sub системою.
Забезпечує підключення, публікацію та підписку на канали,
а також управління з'єднаннями та моніторинг здоров'я.
"""

import asyncio
import os
import json
from datetime import datetime
from typing import Dict, List, Optional, Callable, Any, Set, Union
from contextlib import asynccontextmanager
import structlog

import redis.asyncio as redis
from redis.asyncio import Redis, RedisCluster, Sentinel
from redis.exceptions import ConnectionError, TimeoutError

from config import Settings
from core.async_optimization import AsyncOptimizer


class RedisManager:
    """Менеджер Redis для StreamHub"""

    def __init__(self, settings: Settings):
        """Ініціалізація Redis менеджера"""
        self.settings = settings
        self.logger = structlog.get_logger(__name__)

        # Redis з'єднання
        self.redis_client: Optional[Union[Redis, RedisCluster]] = None
        self.pubsub_client: Optional[Union[Redis, RedisCluster]] = None

        # Sentinel підтримка
        self.sentinel: Optional[Sentinel] = None
        self.sentinel_service_name: str = getattr(
            settings, "redis_sentinel_service_name", "tetracore-master"
        )

        # Режим роботи Redis
        self.redis_mode: str = "standalone"  # standalone, sentinel, cluster, disabled

        # Pipeline для batch операцій
        self.pipeline_enabled: bool = getattr(settings, "redis_pipeline_enabled", True)
        self.pipeline_batch_size: int = getattr(
            settings, "redis_pipeline_batch_size", 100
        )
        self.pipeline_flush_interval: float = getattr(
            settings, "redis_pipeline_flush_interval", 0.1
        )  # секунди
        self.pipeline_buffer: List[tuple] = []
        self.pipeline_task: Optional[asyncio.Task] = None
        self.pipeline_timers: Dict[str, asyncio.Task] = {}

        # Pub/Sub об'єкти
        self.pubsub = None
        self.subscriptions: Set[str] = set()

        # Статистика
        self.messages_published = 0
        self.messages_received = 0
        self.connection_errors = 0
        self.last_error: Optional[str] = None

        # Event handlers
        self.on_message_received: Optional[Callable] = None
        self.on_connection_lost: Optional[Callable] = None
        self.on_connection_restored: Optional[Callable] = None

        # Стан менеджера
        self.is_running = False
        self.is_connected = False
        self.listen_task: Optional[asyncio.Task] = None
        self.health_check_task: Optional[asyncio.Task] = None

        # Кеш повідомлень для надійності
        self.message_cache: Dict[str, Dict[str, Any]] = {}
        self.max_cache_size = 1000

        # TTL для ключів (за замовчуванням 24 години)
        self.default_ttl: int = getattr(settings, "redis_default_ttl", 86400)

        # Асинхронний оптимізатор
        self.async_optimizer = AsyncOptimizer(max_workers=5)

    async def initialize(self):
        """Ініціалізація Redis менеджера"""
        try:
            # Визначення режиму роботи
            await self._detect_redis_mode()

            # Створення Redis клієнтів
            await self._create_redis_clients()

            # Перевірка з'єднання
            await self._test_connection()

            # Ініціалізація асинхронного оптимізатора
            await self.async_optimizer.initialize()

            # Запуск моніторингу
            self.health_check_task = asyncio.create_task(self._health_check_loop())

            # Запуск pipeline якщо увімкнено
            if self.pipeline_enabled:
                self.pipeline_task = asyncio.create_task(self._pipeline_flush_loop())

            self.is_running = True
            self.is_connected = True

            self.logger.info("Redis Manager initialized successfully")

        except Exception as e:
            from core.logging.utils import _mask_text_patterns

            masked = _mask_text_patterns(str(e))
            self.logger.error("Failed to initialize Redis Manager", error=masked)
            self.last_error = masked
            raise

    async def shutdown(self):
        """Зупинка Redis менеджера з повним очищенням пулу з'єднань"""
        self.logger.info("Shutting down Redis Manager")

        self.is_running = False

        try:
            # Зупинка фонових задач
            tasks_to_cancel = [
                self.listen_task,
                self.health_check_task,
                self.pipeline_task,
            ]

            for task in tasks_to_cancel:
                if task and not task.done():
                    task.cancel()
                    try:
                        await asyncio.wait_for(task, timeout=5.0)
                    except (asyncio.CancelledError, asyncio.TimeoutError):
                        pass

            self.logger.info("Background tasks cancelled")

            # Flush pipeline buffer перед закриттям
            if self.pipeline_enabled and self.pipeline_buffer:
                try:
                    await self._flush_pipeline()
                    self.logger.info("Pipeline buffer flushed")
                except Exception as e:
                    self.logger.warning("Error flushing pipeline buffer", error=str(e))

            # Відписка від всіх каналів
            if self.pubsub and self.subscriptions:
                try:
                    await self.pubsub.unsubscribe(*list(self.subscriptions))
                    await asyncio.sleep(0.1)  # Дати час на відписку
                    self.logger.info(
                        "Unsubscribed from channels",
                        channels="all",
                        remaining_subscriptions=0,
                    )
                except Exception as e:
                    self.logger.warning(
                        "Error unsubscribing from channels", error=str(e)
                    )

            # Закриття Pub/Sub об'єкта
            if self.pubsub:
                try:
                    await self.pubsub.close()
                    self.logger.info("Pub/Sub connection closed")
                except Exception as e:
                    self.logger.warning("Error closing Pub/Sub", error=str(e))

            # Закриття з'єднань з тайм-аутом
            close_tasks = []

            if self.redis_client:
                close_tasks.append(
                    self._close_client_with_timeout(
                        self.redis_client, "main Redis client"
                    )
                )

            if self.pubsub_client and self.pubsub_client != self.redis_client:
                close_tasks.append(
                    self._close_client_with_timeout(
                        self.pubsub_client, "Pub/Sub client"
                    )
                )

            # Виконуємо закриття паралельно з тайм-аутом
            if close_tasks:
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*close_tasks, return_exceptions=True),
                        timeout=10.0,
                    )
                except asyncio.TimeoutError:
                    self.logger.warning(
                        "Redis clients close timeout - forcing shutdown"
                    )

            # Зупинка асинхронного оптимізатора
            if hasattr(self, "async_optimizer") and self.async_optimizer:
                try:
                    await self.async_optimizer.shutdown()
                    self.logger.info("Async optimizer shutdown")
                except Exception as e:
                    self.logger.warning(
                        "Error shutting down async optimizer", error=str(e)
                    )

            # Очищення локальних структур
            self.subscriptions.clear()
            self.message_cache.clear()
            self.pipeline_buffer.clear()
            self.pipeline_timers.clear()

            self.is_connected = False
            self.redis_client = None
            self.pubsub_client = None
            self.pubsub = None

            self.logger.info("Redis Manager shutdown complete")

        except Exception as e:
            self.logger.error("Error during Redis Manager shutdown", error=str(e))
            # Форсоване очищення при помилці
            self.is_connected = False
            self.redis_client = None
            self.pubsub_client = None
            self.pubsub = None

    async def _detect_redis_mode(self):
        """Визначення режиму роботи Redis"""
        try:
            # 1) Якщо задано REDISCLOUD_URL — завжди standalone (пріоритетно простий Redis)
            if getattr(self.settings, "redis_url", ""):
                self.redis_mode = "standalone"
                return

            # 2) Sentinel — лише якщо немає REDISCLOUD_URL, але явно налаштовано sentinel
            if getattr(self.settings, "redis_sentinel_urls", []):
                self.redis_mode = "sentinel"
                return

            # 3) Cluster — лише якщо немає REDISCLOUD_URL і sentinel, але налаштовано cluster
            if getattr(self.settings, "redis_cluster_nodes", []):
                self.redis_mode = "cluster"
                return

            # 4) Інакше Redis відключений
            self.redis_mode = "disabled"

        except Exception as e:
            self.logger.warning(
                "Failed to detect Redis mode, disabling Redis", error=str(e)
            )
            self.redis_mode = "disabled"

    async def _create_redis_clients(self):
        """Створення Redis клієнтів залежно від режиму"""
        try:
            if self.redis_mode == "disabled":
                # Вимкнений Redis — працюємо без клієнтів
                self.redis_client = None
                self.pubsub_client = None
                self.logger.info("Redis disabled (no configuration provided)")
                return

            if self.redis_mode == "sentinel":
                try:
                    await self._create_sentinel_clients()
                except Exception as e:
                    # У dev/testing надаємо безпечний fallback
                    if hasattr(self.settings, "is_development") and (
                        self.settings.is_development() or self.settings.is_testing()
                    ):
                        self.logger.warning(
                            "Sentinel setup failed in dev/testing, applying fallback",
                            error=str(e),
                        )
                        if getattr(self.settings, "redis_url", ""):
                            self.redis_mode = "standalone"
                            await self._create_standalone_clients()
                        else:
                            self.redis_mode = "disabled"
                            self.redis_client = None
                            self.pubsub_client = None
                            self.logger.info(
                                "Redis disabled due to missing fallback URL"
                            )
                    else:
                        raise
            elif self.redis_mode == "cluster":
                await self._create_cluster_clients()
            else:
                await self._create_standalone_clients()

            # Створення Pub/Sub об'єкта
            if self.pubsub_client:
                self.pubsub = self.pubsub_client.pubsub()

        except Exception as e:
            self.logger.error("Failed to create Redis clients", error=str(e))
            raise

    async def _create_standalone_clients(self):
        """Створення звичайних Redis клієнтів з покращеним управлінням пулом"""
        # Підготовка URL з TLS параметрами для хмарних провайдерів
        redis_url = self.settings.redis_url

        # Якщо доступний REDIS_TLS_URL або увімкнуто TLS — форсуємо rediss://
        try:
            force_tls = bool(getattr(self.settings, "redis_tls_enabled", False))
        except Exception:
            force_tls = False

        if redis_url and force_tls and redis_url.startswith("redis://"):
            redis_url = redis_url.replace("redis://", "rediss://", 1)

        # Покращені параметри з'єднання з пулом
        base_kwargs = {
            "retry_on_timeout": True,
            "retry_on_error": [ConnectionError, TimeoutError],
            "decode_responses": True,
            "socket_timeout": 30.0,  # Збільшено для хмарного Redis
            "socket_connect_timeout": 15.0,  # Збільшено для хмарного Redis
            "socket_keepalive": True,
            "socket_keepalive_options": {},
            "health_check_interval": 30,  # Регулярна перевірка здоров'я
        }

        # Додаткові SSL параметри для TLS з'єднань
        if redis_url.startswith("rediss://"):
            # Дозволяємо керувати перевіркою TLS через змінні середовища
            import os

            ssl_check_hostname = os.getenv(
                "REDIS_SSL_CHECK_HOSTNAME", "true"
            ).lower() in ("1", "true", "yes")
            ssl_cert_reqs_env = os.getenv(
                "REDIS_SSL_CERT_REQS",
                str(getattr(self.settings, "redis_ssl_cert_reqs", "required")),
            ).lower()
            # Map env to redis-py values
            ssl_cert_reqs_value = (
                None
                if ssl_cert_reqs_env in ("none", "false", "0")
                else ssl_cert_reqs_env
            )

            base_kwargs.update(
                {
                    "ssl_cert_reqs": ssl_cert_reqs_value,
                    "ssl_check_hostname": ssl_check_hostname,
                }
            )

        # Основний клієнт для команд з покращеним пулом
        main_kwargs = base_kwargs.copy()
        main_kwargs["max_connections"] = min(
            self.settings.redis_max_connections, 20
        )  # Збільшено з 5 до 20

        self.redis_client = redis.from_url(redis_url, **main_kwargs)

        # Окремий клієнт для Pub/Sub з меншим pool
        pubsub_kwargs = base_kwargs.copy()
        pubsub_kwargs["max_connections"] = 5  # Збільшено з 2 до 5 для Pub/Sub

        self.pubsub_client = redis.from_url(redis_url, **pubsub_kwargs)

        self.logger.info(
            "Redis clients created with connection pool",
            main_max_connections=main_kwargs["max_connections"],
            pubsub_max_connections=pubsub_kwargs["max_connections"],
        )

    async def _create_sentinel_clients(self):
        """Створення Redis клієнтів через Sentinel"""
        sentinel_urls = self.settings.redis_sentinel_urls
        if not sentinel_urls:
            raise ValueError("Sentinel URLs not configured")

        # Парсинг Sentinel URLs
        sentinels = []
        for url in sentinel_urls:
            host, port = url.split(":")
            sentinels.append((host, int(port)))

        # Створення Sentinel
        self.sentinel = Sentinel(sentinels, decode_responses=True)

        # Отримання master та slave клієнтів
        if self.sentinel:
            self.redis_client = self.sentinel.master_for(
                self.sentinel_service_name,
                max_connections=self.settings.redis_max_connections,
                retry_on_timeout=self.settings.redis_retry_on_timeout,
            )

            # Pub/Sub через master
            self.pubsub_client = self.sentinel.master_for(
                self.sentinel_service_name,
                max_connections=10,
                retry_on_timeout=self.settings.redis_retry_on_timeout,
            )

    async def _create_cluster_clients(self):
        """Створення Redis Cluster клієнтів"""
        cluster_nodes = self.settings.redis_cluster_nodes
        if not cluster_nodes:
            raise ValueError("Cluster nodes not configured")

        # Створення Cluster клієнта
        self.redis_client = RedisCluster(
            startup_nodes=[
                {"host": node.split(":")[0], "port": int(node.split(":")[1])}
                for node in cluster_nodes
            ],
            decode_responses=True,
            skip_full_coverage_check=True,
            max_connections=self.settings.redis_max_connections,
        )

        # Для Pub/Sub використовуємо той самий клієнт
        self.pubsub_client = self.redis_client

    async def _test_connection(self):
        """Тестування з'єднання з Redis"""
        try:
            # Тест основного клієнта
            if self.redis_client:
                await self.redis_client.ping()

            # Тест Pub/Sub клієнта
            if self.pubsub_client:
                await self.pubsub_client.ping()

            self.is_connected = True
            self.logger.info("✅ Redis connection successful")

        except Exception as e:
            from core.logging.utils import _mask_text_patterns

            self.logger.error(
                "❌ Redis connection test failed", error=_mask_text_patterns(str(e))
            )

            # Якщо ми в режимі sentinel і є REDISCLOUD_URL — пробуємо fallback на standalone
            if getattr(self, "redis_mode", "") == "sentinel" and getattr(
                self.settings, "redis_url", ""
            ):
                try:
                    self.logger.warning(
                        "Sentinel ping failed, falling back to standalone using REDISCLOUD_URL"
                    )
                    await self._close_connections()
                    self.redis_mode = "standalone"
                    await self._create_standalone_clients()
                    await self._test_connection()
                    return
                except Exception as fb_e:
                    self.logger.warning(
                        "Fallback to standalone failed, considering dev/test bypass",
                        error=_mask_text_patterns(str(fb_e)),
                    )

            # У dev/testing не валимо ініціалізацію — працюємо без Redis
            try:
                is_dev = hasattr(self.settings, "is_development") and (
                    self.settings.is_development() or self.settings.is_testing()
                )
            except Exception:
                is_dev = os.getenv("ENVIRONMENT", "development").lower() in (
                    "development",
                    "testing",
                )
            if is_dev:
                self.logger.warning(
                    "Development/testing mode: continuing without Redis"
                )
                self.redis_client = None
                self.pubsub_client = None
                self.is_connected = False
                return
            raise

    async def _close_connections(self):
        """Закриття всіх з'єднань"""
        try:
            if self.pubsub:
                await self.pubsub.close()

            if self.redis_client:
                await self.redis_client.close()

            if self.pubsub_client:
                await self.pubsub_client.close()

            self.is_connected = False

        except Exception as e:
            self.logger.error("Error closing Redis connections", error=str(e))

    async def publish(self, channel: str, message: Dict[str, Any]) -> bool:
        """Публікація повідомлення в канал з підтримкою pipeline"""
        try:
            if not self.is_connected or not self.redis_client:
                self.logger.error("Redis not connected", channel=channel)
                return False

            # Серіалізація повідомлення
            message_data = await self.async_optimizer.json_dumps(
                message, default=str, ensure_ascii=False
            )

            # Якщо pipeline увімкнено, додаємо до буфера
            if self.pipeline_enabled:
                self.pipeline_buffer.append(("publish", channel, message_data))

                # Flush якщо досягнуто розмір batch
                if len(self.pipeline_buffer) >= self.pipeline_batch_size:
                    await self._flush_pipeline()
            else:
                # Звичайна публікація
                await self.redis_client.publish(channel, message_data)
                self.logger.debug(
                    "Redis PUBLISH",
                    redis_log=True,
                    channel=channel,
                    size_bytes=(
                        len(message_data) if hasattr(message_data, "__len__") else None
                    ),
                )

            # Кешування для надійності
            self._cache_message(channel, message)

            self.messages_published += 1

            self.logger.debug(
                "Message published",
                channel=channel,
                message_id=message.get("message_id"),
            )

            return True

        except Exception as e:
            self.logger.error(
                "Failed to publish message", channel=channel, error=str(e)
            )
            self.connection_errors += 1
            self.last_error = str(e)
            return False

    async def subscribe(self, channels: List[str]) -> bool:
        """Підписка на канали"""
        try:
            if not self.is_connected or not self.pubsub:
                self.logger.error("Redis not connected for subscription")
                return False

            # Підписка на канали
            if self.pubsub:
                await self.pubsub.subscribe(*channels)

            # Оновлення списку підписок
            self.subscriptions.update(channels)

            # Запуск слухача, якщо ще не запущений
            if not self.listen_task or self.listen_task.done():
                self.listen_task = asyncio.create_task(self._listen_messages())

            self.logger.info(
                "Subscribed to channels",
                channels=channels,
                total_subscriptions=len(self.subscriptions),
            )

            return True

        except Exception as e:
            self.logger.error(
                "Failed to subscribe to channels", channels=channels, error=str(e)
            )
            self.connection_errors += 1
            self.last_error = str(e)
            return False

    async def unsubscribe(self, channels: List[str] = None) -> bool:
        """Відписка від каналів"""
        try:
            if not self.pubsub:
                return False

            # Перевірка чи з'єднання ще активне
            if not self.is_connected:
                # Якщо з'єднання втрачено, просто очищаємо локальний стан
                if channels:
                    self.subscriptions.difference_update(channels)
                else:
                    self.subscriptions.clear()
                self.logger.debug(
                    "Unsubscribed locally (connection lost)", channels=channels or "all"
                )
                return True

            if channels:
                await self.pubsub.unsubscribe(*channels)
                self.subscriptions.difference_update(channels)
            else:
                await self.pubsub.unsubscribe()
                self.subscriptions.clear()

            self.logger.info(
                "Unsubscribed from channels",
                channels=channels or "all",
                remaining_subscriptions=len(self.subscriptions),
            )

            return True

        except Exception as e:
            # Якщо помилка пов'язана з втратою з'єднання, не логуємо як error
            error_str = str(e).lower()
            if any(
                phrase in error_str
                for phrase in [
                    "connection lost",
                    "connection reset",
                    "broken pipe",
                    "connection refused",
                    "no connection",
                ]
            ):
                self.logger.debug(
                    "Unsubscribe failed due to connection loss",
                    channels=channels or "all",
                    error=str(e),
                )
                # Очищаємо локальний стан
                if channels:
                    self.subscriptions.difference_update(channels)
                else:
                    self.subscriptions.clear()
                return True
            else:
                self.logger.error(
                    "Failed to unsubscribe from channels",
                    channels=channels,
                    error=str(e),
                )
            return False

    async def _listen_messages(self):
        """Слухання повідомлень з Pub/Sub"""
        try:
            while self.is_running and self.pubsub:
                try:
                    message = await self.pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=1.0
                    )

                    if message and message["type"] == "message":
                        await self._handle_received_message(message)

                except asyncio.TimeoutError:
                    # Нормальний таймаут, продовжуємо слухати
                    continue

                except Exception as e:
                    self.logger.error("Error receiving message", error=str(e))
                    self.connection_errors += 1
                    self.last_error = str(e)

                    # Спроба відновлення з'єднання
                    await self._try_reconnect()
                    await asyncio.sleep(5)

        except asyncio.CancelledError:
            self.logger.info("Message listening cancelled")
        except Exception as e:
            self.logger.error("Fatal error in message listener", error=str(e))

    async def _handle_received_message(self, message):
        """Обробка отриманого повідомлення"""
        try:
            channel = message["channel"]
            data = message["data"]

            # Десеріалізація повідомлення
            try:
                message_data = json.loads(data)
            except json.JSONDecodeError as e:
                self.logger.error(
                    "Failed to decode message JSON", channel=channel, error=str(e)
                )
                return

            self.messages_received += 1

            # Виклик callback
            if self.on_message_received:
                await self.on_message_received(channel, message_data)

            self.logger.debug(
                "Message received and processed",
                channel=channel,
                message_id=message_data.get("message_id"),
            )

        except Exception as e:
            self.logger.error("Error handling received message", error=str(e))

    async def _try_reconnect(self):
        """Спроба відновлення з'єднання з retry логікою"""
        if self.is_connected:
            return

        max_retries = 5  # Збільшено для хмарного Redis
        retry_delay = 5  # Збільшено базову затримку

        for attempt in range(max_retries):
            try:
                self.logger.info(
                    "🔄 Attempting to reconnect to Upstash Redis",
                    attempt=attempt + 1,
                    max_retries=max_retries,
                )

                # Закриття старих з'єднань
                await self._close_connections()

                # Більша затримка перед спробою підключення для хмарного Redis
                await asyncio.sleep(2 + attempt)

                # Створення нових клієнтів
                await self._create_redis_clients()

                # Тест з'єднання з більшим timeout для Upstash
                await asyncio.wait_for(self._test_connection(), timeout=30.0)

                # Відновлення підписок якщо були
                if self.subscriptions and self.pubsub:
                    try:
                        await self.pubsub.subscribe(*list(self.subscriptions))
                        self.logger.info(
                            "✅ Upstash Redis subscriptions restored",
                            subscriptions=list(self.subscriptions),
                        )
                    except Exception as sub_e:
                        self.logger.warning(
                            "⚠️ Failed to restore Upstash Redis subscriptions",
                            error=str(sub_e),
                        )

                self.is_connected = True

                if self.on_connection_restored:
                    await self.on_connection_restored()

                self.logger.info(
                    "✅ Upstash Redis connection successfully restored",
                    attempt=attempt + 1,
                )
                return  # Успішне відновлення

            except asyncio.TimeoutError:
                self.logger.warning(
                    "⏰ Upstash Redis reconnection attempt timed out",
                    attempt=attempt + 1,
                )
            except Exception as e:
                error_str = str(e).lower()
                if "ssl" in error_str or "tls" in error_str:
                    self.logger.warning(
                        "🔒 Upstash Redis SSL/TLS reconnection error",
                        attempt=attempt + 1,
                        error=str(e),
                    )
                else:
                    self.logger.warning(
                        "⚠️ Upstash Redis reconnection attempt failed",
                        attempt=attempt + 1,
                        error=str(e),
                    )

            # Експоненціальна затримка перед наступною спробою (крім останньої)
            if attempt < max_retries - 1:
                delay = retry_delay * (2**attempt)
                self.logger.debug(
                    f"Waiting {delay}s before next Upstash Redis reconnection attempt"
                )
                await asyncio.sleep(delay)

        # Всі спроби невдалі
        self.logger.error("❌ Failed to reconnect to Upstash Redis after all attempts")
        self.is_connected = False

        if self.on_connection_lost:
            await self.on_connection_lost()

    async def _health_check_loop(self):
        """Перевірка здоров'я Redis з'єднання з автоматичним відновленням"""
        consecutive_failures = 0
        max_failures = 5  # Збільшено для хмарного Redis
        base_sleep_interval = 15  # Збільшено базовий інтервал для Upstash
        max_sleep_interval = 120  # Збільшено максимальний інтервал

        while self.is_running:
            try:
                if self.redis_client:
                    # Використовуємо ще більший timeout для Upstash Redis
                    await asyncio.wait_for(self.redis_client.ping(), timeout=20.0)

                    if not self.is_connected:
                        self.is_connected = True
                        consecutive_failures = 0
                        self.logger.info("✅ Upstash Redis connection restored")

                        if self.on_connection_restored:
                            await self.on_connection_restored()
                else:
                    self.is_connected = False

                # Більший інтервал для хмарного Redis
                sleep_interval = max(self.settings.redis_health_check_interval, 30)
                if consecutive_failures > 0:
                    sleep_interval = min(
                        base_sleep_interval * (2 ** min(consecutive_failures, 4)),
                        max_sleep_interval,
                    )

                await asyncio.sleep(sleep_interval)

            except asyncio.CancelledError:
                break
            except asyncio.TimeoutError:
                consecutive_failures += 1
                if self.is_connected:
                    self.is_connected = False
                    self.connection_errors += 1
                    self.last_error = "Upstash Redis ping timeout"

                    # Тільки логуємо warning для першої помилки
                    if consecutive_failures == 1:
                        self.logger.warning(
                            "⏰ Upstash Redis health check timeout - connection may be slow",
                            consecutive_failures=consecutive_failures,
                        )
                    elif consecutive_failures <= 3:
                        self.logger.debug(
                            "Upstash Redis still timing out",
                            consecutive_failures=consecutive_failures,
                        )

                    if self.on_connection_lost:
                        await self.on_connection_lost()

                # Спроба автоматичного відновлення після більшої кількості невдач
                if consecutive_failures >= max_failures:
                    self.logger.info(
                        "🔄 Attempting automatic Upstash Redis reconnection after multiple timeouts"
                    )
                    await self._try_reconnect()
                    consecutive_failures = (
                        0  # Скидаємо лічильник після спроби відновлення
                    )

                sleep_interval = min(
                    base_sleep_interval * (2 ** min(consecutive_failures, 4)),
                    max_sleep_interval,
                )
                await asyncio.sleep(sleep_interval)

            except Exception as e:
                consecutive_failures += 1
                if self.is_connected:
                    self.is_connected = False
                    self.connection_errors += 1
                    self.last_error = str(e)

                    # Зменшуємо рівень логування для зменшення шуму
                    # Особливо для Upstash Redis connection reset
                    error_str = str(e).lower()
                    if (
                        "connection reset by peer" in error_str
                        or "broken pipe" in error_str
                    ):
                        # Upstash Redis іноді скидує з'єднання для економії ресурсів
                        if consecutive_failures == 1:
                            self.logger.info(
                                "🔄 Upstash Redis connection reset (normal for cloud Redis)",
                                consecutive_failures=consecutive_failures,
                            )
                        # Не логуємо на warning/error рівні для цієї помилки
                    elif "ssl" in error_str or "tls" in error_str:
                        if consecutive_failures == 1:
                            self.logger.warning(
                                "🔒 Upstash Redis SSL/TLS error",
                                error=str(e),
                                consecutive_failures=consecutive_failures,
                            )
                    elif consecutive_failures <= 2:
                        self.logger.warning(
                            "⚠️ Upstash Redis health check failed",
                            error=str(e),
                            consecutive_failures=consecutive_failures,
                        )
                    else:
                        self.logger.debug(
                            "Upstash Redis still disconnected",
                            consecutive_failures=consecutive_failures,
                        )

                    if self.on_connection_lost:
                        await self.on_connection_lost()

                # Спроба автоматичного відновлення після кількох невдач
                if consecutive_failures >= max_failures:
                    self.logger.info(
                        "🔄 Attempting automatic Upstash Redis reconnection after multiple failures"
                    )
                    await self._try_reconnect()
                    consecutive_failures = (
                        0  # Скидаємо лічильник після спроби відновлення
                    )

                sleep_interval = min(
                    base_sleep_interval * (2 ** min(consecutive_failures, 4)),
                    max_sleep_interval,
                )
                await asyncio.sleep(sleep_interval)

    def _cache_message(self, channel: str, message: Dict[str, Any]):
        """Кешування повідомлення для надійності"""
        try:
            message_id = message.get("message_id", str(datetime.utcnow().timestamp()))

            # Додавання до кешу
            self.message_cache[message_id] = {
                "channel": channel,
                "message": message,
                "timestamp": datetime.utcnow(),
                "attempts": 0,
            }

            # Обмеження розміру кешу
            if len(self.message_cache) > self.max_cache_size:
                # Видалення найстарших повідомлень
                oldest_keys = sorted(
                    self.message_cache.keys(),
                    key=lambda k: self.message_cache[k]["timestamp"],
                )[:100]

                for key in oldest_keys:
                    del self.message_cache[key]

        except Exception as e:
            self.logger.error("Error caching message", error=str(e))

    async def get_channel_subscribers(self, channel: str) -> int:
        """Отримання кількості підписників каналу"""
        try:
            if not self.redis_client:
                return 0

            # Використання команди PUBSUB NUMSUB
            result = await self.redis_client.execute_command(
                "PUBSUB", "NUMSUB", channel
            )

            # Результат у форматі [channel, count]
            return result[1] if len(result) > 1 else 0

        except Exception as e:
            self.logger.error(
                "Failed to get channel subscribers", channel=channel, error=str(e)
            )
            return 0

    async def get_active_channels(self) -> List[str]:
        """Отримання списку активних каналів"""
        try:
            if not self.redis_client:
                return []

            # Використання команди PUBSUB CHANNELS
            channels = await self.redis_client.execute_command("PUBSUB", "CHANNELS")
            return channels or []

        except Exception as e:
            self.logger.error("Failed to get active channels", error=str(e))
            return []

    async def set_key(self, key: str, value: Any, expire: int = None) -> bool:
        """Встановлення значення ключа з TTL"""
        try:
            if not self.redis_client:
                return False

            # Серіалізація значення
            if isinstance(value, (dict, list)):
                value = await self.async_optimizer.json_dumps(
                    value, default=str, ensure_ascii=False
                )

            # Використання дефолтного TTL якщо не вказано
            if expire is None:
                expire = self.default_ttl
            else:
                expire = int(expire)

            # Встановлення значення з TTL
            await self.redis_client.set(key, value, ex=expire)
            self.logger.debug(
                "Redis SET",
                redis_log=True,
                key=key,
                has_ttl=True,
                ttl=expire,
            )

            return True

        except Exception as e:
            error_str = str(e).lower()
            self.logger.error("Failed to set key", key=key, error=str(e))

            # При помилці "Too many connections" спробуємо переконнектитися
            if "too many connections" in error_str or "connection" in error_str:
                self.logger.warning(
                    "Redis connection issue detected, attempting reconnect"
                )
                await self._try_reconnect()

            return False

    async def get_key(self, key: str) -> Optional[Any]:
        """Отримання значення ключа"""
        try:
            if not self.redis_client:
                return None

            value = await self.redis_client.get(key)
            self.logger.debug("Redis GET", redis_log=True, key=key, hit=bool(value))

            if value is None:
                return None

            # Спроба десеріалізації JSON
            try:
                return await self.async_optimizer.json_loads(value)
            except json.JSONDecodeError:
                return value

        except Exception as e:
            error_str = str(e).lower()
            self.logger.error("Failed to get key", key=key, error=str(e))

            # При помилці "Too many connections" спробуємо переконнектитися
            if "too many connections" in error_str or "connection" in error_str:
                self.logger.warning(
                    "Redis connection issue detected, attempting reconnect"
                )
                await self._try_reconnect()

            return None

    async def delete_key(self, key: str) -> bool:
        """Видалення ключа"""
        try:
            if not self.redis_client:
                return False

            result = await self.redis_client.delete(key)
            self.logger.debug(
                "Redis DEL", redis_log=True, key=key, deleted=bool(result)
            )
            return result > 0

        except Exception as e:
            self.logger.error("Failed to delete key", key=key, error=str(e))
            return False

    async def is_healthy(self) -> bool:
        """Перевірка здоров'я Redis"""
        try:
            if not self.redis_client:
                return False

            await self.redis_client.ping()
            return True

        except Exception:
            return False

    def get_stats(self) -> Dict[str, Any]:
        """Отримання статистики Redis менеджера"""
        # Маскуємо redis_url, щоб уникнути витоку креденшалів у логах/UI
        safe_url = None
        try:
            full = self.settings.redis_url or ""
            if "@" in full:
                safe_url = (
                    full.split("@")[0].split("://")[0] + "://***@" + full.split("@")[1]
                )
            else:
                safe_url = full
        except Exception:
            safe_url = "<hidden>"
        return {
            "is_connected": self.is_connected,
            "is_running": self.is_running,
            "subscriptions": list(self.subscriptions),
            "subscription_count": len(self.subscriptions),
            "messages_published": self.messages_published,
            "messages_received": self.messages_received,
            "connection_errors": self.connection_errors,
            "last_error": self.last_error,
            "cached_messages": len(self.message_cache),
            "redis_url": safe_url,
            "max_connections": self.settings.redis_max_connections,
        }

    @asynccontextmanager
    async def transaction(self):
        """Контекстний менеджер для Redis транзакцій"""
        if not self.redis_client:
            raise RuntimeError("Redis not connected")

        pipe = self.redis_client.pipeline()
        try:
            yield pipe
            await pipe.execute()
        except Exception as e:
            self.logger.error("Redis transaction failed", error=str(e))
            raise
        finally:
            await pipe.reset()

    # Convenience methods for common channels
    async def publish_task(self, task_data: Dict[str, Any]) -> bool:
        """Публікація повідомлення про завдання"""
        return await self.publish(self.settings.redis_task_channel, task_data)

    async def publish_result(self, result_data: Dict[str, Any]) -> bool:
        """Публікація результату завдання"""
        return await self.publish(self.settings.redis_result_channel, result_data)

    async def publish_broadcast(self, broadcast_data: Dict[str, Any]) -> bool:
        """Публікація широкомовного повідомлення"""
        return await self.publish(self.settings.redis_broadcast_channel, broadcast_data)

    async def subscribe_to_tasks(self) -> bool:
        """Підписка на канал завдань"""
        return await self.subscribe([self.settings.redis_task_channel])

    async def subscribe_to_results(self) -> bool:
        """Підписка на канал результатів"""
        return await self.subscribe([self.settings.redis_result_channel])

    async def subscribe_to_broadcasts(self) -> bool:
        """Підписка на канал широкомовних повідомлень"""
        return await self.subscribe([self.settings.redis_broadcast_channel])

    async def subscribe_to_all(self) -> bool:
        """Підписка на всі основні канали"""
        channels = [
            self.settings.redis_task_channel,
            self.settings.redis_result_channel,
            self.settings.redis_broadcast_channel,
            self.settings.redis_health_channel,
        ]
        return await self.subscribe(channels)

    async def _flush_pipeline(self):
        """Виконання накопичених pipeline операцій"""
        if not self.pipeline_buffer or not self.redis_client:
            return

        try:
            pipe = self.redis_client.pipeline()

            for operation, *args in self.pipeline_buffer:
                if operation == "publish":
                    pipe.publish(*args)
                elif operation == "set":
                    pipe.set(*args)

            results = await pipe.execute()

            self.logger.debug(
                "Pipeline flushed",
                operations=len(self.pipeline_buffer),
                results=len(results),
            )

            self.pipeline_buffer.clear()

        except Exception as e:
            self.logger.error("Failed to flush pipeline", error=str(e))
            # Спроба виконати операції окремо
            for operation, *args in self.pipeline_buffer:
                try:
                    if operation == "publish":
                        await self.redis_client.publish(*args)
                    elif operation == "set":
                        await self.redis_client.set(*args)
                except Exception as inner_e:
                    self.logger.error(
                        "Failed to execute pipeline operation",
                        operation=operation,
                        error=str(inner_e),
                    )
            self.pipeline_buffer.clear()

    async def _pipeline_flush_loop(self):
        """Періодичне виконання pipeline операцій"""
        while self.is_running:
            try:
                await asyncio.sleep(self.pipeline_flush_interval)

                if self.pipeline_buffer:
                    await self._flush_pipeline()

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in pipeline flush loop", error=str(e))

    async def get_memory_usage(self) -> Dict[str, Any]:
        """Отримання інформації про використання пам'яті Redis"""
        try:
            if not self.redis_client:
                return {}

            info = await self.redis_client.info("memory")

            return {
                "used_memory": info.get("used_memory_human", "0"),
                "used_memory_peak": info.get("used_memory_peak_human", "0"),
                "used_memory_rss": info.get("used_memory_rss_human", "0"),
                "mem_fragmentation_ratio": info.get("mem_fragmentation_ratio", 0),
                "evicted_keys": info.get("evicted_keys", 0),
            }

        except Exception as e:
            self.logger.error("Failed to get memory usage", error=str(e))
            return {}

    async def cleanup_old_keys(self, pattern: str = "*", days: int = 7):
        """Видалення старих ключів за паттерном"""
        try:
            if not self.redis_client:
                return 0

            deleted = 0
            async for key in self.redis_client.scan_iter(match=pattern):
                ttl = await self.redis_client.ttl(key)
                # Якщо ключ без TTL або TTL більше ніж days
                if ttl == -1 or ttl > days * 86400:
                    await self.redis_client.expire(key, days * 86400)
                    deleted += 1

            self.logger.info("Cleaned up old keys", pattern=pattern, deleted=deleted)
            return deleted

        except Exception as e:
            self.logger.error("Failed to cleanup old keys", error=str(e))
            return 0

    async def _close_client_with_timeout(self, client, client_name: str):
        """Закриття Redis клієнта з тайм-аутом"""
        try:
            self.logger.info(f"Closing {client_name}")

            # Спробуємо отримати статистику пулу перед закриттям
            try:
                if hasattr(client, "connection_pool"):
                    pool = client.connection_pool
                    if hasattr(pool, "_created_connections"):
                        created = pool._created_connections
                        available = (
                            len(pool._available_connections)
                            if hasattr(pool, "_available_connections")
                            else 0
                        )
                        self.logger.info(
                            f"{client_name} pool stats before close",
                            created_connections=created,
                            available_connections=available,
                        )
            except Exception:
                pass  # Ігноруємо помилки статистики

            await client.close()

            # Додатковий час для завершення всіх з'єднань
            await asyncio.sleep(0.5)

            self.logger.info(f"{client_name} closed successfully")

        except Exception as e:
            self.logger.warning(f"Error closing {client_name}", error=str(e))
