"""
TetraCore StreamHub Main Class

Головний клас StreamHub, який координує всю роботу системи:
- Управління WebSocket з'єднаннями
- Маршрутизація завдань між ботом і воркерами
- Інтеграція з Redis для Pub/Sub
- Моніторинг здоров'я клієнтів
- Збір метрик та статистики
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import structlog

from config import Settings, get_settings
from models.messages import (
    BaseMessage, MessageType, parse_message, create_message
)
from models.client import Client, ClientType, ClientInfo, ConnectionStatus, WorkerCapabilities
from models.task import Task, TaskStatus, TaskPriority
from core.client_manager import ClientManager
from core.task_router import TaskRouter
from core.websocket_manager import WebSocketManager
from core.health_monitor import HealthMonitor
from core.metrics_collector import MetricsCollector
from core.redis_manager import RedisManager
# Removed old dashboard imports - now using React SPA


class StreamHub:
    """Головний клас StreamHub"""

    def __init__(self, settings: Settings = None):
        """Ініціалізація StreamHub"""
        self.settings = settings or get_settings()
        self.logger = structlog.get_logger(__name__)

        # Основні компоненти
        self.client_manager: Optional[ClientManager] = None
        self.task_router: Optional[TaskRouter] = None
        self.redis_manager: Optional[RedisManager] = None
        self.websocket_manager: Optional[WebSocketManager] = None
        self.health_monitor: Optional[HealthMonitor] = None
        self.metrics_collector: Optional[MetricsCollector] = None

        # FastAPI додаток
        self.app: Optional[FastAPI] = None

        # Статус системи
        self.is_running = False
        self.start_time: Optional[datetime] = None

        # Лічильники
        self.total_connections = 0
        self.total_tasks_processed = 0
        self.total_errors = 0
        
        # Задачі
        self.self_client_task: Optional[asyncio.Task] = None

    async def initialize(self):
        """Ініціалізація всіх компонентів"""
        try:
            self.logger.info("Initializing StreamHub", version="1.0.0")

            # Ініціалізація Redis (якщо увімкнено)
            if self.settings.redis_enabled:
                self.logger.info("Redis enabled, initializing Redis manager...")
                self.redis_manager = RedisManager(self.settings)
                await self.redis_manager.initialize()
            else:
                self.logger.info("Redis disabled, skipping Redis initialization")
                self.redis_manager = None

            # Ініціалізація менеджерів
            self.client_manager = ClientManager(self.settings)
            self.task_router = TaskRouter(self.settings, self.redis_manager)
            self.websocket_manager = WebSocketManager(self.settings)
            self.health_monitor = HealthMonitor(self.settings, self.client_manager)
            self.metrics_collector = MetricsCollector(self.settings)

            # Встановлення зв'язків між компонентами
            self.task_router.set_client_manager(self.client_manager)
            self.health_monitor.client_manager = self.client_manager

            # Ініціалізація компонентів
            await self.client_manager.initialize()
            await self.task_router.initialize()
            await self.websocket_manager.initialize()
            await self.health_monitor.initialize()
            await self.metrics_collector.initialize()

            # Налаштування подієвих обробників
            self._setup_event_handlers()

            # Самореєстрація як клієнт
            await self._register_self_as_client()

            self.start_time = datetime.utcnow()
            self.is_running = True

            self.logger.info("StreamHub initialized successfully")

        except Exception as e:
            self.logger.error("Failed to initialize StreamHub", error=str(e))
            raise

    def _setup_event_handlers(self):
        """Налаштування обробників подій"""

        # Обробники подій клієнтів
        self.client_manager.on_client_connected = self._on_client_connected
        self.client_manager.on_client_disconnected = self._on_client_disconnected

        # Обробники подій завдань
        self.task_router.on_task_assigned = self._on_task_assigned
        self.task_router.on_task_completed = self._on_task_completed
        self.task_router.on_task_failed = self._on_task_failed

        # Обробники подій здоров'я
        self.health_monitor.on_client_unhealthy = self._on_client_unhealthy

        # Обробники Redis подій (якщо Redis увімкнено)
        if self.redis_manager:
            self.redis_manager.on_message_received = self._on_redis_message

    def _create_fastapi_app(self):
        """Створення FastAPI додатка"""

        # Використовуємо зовнішній lifespan якщо він є
        lifespan = getattr(self, 'lifespan', None)

        self.app = FastAPI(
            title="TetraCore StreamHub",
            description="Централізований хаб для маршрутизації завдань",
            version="1.0.0",
            lifespan=lifespan
        )

        # CORS middleware
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=self.settings.allowed_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # Templates removed - using React SPA instead

        # Підключення статичних файлів (якщо директорія існує)
        import os
        if os.path.exists("static"):
            self.app.mount("/static", StaticFiles(directory="static"), name="static")

        # Налаштування дашборду (перед загальними роутами)
        self._setup_dashboard()

        # Реєстрація роутів
        self._register_routes()

    def _register_routes(self):
        """Реєстрація HTTP та WebSocket роутів"""

        # Підключення auth router
        try:
            from web.auth import auth_router
            self.app.include_router(auth_router)
        except ImportError as e:
            self.logger.warning("Auth router not available", error=str(e))

        @self.app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket):
            await self.handle_websocket_connection(websocket)

        @self.app.get("/health")
        async def health_check():
            """Перевірка здоров'я системи"""
            return await self.get_health_status()

        @self.app.get("/metrics")
        async def get_metrics():
            """Отримання метрик системи"""
            return await self.get_system_metrics()

        @self.app.get("/clients")
        async def get_clients():
            """Отримання списку підключених клієнтів"""
            if not self.client_manager or not self.client_manager.is_healthy():
                return {
                    "clients": [],
                    "total_count": 0
                }

            return {
                "clients": [client.to_dict() for client in self.client_manager.get_all_clients()],
                "total_count": self.client_manager.get_client_count()
            }

        @self.app.get("/tasks")
        async def get_tasks():
            """Отримання інформації про завдання"""
            if not self.task_router:
                raise HTTPException(status_code=503, detail="StreamHub not initialized")

            return await self.task_router.get_queue_stats()

        @self.app.post("/tasks/{task_id}/cancel")
        async def cancel_task(task_id: str):
            """Скасування завдання"""
            if not self.task_router:
                raise HTTPException(status_code=503, detail="StreamHub not initialized")

            success = await self.task_router.cancel_task(task_id)
            if not success:
                raise HTTPException(status_code=404, detail="Task not found")

            return {"message": "Task cancelled successfully"}

        @self.app.get("/")
        async def serve_react_app():
            """Сервіс React додатку"""
            from fastapi.responses import FileResponse
            import os
            if os.path.exists('static/index.html'):
                return FileResponse('static/index.html')
            else:
                return {"message": "TetraCore StreamHub API", "status": "running", "frontend": "not built"}

        @self.app.get("/{path:path}")
        async def serve_react_routes(path: str):
            """Сервіс React роутів (SPA fallback)"""
            from fastapi.responses import FileResponse
            import os

            # Якщо це API роут, не обробляємо тут (виключили dashboard/ для React Router)
            if path.startswith(('api/', 'dashboard/api/', 'health', 'metrics', 'clients', 'tasks', 'ws')):
                raise HTTPException(status_code=404, detail="Not found")

            # Перевіряємо чи існує статичний файл (CSS, JS, images тощо)
            file_path = f"static/{path}"
            if os.path.isfile(file_path):
                return FileResponse(file_path)

            # Для всіх інших роутів (включно з dashboard/) повертаємо index.html (SPA роутинг)
            if os.path.exists('static/index.html'):
                return FileResponse('static/index.html')
            else:
                raise HTTPException(status_code=404, detail="Frontend not built")

    async def handle_websocket_connection(self, websocket: WebSocket):
        """Обробка WebSocket підключення"""
        try:
            await websocket.accept()
            self.total_connections += 1

            self.logger.info("New WebSocket connection",
                           remote_addr=websocket.client.host if websocket.client else "unknown")

            # Очікування реєстрації клієнта
            client = await self._handle_client_registration(websocket)
            if not client:
                await websocket.close(code=4001, reason="Registration failed")
                return

            # Додавання клієнта до менеджера
            await self.client_manager.add_client(client)

            # Обробка повідомлень від клієнта
            await self._handle_client_messages(client, websocket)

        except WebSocketDisconnect:
            self.logger.info("WebSocket connection closed")
        except Exception as e:
            self.logger.error("WebSocket connection error", error=str(e))
            self.total_errors += 1
        finally:
            if 'client' in locals() and client is not None:
                await self.client_manager.remove_client(client.info.client_id)

    async def _handle_client_registration(self, websocket: WebSocket) -> Optional[Client]:
        """Обробка реєстрації клієнта"""
        try:
            # Очікування повідомлення реєстрації
            self.logger.info("Waiting for client registration message")
            data = await websocket.receive_json()
            self.logger.info("Received registration data", data_keys=list(data.keys()), 
                           message_type=data.get("message_type"))
            
            # Парсинг повідомлення
            try:
                message = parse_message(data)
                self.logger.info("Message parsed successfully", 
                               message_type=message.message_type,
                               client_type=getattr(message, 'client_type', 'unknown'),
                               client_id=getattr(message, 'client_id', 'unknown'))
            except Exception as parse_error:
                self.logger.error("Failed to parse registration message", 
                                error=str(parse_error), raw_data=data)
                await self._send_error(websocket, "PARSE_ERROR", f"Failed to parse message: {str(parse_error)}")
                return None

            if message.message_type != MessageType.CLIENT_REGISTRATION:
                self.logger.warning("Invalid message type for registration", 
                                  expected="client_registration",
                                  received=message.message_type)
                await self._send_error(websocket, "INVALID_REGISTRATION",
                                     "First message must be client registration")
                return None

            # Перевірка аутентифікації
            auth_result = self._authenticate_client(message)
            self.logger.info("Authentication check", 
                           auth_required=bool(self.settings.auth_token),
                           auth_result=auth_result,
                           client_token=bool(getattr(message, 'auth_token', None)))
            
            if not auth_result:
                self.logger.warning("Authentication failed for client", 
                                  client_id=getattr(message, 'client_id', 'unknown'))
                await self._send_error(websocket, "AUTH_FAILED", "Authentication failed")
                return None

            # Створення клієнта
            self.logger.info("Creating client", client_type=message.client_type, 
                           client_id=message.client_id, client_name=message.client_name)
            
            if message.client_type == ClientType.BOT:
                client = Client.create_bot(
                    client_id=message.client_id,
                    client_name=message.client_name,
                    remote_address=websocket.client.host if websocket.client else "unknown"
                )
            elif message.client_type == ClientType.WORKER:
                capabilities = WorkerCapabilities(
                    supported_task_types=getattr(message, 'capabilities', []) or [],
                    max_concurrent_tasks=getattr(message, 'max_concurrent_tasks', 1) or 1
                )
                client = Client.create_worker(
                    client_id=message.client_id,
                    client_name=message.client_name,
                    capabilities=capabilities,
                    remote_address=websocket.client.host if websocket.client else "unknown"
                )
            elif message.client_type == ClientType.WORKER_API:
                capabilities = WorkerCapabilities(
                    supported_task_types=getattr(message, 'capabilities', []) or [],
                    max_concurrent_tasks=getattr(message, 'max_concurrent_tasks', 1) or 1
                )
                client = Client.create_worker_api(
                    client_id=message.client_id,
                    client_name=message.client_name,
                    capabilities=capabilities,
                    remote_address=websocket.client.host if websocket.client else "unknown"
                )
            elif message.client_type == ClientType.MONITOR:
                client = Client.create_monitor(
                    client_id=message.client_id,
                    client_name=message.client_name,
                    remote_address=websocket.client.host if websocket.client else "unknown"
                )
            elif message.client_type == ClientType.STREAM_HUB:
                client = Client.create_stream_hub(
                    client_id=message.client_id,
                    client_name=message.client_name,
                    remote_address=websocket.client.host if websocket.client else "unknown"
                )
            elif message.client_type == ClientType.ADMIN:
                client = Client.create_admin(
                    client_id=message.client_id,
                    client_name=message.client_name,
                    remote_address=websocket.client.host if websocket.client else "unknown"
                )
            else:
                await self._send_error(websocket, "INVALID_CLIENT_TYPE",
                                     f"Unsupported client type: {message.client_type}")
                return None

            # Підключення клієнта
            self.logger.info("Connecting client to websocket", client_id=client.info.client_id)
            client.connect(websocket)

            # Відправка підтвердження реєстрації
            self.logger.info("Creating registration acknowledgment", client_id=client.info.client_id)
            ack_message = create_message(
                MessageType.REGISTRATION_ACK,
                client_id=client.info.client_id,
                session_id=client.info.session_id,
                config=self._get_client_config(client)
            )

            self.logger.info("Sending registration acknowledgment", 
                           client_id=client.info.client_id,
                           session_id=client.info.session_id)
            
            # Використовуємо model_dump з mode='json' для правильної серіалізації datetime
            ack_data = ack_message.model_dump(mode='json')
            await websocket.send_json(ack_data)

            self.logger.info("Client registered successfully",
                           client_id=client.info.client_id,
                           client_type=client.info.client_type.value)

            return client

        except Exception as e:
            self.logger.error("Client registration failed", error=str(e))
            await self._send_error(websocket, "REGISTRATION_ERROR", str(e))
            return None

    async def _handle_client_messages(self, client: Client, websocket: WebSocket):
        """Обробка повідомлень від клієнта"""
        try:
            while True:
                data = await websocket.receive_json()
                message = parse_message(data)

                # Оновлення часу останньої активності
                client.info.stats.last_activity = datetime.utcnow()

                # Обробка повідомлення
                await self._process_client_message(client, message)

        except WebSocketDisconnect:
            self.logger.info("Client disconnected", client_id=client.info.client_id)
        except Exception as e:
            self.logger.error("Error processing client message",
                            client_id=client.info.client_id, error=str(e))
            await self._send_error(websocket, "PROCESSING_ERROR", str(e))

    async def _process_client_message(self, client: Client, message: BaseMessage):
        """Обробка повідомлення від клієнта"""
        try:
            if message.message_type == MessageType.TASK_SUBMIT:
                # Обробка нового завдання від бота
                await self._handle_task_submission(client, message)

            elif message.message_type == MessageType.TASK_RESULT:
                # Обробка результату завдання від воркера
                await self._handle_task_result(client, message)

            elif message.message_type == MessageType.PING:
                # Обробка ping запиту
                await self._handle_ping(client, message)

            elif message.message_type == MessageType.HEALTH_CHECK:
                # Обробка перевірки здоров'я
                await self._handle_health_check(client, message)

            elif message.message_type == MessageType.METRICS_REQUEST:
                # Обробка запиту метрик
                await self._handle_metrics_request(client, message)

            else:
                self.logger.warning("Unknown message type",
                                  message_type=message.message_type,
                                  client_id=client.info.client_id)

        except Exception as e:
            self.logger.error("Error processing message",
                            message_type=message.message_type,
                            client_id=client.info.client_id,
                            error=str(e))

    async def _handle_task_submission(self, client: Client, message: BaseMessage):
        """Обробка подання завдання від бота"""
        if not client.info.is_bot():
            await self._send_error(client.websocket, "UNAUTHORIZED",
                                 "Only bots can submit tasks")
            return

        # Створення завдання з безпечним отриманням атрибутів
        from models.task import TaskType
        
        task_type_str = getattr(message, 'task_type', 'custom')
        task_type = TaskType.CUSTOM if isinstance(task_type_str, str) else task_type_str
        
        task = Task.create(
            task_type=task_type,
            data=getattr(message, 'task_data', {}),
            priority=getattr(message, 'priority', TaskPriority.NORMAL),
            timeout=getattr(message, 'timeout', 300),
            max_retries=getattr(message, 'max_retries', 3),
            worker_requirements=getattr(message, 'worker_requirements', [])
        )

        task.context.client_id = client.info.client_id
        task.context.correlation_id = getattr(message, 'correlation_id', None)

        # Додавання завдання до маршрутизатора
        success = await self.task_router.submit_task(task)

        if success:
            self.total_tasks_processed += 1
            self.logger.info("Task submitted successfully",
                           task_id=task.task_id,
                           client_id=client.info.client_id)
        else:
            await self._send_error(client.websocket, "TASK_REJECTED",
                                 "Task queue is full or task rejected")

    async def _handle_task_result(self, client: Client, message: BaseMessage):
        """Обробка результату завдання від воркера"""
        if not client.info.is_worker():
            await self._send_error(client.websocket, "UNAUTHORIZED",
                                 "Only workers can submit task results")
            return

        # Обробка результату через маршрутизатор з безпечним отриманням атрибутів
        await self.task_router.handle_task_result(
            task_id=getattr(message, 'task_id', ''),
            worker_id=client.info.client_id,
            status=getattr(message, 'status', TaskStatus.FAILED),
            result=getattr(message, 'result', None),
            error_message=getattr(message, 'error_message', None),
            execution_time=getattr(message, 'execution_time', None)
        )

    async def _handle_ping(self, client: Client, message: BaseMessage):
        """Обробка ping запиту"""
        client.ping()

        # Відправка pong відповіді
        pong_message = create_message(
            MessageType.PONG,
            client_id=client.info.client_id,
            correlation_id=message.correlation_id
        )

        await client.websocket.send_json(pong_message.model_dump(mode='json'))
        client.pong()

    async def _handle_health_check(self, client: Client, message: BaseMessage):
        """Обробка перевірки здоров'я"""
        health_status = {
            "healthy": client.is_healthy(),
            "status_details": {
                "active_tasks": client.info.stats.active_tasks,
                "total_tasks": client.info.stats.total_tasks,
                "current_load": client.info.get_load_percentage(),
                "uptime": (datetime.utcnow() - client.info.stats.connected_at).total_seconds()
            }
        }

        response = create_message(
            MessageType.HEALTH_STATUS,
            client_id=client.info.client_id,
            correlation_id=message.correlation_id,
            **health_status
        )

        await client.websocket.send_json(response.model_dump(mode='json'))

    async def _handle_metrics_request(self, client: Client, message: BaseMessage):
        """Обробка запиту метрик"""
        metrics = await self.metrics_collector.get_metrics(
            metric_types=getattr(message, 'metric_types', [])
        )

        response = create_message(
            MessageType.METRICS_RESPONSE,
            correlation_id=message.correlation_id,
            metrics=metrics
        )

        await client.websocket.send_json(response.model_dump(mode='json'))

    async def _send_error(self, websocket: WebSocket, error_code: str, error_message: str):
        """Відправка повідомлення про помилку"""
        error_msg = create_message(
            MessageType.ERROR,
            error_code=error_code,
            error_message=error_message
        )

        try:
            await websocket.send_json(error_msg.model_dump(mode='json'))
        except:
            pass  # WebSocket може бути закритий

    def _authenticate_client(self, message: BaseMessage) -> bool:
        """Аутентифікація клієнта"""
        if not self.settings.auth_token:
            return True  # Аутентифікація вимкнена

        return getattr(message, 'auth_token', None) == self.settings.auth_token

    def _get_client_config(self, client: Client) -> Dict[str, Any]:
        """Отримання конфігурації для клієнта"""
        return {
            "heartbeat_interval": self.settings.websocket_heartbeat_interval,
            "max_message_size": 1024 * 1024,  # 1MB
            "supported_features": ["heartbeat", "compression", "metrics"]
        }

    # Event handlers
    async def _on_client_connected(self, client: Client):
        """Обробник підключення клієнта"""
        self.logger.info("Client connected",
                        client_id=client.info.client_id,
                        client_type=client.info.client_type.value)

        # Оновлення метрик
        self.metrics_collector.increment_counter("clients_connected")

    async def _on_client_disconnected(self, client: Client):
        """Обробник відключення клієнта"""
        self.logger.info("Client disconnected",
                        client_id=client.info.client_id,
                        client_type=client.info.client_type.value)

        # Переназначення активних завдань воркера
        if client.info.is_worker() and client.active_tasks:
            await self.task_router.reassign_worker_tasks(client.info.client_id)

    async def _on_task_assigned(self, task: Task, worker_id: str):
        """Обробник призначення завдання"""
        self.logger.info("Task assigned",
                        task_id=task.task_id,
                        worker_id=worker_id)

    async def _on_task_completed(self, task: Task):
        """Обробник завершення завдання"""
        self.logger.info("Task completed",
                        task_id=task.task_id,
                        status=task.context.current_status.value,
                        execution_time=task.context.get_execution_time())

    async def _on_task_failed(self, task: Task, error: str):
        """Обробник помилки завдання"""
        self.logger.error("Task failed",
                         task_id=task.task_id,
                         error=error)

    async def _on_client_unhealthy(self, client_id: str):
        """Обробник нездорового клієнта"""
        self.logger.warning("Client unhealthy", client_id=client_id)

        # Переназначення завдань від нездорового воркера
        await self.task_router.reassign_worker_tasks(client_id)

    async def _on_redis_message(self, channel: str, message: Dict[str, Any]):
        """Обробник повідомлень Redis"""
        self.logger.debug("Redis message received", channel=channel)

    # Public API methods
    async def get_health_status(self) -> Dict[str, Any]:
        """Отримання статусу здоров'я системи"""
        return {
            "status": "healthy" if self.is_running else "unhealthy",
            "uptime": (datetime.utcnow() - self.start_time).total_seconds() if self.start_time else 0,
            "version": "1.0.0",
            "components": {
                "redis": await self.redis_manager.is_healthy() if self.redis_manager else False,
                "client_manager": self.client_manager.is_healthy() if self.client_manager else False,
                "task_router": self.task_router.is_healthy() if self.task_router else False,
            },
            "stats": {
                "total_connections": self.total_connections,
                "active_clients": self.client_manager.get_client_count() if self.client_manager else 0,
                "total_tasks_processed": self.total_tasks_processed,
                "total_errors": self.total_errors
            }
        }

    async def get_system_metrics(self) -> Dict[str, Any]:
        """Отримання системних метрик"""
        if not self.metrics_collector:
            return {}

        raw_metrics = await self.metrics_collector.get_all_metrics()

        # Transform data for frontend compatibility
        if 'system' in raw_metrics:
            system_data = raw_metrics['system']
            transformed_system = {
                'cpu_usage': system_data.get('cpu_percent', 0),
                'memory_usage': system_data.get('memory_percent', 0),
                'disk_usage': system_data.get('disk_percent', 0),
                'uptime': (datetime.utcnow() - self.start_time).total_seconds() if self.start_time else 0
            }
            raw_metrics['system'] = transformed_system

        # Add hub metrics if missing
        if 'hub' not in raw_metrics:
            raw_metrics['hub'] = {
                'total_connections': self.total_connections,
                'active_clients': self.client_manager.get_client_count() if self.client_manager else 0,
                'total_tasks_processed': self.total_tasks_processed,
                'tasks_per_second': 0,  # TODO: Calculate from recent tasks
                'average_response_time': 0,  # TODO: Calculate from recent responses
                'error_rate': 0  # TODO: Calculate from recent errors
            }

        # Add timestamp
        raw_metrics['timestamp'] = datetime.utcnow().isoformat()

        return raw_metrics

    async def broadcast_message(self, message: BaseMessage, target_clients: List[ClientType] = None):
        """Широкомовна розсилка повідомлення"""
        if not self.client_manager:
            return

        clients = self.client_manager.get_clients_by_type(target_clients) if target_clients else self.client_manager.get_all_clients()

        for client in clients:
            if client.websocket and client.info.is_connected():
                try:
                    await client.websocket.send_json(message.model_dump(mode='json'))
                except:
                    pass  # Ignore failed sends

    async def shutdown(self):
        """Завершення роботи StreamHub"""
        self.logger.info("Shutting down StreamHub")

        self.is_running = False

        # Зупинка задачі підтримки активності
        if self.self_client_task and not self.self_client_task.done():
            self.self_client_task.cancel()
            try:
                await self.self_client_task
            except asyncio.CancelledError:
                pass

        # Видалення самореєстрації
        if hasattr(self, 'self_client') and self.client_manager:
            try:
                await self.client_manager.remove_client("stream_hub_main")
                self.logger.info("StreamHub self-registration removed")
            except Exception as e:
                self.logger.error("Failed to remove StreamHub self-registration", error=str(e))

        # Закриття компонентів
        if self.health_monitor:
            await self.health_monitor.shutdown()

        if self.metrics_collector:
            await self.metrics_collector.shutdown()

        if self.task_router:
            await self.task_router.shutdown()

        if self.client_manager:
            await self.client_manager.shutdown()

        if self.redis_manager:
            await self.redis_manager.shutdown()

        self.logger.info("StreamHub shutdown complete")

    def _setup_dashboard(self):
        """Налаштування веб-дашборду (React SPA)"""
        try:
            # Імпорт та реєстрація dashboard роутів
            from web.dashboard import register_dashboard_routes
            register_dashboard_routes(self.app, self)

            # React додаток сервується через статичні файли
            # Всі налаштування роутів виконані в _register_routes
            self.logger.info("Dashboard configured successfully")
        except ImportError as e:
            self.logger.warning("Dashboard routes not available", error=str(e))
        except Exception as e:
            self.logger.error("Failed to setup dashboard", error=str(e))

    async def _register_self_as_client(self):
        """Реєстрація StreamHub як клієнта в системі"""
        try:
            # Створення клієнта StreamHub
            client_info = ClientInfo(
                client_id="stream_hub_main",
                client_type=ClientType.STREAM_HUB,
                client_name="StreamHub Main Server",
                client_version="1.0.0",
                remote_address="127.0.0.1",
                user_agent="StreamHub/1.0.0",
                metadata={
                    "description": "Головний сервер StreamHub",
                    "hostname": self.settings.host,
                    "port": self.settings.port,
                    "environment": self.settings.environment.value,
                    "start_time": datetime.utcnow().isoformat()
                },
                config={
                    "max_connections": self.settings.max_connections,
                    "websocket_timeout": self.settings.websocket_timeout,
                    "redis_enabled": self.settings.redis_enabled
                }
            )

            self.self_client = Client(info=client_info)

            # Встановлення статусу як підключений
            self.self_client.info.connection_status = ConnectionStatus.CONNECTED
            self.self_client.info.stats.last_activity = datetime.utcnow()

            # Додавання до менеджера клієнтів
            await self.client_manager.add_client(self.self_client)

            # Запуск задачі для підтримки активності
            self.self_client_task = asyncio.create_task(self._maintain_self_client_activity())

            self.logger.info("StreamHub registered as client",
                           client_id=client_info.client_id,
                           client_type=client_info.client_type.value)

        except Exception as e:
            self.logger.error("Failed to register StreamHub as client", error=str(e))

    async def _maintain_self_client_activity(self):
        """Підтримка активності внутрішнього клієнта StreamHub"""
        try:
            while self.is_running:
                if hasattr(self, 'self_client') and self.self_client:
                    # Оновлюємо час останньої активності
                    self.self_client.info.stats.last_activity = datetime.utcnow()
                    
                # Оновлюємо кожні 30 секунд
                await asyncio.sleep(30)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.logger.error("Error maintaining self client activity", error=str(e))

    def get_app(self) -> FastAPI:
        """Отримання FastAPI додатка"""
        if not self.app:
            # Створення FastAPI додатка без ініціалізації
            self._create_fastapi_app()
        return self.app
