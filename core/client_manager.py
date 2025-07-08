"""
TetraCore StreamHub Client Manager

Менеджер для управління підключеннями клієнтів (ботів і воркерів).
Відповідає за реєстрацію, відключення, моніторинг та балансування навантаження.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Callable, Any
from collections import defaultdict
import structlog

from config import Settings
from models.client import Client, ClientType, ClientInfo, WorkerCapabilities, ConnectionStatus, WorkerStatus
from core.async_optimization import AsyncOptimizer, TaskPriority


class ClientManager:
    """Менеджер клієнтів StreamHub"""

    def __init__(self, settings: Settings):
        """Ініціалізація менеджера клієнтів"""
        self.settings = settings
        self.logger = structlog.get_logger(__name__)

        # Зберігання клієнтів
        self.clients: Dict[str, Client] = {}
        self.clients_by_type: Dict[ClientType, Set[str]] = defaultdict(set)
        self.clients_by_capability: Dict[str, Set[str]] = defaultdict(set)

        # Асинхронний оптимізатор
        self.async_optimizer = AsyncOptimizer(max_workers=10)

        # Статистика
        self.total_connections = 0
        self.total_disconnections = 0
        self.peak_connections = 0
        self.start_time = datetime.utcnow()

        # Event handlers
        self.on_client_connected: Optional[Callable] = None
        self.on_client_disconnected: Optional[Callable] = None
        self.on_client_updated: Optional[Callable] = None

        # Стан менеджера
        self.is_running = False
        self.cleanup_task: Optional[asyncio.Task] = None

    async def initialize(self):
        """Ініціалізація менеджера клієнтів"""
        try:
            self.logger.info("Initializing ClientManager")

            # Ініціалізація асинхронного оптимізатора
            await self.async_optimizer.initialize()

            # Запуск задачі очищення
            self.cleanup_task = asyncio.create_task(self._cleanup_loop())

            self.is_running = True
            self.logger.info("ClientManager initialized successfully")

        except Exception as e:
            self.logger.error("Failed to initialize ClientManager", error=str(e))
            raise

    async def shutdown(self):
        """Зупинка менеджера"""
        self.logger.info("Shutting down ClientManager")

        self.is_running = False

        # Зупинка задачі очищення
        if self.cleanup_task and not self.cleanup_task.done():
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except asyncio.CancelledError:
                pass

        # Відключення всіх клієнтів
        for client in list(self.clients.values()):
            await self.remove_client(client.info.client_id)

        # Зупинка асинхронного оптимізатора
        if self.async_optimizer:
            await self.async_optimizer.shutdown()

        self.logger.info("ClientManager shutdown complete")

    async def add_client(self, client: Client) -> bool:
        """Додавання нового клієнта"""
        try:
            client_id = client.info.client_id

            # Перевірка ліміту підключень
            if len(self.clients) >= self.settings.max_connections:
                self.logger.warning("Maximum connections reached",
                                  client_id=client_id,
                                  max_connections=self.settings.max_connections)
                return False

            # Перевірка чи клієнт вже існує
            if client_id in self.clients:
                self.logger.warning("Client already exists", client_id=client_id)
                await self.remove_client(client_id)

            # Додавання клієнта
            self.clients[client_id] = client
            self.clients_by_type[client.info.client_type].add(client_id)

            # Додавання можливостей воркера до індексу
            if client.info.is_worker() and client.info.capabilities:
                for capability in client.info.capabilities.supported_actions:
                    self.clients_by_capability[capability].add(client_id)

            # Статистика
            self.total_connections += 1
            self.peak_connections = max(self.peak_connections, len(self.clients))

            # Логування успішного додавання
            self.logger.info(f"✅ Client added to manager",
                           client_id=client_id,
                           client_type=client.info.client_type.value,
                           client_name=client.info.client_name,
                           total_clients=len(self.clients),
                           clients_of_this_type=len(self.clients_by_type[client.info.client_type]))

            # Event handler
            if self.on_client_connected:
                await self.on_client_connected(client)

            # Зменшуємо рівень логування для зменшення шуму в продакшн
            self.logger.debug("Client added successfully",
                             client_id=client_id,
                             client_type=client.info.client_type.value,
                             total_clients=len(self.clients))

            return True

        except Exception as e:
            self.logger.error("Failed to add client",
                            client_id=client.info.client_id,
                            error=str(e))
            return False

    async def remove_client(self, client_id: str) -> bool:
        """Видалення клієнта"""
        try:
            if client_id not in self.clients:
                return False

            client = self.clients[client_id]

            # Відключення WebSocket
            client.disconnect()

            # Видалення з індексів
            self.clients_by_type[client.info.client_type].discard(client_id)

            if client.info.is_worker() and client.info.capabilities:
                for capability in client.info.capabilities.supported_task_types:
                    self.clients_by_capability[capability].discard(client_id)

            # Видалення з основного сховища
            del self.clients[client_id]

            # Оновлення статистики
            self.total_disconnections += 1

            # Виклик callback
            if self.on_client_disconnected:
                await self.on_client_disconnected(client)

            # Зменшуємо рівень логування для зменшення шуму в продакшн
            self.logger.debug("Client removed successfully",
                             client_id=client_id,
                             client_type=client.info.client_type.value,
                             total_clients=len(self.clients))

            return True

        except Exception as e:
            self.logger.error("Failed to remove client",
                            client_id=client_id,
                            error=str(e))
            return False

    def get_client(self, client_id: str) -> Optional[Client]:
        """Отримання клієнта за ID"""
        return self.clients.get(client_id)

    def get_all_clients(self) -> List[Client]:
        """Отримання всіх клієнтів"""
        return list(self.clients.values())

    def get_clients_by_type(self, client_types: List[ClientType]) -> List[Client]:
        """Отримання клієнтів за типом"""
        if not client_types:
            return self.get_all_clients()

        result = []
        for client_type in client_types:
            client_ids = self.clients_by_type.get(client_type, set())
            for client_id in client_ids:
                if client_id in self.clients:
                    result.append(self.clients[client_id])

        return result

    def get_available_workers(self, task_type: str = None) -> List[Client]:
        """Отримання доступних воркерів"""
        workers = []

        # Якщо вказано тип завдання, фільтруємо по можливостях
        if task_type:
            worker_ids = self.clients_by_capability.get(task_type, set())
        else:
            # Включаємо обидва типи воркерів
            worker_ids = (self.clients_by_type.get(ClientType.WORKER, set()) |
                         self.clients_by_type.get(ClientType.WORKER_API, set()))

        for worker_id in worker_ids:
            if worker_id in self.clients:
                worker = self.clients[worker_id]
                if worker.info.is_available():
                    workers.append(worker)

        # Сортування по навантаженню (менше навантажених спочатку)
        workers.sort(key=lambda w: w.info.get_load_percentage())

        return workers

    def get_best_worker(self, task_type: str = None,
                       worker_requirements: List[str] = None) -> Optional[Client]:
        """Отримання найкращого воркера для завдання"""
        available_workers = self.get_available_workers(task_type)

        if not available_workers:
            return None

        # Фільтрація по вимогам
        if worker_requirements:
            filtered_workers = []
            for worker in available_workers:
                if worker.info.capabilities:
                    worker_capabilities = set(worker.info.capabilities.supported_task_types)
                    if all(req in worker_capabilities for req in worker_requirements):
                        filtered_workers.append(worker)
            available_workers = filtered_workers

        if not available_workers:
            return None

        # Вибір найкращого воркера (з найменшим навантаженням)
        return available_workers[0]

    def get_client_count(self) -> int:
        """Отримання кількості клієнтів"""
        return len(self.clients)

    def get_client_count_by_type(self, client_type: ClientType) -> int:
        """Отримання кількості клієнтів за типом"""
        return len(self.clients_by_type.get(client_type, set()))

    def get_connected_clients(self) -> List[Client]:
        """Отримання підключених клієнтів"""
        return [client for client in self.clients.values()
                if client.info.is_connected()]

    def get_unhealthy_clients(self, timeout: int = 60) -> List[Client]:
        """Отримання нездорових клієнтів"""
        unhealthy = []
        for client in self.clients.values():
            if not client.is_healthy(timeout):
                unhealthy.append(client)
        return unhealthy

    async def update_client_stats(self, client_id: str, stats: Dict[str, Any]) -> bool:
        """Оновлення статистики клієнта"""
        try:
            if client_id not in self.clients:
                return False

            client = self.clients[client_id]
            client.info.update_stats(**stats)

            # Виклик callback
            if self.on_client_updated:
                await self.on_client_updated(client)

            return True

        except Exception as e:
            self.logger.error("Failed to update client stats",
                            client_id=client_id,
                            error=str(e))
            return False

    async def broadcast_to_clients(self, message: Dict[str, Any],
                                 client_types: List[ClientType] = None,
                                 exclude_clients: List[str] = None):
        """Розсилка повідомлення клієнтам"""
        try:
            target_clients = self.get_clients_by_type(client_types) if client_types else self.get_all_clients()
            exclude_set = set(exclude_clients or [])

            sent_count = 0
            failed_count = 0

            for client in target_clients:
                if client.info.client_id in exclude_set:
                    continue

                if client.websocket and client.info.is_connected():
                    try:
                        await client.websocket.send_json(message)
                        sent_count += 1
                    except Exception as e:
                        self.logger.error("Failed to send message to client",
                                        client_id=client.info.client_id,
                                        error=str(e))
                        failed_count += 1

            self.logger.info("Broadcast completed",
                           sent=sent_count,
                           failed=failed_count,
                           target_types=[t.value for t in (client_types or [])])

        except Exception as e:
            self.logger.error("Failed to broadcast message", error=str(e))

    def get_stats(self) -> Dict[str, Any]:
        """Отримання статистики менеджера"""
        uptime = (datetime.utcnow() - self.start_time).total_seconds()

        client_stats = defaultdict(int)
        worker_stats = defaultdict(int)

        for client in self.clients.values():
            client_stats[f"{client.info.client_type.value}_count"] += 1

            if client.info.is_worker():
                if client.info.worker_status:
                    worker_stats[f"worker_{client.info.worker_status.value}"] += 1

        return {
            "uptime_seconds": uptime,
            "total_clients": len(self.clients),
            "connected_clients": len(self.get_connected_clients()),
            "total_connections": self.total_connections,
            "total_disconnections": self.total_disconnections,
            "peak_connections": self.peak_connections,
            "client_stats": dict(client_stats),
            "worker_stats": dict(worker_stats),
            "capabilities": {
                capability: len(client_ids)
                for capability, client_ids in self.clients_by_capability.items()
            }
        }

    def is_healthy(self) -> bool:
        """Перевірка здоров'я менеджера"""
        return self.is_running

    async def _cleanup_loop(self):
        """Фонова задача очищення"""
        while self.is_running:
            try:
                # Використовуємо фонову задачу для очищення
                task_id = await self.async_optimizer.create_background_task(
                    name="cleanup_unhealthy_clients",
                    func=self._cleanup_unhealthy_clients,
                    priority=TaskPriority.LOW
                )

                # Очікуємо результат
                try:
                    await self.async_optimizer.get_task_result(task_id, timeout=25)
                except TimeoutError:
                    self.logger.warning("Cleanup task timeout")
                except ValueError as e:
                    # Таск міг бути видалений або не створений
                    self.logger.debug("Cleanup task not found", task_id=task_id, error=str(e))

                await asyncio.sleep(30)  # Очищення кожні 30 секунд

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in cleanup loop", error=str(e))
                await asyncio.sleep(10)

    async def _cleanup_unhealthy_clients(self):
        """Очищення нездорових клієнтів"""
        try:
            unhealthy_clients = self.get_unhealthy_clients(self.settings.websocket_timeout)

            for client in unhealthy_clients:
                self.logger.info("Removing unhealthy client",
                               client_id=client.info.client_id,
                               last_activity=client.info.stats.last_activity)

                await self.remove_client(client.info.client_id)

        except Exception as e:
            self.logger.error("Error cleaning up unhealthy clients", error=str(e))

    def __len__(self) -> int:
        """Кількість клієнтів"""
        return len(self.clients)

    def __contains__(self, client_id: str) -> bool:
        """Перевірка наявності клієнта"""
        return client_id in self.clients

    def __iter__(self):
        """Ітератор по клієнтах"""
        return iter(self.clients.values())
