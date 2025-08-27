"""
Redis Optimization Module for TetraCore Hub
Redis clustering, pipeline operations, та оптимізація pub/sub
"""

import asyncio
import time
import json
from typing import Dict, List, Optional, Any, Set, Tuple, Callable, Union
from dataclasses import dataclass, field
from collections import defaultdict, deque
from enum import Enum
import zlib

from redis import asyncio as aioredis
from redis.asyncio.cluster import RedisCluster
from redis.asyncio.sentinel import Sentinel
from redis.exceptions import ConnectionError, TimeoutError
import structlog

logger = structlog.get_logger()

# Константи для Redis
DEFAULT_POOL_SIZE = 10
MAX_POOL_SIZE = 50
DEFAULT_TIMEOUT = 5.0
DEFAULT_TTL = 3600  # 1 година
MAX_PIPELINE_SIZE = 1000
PIPELINE_TIMEOUT = 0.1  # 100ms для батчінгу
RETRY_ATTEMPTS = 3
RETRY_DELAY = 0.1
CACHE_PREFIX = "tc:cache:"
LOCK_PREFIX = "tc:lock:"
PUBSUB_PREFIX = "tc:pubsub:"

# Константи для оптимізації
COMPRESSION_THRESHOLD = 1024  # 1KB
LRU_CACHE_SIZE = 10000
BLOOM_FILTER_SIZE = 1000000
BLOOM_FILTER_ERROR_RATE = 0.01


class RedisMode(Enum):
    """Режими роботи Redis"""

    SINGLE = "single"
    CLUSTER = "cluster"
    SENTINEL = "sentinel"


class CacheStrategy(Enum):
    """Стратегії кешування"""

    LRU = "lru"  # Least Recently Used
    LFU = "lfu"  # Least Frequently Used
    TTL = "ttl"  # Time To Live based
    ADAPTIVE = "adaptive"  # Адаптивна стратегія


@dataclass
class CacheEntry:
    """Запис в кеші"""

    key: str
    value: Any
    size: int
    hits: int = 0
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    ttl: Optional[int] = None
    compressed: bool = False

    @property
    def age(self) -> float:
        """Вік запису в секундах"""
        return time.time() - self.created_at

    @property
    def idle_time(self) -> float:
        """Час з останнього доступу"""
        return time.time() - self.last_accessed

    def access(self):
        """Реєстрація доступу"""
        self.hits += 1
        self.last_accessed = time.time()


