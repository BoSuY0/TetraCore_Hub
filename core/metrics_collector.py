"""
TetraCore StreamHub Metrics Collector

Збирач метрик для StreamHub.
Відповідає за збір, агрегацію та експорт метрик продуктивності,
статистики використання та системних показників.
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Set
from collections import defaultdict, deque
from dataclasses import dataclass, field
import structlog
import json

from config import Settings


@dataclass
class Metric:
    """Базовий клас для метрики"""
    name: str
    value: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    labels: Dict[str, str] = field(default_factory=dict)
    unit: str = ""
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Конвертація в словник"""
        return {
            "name": self.name,
            "value": self.value,
            "timestamp": self.timestamp.isoformat(),
            "labels": self.labels,
            "unit": self.unit,
            "description": self.description
        }


@dataclass
class Counter:
    """Лічильник метрик"""
    name: str
    description: str = ""
    labels: Dict[str, str] = field(default_factory=dict)
    value: int = 0

    def increment(self, amount: int = 1):
        """Збільшення лічильника"""
        self.value += amount

    def reset(self):
        """Скидання лічильника"""
        self.value = 0

    def get_metric(self) -> Metric:
        """Отримання метрики"""
        return Metric(
            name=self.name,
            value=float(self.value),
            labels=self.labels,
            unit="count",
            description=self.description
        )


@dataclass
class Gauge:
    """Індикатор метрик"""
    name: str
    description: str = ""
    labels: Dict[str, str] = field(default_factory=dict)
    value: float = 0.0

    def set(self, value: float):
        """Встановлення значення"""
        self.value = value

    def increment(self, amount: float = 1.0):
        """Збільшення значення"""
        self.value += amount

    def decrement(self, amount: float = 1.0):
        """Зменшення значення"""
        self.value -= amount

    def get_metric(self) -> Metric:
        """Отримання метрики"""
        return Metric(
            name=self.name,
            value=self.value,
            labels=self.labels,
            description=self.description
        )


@dataclass
class Histogram:
    """Гістограма метрик"""
    name: str
    description: str = ""
    labels: Dict[str, str] = field(default_factory=dict)
    buckets: List[float] = field(default_factory=lambda: [0.1, 0.5, 1.0, 2.5, 5.0, 10.0])
    values: List[float] = field(default_factory=list)
    max_size: int = 1000

    def observe(self, value: float):
        """Додавання спостереження"""
        self.values.append(value)

        # Обмеження розміру
        if len(self.values) > self.max_size:
            self.values = self.values[-self.max_size:]

    def get_metrics(self) -> List[Metric]:
        """Отримання метрик гістограми"""
        if not self.values:
            return []

        metrics = []

        # Лічильники buckets
        for bucket in self.buckets:
            count = sum(1 for v in self.values if v <= bucket)
            bucket_labels = {**self.labels, "le": str(bucket)}

            metrics.append(Metric(
                name=f"{self.name}_bucket",
                value=float(count),
                labels=bucket_labels,
                unit="count",
                description=f"{self.description} bucket"
            ))

        # Загальна кількість
        metrics.append(Metric(
            name=f"{self.name}_count",
            value=float(len(self.values)),
            labels=self.labels,
            unit="count",
            description=f"{self.description} count"
        ))

        # Сума
        total = sum(self.values)
        metrics.append(Metric(
            name=f"{self.name}_sum",
            value=total,
            labels=self.labels,
            description=f"{self.description} sum"
        ))

        return metrics

    def get_percentile(self, percentile: float) -> float:
        """Отримання перцентиля"""
        if not self.values:
            return 0.0

        sorted_values = sorted(self.values)
        index = int(len(sorted_values) * percentile / 100)
        return sorted_values[min(index, len(sorted_values) - 1)]

    def get_average(self) -> float:
        """Отримання середнього значення"""
        return sum(self.values) / len(self.values) if self.values else 0.0


