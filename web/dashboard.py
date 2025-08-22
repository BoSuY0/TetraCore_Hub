"""
TetraCore StreamHub Web Dashboard Routes

Веб-роути для дашборду моніторингу StreamHub.
Забезпечує HTML інтерфейс та API endpoints для моніторингу.
"""

from datetime import datetime
from fastapi import APIRouter, Request, HTTPException, Query, Depends
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
import structlog
from core.rate_limiter import get_rate_limiter
from typing import Optional

logger = structlog.get_logger(__name__)

# Ініціалізація шаблонів
templates = Jinja2Templates(directory="templates")


async def rate_limit_dependency(request: Request, limit: int = 100, window: int = 60):
    """Rate limiting dependency для API endpoints"""
    rate_limiter = get_rate_limiter()
    
    # Отримуємо IP адресу клієнта
    client_ip = request.client.host if request.client else "unknown"
    
    # Перевіряємо rate limit
    result = await rate_limiter.is_allowed(
        key=f"api:{client_ip}",
        limit=limit,
        window_seconds=window
    )
    
    if not result["allowed"]:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "Rate limit exceeded",
                "limit": result["limit"],
                "remaining": result["remaining"],
                "reset_at": result["reset_at"],
                "retry_after": result["retry_after"]
            },
            headers={
                "X-RateLimit-Limit": str(result["limit"]),
                "X-RateLimit-Remaining": str(result["remaining"]),
                "X-RateLimit-Reset": str(int(result["reset_at"])),
                "Retry-After": str(int(result["retry_after"]))
            }
        )
    
    return result

# Створення роутерів з чіткою структурою
dashboard_router = APIRouter(prefix="/dashboard", tags=["dashboard"])
api_router = APIRouter(prefix="/api", tags=["api"])
frontend_api_router = APIRouter(prefix="/api/frontend", tags=["frontend-api"])

