"""
TetraCore StreamHub Health Monitor

Монітор здоров'я для StreamHub.
Відповідає за перевірку стану клієнтів, системних компонентів,
виявлення проблем та автоматичне відновлення.
"""

import asyncio
import os
from datetime import datetime
from typing import Dict, List, Optional, Callable, Any, Awaitable
import structlog
import psutil

from config import Settings
from models.client import Client, WorkerStatus


class HealthStatus:  # pylint: disable=too-many-instance-attributes
    """Статус здоров'я компонента"""

    def __init__(self, component: str):
        self.component = component
        self.is_healthy = True
        self.last_check = datetime.utcnow()
        self.error_count = 0
        self.last_error: Optional[str] = None
        self.checks_performed = 0
        self.uptime = 0.0
        self.metadata: Dict[str, Any] = {}

    def mark_healthy(self, metadata: Dict[str, Any] = None):
        """Позначити як здоровий"""
        self.is_healthy = True
        self.last_check = datetime.utcnow()
        self.checks_performed += 1
        if metadata:
            self.metadata.update(metadata)

    def mark_unhealthy(self, error: str, metadata: Dict[str, Any] = None):
        """Позначити як нездоровий"""
        self.is_healthy = False
        self.last_check = datetime.utcnow()
        self.error_count += 1
        self.last_error = error
        self.checks_performed += 1
        if metadata:
            self.metadata.update(metadata)

    def to_dict(self) -> Dict[str, Any]:
        """Конвертація в словник"""
        return {
            "component": self.component,
            "is_healthy": self.is_healthy,
            "last_check": self.last_check.isoformat(),
            "error_count": self.error_count,
            "last_error": self.last_error,
            "checks_performed": self.checks_performed,
            "uptime": self.uptime,
            "metadata": self.metadata,
        }


