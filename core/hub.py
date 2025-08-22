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
import uuid
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
    BaseMessage, MessageType, parse_message, create_message, StatsUpdate
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
from core.auth_manager import get_current_user
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

        # Backpressure: ліміт одночасних повідомлень, що опрацьовуються на клієнта
        # Налаштовується через SETTINGS.message_queue_size або ENV WS_MAX_INFLIGHT
        try:
            max_inflight = int(os.getenv("WS_MAX_INFLIGHT", "0"))
        except Exception:
            max_inflight = 0
        self.max_inflight_per_client = max_inflight or max(1, min(32, getattr(self.settings, "message_queue_size", 8)))
        self._client_inflight: Dict[str, int] = {}
        self._client_wait_queues: Dict[str, asyncio.Queue] = {}

        # Задачі
        self.self_client_task: Optional[asyncio.Task] = None

    async def initialize(self):
        """Ініціалізація всіх компонентів"""
        try:
            # Ініціалізація Redis (завжди увімкнено у конфігурації)
            self.redis_manager = RedisManager(self.settings)
            await self.redis_manager.initialize()
            self.logger.info("✅ Redis manager initialized")

            # Ініціалізація асинхронного оптимізатора
            self.async_optimizer = AsyncOptimizer(
                max_workers=self.settings.worker_pool_size,
                max_tasks=self.settings.message_queue_size
            )
            await self.async_optimizer.initialize()

            # Ініціалізація менеджерів
            self.client_manager = ClientManager(self.settings)

            self.task_router = TaskRouter(self.settings, self.redis_manager)

            self.websocket_manager = WebSocketManager(self.settings)
            self.health_monitor = HealthMonitor(self.settings, self.client_manager)
            self.metrics_collector = MetricsCollector(self.settings)

            # Ініціалізація AuthManager з Redis клієнтом
            if self.redis_manager:
                from core.auth_manager import initialize_auth_manager_redis
                try:
                    await initialize_auth_manager_redis()
                except Exception as e:
                    self.logger.warning("⚠️ Could not initialize AuthManager with Redis", error=str(e))

            # Встановлення зв'язків між компонентами (частина 1)
            if self.health_monitor and self.client_manager:
                self.health_monitor.client_manager = self.client_manager
                # Встановлення посилання на hub для доступу до всіх компонентів
                self.health_monitor.hub = self

            # Ініціалізація компонентів
            await self.client_manager.initialize()
            await self.task_router.initialize()
            await self.websocket_manager.initialize()
            await self.health_monitor.initialize()
            await self.metrics_collector.initialize()

            # Встановлення зв'язків між компонентами (частина 2) - після ініціалізації
            if self.task_router and self.client_manager:
                self.task_router.set_client_manager(self.client_manager)
            else:
                self.logger.error("[INIT] Failed to set TaskRouter client_manager",
                                task_router_exists=self.task_router is not None,
                                client_manager_exists=self.client_manager is not None)

            # Налаштування подієвих обробників
            self._setup_event_handlers()

            # Автоматична ротація токенів (якщо увімкнено)
            try:
                if getattr(self.settings, 'enable_token_rotation', False):
                    interval = int(getattr(self.settings, 'token_rotation_interval_minutes', 1440))
                    asyncio.create_task(self._token_rotation_loop(interval))
            except Exception:
                pass

            # Самореєстрація як клієнт
            await self._register_self_as_client()

            # Запуск periodic broadcast для task stats
            asyncio.create_task(self._periodic_task_stats_broadcast())

            # Запуск periodic broadcast для системних метрик (реальний стрім для дашборду)
            asyncio.create_task(self._periodic_metrics_broadcast())

            self.start_time = datetime.utcnow()
            self.is_running = True

            self.logger.info("✅ StreamHub initialized successfully")

        except Exception as e:
            self.logger.error("❌ Failed to initialize StreamHub",
                            error=str(e),
                            exc_info=True)
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
        self.logger.info("Creating FastAPI app",
                        is_initialized=self.is_running,
                        has_components=bool(self.client_manager))

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

        # Налаштування CORS (звужена конфігурація)
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=self.settings.allowed_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Requested-With", "X-Correlation-Id"],
            expose_headers=["X-Total-Count", "X-Page-Count", "X-API-Version"]
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

        # Реєстрація роутів
        self.logger.info("Registering routes",
                        has_client_manager=bool(self.client_manager),
                        is_running=self.is_running)
        self._register_routes()

    def _register_routes(self):
        """Реєстрація HTTP та WebSocket роутів"""
        # Видалений зайвий лог registration

        # Налаштування дашборду (перед реєстрацією роутів)
        self._setup_dashboard()

        # Auth router is now included in security integration

        @self.app.options("/{path:path}")  # type: ignore[attr-defined]
        async def options_handler(path: str):
            """Обробка CORS preflight запитів"""
            from fastapi.responses import Response  # type: ignore
            return Response(status_code=200)

        @self.app.websocket("/ws")  # type: ignore[attr-defined]
        async def websocket_endpoint(websocket: WebSocket):
            """WebSocket endpoint with authentication"""
            # Видалений зайвий лог WebSocket endpoint
            self.logger.info("🔌 WebSocket endpoint called",
                           client=websocket.client.host if websocket.client else "unknown",
                           path=websocket.url.path if websocket.url else "unknown")

            # Отримуємо hub instance з app.state (встановлюється в lifespan)
            hub = getattr(websocket.app.state, 'hub', None)
            self.logger.debug("WebSocket endpoint hub check",
                            hub_exists=hub is not None,
                            hub_type=type(hub).__name__ if hub else "None")

            if hub is None:
                self.logger.error("❌ Hub instance not found in app.state")
                await websocket.close(code=1011, reason="Server not initialized")
                return

            self.logger.info("✅ Passing WebSocket to hub.handle_websocket_connection")
            await hub.handle_websocket_connection(websocket)

        # Видалені зайві логи endpoints
        @self.app.get("/health")  # type: ignore[attr-defined]
        async def health_check(request: fastapi.Request):
            """Перевірка здоров'я системи"""
            # Отримуємо справжній hub instance з app.state якщо доступний
            hub = getattr(request.app.state, 'hub', self)
            return await hub.get_health_status()

        # Видалений зайвий лог config endpoint
        @self.app.get("/api/config")  # type: ignore[attr-defined]
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

        # Prometheus metrics endpoint (обмеження доступу в production в security_integration)
        @self.app.get("/metrics")  # type: ignore[attr-defined]
        async def prometheus_metrics():
            from fastapi.responses import PlainTextResponse  # type: ignore
            try:
                if self.metrics_collector:
                    text = await self.metrics_collector.export_prometheus_metrics()
                    return PlainTextResponse(text, media_type="text/plain")
            except Exception as e:
                self.logger.error("Failed to export Prometheus metrics", error=str(e))
            return PlainTextResponse("", media_type="text/plain")

        # Remove duplicate route registrations - these will be handled by dashboard.py
        # Only register routes that are NOT handled by dashboard.py to avoid conflicts
        
        # Видалений зайвий лог alternative endpoints
        @self.app.get("/clients")  # type: ignore[attr-defined]
        async def get_clients_alternative(request: fastapi.Request, user: Dict[str, Any] = fastapi.Depends(get_current_user)):
            """Отримання списку підключених клієнтів (альтернативний ендпоінт)"""
            # Отримуємо справжній hub instance з app.state якщо доступний
            hub = getattr(request.app.state, 'hub', self)

            if not hub.client_manager or not hub.client_manager.is_healthy():
                return {
                    "clients": [],
                    "total_count": 0
                }

            return {
                "clients": [client.to_dict() for client in hub.client_manager.get_all_clients()],
                "total_count": hub.client_manager.get_client_count()
            }

        # Видалений зайвий лог tasks endpoint
        @self.app.get("/tasks")  # type: ignore[attr-defined]
        async def get_tasks_alternative(request: fastapi.Request, user: Dict[str, Any] = fastapi.Depends(get_current_user)):
            """Отримання інформації про завдання (альтернативний ендпоінт)"""
            # Отримуємо справжній hub instance з app.state якщо доступний
            hub = getattr(request.app.state, 'hub', self)

            try:
                if not hub.task_router:
                    # Повертаємо порожні статистики якщо TaskRouter недоступний
                    return {
                        "total_tasks": 0,
                        "pending_tasks": 0,
                        "processing_tasks": 0,
                        "completed_tasks": 0,
                        "failed_tasks": 0,
                        "average_processing_time": 0,
                        "queue_sizes": {
                            "critical": 0,
                            "high": 0,
                            "normal": 0,
                            "low": 0
                        },
                        "worker_distribution": {}
                    }

                return await hub.task_router.get_queue_stats()
            except Exception as e:
                hub.logger.error("Error getting task stats", error=str(e))
                # Повертаємо порожні статистики при помилці
                return {
                    "total_tasks": 0,
                    "pending_tasks": 0,
                    "processing_tasks": 0,
                    "completed_tasks": 0,
                    "failed_tasks": 0,
                    "average_processing_time": 0,
                    "queue_sizes": {
                        "critical": 0,
                        "high": 0,
                        "normal": 0,
                        "low": 0
                    },
                    "worker_distribution": {}
                }

        # Task cancel endpoint will be handled by dashboard.py to avoid conflicts

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

            # Якщо це API роут, не обробляємо тут - це буде оброблено dashboard.py або повернути 404
            if path.startswith(('api/', 'ws')):
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
        # Видалений зайвий лог connection attempt
        from core.websocket_security import ws_security_manager

        try:
            # Authenticate WebSocket connection before accepting
            token = websocket.query_params.get("token")
            # У production забороняємо токен у query
            try:
                env = os.getenv("ENVIRONMENT", "development").lower()
                if env == "production" and token:
                    await websocket.close(code=1008, reason="Query token not allowed")
                    return
            except Exception:
                pass
            # Видалений детальний лог authentication attempt

            user_data = await ws_security_manager.authenticate_websocket(websocket, token)

            if not user_data:
                self.logger.warning("WebSocket authentication failed",
                                  remote_addr=websocket.client.host if websocket.client else "unknown")
                await websocket.close(code=1008, reason="Authentication failed")
                return

            # Accept connection after successful authentication
            await websocket.accept()
            self.total_connections += 1
            # Видалені детальні логи connection accepted

            # Register connection with security manager
            # Видалений зайвий debug лог ws_security_manager
            conn_info = await ws_security_manager.accept_connection(websocket, user_data)
            if not conn_info:
                self.logger.warning("WebSocket connection rejected by security manager",
                                  user_id=user_data["user_id"],
                                 websocket_state=websocket.client_state.name if websocket.client_state else "unknown")
                if websocket.client_state.name == "CONNECTED":
                    await websocket.close(code=1008, reason="Connection rejected")
                else:
                    self.logger.warning("Cannot close WebSocket - already closed",
                                      state=websocket.client_state.name)
                return

            # Метрики підключень: інкремент
            try:
                if hasattr(self.metrics_collector, 'increment_counter'):
                    self.metrics_collector.increment_counter("streamhub_connections_total", 1)
            except Exception:
                pass

            self.logger.info("New authenticated WebSocket connection",
                           user_id=user_data["user_id"],
                           remote_addr=websocket.client.host if websocket.client else "unknown")

            # Очікування реєстрації клієнта з автентифікованими даними
            self.logger.info("Starting client registration process",
                           websocket_state=websocket.client_state.name if websocket.client_state else "unknown",
                           conn_info_client_id=conn_info.client_id if conn_info else None)
            client = await self._handle_client_registration(websocket, user_data)
            if not client:
                self.logger.error("Client registration failed",
                                websocket_state=websocket.client_state.name if websocket.client_state else "unknown",
                                conn_info_exists=conn_info is not None)
                if conn_info:
                    await ws_security_manager.disconnect_client(conn_info.client_id)
                if websocket.client_state.name == "CONNECTED":
                    await websocket.close(code=4001, reason="Registration failed")
                else:
                    self.logger.warning("Cannot close WebSocket - already closed during registration",
                                      state=websocket.client_state.name)
                return

            # Store client_id for security tracking
            client.security_client_id = conn_info.client_id

            # Додавання клієнта до менеджера
            self.logger.info("Checking ClientManager availability",
                           has_client_manager=hasattr(self, 'client_manager'),
                           client_manager_value=self.client_manager,
                           client_manager_type=type(self.client_manager).__name__ if self.client_manager else None,
                           client_manager_bool=bool(self.client_manager))

            if self.client_manager:
                self.logger.info("Adding client to ClientManager",
                               client_id=client.info.client_id,
                               client_type=client.info.client_type,
                               client_manager_id=id(self.client_manager),
                               manager_is_running=self.client_manager.is_running if hasattr(self.client_manager, 'is_running') else None,
                               current_client_count=self.client_manager.get_client_count() if hasattr(self.client_manager, 'get_client_count') else None)
                added = await self.client_manager.add_client(client)
                self.logger.info("Client added to manager",
                               success=added,
                               client_id=client.info.client_id,
                               total_clients_after=self.client_manager.get_client_count() if hasattr(self.client_manager, 'get_client_count') else None)
            else:
                self.logger.error("ClientManager not available!",
                               has_client_manager=hasattr(self, 'client_manager'),
                               client_manager_value=self.client_manager,
                               client_manager_type=type(self.client_manager).__name__ if self.client_manager else None,
                               hub_id=id(self),
                               is_running=self.is_running)

            # Обробка повідомлень від клієнта
            await self._handle_client_messages(client, websocket)

        except WebSocketDisconnect as e:
            self.logger.debug("WebSocket disconnected",
                           code=e.code,
                           client_id=client.info.client_id if 'client' in locals() and client else None)
        except Exception as e:
            self.logger.error("WebSocket connection error",
                            error=str(e),
                            client_id=client.info.client_id if 'client' in locals() and client else None)
            self.total_errors += 1
        finally:
            # Видалені детальні логи cleanup
            if 'client' in locals() and client is not None:
                # Видалений детальний лог WebSocket cleanup
                if self.client_manager:
                    await self.client_manager.remove_client(client.info.client_id)
                    # Видалений лог client removed
            else:
                # Видалений warning лог no client to remove
                pass

    async def _handle_client_registration(self, websocket: WebSocket, user_data: Dict[str, Any]) -> Optional[Client]:
        """Обробка реєстрації клієнта з автентифікованими даними"""
        try:
            self.logger.info("Waiting for client registration message",
                           remote_addr=websocket.client.host if websocket.client else "unknown",
                           user_data_keys=list(user_data.keys()) if user_data else None,
                           websocket_state=websocket.client_state.name if websocket.client_state else "unknown")
            registration_received = False
            max_attempts = 5
            attempt = 0
            data = None
            any_data_received = False
            while not registration_received and attempt < max_attempts:
                attempt += 1
                try:
                    if websocket.client_state.name != "CONNECTED":
                        self.logger.warning("WebSocket already closed before registration",
                                          attempt=attempt,
                                          state=websocket.client_state.name,
                                          remote_addr=websocket.client.host if websocket.client else "unknown")
                        break
                    self.logger.info("[REGISTRATION] Waiting for registration message",
                                   attempt=attempt,
                                   timeout=10.0)
                    raw_text = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
                    data = json.loads(raw_text)
                    any_data_received = True
                    self.logger.info("[REGISTRATION] Отримано raw повідомлення під час реєстрації",
                                   raw_data=data,
                                   data_keys=list(data.keys()),
                                   type=data.get("type"),
                                   attempt=attempt)
                    if data.get("type") == "ping":
                        self.logger.info("[REGISTRATION] Received ping during registration, responding with pong")
                        pong_response = {
                            "type": "pong",
                            "timestamp": datetime.utcnow().isoformat(),
                            "correlation_id": data.get("correlation_id")
                        }
                        if websocket.client_state.name == "CONNECTED":
                            await websocket.send_json(pong_response)
                        else:
                            self.logger.warning("Cannot send pong, WebSocket already closed", attempt=attempt)
                        continue
                    if data.get("type") == "client_registration":
                        registration_received = True
                        break
                except Exception as e:
                    if websocket.client_state.name != "CONNECTED":
                        self.logger.error("WebSocket closed during registration",
                                        attempt=attempt,
                                        error=str(e),
                                        error_type=type(e).__name__,
                                        websocket_state=websocket.client_state.name,
                                        remote_addr=websocket.client.host if websocket.client else "unknown",
                                        any_data_received=any_data_received)
                        break
                    self.logger.error("[REGISTRATION] Error receiving registration message",
                                    attempt=attempt,
                                    error=str(e),
                                    error_type=type(e).__name__,
                                    websocket_state=websocket.client_state.name if websocket.client_state else "unknown",
                                    remote_addr=websocket.client.host if websocket.client else "unknown")
            if not registration_received:
                if not any_data_received:
                    self.logger.error("[REGISTRATION] Не отримано жодного повідомлення до закриття WebSocket",
                                    websocket_state=websocket.client_state.name if websocket.client_state else "unknown",
                                    remote_addr=websocket.client.host if websocket.client else "unknown",
                                    user_data=user_data)
                self.logger.error("[REGISTRATION] Failed to receive valid registration message after all attempts",
                                attempts_made=attempt,
                                any_data_received=any_data_received,
                                last_data=data if data else None,
                                websocket_state=websocket.client_state.name if websocket.client_state else "unknown",
                                remote_addr=websocket.client.host if websocket.client else "unknown")
                return None

            # Обробка нового формату з полем 'type' та 'data'
            if data.get("type") == "client_registration" and "data" in data:
                # Новий формат: конвертуємо до старого формату для parse_message
                message_data = {
                    "message_type": data["type"],
                    **data["data"]  # Merge registration data
                }
            else:
                # Старий формат або формат з message_type
                message_data = data
                if "type" in data and "message_type" not in data:
                    message_data["message_type"] = data["type"]

            # Парсинг повідомлення
            try:
                message = parse_message(message_data)
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
                # Створюємо capabilities для бота на основі переданих даних або дефолтні
                bot_capabilities = getattr(message, 'capabilities', [])
                if not bot_capabilities:
                    # Дефолтні capabilities для ботів
                    bot_capabilities = ["send_message", "get_chat_info", "generic_bot_task", "custom"]
                    self.logger.info("🤖 Using default capabilities for bot", capabilities=bot_capabilities)
                
                capabilities = WorkerCapabilities(
                    supported_task_types=bot_capabilities,
                    max_concurrent_tasks=getattr(message, 'max_concurrent_tasks', 5) or 5  # Боти можуть обробляти кілька тасків
                )
                client = Client.create_bot(
                    client_id=message.client_id,
                    client_name=message.client_name,
                    capabilities=capabilities,  # Передаємо capabilities одразу при створенні
                    remote_address=websocket.client.host if websocket.client else "unknown"
                )
                self.logger.info("🤖 Bot client registered successfully",
                               client_id=message.client_id,
                               client_name=message.client_name,
                               capabilities=capabilities.supported_task_types,
                               max_concurrent_tasks=capabilities.max_concurrent_tasks,
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
                # StreamHub також може виконувати таски - додаємо базові capabilities
                hub_capabilities = getattr(message, 'capabilities', [])
                if not hub_capabilities:
                    # Дефолтні capabilities для StreamHub
                    hub_capabilities = ["custom", "generic_hub_task", "data_processing"]
                    self.logger.info("🌐 Using default capabilities for StreamHub", capabilities=hub_capabilities)
                
                capabilities = WorkerCapabilities(
                    supported_task_types=hub_capabilities,
                    max_concurrent_tasks=getattr(message, 'max_concurrent_tasks', 3) or 3
                )
                client = Client.create_stream_hub(
                    client_id=message.client_id,
                    client_name=message.client_name,
                    capabilities=capabilities,
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
            ack_message = create_message(
                MessageType.REGISTRATION_ACK,
                client_id=client.info.client_id,
                session_id=client.info.session_id,
                config=self._get_client_config(client),
                timestamp=datetime.utcnow()
            )

            try:
                if websocket.client_state.name in ["CONNECTED", "CONNECTING"]:
                    await websocket.send_json(ack_message.model_dump(mode='json'))
                    self.logger.info("Sending registration acknowledgment",
                                    client_id=client.info.client_id,
                                    session_id=client.info.session_id)
                else:
                    self.logger.warning("Cannot send registration ack - WebSocket not connected",
                                      state=websocket.client_state.name,
                                      client_id=client.info.client_id)
                    return None
            except Exception as e:
                self.logger.error("Failed to send registration acknowledgment",
                                client_id=client.info.client_id,
                                websocket_error=str(e))
                return None

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

        self.logger.info("📨 [MESSAGE HANDLER] Starting message handler for client",
                        client_id=client.info.client_id,
                        client_type=client.info.client_type.value)

        try:
            while True:
                self.logger.debug("[MESSAGE HANDLER] Waiting for message from client",
                                client_id=client.info.client_id)
                raw_data = await websocket.receive_text()

                # Зменшене логування для безпеки в продакшені: без preview
                is_prod = os.getenv("ENVIRONMENT", "development").lower() == "production"
                if is_prod:
                    self.logger.info("[WS RAW] Отримано WebSocket повідомлення",
                                    client_id=client.info.client_id,
                                    client_type=client.info.client_type.value,
                                    raw_data_length=len(raw_data))
                else:
                    self.logger.info("[WS RAW] Отримано сире WebSocket повідомлення",
                                    client_id=client.info.client_id,
                                    client_type=client.info.client_type.value,
                                    raw_data_length=len(raw_data),
                                    raw_data_preview=raw_data[:200] if len(raw_data) > 200 else raw_data)

                # Validate message using security manager
                # Увімкнуто: використовуємо валідацію WS для всіх клієнтів (окрім специфічних кейсів у майбутньому)
                if hasattr(client, 'security_client_id') and client.security_client_id:
                    # Логування raw повідомлення
                    self.logger.info("[DEBUG] Raw WebSocket message received",
                                   client_id=client.info.client_id,
                                   raw_data_preview=raw_data[:500] if len(raw_data) > 500 else raw_data)

                    validated_message = await ws_security_manager.validate_message(client.security_client_id, raw_data)

                    if not validated_message:
                        self.logger.warning("Invalid message received",
                                          client_id=client.info.client_id)
                        continue

                    # Логування validated message (без контенту даних у продакшені)
                    if os.getenv("ENVIRONMENT", "development").lower() == "production":
                        self.logger.debug("[DEBUG] Validated message structure",
                                          client_id=client.info.client_id,
                                          message_type=validated_message.type,
                                          has_data=hasattr(validated_message, 'data'),
                                          data_keys=list(validated_message.data.keys()) if hasattr(validated_message, 'data') and isinstance(validated_message.data, dict) else None)
                    else:
                        self.logger.info("[DEBUG] Validated message structure",
                                         client_id=client.info.client_id,
                                         message_type=validated_message.type,
                                         has_data=hasattr(validated_message, 'data'),
                                         data_keys=list(validated_message.data.keys()) if hasattr(validated_message, 'data') and isinstance(validated_message.data, dict) else None,
                                         data_content=validated_message.data if hasattr(validated_message, 'data') else None)

                    # Convert WebSocketMessage to data format for parse_message
                    # WebSocketMessage uses 'type' field, but parse_message expects 'message_type'
                    message_data = {
                        "message_type": validated_message.type,
                        "timestamp": validated_message.timestamp,
                        "correlation_id": validated_message.correlation_id,
                    }

                    # Спеціальна обробка для TASK_SUBMIT - витягуємо поля з data (уніфікований формат)
                    if validated_message.type == MessageType.TASK_SUBMIT.value:
                        # Всі поля таску знаходяться в validated_message.data
                        message_data.update(validated_message.data)
                        self.logger.info("[DEBUG] TASK_SUBMIT through security manager",
                                         client_id=client.info.client_id,
                                         data_keys=list(validated_message.data.keys()),
                                         has_task_type="task_type" in validated_message.data,
                                         has_task_data="task_data" in validated_message.data)
                    else:
                        # Для інших типів повідомлень
                        message_data.update(validated_message.data)

                    # Додаємо message_id тільки якщо він не None
                    if validated_message.message_id:
                        message_data["message_id"] = validated_message.message_id

                    # Логування message_data перед парсингом (без контенту в продакшені)
                    if os.getenv("ENVIRONMENT", "development").lower() == "production":
                        self.logger.debug("[DEBUG] Message data before parsing",
                                          client_id=client.info.client_id,
                                          message_data_keys=list(message_data.keys()))
                    else:
                        self.logger.info("[DEBUG] Message data before parsing",
                                         client_id=client.info.client_id,
                                         message_data_keys=list(message_data.keys()),
                                         message_data_content=message_data)

                    message = parse_message(message_data)

                    # Логування розпаршеного message (мінімальне у проді)
                    if os.getenv("ENVIRONMENT", "development").lower() == "production":
                        self.logger.debug("[DEBUG] Parsed message structure",
                                          client_id=client.info.client_id,
                                          message_type=getattr(message, 'message_type', None),
                                          has_task_id=hasattr(message, 'task_id'),
                                          has_task_type=hasattr(message, 'task_type'),
                                          has_task_data=hasattr(message, 'task_data'))
                    else:
                        self.logger.info("[DEBUG] Parsed message structure",
                                         client_id=client.info.client_id,
                                         message_type=getattr(message, 'message_type', None),
                                         message_class=type(message).__name__,
                                         has_task_id=hasattr(message, 'task_id'),
                                         task_id=getattr(message, 'task_id', None) if hasattr(message, 'task_id') else None,
                                         has_task_type=hasattr(message, 'task_type'),
                                         task_type=getattr(message, 'task_type', None) if hasattr(message, 'task_type') else None,
                                         has_task_data=hasattr(message, 'task_data'),
                                         message_attrs=list(vars(message).keys()) if hasattr(message, '__dict__') else None)
                else:
                    # Fallback (тимчасово): сувора перевірка розміру перед парсингом
                    try:
                        from core.websocket_security import MAX_MESSAGE_SIZE
                    except Exception:
                        MAX_MESSAGE_SIZE = 1024 * 1024
                    if len(raw_data) > MAX_MESSAGE_SIZE:
                        await self._send_error(websocket, "MESSAGE_TOO_LARGE", "Message exceeds allowed size")
                        continue
                    if self.async_optimizer:
                        data = await self.async_optimizer.json_loads(raw_data)
                    else:
                        data = json.loads(raw_data)

                    # Додаткове логування для API Worker
                    if client.info.client_type == ClientType.WORKER:
                        self.logger.info("[DEBUG] API Worker raw message data",
                                       client_id=client.info.client_id,
                                       data_keys=list(data.keys()),
                                       has_task_type="task_type" in data,
                                       has_task_data="task_data" in data,
                                       data_preview=str(data)[:500])

                    # Support both 'type' and 'message_type'
                    if "type" in data and "message_type" not in data:
                        data = data.copy()
                        data["message_type"] = data["type"]

                    # Логування перед створенням повідомлення
                    self.logger.info("[WS PARSE] Парсинг повідомлення",
                                   client_id=client.info.client_id,
                                   message_type=data.get("message_type"),
                                   has_task_type="task_type" in data,
                                   has_task_data="task_data" in data,
                                   data_keys=list(data.keys()))

                    # Backpressure: перевіряємо ліміт одночасних повідомлень на клієнта
                    _cid = client.info.client_id
                    _cur = self._client_inflight.get(_cid, 0)
                    if _cur >= self.max_inflight_per_client:
                        # Короткий м'який backoff; якщо не звільнилось — повертаємо помилку
                        await asyncio.sleep(0)
                        _cur = self._client_inflight.get(_cid, 0)
                        if _cur >= self.max_inflight_per_client:
                            await self._send_error(websocket, "BACKPRESSURE", "Too many in-flight messages; slow down")
                            continue
                    self._client_inflight[_cid] = _cur + 1

                    # Спеціальна обробка для TASK_SUBMIT повідомлень
                    if data.get("message_type") == MessageType.TASK_SUBMIT.value or data.get("type") == MessageType.TASK_SUBMIT.value:
                        from models.messages import TaskMessage
                        self.logger.info("[DEBUG] Special handling for TASK_SUBMIT",
                                       client_id=client.info.client_id,
                                       data_keys=list(data.keys()))

                        # Створюємо TaskMessage напряму з правильними полями
                        # Обробляємо datetime поля
                        timestamp = data.get("timestamp")
                        if isinstance(timestamp, str):
                            from dateutil import parser
                            timestamp = parser.isoparse(timestamp)
                        elif timestamp is None:
                            timestamp = datetime.utcnow()

                        created_at = data.get("created_at")
                        if isinstance(created_at, str):
                            from dateutil import parser
                            created_at = parser.isoparse(created_at)
                        elif created_at is None:
                            created_at = datetime.utcnow()

                        message = TaskMessage(
                            message_type=MessageType.TASK_SUBMIT,
                            message_id=data.get("message_id", str(uuid.uuid4())),
                            timestamp=timestamp,
                            sender_id=data.get("sender_id"),
                            correlation_id=data.get("correlation_id"),
                            task_id=data.get("task_id", str(uuid.uuid4())),
                            task_type=data.get("task_type", "unknown"),
                            task_data=data.get("task_data", {}),
                            priority=data.get("priority", TaskPriority.NORMAL),
                            timeout=data.get("timeout", 300),
                            max_retries=data.get("max_retries", 3),
                            worker_requirements=data.get("worker_requirements", []),
                            executor_type=data.get("executor_type", "worker"),
                            created_at=created_at
                        )
                    else:
                        message = parse_message(data)

                    # Логування розпаршеного message
                    self.logger.info("[DEBUG] Parsed message structure",
                                   client_id=client.info.client_id,
                                   message_type=getattr(message, 'message_type', None),
                                   message_class=type(message).__name__,
                                   has_task_id=hasattr(message, 'task_id'),
                                   task_id=getattr(message, 'task_id', None) if hasattr(message, 'task_id') else None,
                                   has_task_type=hasattr(message, 'task_type'),
                                   task_type=getattr(message, 'task_type', None) if hasattr(message, 'task_type') else None,
                                   has_task_data=hasattr(message, 'task_data'),
                                   message_attrs=list(vars(message).keys()) if hasattr(message, '__dict__') else None)

                # Оновлення часу останньої активності
                client.info.stats.last_activity = datetime.utcnow()

                # Обробка повідомлення
                try:
                    await self._process_client_message(client, message)
                finally:
                    _cid2 = client.info.client_id
                    self._client_inflight[_cid2] = max(0, self._client_inflight.get(_cid2, 1) - 1)

        except WebSocketDisconnect:
            self.logger.info("Client disconnected", client_id=client.info.client_id)
        except Exception as e:
            self.logger.error("Error processing client message",
                            client_id=client.info.client_id, error=str(e))
            await self._send_error(websocket, "PROCESSING_ERROR", str(e))

    async def _process_client_message(self, client: Client, message: BaseMessage):
        """Обробка повідомлення від клієнта"""
        try:
            # ВИПРАВЛЕННЯ: Оновлюємо активність клієнта при БУДЬ-ЯКОМУ повідомленні
            # Це виправляє проблему з помилковим позначенням активних клієнтів як неактивних
            current_time = datetime.utcnow()
            client.info.last_pong = current_time  # Оновлюємо last_pong для сумісності з get_unhealthy_clients
            client.info.stats.last_activity = current_time  # Оновлюємо загальну активність
            
            self.logger.debug("Client activity updated",
                             client_id=client.info.client_id,
                             message_type=message.message_type.value if hasattr(message.message_type, 'value') else str(message.message_type),
                             last_activity=current_time.isoformat())

            if message.message_type == MessageType.TASK_SUBMIT:
                # Перевірка наявності необхідних атрибутів перед логуванням
                task_data = getattr(message, 'task_data', {}) or {}

                self.logger.debug("[TASK_SUBMIT] Debug message attributes",
                    message_type=message.message_type,
                    has_task_type_attr=hasattr(message, 'task_type'),
                    has_task_data_attr=hasattr(message, 'task_data'),
                    message_vars=vars(message) if hasattr(message, '__dict__') else "No __dict__"
                )

                # Логування отримання нового таску (для всіх типів клієнтів)
                self.logger.info("[TASK_SUBMIT] Отримано новий таск від клієнта (universal)",
                    client_id=client.info.client_id,
                    client_type=client.info.client_type.value,
                    task_id=getattr(message, 'task_id', None),
                    task_type=getattr(message, 'task_type', None),
                    priority=getattr(message, 'priority', None),
                    timeout=getattr(message, 'timeout', None),
                    correlation_id=getattr(message, 'correlation_id', None)
                )
                # Обробка нового завдання від бота
                await self._handle_task_submission(client, message)

            elif message.message_type == MessageType.TASK_RESULT:
                # Обробка результату завдання від воркера або бота
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
            elif message.message_type == MessageType.PONG or message.message_type == "pong":
                self.logger.debug("Received pong from client", client_id=client.info.client_id)
                # Активність вже оновлена вище, додатково оновлюємо last_pong
                client.info.last_pong = current_time
            else:
                self.logger.warning("Unknown message type",
                                  message_type=message.message_type,
                                  client_id=client.info.client_id)

        except Exception as e:
            self.logger.error("Error processing client message",
                            client_id=client.info.client_id,
                            error=str(e))

    async def _handle_task_submission(self, client: Client, message: BaseMessage):
        """Обробка подання завдання від клієнта (бот або воркер)"""

        # Витягуємо дані таску - тепер вони приходять безпосередньо в message
        task_data = {
            'task_id': getattr(message, 'task_id', None),
            'task_type': getattr(message, 'task_type', None),
            'task_data': getattr(message, 'task_data', {}),
            'priority': getattr(message, 'priority', TaskPriority.NORMAL),
            'timeout': getattr(message, 'timeout', 300),
            'max_retries': getattr(message, 'max_retries', 3),
            'worker_requirements': getattr(message, 'worker_requirements', []),
            'executor_type': getattr(message, 'executor_type', 'worker')
        }

        # Логування отримання нового таску
        self.logger.debug("[TASK_SUBMIT] Отримано новий таск від клієнта",
            client_id=client.info.client_id,
            client_type=client.info.client_type.value,
            task_id=task_data.get('task_id'),
            task_type=task_data.get('task_type'),
            priority=task_data.get('priority'),
            timeout=task_data.get('timeout'),
            correlation_id=getattr(message, 'correlation_id', None)
        )

        # Дозволяємо всім типам клієнтів надсилати таски
        # (раніше була перевірка тільки для ботів)
        self.logger.info("[TASK_SUBMIT] Task submission from client",
                       client_id=client.info.client_id,
                       client_type=client.info.client_type.value,
                       task_executor_type=task_data.get('executor_type'),
                       task_type=task_data.get('task_type'))

        # Створення завдання з безпечним отриманням атрибутів
        from models.task import TaskType, ExecutorType

        task_type_str = task_data.get('task_type', 'custom')
        # Намагаємося знайти тип таску в enum
        if isinstance(task_type_str, str):
            # Пробуємо знайти в enum (case-insensitive)
            task_type = None
            for enum_member in TaskType:
                if enum_member.value.lower() == task_type_str.lower():
                    task_type = enum_member
                    break

            if task_type is None:
                # Якщо не знайдено в enum, використовуємо CUSTOM
                self.logger.debug(f"Task type '{task_type_str}' not found in enum, using CUSTOM",
                                task_id=task_data.get('task_id'))
                task_type = TaskType.CUSTOM
        else:
            task_type = task_type_str

        # Отримуємо executor_type
        executor_type_str = task_data.get('executor_type', 'worker')
        executor_type = ExecutorType(executor_type_str) if executor_type_str in ['bot', 'worker', 'worker_api'] else ExecutorType.WORKER

        task = Task.create(
            task_type=task_type,
            data=task_data.get('task_data', {}),
            priority=task_data.get('priority', TaskPriority.NORMAL),
            timeout=task_data.get('timeout', 300),
            max_retries=task_data.get('max_retries', 3),
            worker_requirements=task_data.get('worker_requirements', []),
            executor_type=executor_type
        )

        task.context.client_id = client.info.client_id
        task.context.correlation_id = getattr(message, 'correlation_id', None)

        # Якщо task_id вже був переданий клієнтом, використовуємо його
        if task_data.get('task_id'):
            task.task_id = task_data.get('task_id')

        # Додавання завдання до маршрутизатора
        success = False
        if self.task_router:
            self.logger.debug("[TASK_SUBMIT] Submitting task to router",
                            task_id=task.task_id,
                            executor_type=task.executor_type.value,
                            task_type=task.task_type.value if hasattr(task.task_type, 'value') else task.task_type,
                            priority=task.priority.value,
                            client_manager_exists=self.client_manager is not None)
            success = await self.task_router.submit_task(task)
            self.logger.debug("[TASK_SUBMIT] Router submission result",
                            task_id=task.task_id,
                            success=success)
        else:
            self.logger.error("[TASK_SUBMIT] Task router not initialized!",
                            task_id=task.task_id)

        if success:
            self.total_tasks_processed += 1
            self.logger.info("[TASK_SUBMIT] Task submitted successfully",
                             task_id=task.task_id,
                             client_id=client.info.client_id,
                             executor_type=task.executor_type.value)

            # Логування стану таску
            self.logger.info("[TASK_STATE] ✅ Таск прийнято і поставлено в чергу",
                             task_id=task.task_id,
                             task_type=task.task_type.value if hasattr(task.task_type, 'value') else task.task_type,
                             state="PENDING",
                             priority=task.priority.value,
                             executor_type=task.executor_type.value,
                             status="В очікуванні доступного виконавця")
        else:
            self.logger.error("[TASK_SUBMIT] Task rejected",
                            task_id=task.task_id,
                            client_id=client.info.client_id,
                            executor_type=task.executor_type.value)
            
            # Визначаємо детальну причину відхилення з контексту таску
            error_message = "Task rejected"
            if task.context.errors:
                last_error = task.context.errors[-1]
                error_type = last_error.get("error_type", "unknown")
                
                if error_type == "queue_full":
                    error_message = f"Task queue is full: {last_error.get('error_message', 'No details')}"
                elif error_type == "queue_add_failed":
                    error_message = "Internal error processing task"
                else:
                    error_message = f"Task rejected: {last_error.get('error_message', 'Unknown reason')}"
            
            await self._send_error(client.websocket, "TASK_REJECTED", error_message)

    async def _handle_task_result(self, client: Client, message: BaseMessage):
        """Обробка результату завдання від воркера або бота"""
        # Дозволяємо відправляти результати тасків воркерам та ботам
        if not (client.info.is_worker() or client.info.is_bot()):
            await self._send_error(client.websocket, "UNAUTHORIZED",
                                 "Only workers and bots can submit task results")
            return

        # Логування отриманого результату
        self.logger.info("🎯 [TASK_RESULT] Received task result",
                        client_id=client.info.client_id,
                        client_type=client.info.client_type.value,
                        task_id=getattr(message, 'task_id', 'unknown'),
                        status=getattr(message, 'status', 'unknown'))

        # Обробка результату через маршрутизатор з безпечним отриманням атрибутів
        if self.task_router:
            # Конвертуємо статус з рядка в TaskStatus enum
            status_str = getattr(message, 'status', 'failed')
            if isinstance(status_str, str):
                status_mapping = {
                    'completed': TaskStatus.COMPLETED,
                    'failed': TaskStatus.FAILED,
                    'timeout': TaskStatus.TIMEOUT,
                    'cancelled': TaskStatus.CANCELLED
                }
                status = status_mapping.get(status_str.lower(), TaskStatus.FAILED)
            else:
                status = status_str  # Вже TaskStatus enum
                
            await self.task_router.handle_task_result(
                task_id=getattr(message, 'task_id', ''),
                worker_id=client.info.client_id,
                status=status,
                result=getattr(message, 'result', {}) or {},
                error_message=getattr(message, 'error_message', '') or '',
                execution_time=getattr(message, 'execution_time', 0) or 0,
            )

    async def _handle_ping(self, client: Client, message: BaseMessage):
        """Обробка ping запиту"""
        client.ping()

        # Автоматично додаємо client_id якщо його немає у повідомленні
        if not hasattr(message, 'client_id') or not message.client_id:
            message.client_id = client.info.client_id

        # Створюємо WebSocket-сумісну pong відповідь з полем 'type'
        pong_message = {
            "type": "pong",
            "message_type": "pong",  # Додати для сумісності
            "client_id": client.info.client_id,
            "correlation_id": message.correlation_id,
            "timestamp": datetime.utcnow().isoformat()
        }

        if client.websocket:
            try:
                # Перевіряємо стан WebSocket перед відправкою
                if client.websocket.client_state.name in ["CONNECTED", "CONNECTING"]:
                    await client.websocket.send_json(pong_message)
                    client.pong()
                else:
                    self.logger.debug("Skipping pong send - WebSocket not connected",
                                   state=client.websocket.client_state.name,
                                   client_id=client.info.client_id)
            except Exception as e:
                self.logger.debug("Failed to send pong message",
                                client_id=client.info.client_id,
                                websocket_error=str(e))

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
            try:
                if client.websocket.client_state.name in ["CONNECTED", "CONNECTING"]:
                    await client.websocket.send_json(response.model_dump(mode='json'))
                else:
                    self.logger.debug("Skipping health response send - WebSocket not connected",
                                   state=client.websocket.client_state.name,
                                   client_id=client.info.client_id)
            except Exception as e:
                self.logger.debug("Failed to send health response",
                                client_id=client.info.client_id,
                                websocket_error=str(e))

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
            try:
                if client.websocket.client_state.name in ["CONNECTED", "CONNECTING"]:
                    await client.websocket.send_json(response.model_dump(mode='json'))
                else:
                    self.logger.debug("Skipping metrics response send - WebSocket not connected",
                                   state=client.websocket.client_state.name,
                                   client_id=client.info.client_id)
            except Exception as e:
                self.logger.debug("Failed to send metrics response",
                                client_id=client.info.client_id,
                                websocket_error=str(e))

    async def _send_error(self, websocket: WebSocket, error_code: str, error_message: str):
        """Відправка повідомлення про помилку"""
        # Створюємо WebSocket-сумісне error повідомлення з полем 'type'
        error_msg = {
            "type": "error",
            "error_code": error_code,
            "error_message": error_message,
            "timestamp": datetime.utcnow().isoformat(),
            "retryable": False
        }

        try:
            # Перевіряємо стан WebSocket перед відправкою
            if websocket.client_state.name in ["CONNECTED", "CONNECTING"]:
                await websocket.send_json(error_msg)
            else:
                self.logger.debug("Skipping error message send - WebSocket not connected",
                               state=websocket.client_state.name,
                               error_code=error_code)
        except Exception as e:
            self.logger.debug("Failed to send error message",
                            error_code=error_code,
                            websocket_error=str(e))

    def _authenticate_client(self, message: BaseMessage) -> bool:
        """Аутентифікація клієнта"""
        # 1) MONITOR клієнти вже аутентифіковані через JWT на рівні WS
        from models.client import ClientType  # Локальний імпорт, щоб уникнути циклічних залежностей

        if message.client_type == ClientType.MONITOR:
            return True

        # 2) Підтримуємо ротацію токенів: приймаємо auth_token, auth_token_active, auth_token_next
        allowed_tokens = []
        for tk in [getattr(self.settings, 'auth_token_active', None),
                   getattr(self.settings, 'auth_token_next', None),
                   getattr(self.settings, 'auth_token', None)]:
            if tk:
                allowed_tokens.append(tk)

        # 3) Якщо токени не налаштовані - пропускаємо додаткову перевірку
        if not allowed_tokens:
            return True

        # 4) Перевірка токена з повідомлення реєстрації
        client_token = getattr(message, 'auth_token', None)
        return client_token in allowed_tokens

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

        # Перевірка черги тасків для нового клієнта
        if self.task_router and (client.info.client_type in [ClientType.BOT, ClientType.WORKER, ClientType.WORKER_API]):
            self.logger.info("Checking pending tasks for new client",
                           client_id=client.info.client_id,
                           client_type=client.info.client_type.value)

            # Спроба призначити таски з черги новому клієнту
            try:
                assigned_count = await self.task_router.process_pending_tasks_for_client(client)
                if assigned_count > 0:
                    self.logger.info("Assigned pending tasks to new client",
                                   client_id=client.info.client_id,
                                   assigned_count=assigned_count)
            except Exception as e:
                self.logger.error("Error processing pending tasks for new client",
                                client_id=client.info.client_id,
                                error=str(e))

        # Оновлення метрик
        if self.metrics_collector:
            self.metrics_collector.increment_counter("clients_connected")

    async def _on_client_disconnected(self, client: Client):
        """Обробник відключення клієнта"""
        # Зменшуємо рівень логування для зменшення шуму в продакшн
        self.logger.debug("Client disconnected",
                         client_id=client.info.client_id,
                         client_type=client.info.client_type.value)

        # Переназначення активних завдань виконавця
        if client.info.can_execute_tasks() and client.active_tasks:
            if self.task_router:
                await self.task_router.reassign_executor_tasks(client.info.client_id)

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

        # Переназначення завдань від нездорового виконавця
        if self.task_router:
            await self.task_router.reassign_executor_tasks(client_id)

    async def _on_redis_message(self, channel: str, message: Dict[str, Any]):
        """Обробник повідомлень Redis"""
        self.logger.debug("Redis message received", channel=channel)

    # Public API methods
    async def get_health_status(self) -> Dict[str, Any]:
        """Отримання статусу здоров'я системи"""
        # Перевіряємо чи система ініціалізована
        if not self.is_running or not self.start_time:
            return {
                "status": "initializing",
                "uptime": 0,
                "version": "1.0.0",
                "components": {
                    "redis": False,
                    "client_manager": False,
                    "task_router": False,
                    "websocket_manager": False,
                    "health_monitor": False,
                    "metrics_collector": False,
                },
                "stats": {
                    "total_connections": 0,
                    "active_clients": 0,
                    "total_tasks_processed": 0,
                    "total_errors": 0
                }
            }

        # Проста перевірка компонентів без складної логіки
        async def check_component_simple(component):
            """Проста перевірка компонента"""
            try:
                if not component:
                    return False
                if hasattr(component, 'is_healthy'):
                    health_method = component.is_healthy()
                    # Перевіряємо чи це корутина
                    if hasattr(health_method, '__await__'):
                        return await health_method
                    else:
                        return health_method
                return component is not None
            except Exception as e:
                self.logger.error(f"Error checking component: {e}")
                return False

        # Спеціальна перевірка для WebSocket - перевіряємо чи є активні клієнти
        # оскільки з'єднання керуються через ClientManager, а не WebSocketManager
        websocket_healthy = False
        client_count = 0
        if self.client_manager:
            try:
                client_count = self.client_manager.get_client_count()
                websocket_healthy = client_count > 0
            except Exception as e:
                self.logger.error(f"Error checking WebSocket health: {e}")
                websocket_healthy = False

        components = {
            "redis": await check_component_simple(self.redis_manager),
            "client_manager": await check_component_simple(self.client_manager),
            "task_router": await check_component_simple(self.task_router),
            "websocket_manager": websocket_healthy,
            "health_monitor": await check_component_simple(self.health_monitor),
            "metrics_collector": await check_component_simple(self.metrics_collector),
        }

        # Визначаємо загальний статус системи
        healthy_components = sum(1 for health in components.values() if health)
        total_components = len(components)

        if healthy_components == total_components:
            overall_status = "healthy"
        elif healthy_components > 0:
            overall_status = "degraded"
        else:
            overall_status = "unhealthy"

        health_status = {
            "status": overall_status,
            "uptime": (datetime.utcnow() - self.start_time).total_seconds() if self.start_time else 0,
            "version": "1.0.0",
            "components": components,
            "stats": {
                "total_connections": self.total_connections,
                "active_clients": self.client_manager.get_client_count() if self.client_manager else 0,
                "total_tasks_processed": self.total_tasks_processed,
                "total_errors": self.total_errors
            }
        }

        return health_status

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
                await asyncio.wait_for(self.self_client_task, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

        # Видалення самореєстрації
        if hasattr(self, 'self_client') and self.client_manager:
            try:
                await asyncio.wait_for(
                    self.client_manager.remove_client("stream_hub_main"),
                    timeout=2.0
                )
                self.logger.info("StreamHub self-registration removed")
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self.logger.warning("Self-registration removal timeout")
            except Exception as e:
                self.logger.error("Failed to remove StreamHub self-registration", error=str(e))

        # Швидке завершення компонентів з таймаутами
        shutdown_tasks = []

        # Закриття компонентів паралельно з таймаутами
        if self.health_monitor:
            shutdown_tasks.append(asyncio.create_task(
                asyncio.wait_for(self.health_monitor.shutdown(), timeout=3.0)
            ))

        if self.metrics_collector:
            shutdown_tasks.append(asyncio.create_task(
                asyncio.wait_for(self.metrics_collector.shutdown(), timeout=3.0)
            ))

        if self.task_router:
            shutdown_tasks.append(asyncio.create_task(
                asyncio.wait_for(self.task_router.shutdown(), timeout=3.0)
            ))

        if self.client_manager:
            shutdown_tasks.append(asyncio.create_task(
                asyncio.wait_for(self.client_manager.shutdown(), timeout=3.0)
            ))

        if self.async_optimizer:
            shutdown_tasks.append(asyncio.create_task(
                asyncio.wait_for(self.async_optimizer.shutdown(), timeout=3.0)
            ))

        if self.redis_manager:
            shutdown_tasks.append(asyncio.create_task(
                asyncio.wait_for(self.redis_manager.shutdown(), timeout=3.0)
            ))

        # Очікуємо завершення всіх компонентів з загальним таймаутом
        if shutdown_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*shutdown_tasks, return_exceptions=True),
                    timeout=5.0
                )
            except asyncio.TimeoutError:
                self.logger.warning("Some components shutdown timeout - forcing termination")
            except asyncio.CancelledError:
                self.logger.info("Shutdown was cancelled")
            except Exception as e:
                self.logger.error("Error during parallel shutdown", error=str(e))

        self.logger.info("StreamHub shutdown complete")

    def _setup_dashboard(self):
        """Налаштування веб-дашборду (React SPA)"""
        try:
            # Імпорт та реєстрація dashboard роутів
            from web.dashboard import register_dashboard_routes
            
            self.logger.info("🔧 Attempting to register dashboard routes",
                           app_exists=hasattr(self, 'app') and self.app is not None,
                           streamhub_exists=bool(self))
            
            register_dashboard_routes(self.app, self)

            # Перевіряємо що роути зареєстровані
            api_routes = [r for r in self.app.routes if hasattr(r, 'path') and '/api/' in r.path]
            
            self.logger.info("✅ Dashboard configured successfully",
                           total_routes=len(self.app.routes),
                           api_routes_count=len(api_routes))
            
        except ImportError as e:
            self.logger.warning("Dashboard routes not available", error=str(e))
        except Exception as e:
            self.logger.error("❌ Failed to setup dashboard", 
                            error=str(e),
                            error_type=type(e).__name__)
            # Додаємо більше деталей для діагностики
            import traceback
            self.logger.error("Dashboard setup traceback", traceback=traceback.format_exc())

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
                    "redis_enabled": True
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

    async def _periodic_task_stats_broadcast(self):
        """Періодичне надсилання статистики завдань через WebSocket"""
        try:
            while self.is_running:
                try:
                    # Отримуємо статистику завдань
                    if self.task_router:
                        task_stats = await self.task_router.get_queue_stats(
                            include_tasks=True,
                            use_cache=True
                        )
                        
                        # Створюємо повідомлення для broadcast
                        message = StatsUpdate(
                            client_id="hub",
                            stats=task_stats
                        )
                        
                        # Надсилаємо всім monitor клієнтам (dashboard)
                        try:
                            await self.broadcast_message(message, target_clients=[ClientType.MONITOR])
                        except Exception as broadcast_error:
                            self.logger.debug("Failed to broadcast task stats", 
                                            error=str(broadcast_error))
                    
                    # Чекаємо 10 секунд до наступного broadcast
                    await asyncio.sleep(10)
                    
                except Exception as e:
                    self.logger.warning("Error in periodic task stats broadcast", 
                                    error=str(e))
                    # При помилці чекаємо більше часу
                    await asyncio.sleep(30)
                    
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.logger.error("Fatal error in periodic task stats broadcast", 
                            error=str(e))

    async def _periodic_metrics_broadcast(self):
        """Періодичне надсилання системних метрик через WebSocket"""
        try:
            while self.is_running:
                try:
                    # Отримуємо актуальні системні метрики хабу
                    full_metrics = await self.get_system_metrics()

                    # Формуємо lightweight повідомлення для фронтенду (тільки system + hub)
                    metrics = {
                        "system": full_metrics.get("system", {}),
                        "hub": full_metrics.get("hub", {}),
                        "timestamp": full_metrics.get("timestamp"),
                    }

                    ws_message = {
                        "type": "metrics_update",
                        "timestamp": datetime.utcnow().isoformat(),
                        "data": metrics,
                    }

                    # Розсилаємо тільки моніторинг-клієнтам (дашборд)
                    if self.client_manager:
                        await self.client_manager.broadcast_to_clients(
                            ws_message,
                            client_types=[ClientType.MONITOR],
                        )
                except Exception as e:
                    # Тримаємо логування мʼяким, щоб не засмічувати логи при тимчасових збоях
                    self.logger.debug("Failed to broadcast metrics", error=str(e))

                # Інтервал стріму метрик: 2 секунди (без агресивного 100мс polling)
                await asyncio.sleep(2)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.logger.error("Fatal error in periodic metrics broadcast", error=str(e))

    def get_app(self) -> FastAPI:
        """Отримання FastAPI додатка"""
        if not self.app:
            # Перевіряємо чи hub ініціалізований
            if not self.is_running:
                self.logger.warning("get_app() called before initialize(), hub components may not be available")
            # Створення FastAPI додатка
            self._create_fastapi_app()
        return self.app

    async def _token_rotation_loop(self, interval_minutes: int):
        """Фоновий цикл ротації статичних токенів (AUTH_TOKEN_ACTIVE/NEXT)."""
        try:
            while self.is_running:
                await asyncio.sleep(interval_minutes * 60)
                try:
                    active = getattr(self.settings, 'auth_token_active', None)
                    next_t = getattr(self.settings, 'auth_token_next', None)
                    if next_t:
                        # Переключення next -> active
                        self.settings.auth_token_active = next_t
                        self.settings.auth_token_next = None
                        if self.metrics_collector:
                            self.metrics_collector.increment_counter("auth_token_rotations")
                        self.logger.warning("AUTH token rotated: NEXT -> ACTIVE")
                except Exception as e:
                    self.logger.error("Token rotation loop error", error=str(e))
        except asyncio.CancelledError:
            pass