class RedisOptimizer:
    """Оптимізатор для Redis операцій"""

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        mode: RedisMode = RedisMode.SINGLE,
        pool_size: int = DEFAULT_POOL_SIZE,
        enable_compression: bool = True,
        enable_pipeline: bool = True,
        cache_strategy: CacheStrategy = CacheStrategy.ADAPTIVE,
        cluster_nodes: Optional[List[str]] = None,
        sentinel_hosts: Optional[List[Tuple[str, int]]] = None,
        sentinel_service: str = "mymaster",
    ):
        self.redis_url = redis_url
        self.mode = mode
        self.pool_size = min(pool_size, MAX_POOL_SIZE)
        self.enable_compression = enable_compression
        self.enable_pipeline = enable_pipeline
        self.cache_strategy = cache_strategy

        # Redis clients
        self.redis_client: Optional[Union[aioredis.Redis, RedisCluster]] = None
        self.pubsub_client: Optional[aioredis.Redis] = None

        # Cluster/Sentinel config
        self.cluster_nodes = cluster_nodes or []
        self.sentinel_hosts = sentinel_hosts or []
        self.sentinel_service = sentinel_service

        # Pipeline батчінг
        self.pipeline_queue: Dict[str, List[Tuple[str, Callable, tuple, dict]]] = (
            defaultdict(list)
        )
        self.pipeline_timers: Dict[str, asyncio.Task] = {}

        # Локальний кеш
        self.local_cache: Dict[str, CacheEntry] = {}
        self.cache_order: deque[str] = deque(maxlen=LRU_CACHE_SIZE)

        # Метрики
        self.metrics = {
            "operations": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "pipeline_batches": 0,
            "compressed_values": 0,
            "bytes_saved": 0,
            "errors": 0,
            "retries": 0,
        }

        # Pub/Sub оптимізації
        self.subscriptions: Dict[str, Set[Callable]] = defaultdict(set)
        self.subscription_patterns: Dict[str, Set[Callable]] = defaultdict(set)

        # Distributed locks
        self.locks: Dict[str, asyncio.Lock] = {}

        logger.info(
            "Redis optimizer initialized",
            mode=mode.value,
            pool_size=pool_size,
            compression=enable_compression,
        )

    async def connect(self):
        """Підключення до Redis"""
        try:
            if self.mode == RedisMode.CLUSTER:
                await self._connect_cluster()
            elif self.mode == RedisMode.SENTINEL:
                await self._connect_sentinel()
            else:
                await self._connect_single()

            # Окремий клієнт для Pub/Sub
            self.pubsub_client = await self._create_pubsub_client()

            logger.info("Redis connected successfully", mode=self.mode.value)

        except Exception as e:
            logger.error("Redis connection failed", error=str(e))
            raise

    async def _connect_single(self):
        """Підключення до single Redis instance"""
        self.redis_client = await aioredis.from_url(
            self.redis_url,
            encoding="utf-8",
            decode_responses=False,  # Для підтримки бінарних даних
            max_connections=self.pool_size,
            socket_timeout=DEFAULT_TIMEOUT,
            socket_connect_timeout=DEFAULT_TIMEOUT,
            retry_on_timeout=True,
            retry_on_error=[ConnectionError, TimeoutError],
        )

    async def _connect_cluster(self):
        """Підключення до Redis Cluster"""
        if not self.cluster_nodes:
            raise ValueError("Cluster nodes not provided")

        startup_nodes = [
            {"host": node.split(":")[0], "port": int(node.split(":")[1])}
            for node in self.cluster_nodes
        ]

        self.redis_client = await RedisCluster(
            startup_nodes=startup_nodes,
            decode_responses=False,
            skip_full_coverage_check=True,
            max_connections=self.pool_size,
            socket_timeout=DEFAULT_TIMEOUT,
        )

    async def _connect_sentinel(self):
        """Підключення через Redis Sentinel"""
        if not self.sentinel_hosts:
            raise ValueError("Sentinel hosts not provided")

        sentinel = Sentinel(self.sentinel_hosts, socket_timeout=DEFAULT_TIMEOUT)

        # Отримуємо master для запису
        self.redis_client = await sentinel.master_for(
            self.sentinel_service,
            decode_responses=False,
            max_connections=self.pool_size,
        )

    async def _create_pubsub_client(self) -> aioredis.Redis:
        """Створення окремого клієнта для Pub/Sub"""
        if self.mode == RedisMode.SINGLE:
            return await aioredis.from_url(
                self.redis_url, decode_responses=False, max_connections=5
            )
        else:
            # Для cluster/sentinel використовуємо основний клієнт
            return self.redis_client

    async def disconnect(self):
        """Відключення від Redis"""
        try:
            # Відміна всіх pipeline timers
            for timer in self.pipeline_timers.values():
                timer.cancel()

            # Закриття з'єднань
            if self.redis_client:
                await self.redis_client.close()

            if self.pubsub_client and self.pubsub_client != self.redis_client:
                await self.pubsub_client.close()

            logger.info("Redis disconnected")

        except Exception as e:
            logger.error("Error disconnecting Redis", error=str(e))

    # === GET/SET операції з оптимізаціями ===

    async def get(self, key: str, use_local_cache: bool = True) -> Optional[Any]:
        """Оптимізоване отримання значення"""
        full_key = f"{CACHE_PREFIX}{key}"

        # Перевірка локального кешу
        if use_local_cache and full_key in self.local_cache:
            entry = self.local_cache[full_key]
            entry.access()
            self.metrics["cache_hits"] += 1
            return entry.value

        self.metrics["cache_misses"] += 1

        try:
            # Отримання з Redis
            value = await self._execute_with_retry(self.redis_client.get, full_key)

            if value is None:
                try:
                    logger.debug("Redis GET cache miss", redis_log=True, key=full_key)
                except Exception:
                    pass
                return None

            # Декодування та декомпресія
            decoded_value = self._decode_value(value)
            try:
                logger.debug("Redis GET cache hit", redis_log=True, key=full_key)
            except Exception:
                pass

            # Збереження в локальний кеш
            if use_local_cache:
                self._add_to_local_cache(full_key, decoded_value, len(value))

            return decoded_value

        except Exception as e:
            logger.error("Get operation failed", key=key, error=str(e))
            self.metrics["errors"] += 1
            return None

    async def set(
        self, key: str, value: Any, ttl: Optional[int] = None, use_pipeline: bool = None
    ) -> bool:
        """Оптимізоване збереження значення"""
        full_key = f"{CACHE_PREFIX}{key}"
        ttl = ttl or DEFAULT_TTL

        # Кодування та компресія
        encoded_value = self._encode_value(value)

        # Використання pipeline якщо увімкнено
        if use_pipeline is None:
            use_pipeline = self.enable_pipeline

        if use_pipeline and not self._is_large_value(encoded_value):
            return await self._add_to_pipeline(
                "default", self._set_with_ttl, full_key, encoded_value, ttl
            )

        # Безпосереднє збереження
        try:
            result = await self._execute_with_retry(
                self.redis_client.set, full_key, encoded_value, ex=ttl
            )
            try:
                logger.debug(
                    "Redis SET cache",
                    redis_log=True,
                    key=full_key,
                    ttl=ttl,
                    size_bytes=len(encoded_value) if hasattr(encoded_value, "__len__") else None,
                )
            except Exception:
                pass

            # Оновлення локального кешу
            self._add_to_local_cache(full_key, value, len(encoded_value))

            return bool(result)

        except Exception as e:
            logger.error("Set operation failed", key=key, error=str(e))
            self.metrics["errors"] += 1
            return False

    async def _set_with_ttl(self, key: str, value: bytes, ttl: int):
        """Helper для set з TTL"""
        res = await self.redis_client.set(key, value, ex=ttl)
        try:
            logger.debug("Redis SET", redis_log=True, key=f"{CACHE_PREFIX}{key}", ttl=ttl)
        except Exception:
            pass
        return res

    async def delete(self, *keys: str) -> int:
        """Видалення ключів"""
        if not keys:
            return 0

        full_keys = [f"{CACHE_PREFIX}{key}" for key in keys]

        try:
            result = await self._execute_with_retry(
                self.redis_client.delete, *full_keys
            )

            # Видалення з локального кешу
            for key in full_keys:
                self.local_cache.pop(key, None)

            return result

        except Exception as e:
            logger.error("Delete operation failed", keys=keys, error=str(e))
            self.metrics["errors"] += 1
            return 0

    # === Pipeline операції ===

    async def _add_to_pipeline(
        self, pipeline_id: str, operation: Callable, *args, **kwargs
    ) -> Any:
        """Додавання операції в pipeline"""
        # Додаємо в чергу
        self.pipeline_queue[pipeline_id].append(
            (f"op_{time.time()}", operation, args, kwargs)
        )

        # Запускаємо timer якщо потрібно
        if (
            pipeline_id not in self.pipeline_timers
            or self.pipeline_timers[pipeline_id].done()
        ):
            self.pipeline_timers[pipeline_id] = asyncio.create_task(
                self._pipeline_timer(pipeline_id)
            )

        # Перевіряємо чи потрібно виконати зараз
        if len(self.pipeline_queue[pipeline_id]) >= MAX_PIPELINE_SIZE:
            await self._execute_pipeline(pipeline_id)

        return True

    async def _pipeline_timer(self, pipeline_id: str):
        """Timer для виконання pipeline"""
        try:
            await asyncio.sleep(PIPELINE_TIMEOUT)
            await self._execute_pipeline(pipeline_id)
        except asyncio.CancelledError:
            pass

    async def _execute_pipeline(self, pipeline_id: str):
        """Виконання батчу операцій через pipeline"""
        operations = self.pipeline_queue[pipeline_id]
        if not operations:
            return

        # Очищаємо чергу
        self.pipeline_queue[pipeline_id] = []

        try:
            async with self.redis_client.pipeline(transaction=False) as pipe:
                # Додаємо всі операції
                for _, operation, args, kwargs in operations:
                    # Викликаємо операцію в контексті pipeline
                    method_name = operation.__name__.replace("_", "")
                    if hasattr(pipe, method_name):
                        getattr(pipe, method_name)(*args, **kwargs)

                # Виконуємо pipeline
                results = await pipe.execute()
                try:
                    logger.debug(
                        "Redis PIPELINE executed",
                        redis_log=True,
                        pipeline_id=pipeline_id,
                        operations=len(operations),
                    )
                except Exception:
                    pass

                self.metrics["pipeline_batches"] += 1
                self.metrics["operations"] += len(operations)

                logger.debug(
                    "Pipeline executed",
                    pipeline_id=pipeline_id,
                    operations=len(operations),
                )

                return results

        except Exception as e:
            logger.error(
                "Pipeline execution failed", pipeline_id=pipeline_id, error=str(e)
            )
            self.metrics["errors"] += 1

    # === Pub/Sub оптимізації ===

    async def publish(self, channel: str, message: Any) -> int:
        """Публікація повідомлення з оптимізаціями"""
        full_channel = f"{PUBSUB_PREFIX}{channel}"

        # Кодування повідомлення
        encoded_message = self._encode_value(message)

        try:
            return await self._execute_with_retry(
                self.pubsub_client.publish, full_channel, encoded_message
            )
        except Exception as e:
            logger.error("Publish failed", channel=channel, error=str(e))
            self.metrics["errors"] += 1
            return 0

    async def subscribe(self, channel: str, callback: Callable):
        """Підписка на канал з callback"""
        full_channel = f"{PUBSUB_PREFIX}{channel}"
        self.subscriptions[full_channel].add(callback)

        # Запускаємо listener якщо ще не запущений
        if not hasattr(self, "_pubsub_listener_task"):
            self._pubsub_listener_task = asyncio.create_task(self._pubsub_listener())

        logger.info("Subscribed to channel", channel=channel)

    async def _pubsub_listener(self):
        """Background listener для Pub/Sub"""
        pubsub = self.pubsub_client.pubsub()

        try:
            # Підписуємось на всі канали
            channels = list(self.subscriptions.keys())
            if channels:
                await pubsub.subscribe(*channels)

            # Слухаємо повідомлення
            async for message in pubsub.listen():
                if message["type"] in ("message", "pmessage"):
                    channel = (
                        message["channel"].decode()
                        if isinstance(message["channel"], bytes)
                        else message["channel"]
                    )
                    data = message["data"]

                    # Декодуємо повідомлення
                    try:
                        decoded_data = self._decode_value(data)
                    except Exception:
                        decoded_data = data

                    # Викликаємо callbacks
                    for callback in self.subscriptions.get(channel, []):
                        try:
                            await callback(channel, decoded_data)
                        except Exception as e:
                            logger.error(
                                "Callback error", channel=channel, error=str(e)
                            )

        except asyncio.CancelledError:
            await pubsub.unsubscribe()
            await pubsub.close()
        except Exception as e:
            logger.error("PubSub listener error", error=str(e))

    # === Distributed Locks ===

    async def acquire_lock(
        self, resource: str, timeout: float = 10.0, blocking: bool = True
    ) -> bool:
        """Отримання distributed lock"""
        lock_key = f"{LOCK_PREFIX}{resource}"
        identifier = f"{resource}:{time.time()}"

        try:
            if blocking:
                # Спробуємо отримати lock з очікуванням
                start_time = time.time()
                while time.time() - start_time < timeout:
                    result = await self.redis_client.set(
                        lock_key, identifier, nx=True, ex=int(timeout)
                    )
                    if result:
                        self.locks[resource] = identifier
                        return True
                    await asyncio.sleep(0.1)
                return False
            else:
                # Спробуємо отримати lock без очікування
                result = await self.redis_client.set(
                    lock_key, identifier, nx=True, ex=int(timeout)
                )
                if result:
                    self.locks[resource] = identifier
                return bool(result)

        except Exception as e:
            logger.error("Lock acquisition failed", resource=resource, error=str(e))
            return False

    async def release_lock(self, resource: str) -> bool:
        """Звільнення distributed lock"""
        lock_key = f"{LOCK_PREFIX}{resource}"
        identifier = self.locks.get(resource)

        if not identifier:
            return False

        try:
            # Lua script для атомарного видалення
            lua_script = """
            if redis.call("get", KEYS[1]) == ARGV[1] then
                return redis.call("del", KEYS[1])
            else
                return 0
            end
            """

            result = await self.redis_client.eval(lua_script, 1, lock_key, identifier)

            if result:
                del self.locks[resource]

            return bool(result)

        except Exception as e:
            logger.error("Lock release failed", resource=resource, error=str(e))
            return False

    # === Helper методи ===

    def _encode_value(self, value: Any) -> bytes:
        """Кодування та компресія значення (безпечна серіалізація JSON)."""
        # Серіалізація у JSON, якщо не bytes
        if isinstance(value, bytes):
            serialized = value
        else:
            try:
                serialized = json.dumps(value, default=str, ensure_ascii=False).encode(
                    "utf-8"
                )
            except Exception:
                # Фолбек: перетворити у рядок
                serialized = str(value).encode("utf-8")

        # Компресія якщо потрібно
        if self.enable_compression and len(serialized) > COMPRESSION_THRESHOLD:
            compressed = zlib.compress(serialized)
            if len(compressed) < len(serialized) * 0.9:
                self.metrics["compressed_values"] += 1
                self.metrics["bytes_saved"] += len(serialized) - len(compressed)
                return b"C:" + compressed  # Префікс для позначення компресії

        return serialized

    def _decode_value(self, value: bytes) -> Any:
        """Декодування та декомпресія значення (тільки JSON/UTF-8)."""
        if not value:
            return None

        # Перевірка на компресію
        if value.startswith(b"C:"):
            try:
                decompressed = zlib.decompress(value[2:])
                try:
                    return json.loads(decompressed.decode("utf-8"))
                except Exception:
                    return decompressed.decode("utf-8", errors="ignore")
            except Exception:
                logger.warning("Failed to decompress value")
                try:
                    return value.decode("utf-8", errors="ignore")
                except Exception:
                    return None

        # Звичайне декодування як JSON/рядок
        try:
            return json.loads(value.decode("utf-8"))
        except Exception:
            try:
                return value.decode("utf-8")
            except Exception:
                return value

    def _is_large_value(self, value: bytes) -> bool:
        """Перевірка чи значення занадто велике для pipeline"""
        return len(value) > 100 * 1024  # 100KB

    async def _execute_with_retry(self, operation: Callable, *args, **kwargs) -> Any:
        """Виконання операції з retry"""
        last_error = None

        for attempt in range(RETRY_ATTEMPTS):
            try:
                self.metrics["operations"] += 1
                return await operation(*args, **kwargs)

            except (ConnectionError, TimeoutError) as e:
                last_error = e
                self.metrics["retries"] += 1

                if attempt < RETRY_ATTEMPTS - 1:
                    await asyncio.sleep(RETRY_DELAY * (attempt + 1))
                    logger.warning(
                        "Retrying operation", attempt=attempt + 1, error=str(e)
                    )

            except Exception as e:
                logger.error("Operation failed", error=str(e))
                raise

        raise last_error

    def _add_to_local_cache(self, key: str, value: Any, size: int):
        """Додавання в локальний кеш з врахуванням стратегії"""
        entry = CacheEntry(key=key, value=value, size=size)

        # Додаємо в кеш
        self.local_cache[key] = entry
        self.cache_order.append(key)

        # Очищення якщо переповнено
        if len(self.local_cache) > LRU_CACHE_SIZE:
            self._evict_from_cache()

    def _evict_from_cache(self):
        """Видалення з кешу згідно стратегії"""
        if self.cache_strategy == CacheStrategy.LRU:
            # Видаляємо найстарший за доступом
            oldest_key = min(
                self.local_cache.keys(), key=lambda k: self.local_cache[k].last_accessed
            )
            del self.local_cache[oldest_key]

        elif self.cache_strategy == CacheStrategy.LFU:
            # Видаляємо найменш використовуваний
            least_used_key = min(
                self.local_cache.keys(), key=lambda k: self.local_cache[k].hits
            )
            del self.local_cache[least_used_key]

        elif self.cache_strategy == CacheStrategy.ADAPTIVE:
            # Адаптивна стратегія - враховуємо вік, використання та розмір
            def score(key):
                entry = self.local_cache[key]
                age_factor = entry.age / 3600  # години
                usage_factor = 1 / (entry.hits + 1)
                size_factor = entry.size / 1024  # KB
                return age_factor * usage_factor * size_factor

            worst_key = max(self.local_cache.keys(), key=score)
            del self.local_cache[worst_key]

    def get_stats(self) -> Dict[str, Any]:
        """Отримання статистики"""
        cache_size = sum(entry.size for entry in self.local_cache.values())
        hit_rate = (
            self.metrics["cache_hits"]
            / (self.metrics["cache_hits"] + self.metrics["cache_misses"] + 1)
        ) * 100

        return {
            "mode": self.mode.value,
            "metrics": self.metrics.copy(),
            "local_cache": {
                "entries": len(self.local_cache),
                "size_bytes": cache_size,
                "hit_rate": f"{hit_rate:.1f}%",
            },
            "pipeline": {
                "queued_operations": sum(len(q) for q in self.pipeline_queue.values()),
                "active_timers": len(self.pipeline_timers),
            },
            "pubsub": {
                "subscriptions": sum(len(s) for s in self.subscriptions.values())
            },
            "locks": {"held": len(self.locks)},
        }


# Глобальний оптимізатор
redis_optimizer = RedisOptimizer()


# Швидкі helper функції
async def optimized_get(key: str) -> Optional[Any]:
    """Швидке отримання значення"""
    return await redis_optimizer.get(key)


async def optimized_set(key: str, value: Any, ttl: Optional[int] = None) -> bool:
    """Швидке збереження значення"""
    return await redis_optimizer.set(key, value, ttl)


async def optimized_delete(*keys: str) -> int:
    """Швидке видалення ключів"""
    return await redis_optimizer.delete(*keys)


def get_redis_stats() -> Dict[str, Any]:
    """Отримання статистики Redis"""
    return redis_optimizer.get_stats()