class MetricsCollector:
    """Збирач метрик StreamHub"""

    def __init__(self, settings: Settings):
        """Ініціалізація збирача метрик"""
        self.settings = settings
        self.logger = structlog.get_logger(__name__)

        # Зберігання метрик
        self.counters: Dict[str, Counter] = {}
        self.gauges: Dict[str, Gauge] = {}
        self.histograms: Dict[str, Histogram] = {}

        # Історія метрик
        self.metric_history: deque = deque(maxlen=10000)

        # Часові ряди для агрегації
        self.time_series: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))

        # Стан збирача
        self.is_running = False
        self.start_time = datetime.utcnow()
        self.collection_task: Optional[asyncio.Task] = None
        self.aggregation_task: Optional[asyncio.Task] = None

        # Лічильники системи
        self.collection_count = 0
        self.export_count = 0
        self.errors_count = 0

        # Кеш для швидкого доступу
        self.cached_metrics: Dict[str, Any] = {}
        self.cache_ttl = 30  # секунди
        self.last_cache_update = datetime.utcnow()

    async def initialize(self):
        """Ініціалізація збирача метрик"""
        try:
            self.logger.info("Initializing Metrics Collector")

            # Створення базових метрик
            self._initialize_default_metrics()

            # Запуск фонових задач
            if self.settings.enable_metrics:
                self.collection_task = asyncio.create_task(self._collection_loop())
                self.aggregation_task = asyncio.create_task(self._aggregation_loop())

            self.is_running = True
            self.logger.info("Metrics Collector initialized successfully")

        except Exception as e:
            self.logger.error("Failed to initialize Metrics Collector", error=str(e))
            raise

    async def shutdown(self):
        """Зупинка збирача метрик"""
        self.logger.info("Shutting down Metrics Collector")

        self.is_running = False

        # Зупинка фонових задач
        for task in [self.collection_task, self.aggregation_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Збереження фінальних метрик відключено для зменшення файлового сміття
        # await self._export_final_metrics()

        self.logger.info("Metrics Collector shutdown complete")

    def _initialize_default_metrics(self):
        """Ініціалізація базових метрик"""
        # Лічильники
        self.register_counter("streamhub_connections_total", "Total number of connections")
        self.register_counter("streamhub_tasks_submitted_total", "Total number of submitted tasks")
        self.register_counter("streamhub_tasks_completed_total", "Total number of completed tasks")
        self.register_counter("streamhub_tasks_failed_total", "Total number of failed tasks")
        self.register_counter("streamhub_messages_sent_total", "Total number of messages sent")
        self.register_counter("streamhub_messages_received_total", "Total number of messages received")
        self.register_counter("streamhub_errors_total", "Total number of errors")

        # Індикатори
        self.register_gauge("streamhub_active_connections", "Number of active connections")
        self.register_gauge("streamhub_active_tasks", "Number of active tasks")
        self.register_gauge("streamhub_queue_size", "Size of task queue")
        self.register_gauge("streamhub_cpu_usage", "CPU usage percentage")
        self.register_gauge("streamhub_memory_usage", "Memory usage percentage")
        self.register_gauge("streamhub_redis_connections", "Number of Redis connections")

        # Гістограми
        self.register_histogram("streamhub_task_duration_seconds", "Task execution duration")
        self.register_histogram("streamhub_request_duration_seconds", "Request duration")
        self.register_histogram("streamhub_websocket_message_size_bytes", "WebSocket message size")
        self.register_histogram("streamhub_redis_operation_duration_seconds", "Redis operation duration")

    def register_counter(self, name: str, description: str = "", labels: Dict[str, str] = None) -> Counter:
        """Реєстрація лічильника"""
        counter = Counter(name=name, description=description, labels=labels or {})
        self.counters[name] = counter
        return counter

    def register_gauge(self, name: str, description: str = "", labels: Dict[str, str] = None) -> Gauge:
        """Реєстрація індикатора"""
        gauge = Gauge(name=name, description=description, labels=labels or {})
        self.gauges[name] = gauge
        return gauge

    def register_histogram(self, name: str, description: str = "", labels: Dict[str, str] = None,
                          buckets: List[float] = None) -> Histogram:
        """Реєстрація гістограми"""
        histogram = Histogram(
            name=name,
            description=description,
            labels=labels or {},
            buckets=buckets or [0.1, 0.5, 1.0, 2.5, 5.0, 10.0]
        )
        self.histograms[name] = histogram
        return histogram

    def increment_counter(self, name: str, amount: int = 1, labels: Dict[str, str] = None):
        """Збільшення лічильника"""
        try:
            if name in self.counters:
                self.counters[name].increment(amount)
            else:
                counter = self.register_counter(name, labels=labels)
                counter.increment(amount)

            self._add_to_history(name, amount, "counter")

        except Exception as e:
            self.logger.error("Error incrementing counter", name=name, error=str(e))
            self.errors_count += 1

    def set_gauge(self, name: str, value: float, labels: Dict[str, str] = None):
        """Встановлення значення індикатора"""
        try:
            if name in self.gauges:
                self.gauges[name].set(value)
            else:
                gauge = self.register_gauge(name, labels=labels)
                gauge.set(value)

            self._add_to_history(name, value, "gauge")
            self._add_to_time_series(name, value)

        except Exception as e:
            self.logger.error("Error setting gauge", name=name, error=str(e))
            self.errors_count += 1

    def observe_histogram(self, name: str, value: float, labels: Dict[str, str] = None):
        """Додавання спостереження до гістограми"""
        try:
            if name in self.histograms:
                self.histograms[name].observe(value)
            else:
                histogram = self.register_histogram(name, labels=labels)
                histogram.observe(value)

            self._add_to_history(name, value, "histogram")

        except Exception as e:
            self.logger.error("Error observing histogram", name=name, error=str(e))
            self.errors_count += 1

    def _add_to_history(self, name: str, value: float, metric_type: str):
        """Додавання до історії метрик"""
        self.metric_history.append({
            "name": name,
            "value": value,
            "type": metric_type,
            "timestamp": datetime.utcnow().isoformat()
        })

    def _add_to_time_series(self, name: str, value: float):
        """Додавання до часових рядів"""
        self.time_series[name].append({
            "value": value,
            "timestamp": time.time()
        })

    async def get_metrics(self, metric_types: List[str] = None) -> Dict[str, Any]:
        """Отримання всіх метрик"""
        try:
            # Перевірка кешу
            now = datetime.utcnow()
            if (now - self.last_cache_update).total_seconds() < self.cache_ttl:
                return self.cached_metrics

            metrics = {}

            # Лічильники
            if not metric_types or "counters" in metric_types:
                metrics["counters"] = {
                    name: counter.get_metric().to_dict()
                    for name, counter in self.counters.items()
                }

            # Індикатори
            if not metric_types or "gauges" in metric_types:
                metrics["gauges"] = {
                    name: gauge.get_metric().to_dict()
                    for name, gauge in self.gauges.items()
                }

            # Гістограми
            if not metric_types or "histograms" in metric_types:
                histograms = {}
                for name, histogram in self.histograms.items():
                    histogram_metrics = histogram.get_metrics()
                    histograms[name] = {
                        "metrics": [m.to_dict() for m in histogram_metrics],
                        "percentiles": {
                            "p50": histogram.get_percentile(50),
                            "p90": histogram.get_percentile(90),
                            "p95": histogram.get_percentile(95),
                            "p99": histogram.get_percentile(99)
                        },
                        "average": histogram.get_average()
                    }
                metrics["histograms"] = histograms

            # Метадані
            metrics["metadata"] = {
                "collection_time": now.isoformat(),
                "uptime_seconds": (now - self.start_time).total_seconds(),
                "collection_count": self.collection_count,
                "export_count": self.export_count,
                "errors_count": self.errors_count
            }

            # Кешування
            self.cached_metrics = metrics
            self.last_cache_update = now

            return metrics

        except Exception as e:
            self.logger.error("Error getting metrics", error=str(e))
            self.errors_count += 1
            return {}

    async def get_all_metrics(self) -> Dict[str, Any]:
        """Отримання всіх метрик включно з системними"""
        try:
            base_metrics = await self.get_metrics()

            # Додавання системних метрик
            system_metrics = await self._collect_system_metrics()
            base_metrics["system"] = system_metrics

            # Додавання часових рядів
            base_metrics["time_series"] = self._get_time_series_summary()

            # Додавання історії
            base_metrics["recent_history"] = list(self.metric_history)[-100:]

            return base_metrics

        except Exception as e:
            self.logger.error("Error getting all metrics", error=str(e))
            return {}

    async def _collect_system_metrics(self) -> Dict[str, Any]:
        """Збір системних метрик"""
        try:
            import psutil

            # CPU
            cpu_percent = psutil.cpu_percent(interval=0.1)
            self.set_gauge("streamhub_cpu_usage", cpu_percent)

            # Пам'ять
            memory = psutil.virtual_memory()
            self.set_gauge("streamhub_memory_usage", memory.percent)

            # Диск
            disk = psutil.disk_usage('/')
            disk_percent = disk.percent

            # Мережа
            network = psutil.net_io_counters()

            # Процес Python
            process = psutil.Process()
            process_memory = process.memory_info()

            return {
                "cpu_percent": cpu_percent,
                "memory_percent": memory.percent,
                "memory_available": memory.available,
                "memory_used": memory.used,
                "disk_percent": disk_percent,
                "disk_free": disk.free,
                "disk_used": disk.used,
                "network_bytes_sent": network.bytes_sent,
                "network_bytes_recv": network.bytes_recv,
                "process_memory_rss": process_memory.rss,
                "process_memory_vms": process_memory.vms,
                "process_cpu_percent": process.cpu_percent(),
                "process_threads": process.num_threads()
            }

        except Exception as e:
            self.logger.error("Error collecting system metrics", error=str(e))
            return {}

    def _get_time_series_summary(self) -> Dict[str, Any]:
        """Отримання підсумку часових рядів"""
        summary = {}

        for name, series in self.time_series.items():
            if not series:
                continue

            values = [point["value"] for point in series]

            summary[name] = {
                "count": len(values),
                "min": min(values),
                "max": max(values),
                "avg": sum(values) / len(values),
                "latest": values[-1] if values else 0,
                "trend": self._calculate_trend(values)
            }

        return summary

    def _calculate_trend(self, values: List[float]) -> str:
        """Розрахунок тренду значень"""
        if len(values) < 2:
            return "stable"

        # Простий тренд на основі першої і останньої третини
        first_third = values[:len(values)//3] or [values[0]]
        last_third = values[-len(values)//3:] or [values[-1]]

        first_avg = sum(first_third) / len(first_third)
        last_avg = sum(last_third) / len(last_third)

        if last_avg > first_avg * 1.1:
            return "increasing"
        elif last_avg < first_avg * 0.9:
            return "decreasing"
        else:
            return "stable"

    async def export_prometheus_metrics(self) -> str:
        """Експорт метрик у форматі Prometheus"""
        try:
            output = []

            # Лічильники
            for name, counter in self.counters.items():
                metric = counter.get_metric()
                labels_str = self._format_prometheus_labels(metric.labels)
                output.append(f"# HELP {name} {metric.description}")
                output.append(f"# TYPE {name} counter")
                output.append(f"{name}{labels_str} {metric.value}")
                output.append("")

            # Індикатори
            for name, gauge in self.gauges.items():
                metric = gauge.get_metric()
                labels_str = self._format_prometheus_labels(metric.labels)
                output.append(f"# HELP {name} {metric.description}")
                output.append(f"# TYPE {name} gauge")
                output.append(f"{name}{labels_str} {metric.value}")
                output.append("")

            # Гістограми
            for name, histogram in self.histograms.items():
                metrics = histogram.get_metrics()
                if metrics:
                    output.append(f"# HELP {name} {histogram.description}")
                    output.append(f"# TYPE {name} histogram")

                    for metric in metrics:
                        labels_str = self._format_prometheus_labels(metric.labels)
                        output.append(f"{metric.name}{labels_str} {metric.value}")

                    output.append("")

            self.export_count += 1
            return "\n".join(output)

        except Exception as e:
            self.logger.error("Error exporting Prometheus metrics", error=str(e))
            self.errors_count += 1
            return ""

    def _format_prometheus_labels(self, labels: Dict[str, str]) -> str:
        """Форматування міток для Prometheus"""
        if not labels:
            return ""

        label_pairs = [f'{key}="{value}"' for key, value in labels.items()]
        return "{" + ",".join(label_pairs) + "}"

    async def reset_metrics(self, metric_names: List[str] = None):
        """Скидання метрик"""
        try:
            if metric_names:
                # Скидання конкретних метрик
                for name in metric_names:
                    if name in self.counters:
                        self.counters[name].reset()
                    if name in self.gauges:
                        self.gauges[name].set(0.0)
                    if name in self.histograms:
                        self.histograms[name].values.clear()
            else:
                # Скидання всіх метрик
                for counter in self.counters.values():
                    counter.reset()
                for gauge in self.gauges.values():
                    gauge.set(0.0)
                for histogram in self.histograms.values():
                    histogram.values.clear()

            self.logger.info("Metrics reset", metrics=metric_names or "all")

        except Exception as e:
            self.logger.error("Error resetting metrics", error=str(e))

    async def _export_final_metrics(self):
        """Експорт фінальних метрик при завершенні - ВІДКЛЮЧЕНО"""
        # Метод відключено для запобігання створенню файлів метрик
        # Це зменшує файловий сміття та покращує продуктивність
        self.logger.debug("Metrics export disabled - no files will be created")
        return

        # Закоментований код експорту:
        # try:
        #     final_metrics = await self.get_all_metrics()
        #     timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        #     filename = f"streamhub_metrics_{timestamp}.json"
        #     with open(filename, 'w', encoding='utf-8') as f:
        #         json.dump(final_metrics, f, indent=2, ensure_ascii=False)
        #     self.logger.info("Final metrics exported", filename=filename)
        # except Exception as e:
        #     self.logger.error("Error exporting final metrics", error=str(e))

    async def _collection_loop(self):
        """Фоновий цикл збору метрик"""
        while self.is_running:
            try:
                await self._collect_automatic_metrics()
                self.collection_count += 1
                await asyncio.sleep(60)  # Збір кожну хвилину

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in collection loop", error=str(e))
                self.errors_count += 1
                await asyncio.sleep(30)

    async def _aggregation_loop(self):
        """Фоновий цикл агрегації метрик"""
        while self.is_running:
            try:
                await self._aggregate_metrics()
                await asyncio.sleep(300)  # Агрегація кожні 5 хвилин

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in aggregation loop", error=str(e))
                self.errors_count += 1
                await asyncio.sleep(60)

    async def _collect_automatic_metrics(self):
        """Автоматичний збір метрик"""
        try:
            # Системні метрики
            await self._collect_system_metrics()

            # Очищення кешу для оновлення
            self.last_cache_update = datetime.utcnow() - timedelta(seconds=self.cache_ttl + 1)

        except Exception as e:
            self.logger.error("Error in automatic metrics collection", error=str(e))

    async def _aggregate_metrics(self):
        """Агрегація метрик"""
        try:
            # Очищення старих записів з історії
            cutoff_time = datetime.utcnow() - timedelta(hours=24)

            while (self.metric_history and
                   datetime.fromisoformat(self.metric_history[0]["timestamp"]) < cutoff_time):
                self.metric_history.popleft()

            # Очищення старих часових рядів
            cutoff_timestamp = time.time() - (24 * 3600)  # 24 години

            for name in self.time_series:
                while (self.time_series[name] and
                       self.time_series[name][0]["timestamp"] < cutoff_timestamp):
                    self.time_series[name].popleft()

        except Exception as e:
            self.logger.error("Error in metrics aggregation", error=str(e))

    def is_healthy(self) -> bool:
        """Перевірка здоров'я збирача метрик"""
        return self.is_running

    def get_stats(self) -> Dict[str, Any]:
        """Отримання статистики збирача"""
        return {
            "is_running": self.is_running,
            "uptime_seconds": (datetime.utcnow() - self.start_time).total_seconds(),
            "collection_count": self.collection_count,
            "export_count": self.export_count,
            "errors_count": self.errors_count,
            "metrics_count": {
                "counters": len(self.counters),
                "gauges": len(self.gauges),
                "histograms": len(self.histograms)
            },
            "history_size": len(self.metric_history),
            "time_series_count": len(self.time_series),
            "cache_age_seconds": (datetime.utcnow() - self.last_cache_update).total_seconds()
        }