class HealthMonitor:  # pylint: disable=too-many-instance-attributes
    """Монітор здоров'я StreamHub"""

    def __init__(self, settings: Settings, client_manager=None):
        """Ініціалізація монітора здоров'я"""
        self.settings = settings
        self.client_manager = client_manager
        self.logger = structlog.get_logger(__name__)

        # Статуси компонентів
        self.component_statuses: Dict[str, HealthStatus] = {}

        # Статистика системи
        self.system_stats = {
            "cpu_usage": 0.0,
            "memory_usage": 0.0,
            "disk_usage": 0.0,
            "network_io": {"bytes_sent": 0, "bytes_recv": 0},
            "process_count": 0,
            "load_average": 0.0,
        }

        # Пороги сповіщень
        self.thresholds = {
            "cpu_usage": 80.0,  # %
            "memory_usage": 85.0,  # %
            "disk_usage": 90.0,  # %
            "client_timeout": self.settings.websocket_timeout,  # секунди
            "error_rate": 10,  # помилок за хвилину
            "response_time": 5.0,  # секунди
        }

        # Event handlers
        self.on_component_unhealthy: Optional[Callable[..., Awaitable[None]]] = None
        self.on_component_recovered: Optional[Callable[..., Awaitable[None]]] = None
        self.on_system_alert: Optional[Callable[..., Awaitable[None]]] = None
        self.on_client_unhealthy: Optional[Callable[..., Awaitable[None]]] = None

        # Стан монітора
        self.is_running = False
        self.start_time = datetime.utcnow()
        self.monitoring_task: Optional[asyncio.Task] = None
        self.system_monitor_task: Optional[asyncio.Task] = None

        # Історія перевірок
        self.check_history: List[Dict[str, Any]] = []
        self.max_history_size = 1000

        # Лічильники
        self.total_checks = 0
        self.failed_checks = 0
        self.alerts_sent = 0

        # Інтервал системного моніторингу (fallback, якщо немає в Settings)
        self.system_health_check_interval = getattr(
            self.settings, "system_health_check_interval", 60
        )

    async def initialize(self):
        """Ініціалізація монітора"""
        try:
            self.logger.info("Initializing Health Monitor")

            # Ініціалізація статусів компонентів
            self._initialize_component_statuses()

            # Запуск моніторингу
            self.is_running = True
            self.monitoring_task = asyncio.create_task(self._monitoring_loop())
            self.system_monitor_task = asyncio.create_task(
                self._system_monitoring_loop()
            )

            self.logger.info("Health Monitor initialized successfully")

        except Exception as e:  # pylint: disable=broad-exception-caught
            self.logger.error("Failed to initialize Health Monitor", error=str(e))
            raise

    async def shutdown(self):
        """Зупинка монітора"""
        self.logger.info("Shutting down Health Monitor")

        self.is_running = False

        # Зупинка задач моніторингу
        for task in [self.monitoring_task, self.system_monitor_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        self.logger.info("Health Monitor shutdown complete")

    def _initialize_component_statuses(self):
        """Ініціалізація статусів компонентів"""
        components = [
            "streamhub_core",
            "client_manager",
            "task_router",
            "redis_manager",
            "websocket_manager",
            "metrics_collector",
        ]

        for component in components:
            self.component_statuses[component] = HealthStatus(component)

    async def check_component_health(
        self, component: str, check_func: Callable
    ) -> bool:
        """Перевірка здоров'я компонента"""
        try:
            if component not in self.component_statuses:
                self.component_statuses[component] = HealthStatus(component)

            status = self.component_statuses[component]

            # Виконання перевірки
            start_time = datetime.utcnow()
            result = check_func()
            end_time = datetime.utcnow()

            response_time = (end_time - start_time).total_seconds()

            if result:
                # Компонент здоровий
                if not status.is_healthy:
                    # Відновлення після помилки
                    self.logger.info(
                        "Component recovered",
                        component=component,
                        response_time=response_time,
                    )

                    if callable(self.on_component_recovered):
                        await self.on_component_recovered(component)

                status.mark_healthy(
                    {"response_time": response_time, "check_time": end_time.isoformat()}
                )

            else:
                # Компонент нездоровий
                error_msg = f"Health check failed for {component}"

                if status.is_healthy:
                    # Нова помилка
                    self.logger.warning(
                        "Component became unhealthy",
                        component=component,
                        response_time=response_time,
                    )

                    if callable(self.on_component_unhealthy):
                        await self.on_component_unhealthy(component, error_msg)

                status.mark_unhealthy(
                    error_msg,
                    {
                        "response_time": response_time,
                        "check_time": end_time.isoformat(),
                    },
                )

            self.total_checks += 1
            if not result:
                self.failed_checks += 1

            # Додавання до історії
            self._add_to_history(
                {
                    "component": component,
                    "timestamp": end_time.isoformat(),
                    "is_healthy": result,
                    "response_time": response_time,
                    "error": None if result else error_msg,
                }
            )

            return result

        except Exception as e:  # pylint: disable=broad-exception-caught
            # Annotate broad exception
            self.logger.error(
                "Error checking component health", component=component, error=str(e)
            )

            if component in self.component_statuses:
                self.component_statuses[component].mark_unhealthy(str(e))

            self.failed_checks += 1
            return False

    async def check_client_health(
        self, client: Client
    ) -> bool:  # pylint: disable=too-many-return-statements
        """Перевірка здоров'я клієнта"""
        try:
            # Перевірка базового стану
            if not client.info.is_connected():
                return False

            # Перевірка останньої активності
            if client.info.stats.last_activity:
                inactive_time = (
                    datetime.utcnow() - client.info.stats.last_activity
                ).total_seconds()
                if inactive_time > self.thresholds["client_timeout"]:
                    self.logger.warning(
                        "Client inactive timeout",
                        client_id=client.info.client_id,
                        inactive_time=inactive_time,
                    )

                    if callable(self.on_client_unhealthy):
                        await self.on_client_unhealthy(client.info.client_id)

                    return False

            # Перевірка здоров'я для воркерів
            if client.info.is_worker():
                # Перевірка статусу воркера
                if client.info.worker_status in [
                    WorkerStatus.ERROR,
                    WorkerStatus.MAINTENANCE,
                ]:
                    return False

                # Перевірка перевантаження
                load_percentage = client.info.get_load_percentage()
                if load_percentage > 95:  # Перевантажений воркер
                    self.logger.warning(
                        "Worker overloaded",
                        client_id=client.info.client_id,
                        load=load_percentage,
                    )
                    return False

            # Перевірка рівня помилок
            error_rate = self._calculate_client_error_rate(client)
            if error_rate > self.thresholds["error_rate"]:
                self.logger.warning(
                    "High error rate for client",
                    client_id=client.info.client_id,
                    error_rate=error_rate,
                )
                return False

            return True

        except Exception as e:  # pylint: disable=broad-exception-caught
            self.logger.error(
                "Error checking client health",
                client_id=client.info.client_id,
                error=str(e),
            )
            return False

    def _calculate_client_error_rate(self, client: Client) -> float:
        """Розрахунок рівня помилок клієнта"""
        try:
            total_tasks = client.info.stats.total_tasks
            failed_tasks = client.info.stats.failed_tasks

            if total_tasks == 0:
                return 0.0

            return (failed_tasks / total_tasks) * 100

        except Exception:  # pylint: disable=broad-exception-caught
            return 0.0

    async def check_system_health(self) -> Dict[str, Any]:
        """Перевірка здоров'я системи"""
        try:
            # CPU використання
            cpu_usage = psutil.cpu_percent(interval=1)

            # Пам'ять
            memory = psutil.virtual_memory()
            memory_usage = memory.percent

            # Диск (Windows-сумісний шлях)

            disk_path = (
                os.path.splitdrive(os.getcwd())[0] + os.sep
            )  # Отримуємо поточний диск (наприклад, 'C:\\')
            disk = psutil.disk_usage(disk_path)
            disk_usage = disk.percent

            # Мережа (з обробкою помилок для Windows)
            try:
                network = psutil.net_io_counters()
            except Exception as e:  # pylint: disable=broad-exception-caught
                # Якщо виникає помилка PdhAddEnglishCounterW або інша, використовуємо значення за замовчуванням
                if "PdhAddEnglishCounterW" in str(e):
                    self.logger.info(
                        "[health_monitor.py] Performance counters disabled; "
                        "using default network values",
                        error=str(e),
                        source="health_monitor.py",
                    )
                else:
                    self.logger.warning(
                        "[health_monitor.py] Network counters unavailable",
                        error=str(e),
                        source="health_monitor.py",
                    )
                network = type("NetworkIO", (), {"bytes_sent": 0, "bytes_recv": 0})()

            # Процеси
            process_count = len(psutil.pids())

            # Навантаження системи (не підтримується на Windows)
            try:
                load_avg = (
                    psutil.getloadavg()[0] if hasattr(psutil, "getloadavg") else 0.0
                )
            except (OSError, AttributeError):
                # На Windows getloadavg() може викликати помилку
                load_avg = 0.0

            # Оновлення статистики
            self.system_stats.update(
                {
                    "cpu_usage": cpu_usage,
                    "memory_usage": memory_usage,
                    "disk_usage": disk_usage,
                    "network_io": {
                        "bytes_sent": network.bytes_sent,
                        "bytes_recv": network.bytes_recv,
                    },
                    "process_count": process_count,
                    "load_average": load_avg,
                }
            )

            # Перевірка порогів
            alerts = []

            if cpu_usage > self.thresholds["cpu_usage"]:
                alerts.append(f"High CPU usage: {cpu_usage:.1f}%")

            if memory_usage > self.thresholds["memory_usage"]:
                alerts.append(f"High memory usage: {memory_usage:.1f}%")

            if disk_usage > self.thresholds["disk_usage"]:
                alerts.append(f"High disk usage: {disk_usage:.1f}%")

            # Відправка сповіщень
            for alert in alerts:
                if callable(self.on_system_alert):
                    await self.on_system_alert(alert)
                self.alerts_sent += 1

            return {
                "is_healthy": len(alerts) == 0,
                "alerts": alerts,
                "stats": self.system_stats,
            }

        except Exception as e:  # pylint: disable=broad-exception-caught
            error_msg = str(e)
            if "PdhAddEnglishCounterW" in error_msg:
                self.logger.info(
                    "[health_monitor.py] Performance counters may be disabled. "
                    "System health check continues with limited metrics.",
                    error=error_msg,
                    source="health_monitor.py",
                )
                return {
                    "is_healthy": True,  # Не вважаємо це критичною помилкою
                    "alerts": [],
                    "stats": self.system_stats,
                }
            self.logger.error(
                "[health_monitor.py] Error checking system health",
                error=error_msg,
                source="health_monitor.py",
            )
            return {
                "is_healthy": False,
                "alerts": [f"System health check failed: {error_msg}"],
                "stats": self.system_stats,
            }

    async def get_overall_health(self) -> Dict[str, Any]:
        """Отримання загального стану здоров'я"""
        try:
            # Перевірка компонентів
            healthy_components = sum(
                1 for status in self.component_statuses.values() if status.is_healthy
            )
            total_components = len(self.component_statuses)
            component_health_percentage = (
                (healthy_components / total_components * 100)
                if total_components > 0
                else 100
            )

            # Перевірка клієнтів
            healthy_clients = 0
            total_clients = 0

            if self.client_manager:
                clients = self.client_manager.get_all_clients()
                total_clients = len(clients)

                for client in clients:
                    if await self.check_client_health(client):
                        healthy_clients += 1

            client_health_percentage = (
                (healthy_clients / total_clients * 100) if total_clients > 0 else 100
            )

            # Системне здоров'я
            system_health = await self.check_system_health()

            # Загальна оцінка
            overall_score = (component_health_percentage + client_health_percentage) / 2
            if not system_health["is_healthy"]:
                overall_score *= 0.8  # Штраф за системні проблеми

            # Визначення загального статусу
            if overall_score >= 90:
                overall_status = "excellent"
            elif overall_score >= 75:
                overall_status = "good"
            elif overall_score >= 50:
                overall_status = "warning"
            else:
                overall_status = "critical"

            uptime = (datetime.utcnow() - self.start_time).total_seconds()

            return {
                "overall_status": overall_status,
                "overall_score": round(overall_score, 1),
                "uptime_seconds": uptime,
                "components": {
                    "healthy": healthy_components,
                    "total": total_components,
                    "percentage": round(component_health_percentage, 1),
                },
                "clients": {
                    "healthy": healthy_clients,
                    "total": total_clients,
                    "percentage": round(client_health_percentage, 1),
                },
                "system": system_health,
                "statistics": {
                    "total_checks": self.total_checks,
                    "failed_checks": self.failed_checks,
                    "success_rate": (
                        round(
                            (self.total_checks - self.failed_checks)
                            / self.total_checks
                            * 100,
                            1,
                        )
                        if self.total_checks > 0
                        else 100
                    ),
                    "alerts_sent": self.alerts_sent,
                },
            }

        except Exception as e:  # pylint: disable=broad-exception-caught
            self.logger.error("Error getting overall health", error=str(e))
            return {"overall_status": "error", "overall_score": 0, "error": str(e)}

    def get_component_status(self, component: str) -> Optional[HealthStatus]:
        """Отримання статусу компонента"""
        return self.component_statuses.get(component)

    def get_all_component_statuses(self) -> Dict[str, HealthStatus]:
        """Отримання статусів всіх компонентів"""
        return self.component_statuses.copy()

    def get_system_stats(self) -> Dict[str, Any]:
        """Отримання системної статистики"""
        return self.system_stats.copy()

    def get_health_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Отримання історії перевірок здоров'я"""
        return self.check_history[-limit:] if limit > 0 else self.check_history

    def _add_to_history(self, check_result: Dict[str, Any]):
        """Додавання результату перевірки до історії"""
        self.check_history.append(check_result)

        # Обмеження розміру історії
        if len(self.check_history) > self.max_history_size:
            self.check_history = self.check_history[-self.max_history_size :]

    def is_healthy(self) -> bool:
        """Перевірка чи монітор здоровий"""
        return self.is_running

    async def _monitoring_loop(self):
        """Основний цикл моніторингу компонентів"""
        while self.is_running:
            try:
                # Перевірка компонентів - додаємо посилання на StreamHub
                hub = getattr(self, "hub", None)

                if self.client_manager:
                    await self.check_component_health(
                        "client_manager", self.client_manager.is_healthy
                    )

                # Перевірка WebSocket менеджера
                if hub and hasattr(hub, "websocket_manager") and hub.websocket_manager:
                    await self.check_component_health(
                        "websocket_manager", hub.websocket_manager.is_healthy
                    )

                # Перевірка Task Router
                if hub and hasattr(hub, "task_router") and hub.task_router:
                    await self.check_component_health(
                        "task_router", hub.task_router.is_healthy
                    )

                # Перевірка Redis менеджера
                if hub and hasattr(hub, "redis_manager") and hub.redis_manager:
                    await self.check_component_health(
                        "redis_manager", hub.redis_manager.is_healthy
                    )

                # Перевірка Metrics Collector
                if hub and hasattr(hub, "metrics_collector") and hub.metrics_collector:
                    await self.check_component_health(
                        "metrics_collector", hub.metrics_collector.is_healthy
                    )

                # Перевірка клієнтів
                if self.client_manager:
                    clients = self.client_manager.get_all_clients()
                    for client in clients:
                        await self.check_client_health(client)

                await asyncio.sleep(30)  # Перевірка кожні 30 секунд

            except asyncio.CancelledError:
                break
            except Exception as e:  # pylint: disable=broad-exception-caught
                self.logger.error("Error in monitoring loop", error=str(e))
                await asyncio.sleep(10)

    async def _system_monitoring_loop(self):
        """Цикл моніторингу системних ресурсів"""
        self.logger.info("Starting system monitoring loop")
        while self.is_running:
            try:
                await self.check_system_health()
                await asyncio.sleep(self.system_health_check_interval)
            except psutil.Error as e:
                error_msg = str(e)
                if "PdhAddEnglishCounterW" in error_msg:
                    self.logger.info(
                        "[health_monitor.py] Performance counters disabled. "
                        "Using default system health metrics.",
                        error=error_msg,
                        source="health_monitor.py",
                    )
                else:
                    self.logger.warning(
                        "[health_monitor.py] Could not collect system health metrics. "
                        "Performance counters might be disabled on Windows.",
                        error=error_msg,
                        source="health_monitor.py",
                    )
                # Продовжуємо роботу, але з більшою затримкою
                await asyncio.sleep(self.system_health_check_interval * 5)

            except asyncio.CancelledError:
                break
            except Exception as e:  # pylint: disable=broad-exception-caught
                self.logger.error("Error in system monitoring loop", error=str(e))
                await asyncio.sleep(self.system_health_check_interval)
        self.logger.info("System monitoring loop stopped")

    def update_threshold(self, metric: str, value: float):
        """Оновлення порогу метрики"""
        if metric in self.thresholds:
            old_value = self.thresholds[metric]
            self.thresholds[metric] = value
            self.logger.info(
                "Threshold updated", metric=metric, old_value=old_value, new_value=value
            )

    def get_thresholds(self) -> Dict[str, float]:
        """Отримання всіх порогів"""
        return self.thresholds.copy()

    async def force_health_check(self) -> Dict[str, Any]:
        """Примусова перевірка здоров'я всіх компонентів"""
        try:
            self.logger.info("Performing forced health check")

            results = {}

            # Перевірка всіх компонентів
            for component in self.component_statuses:
                try:
                    if component == "client_manager" and self.client_manager:
                        result = await self.check_component_health(
                            component, self.client_manager.is_healthy
                        )
                    else:
                        # Заглушка для інших компонентів
                        result = True

                    results[component] = result
                except Exception as e:  # pylint: disable=broad-exception-caught
                    results[component] = False
                    self.logger.error(
                        "Error in forced check", component=component, error=str(e)
                    )

            # Системна перевірка
            system_health = await self.check_system_health()
            results["system"] = system_health["is_healthy"]

            return {
                "timestamp": datetime.utcnow().isoformat(),
                "results": results,
                "overall": await self.get_overall_health(),
            }

        except Exception as e:  # pylint: disable=broad-exception-caught
            self.logger.error("Error in forced health check", error=str(e))
            return {"timestamp": datetime.utcnow().isoformat(), "error": str(e)}
