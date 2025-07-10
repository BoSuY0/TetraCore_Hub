"""
TetraCore StreamHub Redis Manager

Менеджер для роботи з Redis Pub/Sub системою.
Забезпечує підключення, публікацію та підписку на канали,
а також управління з'єднаннями та моніторинг здоров'я.
"""

import asyncio
import json
from datetime import datetime
from typing import Dict, List, Optional, Callable, Any, Set, Union
from contextlib import asynccontextmanager
import structlog

import redis.asyncio as redis
from redis.asyncio import Redis, RedisCluster, Sentinel
from redis.exceptions import RedisError, ConnectionError, TimeoutError

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
        self.sentinel_service_name: str = getattr(settings, 'redis_sentinel_service_name', "tetracore-master")

        # Режим роботи Redis
        self.redis_mode: str = "standalone"  # standalone, sentinel, cluster

        # Pipeline для batch операцій
        self.pipeline_enabled: bool = getattr(settings, 'redis_pipeline_enabled', True)
        self.pipeline_batch_size: int = getattr(settings, 'redis_pipeline_batch_size', 100)
        self.pipeline_flush_interval: float = getattr(settings, 'redis_pipeline_flush_interval', 0.1)  # секунди
        self.pipeline_buffer: List[tuple] = []
        self.pipeline_task: Optional[asyncio.Task] = None

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
        self.default_ttl: int = getattr(settings, 'redis_default_ttl', 86400)

        # Асинхронний оптимізатор
        self.async_optimizer = AsyncOptimizer(max_workers=5)

    async def initialize(self):
        """Ініціалізація Redis менеджера"""
        try:
            self.logger.info("Initializing Redis Manager",
                           redis_url=self.settings.redis_url,
                           mode=self.redis_mode)

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

            self.logger.info("Redis Manager initialized successfully",
                           mode=self.redis_mode)

        except Exception as e:
            self.logger.error("Failed to initialize Redis Manager", error=str(e))
            self.last_error = str(e)
            raise

    async def shutdown(self):
        """Зупинка Redis менеджера"""
        self.logger.info("Shutting down Redis Manager")

        self.is_running = False

        # Зупинка задач
        for task in [self.listen_task, self.health_check_task, self.pipeline_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Flush pipeline buffer
        if self.pipeline_buffer:
            await self._flush_pipeline()

        # Відписка від всіх каналів
        if self.pubsub:
            try:
                await self.pubsub.unsubscribe()
                await self.pubsub.reset()
            except Exception as e:
                self.logger.error("Error unsubscribing from channels", error=str(e))

        # Закриття з'єднань
        await self._close_connections()

        # Зупинка асинхронного оптимізатора
        if self.async_optimizer:
            await self.async_optimizer.shutdown()

        self.logger.info("Redis Manager shutdown complete")

    async def _detect_redis_mode(self):
        """Визначення режиму роботи Redis"""
        try:
            # Перевірка наявності валідної конфігурації Sentinel
            if (self.settings.redis_sentinel_urls and 
                len(self.settings.redis_sentinel_urls) > 0 and
                not any('host' in url and 'port' in url for url in self.settings.redis_sentinel_urls)):
                self.redis_mode = "sentinel"
                return

            # Перевірка наявності валідної конфігурації Cluster
            if (self.settings.redis_cluster_nodes and 
                len(self.settings.redis_cluster_nodes) > 0 and
                not any('host' in node and 'port' in node for node in self.settings.redis_cluster_nodes)):
                self.redis_mode = "cluster"
                return

            # За замовчуванням - standalone
            self.redis_mode = "standalone"

        except Exception as e:
            self.logger.warning("Failed to detect Redis mode, using standalone", error=str(e))
            self.redis_mode = "standalone"

    async def _create_redis_clients(self):
        """Створення Redis клієнтів залежно від режиму"""
        try:
            if self.redis_mode == "sentinel":
                await self._create_sentinel_clients()
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
        """Створення звичайних Redis клієнтів"""
        # Підготовка URL з TLS параметрами для Upstash
        redis_url = self.settings.redis_url
        
        # Додавання SSL параметрів до URL якщо потрібно
        if getattr(self.settings, 'redis_tls_enabled', False):
            # Для Upstash змінюємо протокол на rediss:// для TLS
            if redis_url.startswith('redis://'):
                redis_url = redis_url.replace('redis://', 'rediss://')
        
        # Базові параметри з'єднання
        connection_kwargs = {
            'max_connections': self.settings.redis_max_connections,
            'retry_on_timeout': self.settings.redis_retry_on_timeout,
            'decode_responses': True
        }
        
        # Основний клієнт для команд
        self.redis_client = redis.from_url(
            redis_url,
            **connection_kwargs
        )

        # Окремий клієнт для Pub/Sub
        pubsub_kwargs = connection_kwargs.copy()
        pubsub_kwargs['max_connections'] = 10
        
        self.pubsub_client = redis.from_url(
            redis_url,
            **pubsub_kwargs
        )

    async def _create_sentinel_clients(self):
        """Створення Redis клієнтів через Sentinel"""
        sentinel_urls = self.settings.redis_sentinel_urls
        if not sentinel_urls:
            raise ValueError("Sentinel URLs not configured")

        # Парсинг Sentinel URLs
        sentinels = []
        for url in sentinel_urls:
            host, port = url.split(':')
            sentinels.append((host, int(port)))

        # Створення Sentinel
        self.sentinel = Sentinel(sentinels, decode_responses=True)

        # Отримання master та slave клієнтів
        if self.sentinel:
            self.redis_client = self.sentinel.master_for(
                self.sentinel_service_name,
                max_connections=self.settings.redis_max_connections,
                retry_on_timeout=self.settings.redis_retry_on_timeout
            )

            # Pub/Sub через master
            self.pubsub_client = self.sentinel.master_for(
                self.sentinel_service_name,
                max_connections=10,
                retry_on_timeout=self.settings.redis_retry_on_timeout
            )

    async def _create_cluster_clients(self):
        """Створення Redis Cluster клієнтів"""
        cluster_nodes = self.settings.redis_cluster_nodes
        if not cluster_nodes:
            raise ValueError("Cluster nodes not configured")

        # Створення Cluster клієнта
        self.redis_client = RedisCluster(
            startup_nodes=[{"host": node.split(':')[0], "port": int(node.split(':')[1])}
                          for node in cluster_nodes],
            decode_responses=True,
            skip_full_coverage_check=True,
            max_connections=self.settings.redis_max_connections
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

            self.logger.info("✅ Redis connection successful", 
                           redis_host="merry-mammal-56796.upstash.io",
                           tls_enabled=getattr(self.settings, 'redis_tls_enabled', False))

        except Exception as e:
            self.logger.error("❌ Redis connection test failed", error=str(e))
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
            message_data = await self.async_optimizer.json_dumps(message, default=str, ensure_ascii=False)

            # Якщо pipeline увімкнено, додаємо до буфера
            if self.pipeline_enabled:
                self.pipeline_buffer.append(('publish', channel, message_data))

                # Flush якщо досягнуто розмір batch
                if len(self.pipeline_buffer) >= self.pipeline_batch_size:
                    await self._flush_pipeline()
            else:
                # Звичайна публікація
                await self.redis_client.publish(channel, message_data)

            # Кешування для надійності
            self._cache_message(channel, message)

            self.messages_published += 1

            self.logger.debug("Message published",
                            channel=channel,
                            message_id=message.get('message_id'))

            return True

        except Exception as e:
            self.logger.error("Failed to publish message",
                            channel=channel,
                            error=str(e))
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

            self.logger.info("Subscribed to channels",
                           channels=channels,
                           total_subscriptions=len(self.subscriptions))

            return True

        except Exception as e:
            self.logger.error("Failed to subscribe to channels",
                            channels=channels,
                            error=str(e))
            self.connection_errors += 1
            self.last_error = str(e)
            return False

    async def unsubscribe(self, channels: List[str] = None) -> bool:
        """Відписка від каналів"""
        try:
            if not self.pubsub:
                return False

            if channels:
                await self.pubsub.unsubscribe(*channels)
                self.subscriptions.difference_update(channels)
            else:
                await self.pubsub.unsubscribe()
                self.subscriptions.clear()

            self.logger.info("Unsubscribed from channels",
                           channels=channels or "all",
                           remaining_subscriptions=len(self.subscriptions))

            return True

        except Exception as e:
            self.logger.error("Failed to unsubscribe from channels",
                            channels=channels,
                            error=str(e))
            return False

    async def _listen_messages(self):
        """Слухання повідомлень з Pub/Sub"""
        try:
            while self.is_running and self.pubsub:
                try:
                    message = await self.pubsub.get_message(
                        ignore_subscribe_messages=True,
                        timeout=1.0
                    )

                    if message and message['type'] == 'message':
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
            channel = message['channel']
            data = message['data']

            # Десеріалізація повідомлення
            try:
                message_data = json.loads(data)
            except json.JSONDecodeError as e:
                self.logger.error("Failed to decode message JSON",
                                channel=channel,
                                error=str(e))
                return

            self.messages_received += 1

            # Виклик callback
            if self.on_message_received:
                await self.on_message_received(channel, message_data)

            self.logger.debug("Message received and processed",
                            channel=channel,
                            message_id=message_data.get('message_id'))

        except Exception as e:
            self.logger.error("Error handling received message", error=str(e))

    async def _try_reconnect(self):
        """Спроба відновлення з'єднання"""
        try:
            if self.is_connected:
                return

            self.logger.info("Attempting to reconnect to Redis")

            # Відновлення з'єднання
            await self._close_connections()
            await self._create_redis_clients()
            await self._test_connection()

            # Відновлення підписок
            if self.subscriptions and self.pubsub:
                await self.pubsub.subscribe(*list(self.subscriptions))

            self.is_connected = True

            if self.on_connection_restored:
                await self.on_connection_restored()

            self.logger.info("Redis connection restored")

        except Exception as e:
            self.logger.error("Failed to reconnect to Redis", error=str(e))
            self.is_connected = False

            if self.on_connection_lost:
                await self.on_connection_lost()

    async def _health_check_loop(self):
        """Перевірка здоров'я Redis з'єднання"""
        while self.is_running:
            try:
                if self.redis_client:
                    await self.redis_client.ping()

                    if not self.is_connected:
                        self.is_connected = True
                        self.logger.info("Redis connection restored")

                        if self.on_connection_restored:
                            await self.on_connection_restored()
                else:
                    self.is_connected = False

                await asyncio.sleep(self.settings.redis_health_check_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                if self.is_connected:
                    self.is_connected = False
                    self.connection_errors += 1
                    self.last_error = str(e)

                    self.logger.error("Redis health check failed", error=str(e))

                    if self.on_connection_lost:
                        await self.on_connection_lost()

                await asyncio.sleep(5)  # Коротша затримка при помилках

    def _cache_message(self, channel: str, message: Dict[str, Any]):
        """Кешування повідомлення для надійності"""
        try:
            message_id = message.get('message_id', str(datetime.utcnow().timestamp()))

            # Додавання до кешу
            self.message_cache[message_id] = {
                'channel': channel,
                'message': message,
                'timestamp': datetime.utcnow(),
                'attempts': 0
            }

            # Обмеження розміру кешу
            if len(self.message_cache) > self.max_cache_size:
                # Видалення найстарших повідомлень
                oldest_keys = sorted(
                    self.message_cache.keys(),
                    key=lambda k: self.message_cache[k]['timestamp']
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
            result = await self.redis_client.execute_command('PUBSUB', 'NUMSUB', channel)

            # Результат у форматі [channel, count]
            return result[1] if len(result) > 1 else 0

        except Exception as e:
            self.logger.error("Failed to get channel subscribers",
                            channel=channel,
                            error=str(e))
            return 0

    async def get_active_channels(self) -> List[str]:
        """Отримання списку активних каналів"""
        try:
            if not self.redis_client:
                return []

            # Використання команди PUBSUB CHANNELS
            channels = await self.redis_client.execute_command('PUBSUB', 'CHANNELS')
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
                value = await self.async_optimizer.json_dumps(value, default=str, ensure_ascii=False)

            # Використання дефолтного TTL якщо не вказано
            if expire is None:
                expire = self.default_ttl
            else:
                expire = int(expire)

            # Встановлення значення з TTL
            await self.redis_client.set(key, value, ex=expire)

            return True

        except Exception as e:
            self.logger.error("Failed to set key",
                            key=key,
                            error=str(e))
            return False

    async def get_key(self, key: str) -> Optional[Any]:
        """Отримання значення ключа"""
        try:
            if not self.redis_client:
                return None

            value = await self.redis_client.get(key)

            if value is None:
                return None

            # Спроба десеріалізації JSON
            try:
                return await self.async_optimizer.json_loads(value)
            except json.JSONDecodeError:
                return value

        except Exception as e:
            self.logger.error("Failed to get key",
                            key=key,
                            error=str(e))
            return None

    async def delete_key(self, key: str) -> bool:
        """Видалення ключа"""
        try:
            if not self.redis_client:
                return False

            result = await self.redis_client.delete(key)
            return result > 0

        except Exception as e:
            self.logger.error("Failed to delete key",
                            key=key,
                            error=str(e))
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
            "redis_url": self.settings.redis_url,
            "max_connections": self.settings.redis_max_connections
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
            self.settings.redis_health_channel
        ]
        return await self.subscribe(channels)

    async def _flush_pipeline(self):
        """Виконання накопичених pipeline операцій"""
        if not self.pipeline_buffer or not self.redis_client:
            return

        try:
            pipe = self.redis_client.pipeline()

            for operation, *args in self.pipeline_buffer:
                if operation == 'publish':
                    pipe.publish(*args)
                elif operation == 'set':
                    pipe.set(*args)

            results = await pipe.execute()

            self.logger.debug("Pipeline flushed",
                            operations=len(self.pipeline_buffer),
                            results=len(results))

            self.pipeline_buffer.clear()

        except Exception as e:
            self.logger.error("Failed to flush pipeline", error=str(e))
            # Спроба виконати операції окремо
            for operation, *args in self.pipeline_buffer:
                try:
                    if operation == 'publish':
                        await self.redis_client.publish(*args)
                    elif operation == 'set':
                        await self.redis_client.set(*args)
                except Exception as inner_e:
                    self.logger.error("Failed to execute pipeline operation",
                                    operation=operation,
                                    error=str(inner_e))
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
                "evicted_keys": info.get("evicted_keys", 0)
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

            self.logger.info("Cleaned up old keys",
                           pattern=pattern,
                           deleted=deleted)
            return deleted

        except Exception as e:
            self.logger.error("Failed to cleanup old keys", error=str(e))
            return 0
