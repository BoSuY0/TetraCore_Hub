"""
TetraCore StreamHub Main Class

Головний клас StreamHub, який координує всю роботу системи:
- Управління WebSocket з'єднаннями
- Маршрутизація завдань між ботом і воркерами
- Інтеграція з Redis для Pub/Sub
- Моніторинг здоров'я клієнтів
- Збір метрик та статистики
"""

# Standard library
import asyncio
import logging
import json
from datetime import datetime
from typing import Dict, List, Optional, Any, cast
from contextlib import asynccontextmanager
import os

# Third-party libraries
import fastapi  # type: ignore  # noqa: F401 (used for typing and sub-modules)
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException  # type: ignore
from fastapi.middleware.cors import CORSMiddleware  # type: ignore
from fastapi.staticfiles import StaticFiles  # type: ignore

import structlog  # type: ignore

from config import Settings, get_settings, is_heroku_environment
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
from core.security_integration import security_integration, integrate_security
from core.async_optimization import AsyncOptimizer
# Celery task queue видалено - завдання тепер обробляються через tetra-core-api
# Removed old dashboard imports - now using React SPA


class StreamHub:
    """Головний клас StreamHub"""

    def __init__(self, settings: Optional[Settings] = None):
        """Ініціалізація StreamHub"""
        self.settings = settings or get_settings()
        self.logger = structlog.get_logger(__name__)

        # Основні компоненти
        self.client_manager: Optional[ClientManager] = None
        self.async_optimizer: Optional[AsyncOptimizer] = None
        # task_queue_manager видалено - завдання тепер обробляються через tetra-core-api
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

            # Ініціалізація асинхронного оптимізатора
            self.async_optimizer = AsyncOptimizer(
                max_workers=self.settings.worker_pool_size,
                max_tasks=self.settings.message_queue_size
            )
            await self.async_optimizer.initialize()

            # Celery task queue видалено - завдання тепер обробляються через tetra-core-api
            self.logger.info("Task processing delegated to tetra-core-api workers")

            # Ініціалізація менеджерів
            self.client_manager = ClientManager(self.settings)
            self.task_router = TaskRouter(self.settings, self.redis_manager)
            self.websocket_manager = WebSocketManager(self.settings)
            self.health_monitor = HealthMonitor(self.settings, self.client_manager)
            self.metrics_collector = MetricsCollector(self.settings)

            # Встановлення зв'язків між компонентами
            if self.task_router and self.client_manager:
                self.task_router.set_client_manager(self.client_manager)
            if self.health_monitor and self.client_manager:
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
        if self.client_manager:
            self.client_manager.on_client_connected = self._on_client_connected
            self.client_manager.on_client_disconnected = self._on_client_disconnected

        # Обробники подій завдань
        if self.task_router:
            self.task_router.on_task_assigned = self._on_task_assigned
            self.task_router.on_task_completed = self._on_task_completed
            self.task_router.on_task_failed = self._on_task_failed

        # Обробники подій здоров'я
        if self.health_monitor:
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

        # Статична перевірка: self.app тепер гарантовано не None
        assert self.app is not None

        # Налаштування CORS
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=self.settings.allowed_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["*"]
        )

        integrate_security(
            self.app,
            # type: ignore[attr-defined] – атрибут client додається під час ініціалізації RedisManager
            redis_client=cast(Any, self.redis_manager).client if self.redis_manager else None,
            require_auth=self.settings.require_authentication,
        )

        # Детальне логування URL конфігурації
        self.logger.info("URL Configuration",
                        backend_url=self.settings.get_backend_url(),
                        frontend_url=self.settings.get_frontend_url(),
                        dashboard_url=self.settings.get_dashboard_url(),
                        websocket_url=self.settings.get_websocket_url(),
                        is_heroku=is_heroku_environment(),
                        host=self.settings.host,
                        port=self.settings.port)

        # Templates removed - using React SPA instead

        # Підключення статичних файлів (якщо директорія існує)
        if os.path.exists("frontend/build"):
            self.app.mount("/static", StaticFiles(directory="frontend/build/static"), name="static")

        # Налаштування дашборду (перед загальними роутами)
        self._setup_dashboard()

        # Реєстрація роутів
        self._register_routes()

    def _register_routes(self):
        """Реєстрація HTTP та WebSocket роутів"""

        # Auth router is now included in security integration

        @self.app.options("/{path:path}")  # type: ignore[attr-defined]
        async def options_handler(path: str):
            """Обробка CORS preflight запитів"""
            from fastapi.responses import Response  # type: ignore
            return Response(status_code=200)

        @self.app.websocket("/ws")  # type: ignore[attr-defined]
        async def websocket_endpoint(websocket: WebSocket):
            """WebSocket endpoint with authentication"""
            await self.handle_websocket_connection(websocket)

        @self.app.get("/health")  # type: ignore[attr-defined]
        async def health_check():
            """Перевірка здоров'я системи"""
            return await self.get_health_status()

        @self.app.get("/config")  # type: ignore[attr-defined]
        async def get_app_config():
            """Отримання конфігурації додатку для frontend"""
            return {
                "backend_url": self.settings.get_backend_url(),
                "frontend_url": self.settings.get_frontend_url(),
                "dashboard_url": self.settings.get_dashboard_url(),
                "websocket_url": self.settings.get_websocket_url(),
                "environment": self.settings.environment.value,
                "version": "1.0.0"
            }

        @self.app.get("/metrics")  # type: ignore[attr-defined]
        async def get_metrics():
            """Отримання метрик системи"""
            return await self.get_system_metrics()

        @self.app.get("/clients")  # type: ignore[attr-defined]
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

        @self.app.get("/tasks")  # type: ignore[attr-defined]
        async def get_tasks():
            """Отримання інформації про завдання"""
            if not self.task_router:
                raise HTTPException(status_code=503, detail="StreamHub not initialized")

            return await self.task_router.get_queue_stats()

        @self.app.post("/tasks/{task_id}/cancel")  # type: ignore[attr-defined]
        async def cancel_task(task_id: str):
            """Скасування завдання"""
            if not self.task_router:
                raise HTTPException(status_code=503, detail="StreamHub not initialized")

            success = await self.task_router.cancel_task(task_id)
            if not success:
                raise HTTPException(status_code=404, detail="Task not found")

            return {"message": "Task cancelled successfully"}

        @self.app.get("/")  # type: ignore[attr-defined]
        async def serve_react_app():
            """Сервіс React додатку"""
            from fastapi.responses import FileResponse  # type: ignore
            """Serve React app for root and dashboard routes"""
            if os.path.exists('frontend/build/index.html'):
                return FileResponse('frontend/build/index.html')
            else:
                return {"message": "TetraCore StreamHub API", "status": "running", "frontend": "not built"}

        @self.app.get("/{path:path}")  # type: ignore[attr-defined]
        async def serve_react_routes(path: str):
            """Сервіс React роутів (SPA fallback)"""
            from fastapi.responses import FileResponse  # type: ignore

            # Якщо це API роут, не обробляємо тут (виключили dashboard/ для React Router)
            if path.startswith(('api/', 'dashboard/api/', 'health', 'metrics', 'clients', 'tasks', 'ws')):
                raise HTTPException(status_code=404, detail="Not found")

            # Перевіряємо чи існує статичний файл (CSS, JS, images тощо)
            file_path = f"static/{path}"
            if os.path.isfile(file_path):
                return FileResponse(file_path)

            # Для всіх інших роутів (включно з dashboard/) повертаємо index.html (SPA роутинг)
            """Serve React app for all unmatched routes (React Router support)"""
            if os.path.exists('frontend/build/index.html'):
                return FileResponse('frontend/build/index.html')
            else:
                raise HTTPException(status_code=404, detail="Frontend not built")

    async def handle_websocket_connection(self, websocket: WebSocket):
        """Обробка WebSocket підключення"""
        from core.websocket_security import ws_security_manager

        try:
            # Authenticate WebSocket connection before accepting
            token = websocket.query_params.get("token")
            user_data = await ws_security_manager.authenticate_websocket(websocket, token)

            if not user_data:
                await websocket.close(code=1008, reason="Authentication failed")
                return

            # Accept connection after successful authentication
            await websocket.accept()
            self.total_connections += 1

            # Register connection with security manager
            conn_info = await ws_security_manager.accept_connection(websocket, user_data)
            if not conn_info:
                await websocket.close(code=1008, reason="Connection rejected")
                return

            self.logger.info("New authenticated WebSocket connection",
                           user_id=user_data["user_id"],
                           remote_addr=websocket.client.host if websocket.client else "unknown")

            # Очікування реєстрації клієнта з автентифікованими даними
            client = await self._handle_client_registration(websocket, user_data)
            if not client:
                await ws_security_manager.disconnect_client(conn_info.client_id)
                await websocket.close(code=4001, reason="Registration failed")
                return

            # Store client_id for security tracking
            client.security_client_id = conn_info.client_id

            # Додавання клієнта до менеджера
            if self.client_manager:
                await self.client_manager.add_client(client)

            # Обробка повідомлень від клієнта
            await self._handle_client_messages(client, websocket)

        except WebSocketDisconnect:
            self.logger.info("WebSocket connection closed")
        except Exception as e:
            self.logger.error("WebSocket connection error", error=str(e))
            self.total_errors += 1
        finally:
            if 'client' in locals() and client is not None and self.client_manager:
                await self.client_manager.remove_client(client.info.client_id)

    async def _handle_client_registration(self, websocket: WebSocket, user_data: Dict[str, Any]) -> Optional[Client]:
        """Обробка реєстрації клієнта з автентифікованими даними"""
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
                self.logger.info("🤖 Bot client registered successfully",
                               client_id=message.client_id,
                               client_name=message.client_name,
                               remote_address=websocket.client.host if websocket.client else "unknown")
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
                self.logger.info("⚙️ Worker client registered successfully",
                               client_id=message.client_id,
                               client_name=message.client_name,
                               remote_address=websocket.client.host if websocket.client else "unknown")
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
                self.logger.info("✅ API Worker registered successfully",
                               client_id=message.client_id,
                               client_name=message.client_name,
                               remote_address=websocket.client.host if websocket.client else "unknown")
            elif message.client_type == ClientType.MONITOR:
                client = Client.create_monitor(
                    client_id=message.client_id,
                    client_name=message.client_name,
                    remote_address=websocket.client.host if websocket.client else "unknown"
                )
                self.logger.info("📊 Monitor client registered successfully",
                               client_id=message.client_id,
                               client_name=message.client_name,
                               remote_address=websocket.client.host if websocket.client else "unknown")
            elif message.client_type == ClientType.STREAM_HUB:
                client = Client.create_stream_hub(
                    client_id=message.client_id,
                    client_name=message.client_name,
                    remote_address=websocket.client.host if websocket.client else "unknown"
                )
                self.logger.info("🌐 StreamHub client registered successfully",
                               client_id=message.client_id,
                               client_name=message.client_name,
                               remote_address=websocket.client.host if websocket.client else "unknown")
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

            # Фінальне логування успішної реєстрації
            self.logger.info("✅ Client successfully connected to StreamHub",
                             client_id=client.info.client_id,
                             client_type=client.info.client_type.value,
                             session_id=client.info.session_id)

            return client

        except Exception as e:
            self.logger.error("Client registration failed", error=str(e))
            await self._send_error(websocket, "REGISTRATION_ERROR", str(e))
            return None

    async def _handle_client_messages(self, client: Client, websocket: WebSocket):
        """Обробка повідомлень від клієнта"""
        from core.websocket_security import ws_security_manager

        try:
            while True:
                raw_data = await websocket.receive_text()

                # Validate message using security manager
                if hasattr(client, 'security_client_id'):
                    validated_message = await ws_security_manager.validate_message(
                        client.security_client_id,
                        raw_data
                    )

                    if not validated_message:
                        self.logger.warning("Invalid message received",
                                          client_id=client.info.client_id)
                        continue

                    # Parse validated message data
                    message = parse_message(validated_message.data)
                else:
                    # Fallback for legacy connections (should be removed in future)
                    if self.async_optimizer:
                        data = await self.async_optimizer.json_loads(raw_data)
                    else:
                        # Фолбек на стандартний json.loads у малоймовірному випадку, коли async_optimizer не ініціалізовано
                        data = json.loads(raw_data)
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
        success = False
        if self.task_router:
            success = await self.task_router.submit_task(task)

        if success:
            self.total_tasks_processed += 1
            # Зменшуємо рівень логування для зменшення шуму в продакшн
            self.logger.debug("Task submitted successfully",
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
        if self.task_router:
            await self.task_router.handle_task_result(
                task_id=getattr(message, 'task_id', ''),
                worker_id=client.info.client_id,
                status=getattr(message, 'status', TaskStatus.FAILED),
                result=getattr(message, 'result', {}) or {},
                error_message=getattr(message, 'error_message', '') or '',
                execution_time=getattr(message, 'execution_time', 0) or 0,
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

        if client.websocket:
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

        if client.websocket:
            await client.websocket.send_json(response.model_dump(mode='json'))

    async def _handle_metrics_request(self, client: Client, message: BaseMessage):
        """Обробка запиту метрик"""
        metrics = {}
        if self.metrics_collector:
            metrics = await self.metrics_collector.get_metrics(
                metric_types=getattr(message, 'metric_types', [])
            )

        response = create_message(
            MessageType.METRICS_RESPONSE,
            correlation_id=message.correlation_id,
            metrics=metrics
        )

        if client.websocket:
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
        # 1. Dashboard / monitor клієнти вже проходять JWT-аутентифікацію під час
        #    встановлення WebSocket-зʼєднання, тому їм не потрібен додатковий
        #    static auth_token. Дозволяємо реєстрацію, щоб уникнути помилки
        #    «AUTH_FAILED» та циклів reconnection на фронтенді.
        from models.client import ClientType  # Локальний імпорт, щоб уникнути циклічних залежностей

        if message.client_type == ClientType.MONITOR:
            return True

        # 2. Якщо глобальний static AUTH_TOKEN не налаштований – додаткова
        #    перевірка не потрібна.
        if not self.settings.auth_token:
            return True

        # 3. Для усіх інших клієнтів вимагаємо збіг із налаштованим AUTH_TOKEN.
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
        # Зменшуємо рівень логування для зменшення шуму в продакшн
        self.logger.debug("Client connected",
                         client_id=client.info.client_id,
                         client_type=client.info.client_type.value)

        # Оновлення метрик
        if self.metrics_collector:
            self.metrics_collector.increment_counter("clients_connected")

    async def _on_client_disconnected(self, client: Client):
        """Обробник відключення клієнта"""
        # Зменшуємо рівень логування для зменшення шуму в продакшн
        self.logger.debug("Client disconnected",
                         client_id=client.info.client_id,
                         client_type=client.info.client_type.value)

        # Переназначення активних завдань воркера
        if client.info.is_worker() and client.active_tasks:
            if self.task_router:
                await self.task_router.reassign_worker_tasks(client.info.client_id)

    async def _on_task_assigned(self, task: Task, worker_id: str):
        """Обробник призначення завдання"""
        # Зменшуємо рівень логування для зменшення шуму в продакшн
        self.logger.debug("Task assigned",
                         task_id=task.task_id,
                         worker_id=worker_id)

    async def _on_task_completed(self, task: Task):
        """Обробник завершення завдання"""
        # Зменшуємо рівень логування для зменшення шуму в продакшн
        self.logger.debug("Task completed",
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
        if self.task_router:
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

    async def broadcast_message(self, message: BaseMessage, target_clients: Optional[List[ClientType]] = None):
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

        if self.async_optimizer:
            await self.async_optimizer.shutdown()

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
            if self.client_manager:
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
