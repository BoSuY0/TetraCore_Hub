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
            client_type = client.info.client_type

            self.logger.info("[CLIENT_MANAGER] Registering new client",
                           client_id=client_id,
                           client_type=client_type.value,
                           client_name=client.info.client_name,
                           capabilities=client.info.capabilities.supported_task_types if client.info.capabilities else None,
                           max_concurrent_tasks=client.info.capabilities.max_concurrent_tasks if client.info.capabilities else None,
                           current_count=len(self.clients))

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

            # Додавання можливостей клієнта до індексу (всі клієнти з capabilities)
            if client.info.can_execute_tasks():
                for capability in client.info.capabilities.supported_task_types:
                    self.clients_by_capability[capability].add(client_id)

            # Статистика
            self.total_connections += 1

            self.logger.info("Client added successfully",
                           client_id=client_id,
                           client_type=client.info.client_type,
                           total_clients=len(self.clients),
                           clients_by_type={k.value: len(v) for k, v in self.clients_by_type.items()})
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

            if client.info.can_execute_tasks():
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

    def get_available_workers(self, task_type: str = None, executor_type: str = None) -> List[Client]:
        """Отримання доступних воркерів"""
        workers = []

        executor_desc = {
            'bot': 'bots',
            'worker': 'workers',
            'worker_api': 'API workers',
            None: 'executors (all types)'
        }

        self.logger.info(f"[CLIENT_MANAGER] Looking for available {executor_desc.get(executor_type, 'executors')}",
                        task_type=task_type,
                        executor_type=executor_type,
                        total_clients=len(self.clients))

        # Визначаємо типи клієнтів на основі executor_type
        if executor_type == 'bot':
            client_types = [ClientType.BOT]
        elif executor_type == 'worker':
            client_types = [ClientType.WORKER]
        elif executor_type == 'worker_api':
            client_types = [ClientType.WORKER_API]
        elif executor_type == 'stream_hub':
            client_types = [ClientType.STREAM_HUB]
        else:
            # За замовчуванням включаємо всі типи виконавців (крім MONITOR та ADMIN)
            client_types = [ClientType.WORKER, ClientType.WORKER_API, ClientType.BOT, ClientType.STREAM_HUB]

        self.logger.debug("[CLIENT_MANAGER] Client types to search",
                         client_types=[ct.value for ct in client_types])

        # Збираємо всі ID клієнтів потрібних типів
        worker_ids = set()
        for client_type in client_types:
            type_clients = self.clients_by_type.get(client_type, set())
            self.logger.debug(f"[CLIENT_MANAGER] Clients of type {client_type.value}",
                            count=len(type_clients),
                            ids=list(type_clients))
            worker_ids.update(type_clients)

        # Якщо вказано тип завдання, додатково фільтруємо по можливостях
        if task_type:
            capability_ids = self.clients_by_capability.get(task_type, set())
            self.logger.debug("[CLIENT_MANAGER] Filtering by capability",
                            task_type=task_type,
                            capability_clients=len(capability_ids))
            worker_ids = worker_ids.intersection(capability_ids)

        self.logger.debug("[CLIENT_MANAGER] Checking client availability",
                    potential_clients=len(worker_ids))

        for worker_id in worker_ids:
            if worker_id in self.clients:
                worker = self.clients[worker_id]
                is_available = worker.info.is_available()
                self.logger.debug(f"[CLIENT_MANAGER] Checking {worker.info.client_type.value}",
                                client_id=worker_id,
                                client_type=worker.info.client_type.value,
                                is_connected=worker.info.is_connected(),
                                is_available=is_available,
                                current_tasks=worker.info.stats.active_tasks,
                                max_tasks=worker.info.capabilities.max_concurrent_tasks if worker.info.capabilities else 1)
                if is_available:
                    workers.append(worker)

        # Сортування по навантаженню (менше навантажених спочатку)
        workers.sort(key=lambda w: w.info.get_load_percentage())

        executor_type_desc = 'executors'
        if executor_type == 'bot':
            executor_type_desc = 'bots'
        elif executor_type == 'worker':
            executor_type_desc = 'workers'
        elif executor_type == 'worker_api':
            executor_type_desc = 'API workers'

        self.logger.info(f"[CLIENT_MANAGER] Available {executor_type_desc} found",
                        count=len(workers),
                        client_ids=[w.info.client_id for w in workers])

        return workers

    def get_best_worker(self, task_type: str = None,
                       worker_requirements: List[str] = None,
                       executor_type: str = None) -> Optional[Client]:
        """Отримання найкращого воркера для завдання"""
        self.logger.info("[CLIENT_MANAGER] get_best_worker called",
                        task_type=task_type,
                        executor_type=executor_type,
                        worker_requirements=worker_requirements)

        available_workers = self.get_available_workers(task_type, executor_type)

        if not available_workers:
            executor_desc = {
                'bot': 'bots',
                'worker': 'workers',
                'worker_api': 'API workers',
                None: 'executors'
            }
            self.logger.debug(f"[CLIENT_MANAGER] No available {executor_desc.get(executor_type, 'executors')} found",
                              task_type=task_type,
                              executor_type=executor_type)
            return None

        # Фільтрація по вимогам
        if worker_requirements:
            filtered_workers = []
            for worker in available_workers:
                if worker.info.capabilities:
                    worker_capabilities = set(worker.info.capabilities.supported_task_types)
                    if all(req in worker_capabilities for req in worker_requirements):
                        filtered_workers.append(worker)
            
            # Якщо після фільтрації нічого не залишилося, спробуємо fallback
            if not filtered_workers:
                self.logger.warning("[CLIENT_MANAGER] No workers match strict requirements, trying fallback",
                                  task_type=task_type,
                                  executor_type=executor_type,
                                  worker_requirements=worker_requirements)
                
                # Fallback 1: Воркери без строгих вимог (тільки за executor_type)
                fallback_workers = self.get_available_workers(task_type=None, executor_type=executor_type)
                if fallback_workers:
                    self.logger.info("[CLIENT_MANAGER] Using fallback worker (relaxed requirements)",
                                   worker_count=len(fallback_workers),
                                   executor_type=executor_type)
                    # Вибираємо найменш навантаженого
                    fallback_workers.sort(key=lambda w: w.info.get_load_percentage())
                    return fallback_workers[0]
                
                # Fallback 2: Будь-який доступний воркер відповідного типу
                import random
                all_type_workers = self.get_available_workers(task_type=None, executor_type=executor_type)
                if all_type_workers:
                    random_worker = random.choice(all_type_workers)
                    self.logger.info("[CLIENT_MANAGER] Using random available worker as last resort",
                                   worker_id=random_worker.info.client_id,
                                   executor_type=executor_type)
                    return random_worker
                
                return None
            
            available_workers = filtered_workers

        if not available_workers:
            self.logger.warning("[CLIENT_MANAGER] No workers after filtering",
                              task_type=task_type,
                              executor_type=executor_type,
                              worker_requirements=worker_requirements)
            return None

        # Вибір найкращого воркера (з найменшим навантаженням)
        best_worker = available_workers[0]
        self.logger.info("[CLIENT_MANAGER] Best worker selected",
                        worker_id=best_worker.info.client_id,
                        client_type=best_worker.info.client_type.value,
                        load_percentage=best_worker.info.get_load_percentage(),
                        capabilities=best_worker.info.capabilities.supported_task_types if best_worker.info.capabilities else None)
        return best_worker

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
                # ПОКРАЩЕННЯ: Розраховуємо час неактивності для діагностики
                inactive_time = None
                if client.info.stats.last_activity:
                    inactive_time = (datetime.utcnow() - client.info.stats.last_activity).total_seconds()
                elif client.info.last_pong:
                    inactive_time = (datetime.utcnow() - client.info.last_pong).total_seconds()

                self.logger.info("Removing unhealthy client",
                               client_id=client.info.client_id,
                               client_type=client.info.client_type.value,
                               last_activity=client.info.stats.last_activity.isoformat() if client.info.stats.last_activity else None,
                               last_pong=client.info.last_pong.isoformat() if client.info.last_pong else None,
                               inactive_time_seconds=inactive_time,
                               timeout_threshold=self.settings.websocket_timeout)

                # ПОКРАЩЕННЯ: Активне закриття WebSocket перед видаленням клієнта
                if client.websocket:
                    try:
                        # Надсилаємо код 1001 (Going Away) з причиною неактивності
                        await client.websocket.close(code=1001, reason="Client inactive")
                        self.logger.debug("WebSocket closed for inactive client",
                                        client_id=client.info.client_id)
                    except Exception as websocket_error:
                        # Логуємо помилки закриття WebSocket, але не припиняємо cleanup
                        self.logger.debug("Failed to close WebSocket for inactive client",
                                        client_id=client.info.client_id,
                                        error=str(websocket_error))

                # Видаляємо клієнта з менеджера
                await self.remove_client(client.info.client_id)

        except Exception as e:
            self.logger.error("Error cleaning up unhealthy clients", error=str(e))

    def __bool__(self) -> bool:
        """Булеве значення - True якщо менеджер ініціалізований"""
        return self.is_running

    def __len__(self) -> int:
        """Кількість клієнтів"""
        return len(self.clients)

    def __contains__(self, client_id: str) -> bool:
        """Перевірка наявності клієнта"""
        return client_id in self.clients

    def __iter__(self):
        """Ітератор по клієнтах"""
        return iter(self.clients.values())
