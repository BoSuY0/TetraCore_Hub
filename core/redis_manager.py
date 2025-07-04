"""
TetraCore StreamHub Redis Manager

Менеджер для роботи з Redis Pub/Sub системою.
Забезпечує підключення, публікацію та підписку на канали,
а також управління з'єднаннями та моніторинг здоров'я.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Callable, Any, Set
from contextlib import asynccontextmanager
import structlog

import redis.asyncio as redis
from redis.asyncio import Redis
from redis.exceptions import RedisError, ConnectionError, TimeoutError

from config import Settings


class RedisManager:
    """Менеджер Redis для StreamHub"""

    def __init__(self, settings: Settings):
        """Ініціалізація Redis менеджера"""
        self.settings = settings
        self.logger = structlog.get_logger(__name__)

        # Redis з'єднання
        self.redis_client: Optional[Redis] = None
        self.pubsub_client: Optional[Redis] = None

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

    async def initialize(self):
        """Ініціалізація Redis менеджера"""
        try:
            self.logger.info("Initializing Redis Manager",
                           redis_url=self.settings.redis_url)

            # Створення Redis клієнтів
            await self._create_redis_clients()

            # Перевірка з'єднання
            await self._test_connection()

            # Запуск моніторингу
            self.health_check_task = asyncio.create_task(self._health_check_loop())

            self.is_running = True
            self.is_connected = True

            self.logger.info("Redis Manager initialized successfully")

        except Exception as e:
            self.logger.error("Failed to initialize Redis Manager", error=str(e))
            self.last_error = str(e)
            raise

    async def shutdown(self):
        """Зупинка Redis менеджера"""
        self.logger.info("Shutting down Redis Manager")

        self.is_running = False

        # Зупинка задач
        for task in [self.listen_task, self.health_check_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Відписка від всіх каналів
        if self.pubsub:
            try:
                await self.pubsub.unsubscribe()
                await self.pubsub.reset()
            except Exception as e:
                self.logger.error("Error unsubscribing from channels", error=str(e))

        # Закриття з'єднань
        await self._close_connections()

        self.logger.info("Redis Manager shutdown complete")

    async def _create_redis_clients(self):
        """Створення Redis клієнтів"""
        try:
            # Основний клієнт для команд
            self.redis_client = redis.from_url(
                self.settings.redis_url,
                max_connections=self.settings.redis_max_connections,
                retry_on_timeout=self.settings.redis_retry_on_timeout,
                decode_responses=True
            )

            # Окремий клієнт для Pub/Sub
            self.pubsub_client = redis.from_url(
                self.settings.redis_url,
                max_connections=10,
                retry_on_timeout=self.settings.redis_retry_on_timeout,
                decode_responses=True
            )

            # Створення Pub/Sub об'єкта
            self.pubsub = self.pubsub_client.pubsub()

        except Exception as e:
            self.logger.error("Failed to create Redis clients", error=str(e))
            raise

    async def _test_connection(self):
        """Тестування з'єднання з Redis"""
        try:
            # Тест основного клієнта
            await self.redis_client.ping()

            # Тест Pub/Sub клієнта
            await self.pubsub_client.ping()

            self.logger.info("Redis connection test successful")

        except Exception as e:
            self.logger.error("Redis connection test failed", error=str(e))
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
        """Публікація повідомлення в канал"""
        try:
            if not self.is_connected or not self.redis_client:
                self.logger.error("Redis not connected", channel=channel)
                return False

            # Серіалізація повідомлення
            message_data = json.dumps(message, default=str, ensure_ascii=False)

            # Публікація
            result = await self.redis_client.publish(channel, message_data)

            # Кешування для надійності
            self._cache_message(channel, message)

            self.messages_published += 1

            self.logger.debug("Message published",
                            channel=channel,
                            subscribers=result,
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
            if self.subscriptions:
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
        """Встановлення значення ключа"""
        try:
            if not self.redis_client:
                return False

            # Серіалізація значення
            if isinstance(value, (dict, list)):
                value = json.dumps(value, default=str, ensure_ascii=False)

            # Встановлення значення
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
                return json.loads(value)
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
