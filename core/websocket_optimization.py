"""
WebSocket Optimization Module for TetraCore Hub
Compression, batch processing та оптимізований heartbeat механізм
"""

import asyncio
import gzip
import zlib
import json
import time
from typing import Dict, List, Optional, Any, Tuple, Set, Callable, Union
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from collections import deque, defaultdict
from enum import Enum
import weakref
import statistics

from fastapi import WebSocket
import structlog
import msgpack

logger = structlog.get_logger()

# Константи для compression
COMPRESSION_THRESHOLD = 1024  # Мінімальний розмір для compression (1KB)
COMPRESSION_LEVEL = 6  # zlib compression level (1-9)
MAX_WINDOW_BITS = 15  # Для permessage-deflate
CHUNK_SIZE = 65536  # 64KB chunks

# Константи для batching
BATCH_SIZE = 50  # Максимум повідомлень в batch
BATCH_TIMEOUT = 0.1  # 100ms timeout для batching
MAX_BATCH_SIZE_BYTES = 1024 * 1024  # 1MB максимальний розмір batch

# Константи для heartbeat
HEARTBEAT_INTERVAL = 60  # Збільшено з 30 до 60 секунд для зменшення навантаження
HEARTBEAT_TIMEOUT = 15  # Збільшено з 10 до 15 секунд пропорційно
ADAPTIVE_HEARTBEAT_MIN = 30  # Збільшено з 10 до 30 секунд
ADAPTIVE_HEARTBEAT_MAX = 180  # Збільшено з 120 до 180 секунд
HEARTBEAT_BATCH_SIZE = 10  # Кількість клієнтів в одному batch для heartbeat

# Константи для performance
MESSAGE_QUEUE_SIZE = 1000  # Максимальний розмір черги повідомлень
PERFORMANCE_SAMPLE_SIZE = 100  # Розмір вибірки для метрик


class CompressionType(Enum):
    """Типи compression"""
    NONE = "none"
    GZIP = "gzip"
    ZLIB = "zlib"
    DEFLATE = "deflate"
    MSGPACK = "msgpack"


class MessagePriority(Enum):
    """Пріоритети повідомлень"""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3
    REALTIME = 4


@dataclass
class OptimizedMessage:
    """Оптимізоване повідомлення"""
    id: str
    data: Any
    priority: MessagePriority = MessagePriority.NORMAL
    timestamp: float = field(default_factory=time.time)
    compression: Optional[CompressionType] = None
    size: int = 0
    batch_id: Optional[str] = None

    @property
    def age(self) -> float:
        """Вік повідомлення в секундах"""
        return time.time() - self.timestamp


@dataclass
class HeartbeatInfo:
    """Інформація про heartbeat для клієнта"""
    client_id: str
    last_ping: Optional[float] = None
    last_pong: Optional[float] = None
    latency_samples: List[float] = field(default_factory=list)
    missed_pongs: int = 0
    adaptive_interval: float = HEARTBEAT_INTERVAL

    @property
    def average_latency(self) -> float:
        """Середня затримка"""
        if not self.latency_samples:
            return 0
        return statistics.mean(self.latency_samples[-10:])  # Останні 10 вимірів

    @property
    def is_responsive(self) -> bool:
        """Чи відповідає клієнт на ping"""
        return self.missed_pongs < 3

    def record_latency(self, latency: float):
        """Запис нової затримки"""
        self.latency_samples.append(latency)
        if len(self.latency_samples) > PERFORMANCE_SAMPLE_SIZE:
            self.latency_samples = self.latency_samples[-PERFORMANCE_SAMPLE_SIZE:]

        # Адаптивний інтервал на основі латентності
        avg_latency = self.average_latency
        if avg_latency < 0.1:  # < 100ms - хороше з'єднання
            self.adaptive_interval = min(HEARTBEAT_INTERVAL * 2, ADAPTIVE_HEARTBEAT_MAX)
        elif avg_latency > 1.0:  # > 1s - погане з'єднання
            self.adaptive_interval = max(HEARTBEAT_INTERVAL / 2, ADAPTIVE_HEARTBEAT_MIN)
        else:
            self.adaptive_interval = HEARTBEAT_INTERVAL