# Простий favicon як bytes (16x16 прозорий PNG)
SIMPLE_FAVICON = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x10\x00\x00\x00\x10\x08\x06\x00\x00\x00\x1f\xf3\xffa\x00\x00\x00\x19tEXtSoftware\x00Adobe ImageReadyq\xc9e<\x00\x00\x00\x0eIDATx\xdac\xf8\x0f\x00\x00\x01\x00\x01\x00\x00\x00\x00\x00IEND\xaeB`\x82'


# =============================================================================
# HTML СТОРІНКИ ДАШБОРДУ
# =============================================================================

@dashboard_router.get("/", response_class=HTMLResponse)
async def dashboard_home(request: Request):
    """Головна сторінка дашборду"""
    try:
        return templates.TemplateResponse("dashboard.html", {
            "request": request,
            "title": "StreamHub Dashboard",
            "timestamp": datetime.utcnow().isoformat()
        })
    except Exception as e:
        logger.error("Error rendering dashboard", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to render dashboard")


@dashboard_router.get("/clients", response_class=HTMLResponse)
async def dashboard_clients(request: Request):
    """Сторінка клієнтів дашборду"""
    try:
        return templates.TemplateResponse("clients.html", {
            "request": request,
            "title": "StreamHub Clients",
            "timestamp": datetime.utcnow().isoformat()
        })
    except Exception as e:
        logger.error("Error rendering clients page", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to render clients page")


# =============================================================================
# ОСНОВНІ API ЕНДПОІНТИ (/api/)
# =============================================================================

# Базові заглушки - будуть перевизначені в register_dashboard_routes
async def get_api_health():
    """Основний health check API"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "tetra-core-hub"
    }

async def get_api_metrics():
    """Основні метрики API"""
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "metrics": {
            "uptime": 0,
            "connections": 0,
            "tasks": 0
        }
    }

async def get_api_clients():
    """Основний список клієнтів API"""
    return []

async def get_api_tasks():
    """Основний список завдань API"""
    return {
        "total_tasks": 0,
        "pending_tasks": 0,
        "processing_tasks": 0,
        "completed_tasks": 0,
        "failed_tasks": 0,
        "tasks": [],
        "timestamp": datetime.utcnow().isoformat()
    }




# =============================================================================
# FRONTEND API ЕНДПОІНТИ (/api/frontend/)
# =============================================================================

@frontend_api_router.get("/status")
async def get_frontend_status():
    """Статус для frontend компонентів"""
    return {
        "dashboard_status": "online",
        "api_status": "healthy",
        "websocket_status": "connected",
        "timestamp": datetime.utcnow().isoformat()
    }


@frontend_api_router.get("/health")
async def get_frontend_health():
    """Health check спеціально для frontend"""
    return {
        "status": "healthy",
        "frontend_version": "1.0.0",
        "backend_version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat()
    }


@frontend_api_router.get("/real-time-metrics")
async def get_real_time_metrics():
    """Метрики реального часу для frontend (реальні з хабу)"""
    try:
        # Імпортуємо тут, щоб уникнути циклічних залежностей при імпорті модуля
        # Поточний FastAPI app недоступний тут напряму; цей ендпоінт використовується
        # як standalone. Для реальних даних використовується перевизначення у register_dashboard_routes.
        # Тож тут залишаємо бековий fallback на випадок прямого виклику без інтеграції.
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "tasks_per_second": 0,
            "average_latency": 0,
            "active_connections": 0,
            "queue_sizes": {
                "critical": 0,
                "high": 0,
                "normal": 0,
                "low": 0,
            },
            "performance_data": {
                "cpu_usage": 0,
                "memory_usage": 0,
                "network_io": 0,
            },
        }
    except Exception:
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "tasks_per_second": 0,
            "average_latency": 0,
            "active_connections": 0,
            "queue_sizes": {
                "critical": 0,
                "high": 0,
                "normal": 0,
                "low": 0,
            },
            "performance_data": {
                "cpu_usage": 0,
                "memory_usage": 0,
                "network_io": 0,
            },
        }


@frontend_api_router.get("/system-logs")
async def get_system_logs():
    """Системні логи для frontend"""
    return {
        "logs": [],
        "total_count": 0,
        "timestamp": datetime.utcnow().isoformat()
    }


# =============================================================================
# ДЕТАЛЬНІ ЕНДПОІНТИ (/api/clients/, /api/tasks/)
# =============================================================================

@api_router.get("/clients/detailed")
async def get_detailed_clients():
    """Детальна інформація про клієнтів"""
    return {
        "clients": [],
        "total_count": 0,
        "details": {
            "worker_count": 0,
            "bot_count": 0,
            "monitor_count": 0
        },
        "timestamp": datetime.utcnow().isoformat()
    }


@api_router.get("/clients/{client_id}")
async def get_client_by_id(client_id: str):
    """Інформація про конкретного клієнта"""
    return {
        "client_id": client_id,
        "status": "not_found",
        "timestamp": datetime.utcnow().isoformat()
    }


@api_router.get("/clients/{client_id}/metrics")
async def get_client_metrics(client_id: str):
    """Метрики конкретного клієнта"""
    return {
        "client_id": client_id,
        "metrics": {},
        "timestamp": datetime.utcnow().isoformat()
    }


@api_router.get("/tasks/stats")
async def get_task_stats():
    """Детальна статистика завдань"""
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
        "worker_distribution": {},
        "timestamp": datetime.utcnow().isoformat()
    }


@api_router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    """Скасування завдання"""
    logger.info("Task cancellation requested", task_id=task_id)
    return {
        "status": "success",
        "message": f"Task {task_id} cancelled",
        "task_id": task_id,
        "timestamp": datetime.utcnow().isoformat()
    }


@api_router.post("/tasks/{task_id}/retry")
async def retry_task(task_id: str):
    """Повтор завдання"""
    logger.info("Task retry requested", task_id=task_id)
    return {
        "status": "success",
        "message": f"Task {task_id} queued for retry",
        "task_id": task_id,
        "timestamp": datetime.utcnow().isoformat()
    }


@api_router.post("/tasks/clear-queue")
async def clear_task_queue(request: dict):
    """Очищення черги завдань"""
    priority = request.get("priority", "all")
    valid_priorities = ["critical", "high", "normal", "low", "all"]

    if priority not in valid_priorities:
        raise HTTPException(status_code=400, detail=f"Invalid priority: {priority}")

    logger.info("Queue clear requested", priority=priority)
    return {
        "status": "success",
        "message": f"Queue {priority} cleared",
        "priority": priority,
        "timestamp": datetime.utcnow().isoformat()
    }


# =============================================================================
# АДМІНІСТРАТИВНІ ЕНДПОІНТИ (/api/admin/)
# =============================================================================

admin_router = APIRouter(prefix="/api/admin", tags=["admin"])


@admin_router.post("/restart-component")
async def restart_component(request: dict):
    """Перезапуск компонентів системи"""
    component = request.get("component")
    valid_components = ["client_manager", "task_router", "redis_manager", "health_monitor"]

    if component not in valid_components:
        raise HTTPException(status_code=400, detail=f"Invalid component: {component}")

    logger.info("Component restart requested", component=component)
    return {
        "status": "success",
        "message": f"Component {component} restart initiated",
        "component": component,
        "timestamp": datetime.utcnow().isoformat()
    }


@admin_router.get("/export/metrics")
async def export_metrics():
    """Експорт метрик для адміністраторів"""
    return {
        "export_format": "json",
        "metrics": {},
        "exported_at": datetime.utcnow().isoformat()
    }


# =============================================================================
# РЕЄСТРАЦІЯ РОУТІВ
# =============================================================================

def register_dashboard_routes(app, streamhub_instance):
    """Реєстрація роутів дашборду з інстансом StreamHub"""

    # Видалені зайві логи registration

    # Інтеграція з StreamHub для реальних даних
    if streamhub_instance:

        # Реєструємо API ендпоінти з реальними даними
        # Factory for rate limit dependency
        def get_rate_limiter(limit: int, window: int):
            async def dependency(request: Request):
                return await rate_limit_dependency(request, limit, window)
            return dependency

        @app.get("/api/health")
        async def get_api_health_with_hub(
            rate_limit_info: dict = Depends(get_rate_limiter(limit=30, window=60))
        ):
            """Health check з реальними даними"""
            return await streamhub_instance.get_health_status()

        @app.get("/api/metrics")
        async def get_api_metrics_with_hub(
            rate_limit_info: dict = Depends(get_rate_limiter(limit=30, window=60))
        ):
            """Метрики з реальними даними"""
            return await streamhub_instance.get_system_metrics()

        @app.get("/api/clients")
        async def get_api_clients_with_hub():
            """Клієнти з реальними даними"""
            if streamhub_instance.client_manager:
                clients = streamhub_instance.client_manager.get_all_clients()
                return [client.to_dict() for client in clients]
            return []

        @app.get("/api/tasks")
        async def get_api_tasks_with_hub(
            page: int = Query(1, ge=1, description="Номер сторінки"),
            limit: int = Query(50, ge=1, le=1000, description="Кількість тасків на сторінку"),
            sort: str = Query("created_at", description="Поле для сортування (created_at, priority, status, task_type)"),
            order: str = Query("desc", description="Порядок сортування (asc, desc)"),
            status: Optional[str] = Query(None, description="Фільтр за статусом"),
            priority: Optional[str] = Query(None, description="Фільтр за пріоритетом"),
            task_type: str = Query(None, description="Фільтр за типом завдання", regex="^[a-zA-Z_][a-zA-Z0-9_]*$"),
            search: str = Query(None, description="Пошук за ID завдання або типом", max_length=100),
            worker: str = Query(None, description="Фільтр за worker ID", max_length=50),
            rate_limit_info: dict = Depends(get_rate_limiter(limit=60, window=60))
        ):
            """Завдання з реальними даними з підтримкою пагінації та фільтрації"""
            if streamhub_instance.task_router:
                # Передаємо параметри сортування та фільтрації напряму в task_router
                stats = await streamhub_instance.task_router.get_queue_stats(
                    sort=sort,
                    order=order,
                    status=status,
                    priority=priority,
                    task_type=task_type,
                    search=search,
                    worker=worker,
                    include_tasks=True
                )

                # Отримуємо всі відфільтровані та відсортовані таски
                all_tasks = stats.get("tasks", [])
                total_tasks_count = len(all_tasks)

                # Розрахунок offset
                offset = (page - 1) * limit
                paginated_tasks = all_tasks[offset:offset + limit]

                # Додаємо інформацію про пагінацію
                stats["tasks"] = paginated_tasks
                stats["pagination"] = {
                    "page": page,
                    "limit": limit,
                    "total_items": total_tasks_count,
                    "total_pages": (total_tasks_count + limit - 1) // limit,
                    "has_next": offset + limit < total_tasks_count,
                    "has_prev": page > 1
                }

                return stats
            return {
                "total_tasks": 0,
                "pending_tasks": 0,
                "processing_tasks": 0,
                "completed_tasks": 0,
                "failed_tasks": 0,
                "tasks": [],
                "pagination": {
                    "page": page,
                    "limit": limit,
                    "total_items": 0,
                    "total_pages": 0,
                    "has_next": False,
                    "has_prev": False
                },
                "timestamp": datetime.utcnow().isoformat()
            }

        @app.get("/api/tasks/stats")
        async def get_api_tasks_stats_with_hub():
            """Статистика тасків без списку завдань (для швидкого завантаження)"""
            if streamhub_instance.task_router:
                stats = await streamhub_instance.task_router.get_queue_stats(include_tasks=False)
                # Видаляємо масив тасків, залишаємо тільки статистику
                stats_only = {k: v for k, v in stats.items() if k != "tasks"}
                stats_only["timestamp"] = datetime.utcnow().isoformat()
                return stats_only
            return {
                "total_tasks": 0,
                "pending_tasks": 0,
                "processing_tasks": 0,
                "completed_tasks": 0,
                "failed_tasks": 0,
                "average_processing_time": 0,
                "queue_sizes": {},
                "worker_distribution": {},
                "active_tasks": 0,
                "workers_count": 0,
                "timestamp": datetime.utcnow().isoformat()
            }

        @app.post("/api/tasks/{task_id}/cancel")
        async def cancel_task_with_hub(task_id: str):
            """Скасування завдання"""
            if streamhub_instance.task_router:
                success = await streamhub_instance.task_router.cancel_task(task_id)
                if success:
                    return {"success": True, "message": "Task cancelled successfully"}
                else:
                    raise HTTPException(status_code=404, detail="Task not found")
            raise HTTPException(status_code=503, detail="StreamHub not initialized")

        @app.post("/api/tasks/{task_id}/retry")
        async def retry_task_with_hub(task_id: str):
            """Повторний запуск завдання"""
            if streamhub_instance.task_router:
                # Знаходимо таск в активних або завершених
                task = streamhub_instance.task_router.active_tasks.get(task_id)
                if task and task.can_retry():
                    # Створюємо новий таск на основі поточного
                    new_task_id = await streamhub_instance.task_router.submit_task(
                        task_type=task.task_type,
                        task_data=task.data,
                        priority=task.priority,
                        client_id=task.context.client_id,
                        timeout=task.timeout,
                        max_retries=task.max_retries,
                        executor_type=task.executor_type,
                        worker_requirements=task.worker_requirements
                    )
                    if new_task_id:
                        return {"success": True, "new_task_id": new_task_id, "message": "Task retry scheduled"}
                    else:
                        raise HTTPException(status_code=500, detail="Failed to retry task")
                else:
                    raise HTTPException(status_code=404, detail="Task not found or cannot be retried")
            raise HTTPException(status_code=503, detail="StreamHub not initialized")

        @app.post("/api/tasks/clear-queue")
        async def clear_queue_with_hub(priority: str = Query("all", description="Priority queue to clear (all, high, normal, low)")):
            """Очищення черги завдань"""
            if streamhub_instance.task_router:
                try:
                    cleared_count = 0
                    if priority == "all":
                        # Очищуємо всі черги
                        for queue in streamhub_instance.task_router.task_queues.values():
                            cleared_count += len(queue.tasks)
                            queue.tasks.clear()
                    else:
                        # Очищуємо конкретну чергу
                        from models.task import TaskPriority
                        priority_enum = None
                        for p in TaskPriority:
                            if p.value.lower() == priority.lower():
                                priority_enum = p
                                break

                        if priority_enum and priority_enum in streamhub_instance.task_router.task_queues:
                            queue = streamhub_instance.task_router.task_queues[priority_enum]
                            cleared_count = len(queue.tasks)
                            queue.tasks.clear()
                        else:
                            raise HTTPException(status_code=400, detail=f"Invalid priority: {priority}")

                    return {"success": True, "cleared_count": cleared_count, "message": f"Cleared {cleared_count} tasks from queue"}
                except Exception as e:
                    raise HTTPException(status_code=500, detail=f"Failed to clear queue: {str(e)}")
            raise HTTPException(status_code=503, detail="StreamHub not initialized")

        @app.get("/api/clients/detailed")
        async def get_detailed_clients_with_hub():
            """Детальна інформація про клієнтів з реальними даними"""
            if not streamhub_instance.client_manager:
                return {
                    "stats_by_type": {
                        "bot": {"count": 0, "connected": 0},
                        "worker": {"count": 0, "connected": 0, "available": 0, "busy": 0},
                        "worker_api": {"count": 0, "connected": 0, "available": 0, "busy": 0},
                        "stream_hub": {"count": 0, "connected": 0},
                        "monitor": {"count": 0, "connected": 0},
                        "admin": {"count": 0, "connected": 0}
                    },
                    "clients_by_type": {
                        "bot": [],
                        "worker": [],
                        "worker_api": [],
                        "stream_hub": [],
                        "monitor": [],
                        "admin": []
                    },
                    "total_clients": 0,
                    "timestamp": datetime.utcnow().isoformat()
                }

            # Отримуємо всіх клієнтів
            all_clients = streamhub_instance.client_manager.get_all_clients()

            # Групуємо клієнтів за типами
            clients_by_type = {
                "bot": [],
                "worker": [],
                "worker_api": [],
                "stream_hub": [],
                "monitor": [],
                "admin": []
            }

            stats_by_type = {
                "bot": {"count": 0, "connected": 0},
                "worker": {"count": 0, "connected": 0, "available": 0, "busy": 0},
                "worker_api": {"count": 0, "connected": 0, "available": 0, "busy": 0},
                "stream_hub": {"count": 0, "connected": 0},
                "monitor": {"count": 0, "connected": 0},
                "admin": {"count": 0, "connected": 0}
            }

            for client in all_clients:
                client_dict = client.to_dict()
                client_type = client.info.client_type.value

                # Мапінг типів клієнтів
                if client_type == "bot":
                    key = "bot"
                elif client_type == "worker":
                    key = "worker"
                elif client_type == "worker_api":
                    key = "worker_api"
                elif client_type == "stream_hub":
                    key = "stream_hub"
                elif client_type == "monitor":
                    key = "monitor"
                elif client_type == "admin":
                    key = "admin"
                else:
                    continue

                clients_by_type[key].append(client_dict)
                stats_by_type[key]["count"] += 1

                if client.info.is_connected():
                    stats_by_type[key]["connected"] += 1

                # Для воркерів додаємо статистику доступності
                if key in ["worker", "worker_api"] and client.info.is_worker():
                    if client.info.is_available():
                        stats_by_type[key]["available"] += 1
                    else:
                        stats_by_type[key]["busy"] += 1

            return {
                "stats_by_type": stats_by_type,
                "clients_by_type": clients_by_type,
                "total_clients": len(all_clients),
                "timestamp": datetime.utcnow().isoformat()
            }

        @app.get("/api/frontend/system-logs")
        async def get_system_logs_with_hub():
            """Системні логи з реальними даними"""
            try:
                from utils.in_memory_logger import get_recent_logs
                logs = get_recent_logs(limit=200)
                return {
                    "logs": logs,
                    "total_count": len(logs),
                    "timestamp": datetime.utcnow().isoformat()
                }
            except Exception as e:
                logger.error("Error getting system logs", error=str(e))

            return {
                "logs": [],
                "total_count": 0,
                "timestamp": datetime.utcnow().isoformat()
            }

        # Додаємо інші frontend API роути
        @app.get("/api/frontend/status")
        async def get_frontend_status_with_hub():
            """Статус для frontend компонентів"""
            return {
                "dashboard_status": "online",
                "api_status": "healthy",
                "websocket_status": "connected",
                "timestamp": datetime.utcnow().isoformat()
            }

        @app.get("/api/frontend/health")
        async def get_frontend_health_with_hub():
            """Health check спеціально для frontend"""
            return {
                "status": "healthy",
                "frontend_version": "1.0.0",
                "backend_version": "1.0.0",
                "timestamp": datetime.utcnow().isoformat()
            }

        @app.get("/favicon.ico")
        async def get_favicon():
            """Простий favicon щоб уникнути 404 помилок"""
            return Response(content=SIMPLE_FAVICON, media_type="image/x-icon")

        # Додаємо favicon також для frontend
        @app.get("/api/favicon.ico")
        async def get_api_favicon():
            """Favicon для API запитів"""
            return Response(content=SIMPLE_FAVICON, media_type="image/x-icon")

        @app.get("/api/frontend/real-time-metrics")
        async def get_real_time_metrics_with_hub():
            """Метрики реального часу для frontend (живі з StreamHub)"""
            try:
                # Отримаємо системні та hub метрики одним викликом
                raw = await streamhub_instance.get_system_metrics()

                # Спробуємо отримати також оперативні черги завдань без списку тасків
                task_stats = {}
                try:
                    if streamhub_instance.task_router:
                        task_stats = await streamhub_instance.task_router.get_queue_stats(include_tasks=False)
                except Exception:
                    task_stats = {}

                return {
                    "timestamp": datetime.utcnow().isoformat(),
                    "tasks_per_second": raw.get("hub", {}).get("tasks_per_second", 0),
                    "average_latency": raw.get("hub", {}).get("average_response_time", 0),
                    "active_connections": raw.get("hub", {}).get("active_clients", 0),
                    "queue_sizes": task_stats.get("queue_sizes", {
                        "critical": 0,
                        "high": 0,
                        "normal": 0,
                        "low": 0,
                    }),
                    "performance_data": {
                        "cpu_usage": raw.get("system", {}).get("cpu_usage", 0),
                        "memory_usage": raw.get("system", {}).get("memory_usage", 0),
                        # У простому форматі даємо один агрегований network_io
                        "network_io": raw.get("system", {}).get("network_bytes_recv", 0),
                    },
                }
            except Exception as e:
                logger.debug("Failed to build real-time metrics", error=str(e))
                return {
                    "timestamp": datetime.utcnow().isoformat(),
                    "tasks_per_second": 0,
                    "average_latency": 0,
                    "active_connections": 0,
                    "queue_sizes": {
                        "critical": 0,
                        "high": 0,
                        "normal": 0,
                        "low": 0,
                    },
                    "performance_data": {
                        "cpu_usage": 0,
                        "memory_usage": 0,
                        "network_io": 0,
                    },
                }
    else:
        # Якщо StreamHub не доступний, реєструємо базові заглушки
        @app.get("/api/health")
        async def get_api_health_fallback():
            return await get_api_health()

        @app.get("/api/metrics")
        async def get_api_metrics_fallback():
            return await get_api_metrics()

        @app.get("/api/clients")
        async def get_api_clients_fallback():
            return await get_api_clients()

        @app.get("/api/tasks")
        async def get_api_tasks_fallback():
            return await get_api_tasks()

    # Реєстрація роутерів (тільки ті що не конфліктують)
    app.include_router(dashboard_router)
    app.include_router(frontend_api_router)
    app.include_router(admin_router)

    # Додаємо роути з api_router які не конфліктують з нашими перевизначеними
    # Важливо: це має бути після реєстрації наших роутів, але роути з app.get мають вищий пріоритет
    for route in api_router.routes:
        # Виключаємо роути які перевизначені вище
        if route.path not in ["/api/health", "/api/metrics", "/api/clients", "/api/tasks", "/api/clients/detailed"]:
            app.routes.append(route)

    # Видалені зайві логи успішної реєстрації
