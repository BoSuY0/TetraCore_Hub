"""
TetraCore StreamHub Web Dashboard Routes

Веб-роути для дашборду моніторингу StreamHub.
Забезпечує HTML інтерфейс та API endpoints для моніторингу.
"""

import json
import random
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import structlog

logger = structlog.get_logger(__name__)

# Ініціалізація шаблонів
templates = Jinja2Templates(directory="templates")

# Створення роутера
dashboard_router = APIRouter(prefix="/dashboard", tags=["dashboard"])


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
async def clients_page(request: Request):
    """Сторінка клієнтів"""
    try:
        return templates.TemplateResponse("clients.html", {
            "request": request,
            "title": "Клієнти - StreamHub Dashboard",
            "timestamp": datetime.utcnow().isoformat()
        })
    except Exception as e:
        logger.error("Error rendering clients page", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to render clients page")


@dashboard_router.get("/api/status")
async def get_dashboard_status():
    """API endpoint для статусу дашборду"""
    return {
        "status": "online",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0"
    }





@dashboard_router.get("/api/system-logs")
async def get_system_logs(limit: int = 200):
    """API endpoint для отримання останніх системних логів

    Повертає *limit* останніх записів, які зберігаються у
    ``utils.in_memory_logger``.  Якщо параметр не вказано, за замовчуванням
    повертаємо 200 записів.  Логи вже відсортовані від старіших до новіших.
    """

    try:
        from utils.in_memory_logger import get_recent_logs  # локальний імпорт щоб уникнути циклів

        logs = get_recent_logs(limit)
        # ``get_recent_logs`` повертає логи у правильному порядку.
        return {
            "logs": logs,
            "total_count": len(logs),
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as exc:
        logger.error("Failed to fetch system logs", error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to fetch system logs")


@dashboard_router.post("/api/actions/restart-component")
async def restart_component(component: str):
    """API endpoint для перезапуску компонентів"""
    valid_components = ["client_manager", "task_router", "redis_manager", "health_monitor"]

    if component not in valid_components:
        raise HTTPException(status_code=400, detail=f"Invalid component: {component}")

    # TODO: Реалізувати перезапуск компонентів
    logger.info("Component restart requested", component=component)

    return {
        "status": "success",
        "message": f"Component {component} restart initiated",
        "timestamp": datetime.utcnow().isoformat()
    }


@dashboard_router.post("/api/actions/clear-queue")
async def clear_task_queue(priority: str):
    """API endpoint для очищення черги завдань"""
    valid_priorities = ["critical", "high", "normal", "low", "all"]

    if priority not in valid_priorities:
        raise HTTPException(status_code=400, detail=f"Invalid priority: {priority}")

    # TODO: Інтегрувати з TaskRouter
    logger.info("Queue clear requested", priority=priority)

    return {
        "status": "success",
        "message": f"Queue {priority} cleared",
        "timestamp": datetime.utcnow().isoformat()
    }


@dashboard_router.get("/api/export/metrics")
async def export_metrics():
    """API endpoint для експорту метрик"""
    # TODO: Реалізувати експорт метрик
    return {
        "export_url": "/dashboard/api/export/metrics.json",
        "format": "json",
        "timestamp": datetime.utcnow().isoformat()
    }


def register_dashboard_routes(app, streamhub_instance):
    """Реєстрація роутів дашборду з інстансом StreamHub"""

    @dashboard_router.get("/api/hub-health")
    async def get_hub_health():
        """Отримання здоров'я StreamHub"""
        if streamhub_instance:
            return await streamhub_instance.get_health_status()
        return {"status": "hub_not_initialized"}

    @dashboard_router.get("/api/hub-clients")
    async def get_hub_clients():
        """Отримання клієнтів StreamHub"""
        if streamhub_instance and streamhub_instance.client_manager:
            clients = streamhub_instance.client_manager.get_all_clients()
            return {
                "clients": [client.to_dict() for client in clients],
                "total_count": len(clients)
            }
        return {"clients": [], "total_count": 0}

    @dashboard_router.get("/api/clients/detailed")
    async def get_clients_detailed():
        """Отримання детальної інформації про клієнтів"""
        if streamhub_instance and streamhub_instance.client_manager:
            clients = streamhub_instance.client_manager.get_all_clients()

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

            for client in clients:
                client_type = client.info.client_type.value
                client_dict = client.to_dict()

                # Додаткова інформація
                client_dict.update({
                    "uptime": (datetime.utcnow() - client.info.stats.connected_at).total_seconds() if client.info.is_connected() else 0,
                    "last_activity": client.info.stats.last_activity.isoformat() if client.info.stats.last_activity else None,
                    "total_connection_time": client.info.stats.total_connection_time,
                    "disconnection_count": client.info.stats.disconnection_count
                })

                if client_type in clients_by_type:
                    clients_by_type[client_type].append(client_dict)

                    # Статистика по типам
                    stats_by_type[client_type]["count"] += 1
                    if client.info.is_connected():
                        stats_by_type[client_type]["connected"] += 1

                    # Додаткова статистика для воркерів
                    if client_type in ["worker", "worker_api"]:
                        if client.info.is_available():
                            stats_by_type[client_type]["available"] += 1
                        elif client.info.worker_status and client.info.worker_status.value == "busy":
                            stats_by_type[client_type]["busy"] += 1

            return {
                "clients_by_type": clients_by_type,
                "stats_by_type": stats_by_type,
                "total_clients": len(clients),
                "timestamp": datetime.utcnow().isoformat()
            }

        return {
            "clients_by_type": {
                "bot": [],
                "worker": [],
                "worker_api": [],
                "stream_hub": [],
                "monitor": [],
                "admin": []
            },
            "stats_by_type": {
                "bot": {"count": 0, "connected": 0},
                "worker": {"count": 0, "connected": 0, "available": 0, "busy": 0},
                "worker_api": {"count": 0, "connected": 0, "available": 0, "busy": 0},
                "stream_hub": {"count": 0, "connected": 0},
                "monitor": {"count": 0, "connected": 0},
                "admin": {"count": 0, "connected": 0}
            },
            "total_clients": 0,
            "timestamp": datetime.utcnow().isoformat()
        }

    @dashboard_router.get("/api/clients/{client_id}")
    async def get_client_details(client_id: str):
        """Отримання детальної інформації про конкретного клієнта"""
        if streamhub_instance and streamhub_instance.client_manager:
            client = streamhub_instance.client_manager.get_client(client_id)
            if client:
                client_dict = client.to_dict()
                client_dict.update({
                    "uptime": (datetime.utcnow() - client.info.stats.connected_at).total_seconds() if client.info.is_connected() else 0,
                    "last_activity": client.info.stats.last_activity.isoformat() if client.info.stats.last_activity else None,
                    "task_history": client.task_history[-10:],  # Last 10 tasks
                    "active_tasks_list": list(client.active_tasks.keys()),
                    "metadata": client.info.metadata,
                    "config": client.info.config
                })
                return client_dict

        raise HTTPException(status_code=404, detail="Client not found")

    @dashboard_router.get("/api/clients/{client_id}/metrics")
    async def get_client_metrics(client_id: str):
        """Отримання метрик конкретного клієнта"""
        if streamhub_instance and streamhub_instance.client_manager:
            client = streamhub_instance.client_manager.get_client(client_id)
            if not client:
                raise HTTPException(status_code=404, detail="Client not found")

            # Отримуємо метрики з MetricsCollector
            metrics_data = []
            if streamhub_instance.metrics_collector:
                try:
                    # Отримуємо системні метрики
                    system_metrics = await streamhub_instance.get_system_metrics()
                    
                    # Генеруємо історичні дані на основі поточних метрик
                    now = datetime.utcnow()
                    for i in range(20):  # Останні 20 точок даних
                        timestamp = now - timedelta(minutes=i * 5)  # Кожні 5 хвилин
                        
                        # Базові метрики з невеликими варіаціями
                        base_cpu = system_metrics.get('system', {}).get('cpu_usage', 0)
                        base_memory = system_metrics.get('system', {}).get('memory_usage', 0)
                        
                        metrics_data.append({
                            "timestamp": timestamp.isoformat(),
                            "cpu_usage": max(0, min(100, base_cpu + (random.random() - 0.5) * 20)),
                            "memory_usage": max(0, min(100, base_memory + (random.random() - 0.5) * 10)),
                            "active_tasks": client.active_tasks_count if hasattr(client, 'active_tasks_count') else 0,
                            "completed_tasks": random.randint(50, 200),  # TODO: Отримувати з реальної статистики
                            "failed_tasks": random.randint(0, 5),
                            "response_time": 0.1 + random.random() * 1.5,
                        })
                    
                    # Сортуємо за часом (найстаріші спочатку)
                    metrics_data.sort(key=lambda x: x["timestamp"])
                    
                except Exception as e:
                    logger.error(f"Error generating metrics for client {client_id}: {e}")
                    # Повертаємо порожні метрики у випадку помилки
                    metrics_data = []

            return {
                "client_id": client_id,
                "metrics": metrics_data,
                "timestamp": datetime.utcnow().isoformat()
            }

        raise HTTPException(status_code=404, detail="StreamHub not available")

    @dashboard_router.get("/api/hub-tasks")
    async def get_hub_tasks():
        """Отримання завдань StreamHub"""
        if streamhub_instance and streamhub_instance.task_router:
            return await streamhub_instance.task_router.get_queue_stats()
        return {"queue_sizes": {}, "total_tasks": 0}

    @dashboard_router.get("/api/tasks")
    async def get_tasks():
        """Отримання списку всіх завдань"""
        # TODO: Інтегрувати з реальним TaskRouter
        return {
            "tasks": [],
            "total_count": 0,
            "timestamp": datetime.utcnow().isoformat()
        }

    @dashboard_router.get("/api/tasks/stats")
    async def get_task_stats():
        """Отримання статистики завдань"""
        if streamhub_instance and streamhub_instance.task_router:
            return await streamhub_instance.task_router.get_queue_stats()
        
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

    @dashboard_router.post("/api/tasks/{task_id}/cancel")
    async def cancel_task(task_id: str):
        """Скасування завдання"""
        # TODO: Інтегрувати з TaskRouter
        logger.info("Task cancellation requested", task_id=task_id)
        return {
            "status": "success",
            "message": f"Task {task_id} cancelled",
            "timestamp": datetime.utcnow().isoformat()
        }

    @dashboard_router.post("/api/tasks/{task_id}/retry")
    async def retry_task(task_id: str):
        """Повтор завдання"""
        # TODO: Інтегрувати з TaskRouter
        logger.info("Task retry requested", task_id=task_id)
        return {
            "status": "success",
            "message": f"Task {task_id} queued for retry",
            "timestamp": datetime.utcnow().isoformat()
        }

    @dashboard_router.post("/api/tasks/clear-queue")
    async def clear_task_queue_by_priority(request: dict):
        """Очищення черги завдань за пріоритетом"""
        priority = request.get("priority", "all")
        valid_priorities = ["critical", "high", "normal", "low", "all"]

        if priority not in valid_priorities:
            raise HTTPException(status_code=400, detail=f"Invalid priority: {priority}")

        # TODO: Інтегрувати з TaskRouter
        logger.info("Queue clear requested", priority=priority)

        return {
            "status": "success",
            "message": f"Queue {priority} cleared",
            "timestamp": datetime.utcnow().isoformat()
        }

    @dashboard_router.get("/api/hub-metrics")
    async def get_hub_metrics():
        """Отримання метрик StreamHub"""
        if streamhub_instance:
            return await streamhub_instance.get_system_metrics()
        return {}

    @dashboard_router.get("/api/real-time-metrics")
    async def get_real_time_metrics():
        """API endpoint для метрик в реальному часі"""
        if streamhub_instance:
            try:
                # Отримуємо реальні метрики з StreamHub
                hub_metrics = await streamhub_instance.get_system_metrics()
                
                # Отримуємо статистику завдань
                task_stats = {}
                if streamhub_instance.task_router:
                    task_stats = await streamhub_instance.task_router.get_queue_stats()
                
                # Отримуємо кількість активних підключень
                active_connections = 0
                if streamhub_instance.client_manager:
                    active_connections = streamhub_instance.client_manager.get_client_count()
                
                return {
                    "timestamp": datetime.utcnow().isoformat(),
                    "tasks_per_second": hub_metrics.get('hub', {}).get('tasks_per_second', 0),
                    "average_latency": hub_metrics.get('hub', {}).get('average_response_time', 0),
                    "active_connections": active_connections,
                    "queue_sizes": task_stats.get('queue_sizes', {
                        "critical": 0,
                        "high": 0,
                        "normal": 0,
                        "low": 0
                    }),
                    "performance_data": {
                        "cpu_usage": hub_metrics.get('system', {}).get('cpu_usage', 0),
                        "memory_usage": hub_metrics.get('system', {}).get('memory_usage', 0),
                        "network_io": hub_metrics.get('system', {}).get('network_io', 0)
                    }
                }
            except Exception as e:
                logger.error(f"Error getting real-time metrics: {e}")
        
        # Fallback дані якщо StreamHub недоступний
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "tasks_per_second": 0,
            "average_latency": 0,
            "active_connections": 0,
            "queue_sizes": {
                "critical": 0,
                "high": 0,
                "normal": 0,
                "low": 0
            },
            "performance_data": {
                "cpu_usage": 0,
                "memory_usage": 0,
                "network_io": 0
            }
        }

    # Реєстрація роутів
    app.include_router(dashboard_router)