class WebSocketOptimizer:
    """Оптимізатор для WebSocket з'єднань"""

    def __init__(
        self,
        enable_compression: bool = True,
        enable_batching: bool = True,
        enable_adaptive_heartbeat: bool = True,
        compression_type: CompressionType = CompressionType.ZLIB
    ):
        self.enable_compression = enable_compression
        self.enable_batching = enable_batching
        self.enable_adaptive_heartbeat = enable_adaptive_heartbeat
        self.compression_type = compression_type

        # Message queues per client
        self.message_queues: Dict[str, deque[OptimizedMessage]] = defaultdict(deque)
        self.batch_timers: Dict[str, asyncio.Task] = {}

        # Heartbeat tracking
        self.heartbeat_info: Dict[str, HeartbeatInfo] = {}
        self.heartbeat_tasks: Dict[str, asyncio.Task] = {}

        # Performance metrics
        self.metrics = {
            "messages_sent": 0,
            "messages_compressed": 0,
            "bytes_saved": 0,
            "batches_sent": 0,
            "heartbeats_sent": 0,
            "average_compression_ratio": 0.0,
            "average_batch_size": 0.0
        }

        # Compression stats
        self.compression_samples: deque[float] = deque(maxlen=PERFORMANCE_SAMPLE_SIZE)

        # WebSocket references (weak to avoid memory leaks)
        self.websockets: Dict[str, weakref.ref[WebSocket]] = {}

        logger.info("WebSocket optimizer initialized",
                   compression=enable_compression,
                   batching=enable_batching,
                   adaptive_heartbeat=enable_adaptive_heartbeat)

    def register_client(self, client_id: str, websocket: WebSocket):
        """Реєстрація клієнта для оптимізації"""
        self.websockets[client_id] = weakref.ref(websocket)
        self.heartbeat_info[client_id] = HeartbeatInfo(client_id=client_id)

        if self.enable_adaptive_heartbeat:
            self.heartbeat_tasks[client_id] = asyncio.create_task(
                self._heartbeat_loop(client_id)
            )

        logger.debug("Client registered for optimization", client_id=client_id)

    def unregister_client(self, client_id: str):
        """Видалення клієнта з оптимізації"""
        # Cancel heartbeat
        if client_id in self.heartbeat_tasks:
            self.heartbeat_tasks[client_id].cancel()
            del self.heartbeat_tasks[client_id]

        # Cancel batch timer
        if client_id in self.batch_timers:
            self.batch_timers[client_id].cancel()
            del self.batch_timers[client_id]

        # Cleanup
        self.websockets.pop(client_id, None)
        self.heartbeat_info.pop(client_id, None)
        self.message_queues.pop(client_id, None)

        logger.debug("Client unregistered from optimization", client_id=client_id)

    async def send_message(
        self,
        client_id: str,
        data: Any,
        priority: MessagePriority = MessagePriority.NORMAL,
        force_immediate: bool = False
    ) -> bool:
        """Оптимізована відправка повідомлення"""
        # Створюємо оптимізоване повідомлення
        message = OptimizedMessage(
            id=f"{client_id}:{time.time()}",
            data=data,
            priority=priority
        )

        # Обчислюємо розмір
        serialized = self._serialize_data(data)
        message.size = len(serialized)

        # Для критичних повідомлень - відправляємо одразу
        if priority >= MessagePriority.CRITICAL or force_immediate or not self.enable_batching:
            return await self._send_immediate(client_id, message)

        # Додаємо в чергу для batching
        self.message_queues[client_id].append(message)

        # Запускаємо batch timer якщо ще не запущений
        if client_id not in self.batch_timers or self.batch_timers[client_id].done():
            self.batch_timers[client_id] = asyncio.create_task(
                self._batch_timer(client_id)
            )

        # Перевіряємо чи потрібно відправити batch зараз
        if self._should_send_batch(client_id):
            await self._send_batch(client_id)

        return True

    async def _send_immediate(self, client_id: str, message: OptimizedMessage) -> bool:
        """Негайна відправка повідомлення"""
        ws_ref = self.websockets.get(client_id)
        if not ws_ref:
            return False

        websocket = ws_ref()
        if not websocket:
            return False

        try:
            # Серіалізація та compression
            data = self._prepare_message(message)

            # Відправка
            if isinstance(data, bytes):
                await websocket.send_bytes(data)
            else:
                await websocket.send_text(data)

            self.metrics["messages_sent"] += 1
            return True

        except Exception as e:
            logger.error("Error sending immediate message",
                        client_id=client_id,
                        error=str(e))
            return False

    def _should_send_batch(self, client_id: str) -> bool:
        """Перевірка чи потрібно відправити batch"""
        queue = self.message_queues[client_id]

        if not queue:
            return False

        # Перевірка розміру
        if len(queue) >= BATCH_SIZE:
            return True

        # Перевірка загального розміру в байтах
        total_size = sum(msg.size for msg in queue)
        if total_size >= MAX_BATCH_SIZE_BYTES:
            return True

        # Перевірка на high priority messages
        if any(msg.priority >= MessagePriority.HIGH for msg in queue):
            return True

        return False

    async def _batch_timer(self, client_id: str):
        """Timer для відправки batch"""
        try:
            await asyncio.sleep(BATCH_TIMEOUT)
            await self._send_batch(client_id)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Batch timer error", client_id=client_id, error=str(e))

    async def _send_batch(self, client_id: str):
        """Відправка batch повідомлень"""
        queue = self.message_queues[client_id]
        if not queue:
            return

        ws_ref = self.websockets.get(client_id)
        if not ws_ref:
            return

        websocket = ws_ref()
        if not websocket:
            return

        # Збираємо повідомлення для batch
        batch_messages = []
        batch_size = 0

        while queue and len(batch_messages) < BATCH_SIZE:
            msg = queue.popleft()
            batch_messages.append(msg)
            batch_size += msg.size

            if batch_size >= MAX_BATCH_SIZE_BYTES:
                break

        if not batch_messages:
            return

        try:
            # Сортуємо за пріоритетом
            batch_messages.sort(key=lambda m: m.priority.value, reverse=True)

            # Створюємо batch
            batch_data = {
                "type": "batch",
                "messages": [
                    {
                        "id": msg.id,
                        "data": msg.data,
                        "priority": msg.priority.value,
                        "timestamp": msg.timestamp
                    }
                    for msg in batch_messages
                ],
                "count": len(batch_messages),
                "timestamp": time.time()
            }

            # Compression для batch
            if self.enable_compression and batch_size > COMPRESSION_THRESHOLD:
                compressed = self._compress_data(json.dumps(batch_data))
                if len(compressed) < batch_size * 0.9:  # Якщо економія > 10%
                    await websocket.send_bytes(compressed)
                    self.metrics["bytes_saved"] += batch_size - len(compressed)
                else:
                    await websocket.send_json(batch_data)
            else:
                await websocket.send_json(batch_data)

            self.metrics["batches_sent"] += 1
            self.metrics["messages_sent"] += len(batch_messages)

            # Оновлюємо середній розмір batch
            self._update_average_metric("average_batch_size", len(batch_messages))

            logger.debug("Batch sent",
                        client_id=client_id,
                        messages=len(batch_messages),
                        size=batch_size)

        except Exception as e:
            logger.error("Error sending batch",
                        client_id=client_id,
                        error=str(e))

            # Повертаємо повідомлення в чергу
            for msg in reversed(batch_messages):
                queue.appendleft(msg)

    def _prepare_message(self, message: OptimizedMessage) -> Union[str, bytes]:
        """Підготовка повідомлення для відправки"""
        data = message.data

        # Серіалізація
        if self.compression_type == CompressionType.MSGPACK:
            serialized = msgpack.packb(data)
        else:
            serialized = json.dumps(data).encode()

        # Compression
        if self.enable_compression and len(serialized) > COMPRESSION_THRESHOLD:
            compressed = self._compress_data(serialized)

            if len(compressed) < len(serialized) * 0.9:  # Якщо економія > 10%
                self.metrics["messages_compressed"] += 1
                self.metrics["bytes_saved"] += len(serialized) - len(compressed)

                # Записуємо compression ratio
                ratio = len(compressed) / len(serialized)
                self.compression_samples.append(ratio)
                self._update_compression_ratio()

                return compressed

        return serialized.decode() if isinstance(serialized, bytes) else serialized

    def _compress_data(self, data: bytes) -> bytes:
        """Compression даних"""
        if self.compression_type == CompressionType.GZIP:
            return gzip.compress(data, compresslevel=COMPRESSION_LEVEL)
        elif self.compression_type == CompressionType.ZLIB:
            return zlib.compress(data, level=COMPRESSION_LEVEL)
        elif self.compression_type == CompressionType.DEFLATE:
            compressor = zlib.compressobj(
                level=COMPRESSION_LEVEL,
                wbits=-MAX_WINDOW_BITS
            )
            return compressor.compress(data) + compressor.flush()
        else:
            return data

    def _serialize_data(self, data: Any) -> bytes:
        """Серіалізація даних для обчислення розміру"""
        if isinstance(data, bytes):
            return data
        elif isinstance(data, str):
            return data.encode()
        else:
            return json.dumps(data).encode()

    async def _heartbeat_loop(self, client_id: str):
        """Адаптивний heartbeat loop для клієнта"""
        heartbeat = self.heartbeat_info[client_id]

        while True:
            try:
                # Використовуємо адаптивний інтервал
                interval = heartbeat.adaptive_interval if self.enable_adaptive_heartbeat else HEARTBEAT_INTERVAL
                await asyncio.sleep(interval)

                ws_ref = self.websockets.get(client_id)
                if not ws_ref:
                    break

                websocket = ws_ref()
                if not websocket:
                    break

                # Відправляємо ping
                heartbeat.last_ping = time.time()

                try:
                    pong_waiter = await websocket.ping()
                    await asyncio.wait_for(pong_waiter, timeout=HEARTBEAT_TIMEOUT)

                    # Pong отримано
                    heartbeat.last_pong = time.time()
                    latency = heartbeat.last_pong - heartbeat.last_ping
                    heartbeat.record_latency(latency)
                    heartbeat.missed_pongs = 0

                    self.metrics["heartbeats_sent"] += 1

                    logger.debug("Heartbeat successful",
                               client_id=client_id,
                               latency=f"{latency*1000:.1f}ms",
                               interval=interval)

                except asyncio.TimeoutError:
                    heartbeat.missed_pongs += 1
                    logger.warning("Heartbeat timeout",
                                 client_id=client_id,
                                 missed=heartbeat.missed_pongs)

                    if not heartbeat.is_responsive:
                        # Клієнт не відповідає, розриваємо з'єднання
                        logger.error("Client unresponsive, closing connection",
                                   client_id=client_id)
                        await websocket.close()
                        break

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Heartbeat error",
                           client_id=client_id,
                           error=str(e))
                break

    def _update_average_metric(self, metric_name: str, value: float):
        """Оновлення середнього значення метрики"""
        current = self.metrics.get(metric_name, 0.0)
        count = self.metrics.get(f"{metric_name}_count", 0) + 1
        self.metrics[metric_name] = (current * (count - 1) + value) / count
        self.metrics[f"{metric_name}_count"] = count

    def _update_compression_ratio(self):
        """Оновлення середнього compression ratio"""
        if self.compression_samples:
            self.metrics["average_compression_ratio"] = statistics.mean(self.compression_samples)

    def get_client_stats(self, client_id: str) -> Dict[str, Any]:
        """Статистика для конкретного клієнта"""
        heartbeat = self.heartbeat_info.get(client_id)
        queue = self.message_queues.get(client_id, deque())

        stats = {
            "queued_messages": len(queue),
            "queue_size_bytes": sum(msg.size for msg in queue)
        }

        if heartbeat:
            stats.update({
                "average_latency": heartbeat.average_latency,
                "adaptive_interval": heartbeat.adaptive_interval,
                "missed_pongs": heartbeat.missed_pongs,
                "is_responsive": heartbeat.is_responsive
            })

        return stats

    def get_global_stats(self) -> Dict[str, Any]:
        """Глобальна статистика оптимізатора"""
        total_queued = sum(len(q) for q in self.message_queues.values())
        total_queue_size = sum(
            sum(msg.size for msg in q)
            for q in self.message_queues.values()
        )

        return {
            "metrics": self.metrics.copy(),
            "total_clients": len(self.websockets),
            "active_heartbeats": len(self.heartbeat_tasks),
            "total_queued_messages": total_queued,
            "total_queue_size_bytes": total_queue_size,
            "compression_enabled": self.enable_compression,
            "batching_enabled": self.enable_batching,
            "adaptive_heartbeat_enabled": self.enable_adaptive_heartbeat
        }


# Глобальний оптимізатор
websocket_optimizer = WebSocketOptimizer()


# Допоміжні функції
async def optimize_send(
    client_id: str,
    data: Any,
    priority: MessagePriority = MessagePriority.NORMAL
) -> bool:
    """Швидка оптимізована відправка через глобальний оптимізатор"""
    return await websocket_optimizer.send_message(client_id, data, priority)


def register_websocket(client_id: str, websocket: WebSocket):
    """Реєстрація WebSocket для оптимізації"""
    websocket_optimizer.register_client(client_id, websocket)


def unregister_websocket(client_id: str):
    """Видалення WebSocket з оптимізації"""
    websocket_optimizer.unregister_client(client_id)


def get_optimization_stats() -> Dict[str, Any]:
    """Отримання статистики оптимізації"""
    return websocket_optimizer.get_global_stats()
