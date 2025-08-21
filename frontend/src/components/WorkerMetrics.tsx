import React, { useState, useEffect, useMemo, memo, useCallback } from "react";
import { useI18n } from "../contexts/I18nContext";
import { useStatus } from "../contexts/StatusContext";
import { Client } from "../types/api";
import { API_BASE_URL, buildUrl } from "../config";
import "../animations.css";
import {
  CpuIcon,
  CheckIcon,
  AlertIcon,
  ProcessingIcon,
  MemoryIcon,
  SpeedIcon,
  AnimatedHeartIcon,
  WarningIcon,
  ErrorIcon,
} from "./Icons";

interface WorkerMetricsData {
  timestamp: string;
  cpu_usage: number;
  memory_usage: number;
  active_tasks: number;
  completed_tasks: number;
  failed_tasks: number;
  response_time: number;
}

// Новий інтерфейс для системних ресурсів
interface SystemResourceData {
  cpu_usage: number;
  memory_usage: number;
  disk_usage: number;
  network_in: number;
  network_out: number;
  uptime: number;
}

interface WorkerMetricsProps {
  clients: Client[];
}

// API функції для отримання реальних даних
// API_BASE_URL імпортується з config.ts

const fetchHubMetrics = async (): Promise<any> => {
  try {
    const sessionId = localStorage.getItem('sessionId');
    const headers: HeadersInit = {
      'Content-Type': 'application/json',
    };
    
    if (sessionId) {
      headers.Authorization = `Bearer ${sessionId}`;
    }
    
    const response = await fetch(buildUrl("/api/metrics"), {
      headers,
    });
    
    if (!response.ok) {
      if (response.status === 401) {
        // Redirect to login on authentication failure
        window.location.href = '/';
        return null;
      }
      throw new Error("Failed to fetch hub metrics");
    }
    
    return await response.json();
  } catch (error) {
    console.error("Error fetching hub metrics:", error);
    return null;
  }
};

const fetchClientMetrics = async (
  clientId: string,
): Promise<WorkerMetricsData[]> => {
  try {
    const sessionId = localStorage.getItem('sessionId');
    const headers: HeadersInit = {
      'Content-Type': 'application/json',
    };
    
    if (sessionId) {
      headers.Authorization = `Bearer ${sessionId}`;
    }
    
    const response = await fetch(
      `${API_BASE_URL}/api/clients/${clientId}/metrics`,
      {
        headers,
      }
    );
    
    if (!response.ok) {
      if (response.status === 401) {
        // Redirect to login on authentication failure
        window.location.href = '/';
        return [];
      }
      
      if (response.status === 404) {
        // Клієнт не має метрик - це нормально, не логуємо як помилку
        console.debug(`📊 No metrics available for client ${clientId} (404)`);
        return [];
      }
      
      if (response.status === 429) {
        // Rate limiting - логуємо один раз
        console.warn(`⚠️ Rate limited when fetching metrics for client ${clientId}`);
        return [];
      }
      
      // Тільки для інших помилок логуємо як error
      console.error(`❌ HTTP ${response.status} when fetching metrics for client ${clientId}`);
      return [];
    }
    
    const data = await response.json();

    // Перетворюємо дані з API у формат WorkerMetricsData
    if (data.metrics && Array.isArray(data.metrics)) {
      return data.metrics.map((metric: any) => ({
        timestamp: metric.timestamp || new Date().toISOString(),
        cpu_usage: metric.cpu_usage || 0,
        memory_usage: metric.memory_usage || 0,
        active_tasks: metric.active_tasks || 0,
        completed_tasks: metric.completed_tasks || 0,
        failed_tasks: metric.failed_tasks || 0,
        response_time: metric.response_time || 0,
      }));
    }

    // Якщо метрики відсутні, повертаємо порожній масив без логування
    return [];
  } catch (error) {
    // Логуємо тільки критичні помилки (мережа тощо)
    if (error instanceof Error && error.message.includes('fetch')) {
      console.error(`🌐 Network error fetching metrics for client ${clientId}:`, error.message);
    } else {
      console.debug(`📊 No metrics data available for client ${clientId}`);
    }
    return [];
  }
};

const fetchRealTimeMetrics = async (): Promise<any> => {
  try {
    const sessionId = localStorage.getItem('sessionId');
    const headers: HeadersInit = {
      'Content-Type': 'application/json',
    };
    
    if (sessionId) {
      headers.Authorization = `Bearer ${sessionId}`;
    }
    
    const response = await fetch(
      `${API_BASE_URL}/api/frontend/real-time-metrics`,
      {
        headers,
      }
    );
    
    if (!response.ok) {
      if (response.status === 401) {
        // Redirect to login on authentication failure
        window.location.href = '/';
        return null;
      }
      throw new Error("Failed to fetch real-time metrics");
    }
    
    return await response.json();
  } catch (error) {
    console.error("Error fetching real-time metrics:", error);
    return null;
  }
};

// Компонент системного моніторингу ресурсів
const SystemResourceMonitor: React.FC<{
  selectedClient?: Client | null;
  resourceData?: SystemResourceData;
}> = ({ selectedClient, resourceData }) => {
  const { t } = useI18n();
  const { state } = useStatus();
  const [realTimeData, setRealTimeData] = useState<any>(null);

  // Отримуємо реальні дані з API
  useEffect(() => {
    // Оскільки метрики приходять по WebSocket через StatusContext,
    // підтримуємо тільки одноразове завантаження як стартовий fallback.
    let cancelled = false;
    const primeData = async () => {
      const hubMetrics = await fetchHubMetrics();
      const rtMetrics = await fetchRealTimeMetrics();
      if (!cancelled && (hubMetrics || rtMetrics)) {
        setRealTimeData({ hub: hubMetrics, realTime: rtMetrics });
      }
    };
    primeData();
    return () => {
      cancelled = true;
    };
  }, [selectedClient]);

  const getUsageColor = (value: number) => {
    if (value > 80) return "bg-red-500";
    if (value > 60) return "bg-yellow-500";
    return "bg-green-500";
  };

  const getUsageTextColor = (value: number) => {
    if (value > 80) return "text-red-600";
    if (value > 60) return "text-yellow-600";
    return "text-green-600";
  };

  const formatBytes = (bytes: number) => {
    if (bytes === 0) return "0 B";
    const k = 1024;
    const sizes = ["B", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
  };

  const formatUptime = (seconds: number) => {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    return `${hours}г ${minutes}хв`;
  };

  // Використовуємо реальні дані з API
  const systemData = resourceData || {
    cpu_usage: state.metrics?.system?.cpu_usage ?? realTimeData?.hub?.system?.cpu_usage ?? 0,
    memory_usage: state.metrics?.system?.memory_usage ?? realTimeData?.hub?.system?.memory_usage ?? 0,
    disk_usage: state.metrics?.system?.disk_usage ?? realTimeData?.hub?.system?.disk_usage ?? 0,
    network_in: 0,
    network_out: 0,
    uptime: state.metrics?.system?.uptime ?? realTimeData?.hub?.uptime ?? state.health?.uptime ?? 0,
  };

  const resources = [
    {
      name: "CPU",
      value: systemData.cpu_usage,
      icon: <CpuIcon size="md" className="text-blue-600" />,
      color: "blue",
    },
    {
      name: t("dashboard.memory"),
      value: systemData.memory_usage,
      icon: <MemoryIcon size="md" className="text-green-600" />,
      color: "green",
    },
    {
      name: t("dashboard.disk"),
      value: systemData.disk_usage,
      icon: "💿",
      color: "purple",
    },
  ];

  return (
    <div className="bg-white rounded-xl shadow-sm border border-secondary-100 p-6">
      <h3 className="text-lg font-semibold text-secondary-900 mb-6 flex items-center">
        📊 {t("dashboard.resourceMonitor")}
        {selectedClient && (
          <span className="ml-2 text-sm text-secondary-600 font-normal">
            - {selectedClient.client_name || selectedClient.client_id}
          </span>
        )}
      </h3>

      <div className="space-y-6">
        {resources.map((resource, index) => (
          <div
            key={resource.name}
            className="space-y-3 p-4 bg-secondary-50 rounded-lg hover:bg-secondary-100 transition-colors duration-200"
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-3">
                {typeof resource.icon === "string" ? (
                  <span className="text-2xl">{resource.icon}</span>
                ) : (
                  resource.icon
                )}
                <span className="text-base font-medium text-secondary-800">
                  {resource.name}
                </span>
              </div>
              <span
                className={`text-lg font-bold ${getUsageTextColor(resource.value)}`}
              >
                {Math.round(resource.value)}%
              </span>
            </div>
            <div className="w-full bg-secondary-200 rounded-full h-3">
              <div
                className={`h-3 rounded-full transition-all duration-500 ${getUsageColor(resource.value)}`}
                style={{ width: `${Math.min(resource.value, 100)}%` }}
              />
            </div>
          </div>
        ))}

        {/* Мережева активність */}
        <div className="grid grid-cols-2 gap-4 mt-6">
          <div className="text-center p-4 bg-blue-50 rounded-lg">
            <p className="text-lg font-bold text-blue-600">
              {formatBytes(systemData.network_in * 1024 * 1024)}
            </p>
            <p className="text-sm text-blue-700">
              {t("dashboard.incomingTraffic")}
            </p>
          </div>
          <div className="text-center p-4 bg-green-50 rounded-lg">
            <p className="text-lg font-bold text-green-600">
              {formatBytes(systemData.network_out * 1024 * 1024)}
            </p>
            <p className="text-sm text-green-700">
              {t("dashboard.outgoingTraffic")}
            </p>
          </div>
        </div>

        {/* Час роботи */}
        {systemData.uptime > 0 && (
          <div className="pt-4 border-t border-secondary-200">
            <div className="flex justify-between items-center">
              <span className="text-sm text-secondary-600">
                {t("dashboard.systemUptime")}
              </span>
              <span className="text-lg font-bold text-purple-600">
                {formatUptime(systemData.uptime)}
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

const MetricChart: React.FC<{
  title: string;
  data: WorkerMetricsData[];
  dataKey: keyof WorkerMetricsData;
  color: string;
  unit?: string;
}> = memo(
  ({ title, data, dataKey, color, unit = "" }) => {
    const { maxValue, minValue, range, points, yAxisLabels } = useMemo(() => {
      // Handle empty or invalid data
      if (!data || data.length === 0) {
        return {
          maxValue: 0,
          minValue: 0,
          range: 1,
          points: [],
          yAxisLabels: [],
        };
      }

      const values = data
        .map((d) => {
          const val = Number(d[dataKey]);
          return isNaN(val) ? 0 : val;
        })
        .filter((val) => !isNaN(val));

      if (values.length === 0) {
        return {
          maxValue: 0,
          minValue: 0,
          range: 1,
          points: [],
          yAxisLabels: [],
        };
      }

      const max = Math.max(...values);
      const min = Math.min(...values);

      // Додаємо відступи для кращого відображення
      const padding = (max - min) * 0.1 || 1;
      const adjustedMax = max + padding;
      const adjustedMin = Math.max(0, min - padding);
      const r = adjustedMax - adjustedMin || 1;

      // Розміри графіка
      const chartWidth = 340;
      const chartHeight = 120;
      const leftMargin = 60;
      const topMargin = 20;

      const chartPoints = data.map((point, index) => {
        const x =
          leftMargin + (index * chartWidth) / Math.max(data.length - 1, 1);
        const value = Number(point[dataKey]);
        const safeValue = isNaN(value) ? 0 : value;
        const y =
          topMargin +
          chartHeight -
          ((safeValue - adjustedMin) / r) * chartHeight;
        return {
          x,
          y: isNaN(y)
            ? topMargin + chartHeight
            : Math.max(topMargin, Math.min(topMargin + chartHeight, y)),
          value: safeValue,
          timestamp: point.timestamp,
        };
      });

      // Генеруємо лейбли для Y-осі
      const labelCount = 5;
      const yLabels = Array.from({ length: labelCount }, (_, i) => {
        const value = adjustedMax - (i * r) / (labelCount - 1);
        const y = topMargin + (i * chartHeight) / (labelCount - 1);
        return { value, y };
      });

      return {
        maxValue: adjustedMax,
        minValue: adjustedMin,
        range: r,
        points: chartPoints,
        yAxisLabels: yLabels,
      };
    }, [data, dataKey]);

    return (
      <div className="bg-white rounded-xl shadow-sm p-6 transform hover:scale-105 transition-all duration-300 hover:shadow-lg animate-fade-in">
        <h3 className="text-lg font-semibold text-secondary-900 mb-4">
          {title}
        </h3>
        <div className="relative h-56">
          {points.length === 0 ? (
            <div className="flex items-center justify-center h-full">
              <p className="text-secondary-500 text-sm">
                Немає даних для відображення
              </p>
            </div>
          ) : (
            <svg
              className="w-full h-full"
              viewBox="0 0 420 180"
              preserveAspectRatio="xMidYMid meet"
            >
              {/* Grid lines */}
              {yAxisLabels.map((label, i) => (
                <line
                  key={i}
                  x1="60"
                  y1={label.y}
                  x2="400"
                  y2={label.y}
                  stroke="#f3f4f6"
                  strokeWidth="1"
                />
              ))}

              {/* Y-axis */}
              <line
                x1="60"
                y1="20"
                x2="60"
                y2="140"
                stroke="#e5e7eb"
                strokeWidth="1"
              />

              {/* X-axis */}
              <line
                x1="60"
                y1="140"
                x2="400"
                y2="140"
                stroke="#e5e7eb"
                strokeWidth="1"
              />

              {/* Y-axis labels */}
              {yAxisLabels.map((label, i) => (
                <text
                  key={i}
                  x="55"
                  y={label.y + 4}
                  textAnchor="end"
                  className="text-xs fill-secondary-500"
                  fontSize="10"
                >
                  {label.value.toFixed(1)}
                  {unit}
                </text>
              ))}

              {/* Chart area background */}
              <rect
                x="60"
                y="20"
                width="340"
                height="120"
                fill="transparent"
                stroke="none"
              />

              {/* Chart line */}
              {points.length > 1 && (
                <polyline
                  fill="none"
                  stroke={color}
                  strokeWidth="2.5"
                  points={points.map((p) => `${p.x},${p.y}`).join(" ")}
                  style={{
                    strokeDasharray: "1000",
                    strokeDashoffset: "1000",
                    animation: "drawLine 2s ease-out forwards",
                  }}
                />
              )}

              {/* Area fill under line */}
              {points.length > 1 && (
                <polygon
                  fill={color}
                  fillOpacity="0.1"
                  points={`
                    ${points.map((p) => `${p.x},${p.y}`).join(" ")}
                    ${points[points.length - 1].x},140
                    ${points[0].x},140
                  `}
                />
              )}

              {/* Data points */}
              {points.map((point, index) => (
                <g key={index}>
                  <circle
                    cx={point.x}
                    cy={point.y}
                    r="4"
                    fill="white"
                    stroke={color}
                    strokeWidth="2"
                    className="hover:r-6 transition-all cursor-pointer"
                  />
                  <circle cx={point.x} cy={point.y} r="2" fill={color} />
                  <title>{`${title}: ${point.value.toFixed(2)}${unit}\nЧас: ${new Date(point.timestamp).toLocaleTimeString()}`}</title>
                </g>
              ))}

              {/* Current value indicator */}
              {points.length > 0 && (
                <g>
                  <text
                    x={points[points.length - 1].x}
                    y={points[points.length - 1].y - 10}
                    textAnchor="middle"
                    className="text-xs font-semibold"
                    fill={color}
                    fontSize="11"
                  >
                    {points[points.length - 1].value.toFixed(1)}
                    {unit}
                  </text>
                </g>
              )}
            </svg>
          )}
        </div>
      </div>
    );
  },
  (prevProps, nextProps) => {
    // Custom comparison for MetricChart
    return (
      prevProps.title === nextProps.title &&
      prevProps.dataKey === nextProps.dataKey &&
      prevProps.color === nextProps.color &&
      prevProps.unit === nextProps.unit &&
      prevProps.data.length === nextProps.data.length &&
      prevProps.data.every(
        (item, index) =>
          item[prevProps.dataKey] ===
          nextProps.data[index]?.[nextProps.dataKey],
      )
    );
  },
);

const WorkerCard: React.FC<{
  client: Client;
  metrics: WorkerMetricsData[];
  onSelect?: () => void;
  isSelected?: boolean;
}> = memo(
  ({ client, metrics, onSelect, isSelected = false }) => {
    const isHealthy = client.is_healthy !== false;
    const currentLoad = client.current_load || 0;
    const maxTasks = client.max_concurrent_tasks || 1;
    const loadPercentage = Math.min((currentLoad / maxTasks) * 100, 100);

    const getStatusColor = (status: string) => {
      switch (status) {
        case "idle":
          return "bg-success-100 text-success-800";
        case "busy":
          return "bg-warning-100 text-warning-800";
        case "overloaded":
          return "bg-error-100 text-error-800";
        case "maintenance":
          return "bg-secondary-100 text-secondary-800";
        case "error":
          return "bg-error-100 text-error-800";
        default:
          return "bg-secondary-100 text-secondary-800";
      }
    };

    const getLoadColor = () => {
      if (loadPercentage < 50) return "bg-success-500";
      if (loadPercentage < 80) return "bg-warning-500";
      return "bg-error-500";
    };

    return (
      <div
        className={`bg-white rounded-xl shadow-sm p-6 space-y-4 card-hover hover-glow transition-all duration-300 ${isSelected ? "ring-2 ring-primary-500 bg-primary-50" : ""}`}
      >
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <div className="p-2 bg-primary-50 rounded-lg">
              {client.client_type === "worker_api" ? (
                <CpuIcon size="lg" className="text-primary-600" />
              ) : (
                <MemoryIcon size="lg" className="text-primary-600" />
              )}
            </div>
            <div>
              <h3 className="text-lg font-semibold text-secondary-900">
                {client.client_name || client.client_id}
              </h3>
              <p className="text-sm text-secondary-600">
                {client.client_type === "worker_api" ? "API Worker" : "Worker"}
              </p>
            </div>
          </div>
          <div className="flex items-center space-x-3">
            <span
              className={`inline-flex items-center px-3 py-1 rounded-full text-xs font-medium transition-all duration-300 ${getStatusColor(client.worker_status || "unknown")}`}
            >
              {client.worker_status || "Unknown"}
            </span>
            <div className="flex items-center">
              {isHealthy ? (
                <AnimatedHeartIcon size="md" className="text-success-500" />
              ) : (
                <ErrorIcon size="md" className="text-error-500" />
              )}
            </div>
          </div>
        </div>

        {/* Load indicator */}
        <div>
          <div className="flex justify-between text-sm text-secondary-600 mb-1">
            <span>Навантаження</span>
            <span>
              {currentLoad}/{maxTasks} задач
            </span>
          </div>
          <div className="w-full bg-secondary-200 rounded-full h-2 overflow-hidden">
            <div
              className={`h-2 rounded-full transition-all duration-700 ease-out ${getLoadColor()}`}
              style={{ width: `${loadPercentage}%` }}
            />
          </div>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-2 gap-4">
          <div className="bg-secondary-50 rounded-lg p-4 text-center card-hover hover-icon-scale">
            <div className="flex items-center justify-center mb-2">
              <ProcessingIcon size="md" className="text-secondary-600 mr-2" />
            </div>
            <p className="text-2xl font-bold text-secondary-900">
              {client.stats?.total_tasks || 0}
            </p>
            <p className="text-sm text-secondary-600">Всього задач</p>
          </div>
          <div className="bg-success-50 rounded-lg p-4 text-center card-hover hover-icon-scale">
            <div className="flex items-center justify-center mb-2">
              <CheckIcon size="md" className="text-success-600 mr-2" />
            </div>
            <p className="text-2xl font-bold text-success-600">
              {client.stats?.successful_tasks || 0}
            </p>
            <p className="text-sm text-secondary-600">Успішно</p>
          </div>
          <div className="bg-error-50 rounded-lg p-4 text-center card-hover hover-icon-scale">
            <div className="flex items-center justify-center mb-2">
              <AlertIcon size="md" className="text-error-600 mr-2" />
            </div>
            <p className="text-2xl font-bold text-error-600">
              {client.stats?.failed_tasks || 0}
            </p>
            <p className="text-sm text-secondary-600">Помилки</p>
          </div>
          <div className="bg-primary-50 rounded-lg p-4 text-center card-hover hover-icon-scale">
            <div className="flex items-center justify-center mb-2">
              <SpeedIcon size="md" className="text-primary-600 mr-2" />
            </div>
            <p className="text-2xl font-bold text-primary-600">
              {client.stats?.average_processing_time
                ? `${client.stats.average_processing_time.toFixed(2)}s`
                : "N/A"}
            </p>
            <p className="text-sm text-secondary-600">Сер. час</p>
          </div>
        </div>

        {/* Mini charts */}
        {useMemo(() => {
          if (metrics.length === 0) return null;

          const recentMetrics = metrics.slice(-10);
          const maxActiveTasks = Math.max(
            ...metrics.map((m) => m.active_tasks),
            1,
          );
          const maxResponseTime = Math.max(
            ...metrics.map((m) => m.response_time),
            1,
          );

          const activeTasksPoints = recentMetrics
            .map((point, index) => {
              const x = (index * 180) / Math.max(recentMetrics.length - 1, 1);
              const y = 50 - (point.active_tasks * 40) / maxActiveTasks;
              return `${x + 10},${y + 5}`;
            })
            .join(" ");

          const responseTimePoints = recentMetrics
            .map((point, index) => {
              const x = (index * 180) / Math.max(recentMetrics.length - 1, 1);
              const y = 50 - (point.response_time * 40) / maxResponseTime;
              return `${x + 10},${y + 5}`;
            })
            .join(" ");

          return (
            <div
              className="grid grid-cols-2 gap-4"
              key={`mini-charts-${client.client_id}`}
            >
              <div>
                <p className="text-sm font-medium text-secondary-700 mb-2">
                  Активні задачі
                </p>
                <div className="h-16 relative">
                  <svg className="w-full h-full" viewBox="0 0 200 60">
                    <polyline
                      fill="none"
                      stroke="#3b82f6"
                      strokeWidth="2"
                      points={activeTasksPoints}
                      className="mini-chart-line"
                    />
                  </svg>
                </div>
              </div>
              <div>
                <p className="text-sm font-medium text-secondary-700 mb-2">
                  Час відповіді
                </p>
                <div className="h-16 relative">
                  <svg className="w-full h-full" viewBox="0 0 200 60">
                    <polyline
                      fill="none"
                      stroke="#10b981"
                      strokeWidth="2"
                      points={responseTimePoints}
                      className="mini-chart-line"
                      style={{ animationDelay: "0.5s" }}
                    />
                  </svg>
                </div>
              </div>
            </div>
          );
        }, [metrics, client.client_id])}

        {/* Select button */}
        {onSelect && (
          <div className="pt-4 border-t border-secondary-200 animate-slide-up">
            <button
              onClick={onSelect}
              className={`w-full px-4 py-2 rounded-lg font-medium transition-all duration-300 transform hover:scale-105 ${
                isSelected
                  ? "bg-primary-500 text-white shadow-lg animate-pulse-soft"
                  : "bg-secondary-100 text-secondary-700 hover:bg-primary-100 hover:text-primary-700 hover:shadow-md"
              }`}
            >
              {isSelected ? (
                <span className="flex items-center justify-center space-x-2">
                  <svg
                    className="w-4 h-4"
                    fill="currentColor"
                    viewBox="0 0 20 20"
                  >
                    <path
                      fillRule="evenodd"
                      d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                      clipRule="evenodd"
                    />
                  </svg>
                  <span>Обрано для аналізу</span>
                </span>
              ) : (
                "Обрати для аналізу"
              )}
            </button>
          </div>
        )}
      </div>
    );
  },
  (prevProps, nextProps) => {
    // Custom comparison for better performance
    return (
      prevProps.client.client_id === nextProps.client.client_id &&
      prevProps.client.connection_status ===
        nextProps.client.connection_status &&
      prevProps.client.worker_status === nextProps.client.worker_status &&
      prevProps.client.active_tasks_count ===
        nextProps.client.active_tasks_count &&
      prevProps.metrics.length === nextProps.metrics.length &&
      prevProps.isSelected === nextProps.isSelected &&
      JSON.stringify(prevProps.client.stats) ===
        JSON.stringify(nextProps.client.stats)
    );
  },
);

const WorkerMetrics: React.FC<WorkerMetricsProps> = ({ clients }) => {
  const { t } = useI18n();
  const [selectedWorker, setSelectedWorker] = useState<string | null>(null);
  const [metricsData, setMetricsData] = useState<
    Record<string, WorkerMetricsData[]>
  >({});
  const [timeRange, setTimeRange] = useState<"1h" | "6h" | "24h" | "7d">("1h");
  const [showDetailedMetrics, setShowDetailedMetrics] = useState(false);
  const [showSystemMonitor, setShowSystemMonitor] = useState(false);
  const [showClientSelection, setShowClientSelection] = useState(false);

  // Memoize filtered workers to prevent unnecessary re-renders
  const workers = useMemo(
    () =>
      clients.filter(
        (client) =>
          client.client_type === "worker" ||
          client.client_type === "worker_api",
      ),
    [clients],
  );

  // Розширюємо для всіх типів клієнтів (воркери, API-воркери, боти, стрім-хаби)
  const allClients = useMemo(() => clients, [clients]);

  const { apiWorkers, regularWorkers, bots, streamHubs } = useMemo(
    () => ({
      apiWorkers: workers.filter(
        (worker) => worker.client_type === "worker_api",
      ),
      regularWorkers: workers.filter(
        (worker) => worker.client_type === "worker",
      ),
      bots: clients.filter((client) => client.client_type === "bot"),
      streamHubs: clients.filter(
        (client) => client.client_type === "stream_hub",
      ),
    }),
    [workers, clients],
  );

  // Memoize worker selection handler
  const handleWorkerSelect = useCallback(
    (workerId: string) => {
      const isNewSelection = selectedWorker !== workerId;

      if (selectedWorker === workerId) {
        // Скрываем секции с анимацией
        setShowDetailedMetrics(false);
        setShowSystemMonitor(false);
        setShowClientSelection(false);

        setTimeout(() => {
          setSelectedWorker(null);
        }, 300);
      } else {
        setSelectedWorker(workerId);

        // Показываем секции с задержкой для плавности
        setTimeout(() => setShowDetailedMetrics(true), 100);
        setTimeout(() => setShowSystemMonitor(true), 300);
        setTimeout(() => setShowClientSelection(true), 500);
      }
    },
    [selectedWorker],
  );

  // Memoize time range change handler
  const handleTimeRangeChange = useCallback(
    (e: React.ChangeEvent<HTMLSelectElement>) => {
      setTimeRange(e.target.value as any);
    },
    [],
  );

  // Отримуємо реальні метрики з API
  const fetchMetricsForClient = useCallback(
    async (clientId: string): Promise<WorkerMetricsData[]> => {
      try {
        const metrics = await fetchClientMetrics(clientId);
        if (metrics.length === 0) {
          // Якщо API не повертає дані, логуємо як debug замість warning
          console.debug(`📊 No metrics data available for client ${clientId} - це нормально для деяких типів клієнтів`);
          return [];
        }
        return metrics;
      } catch (error) {
        console.error(`Failed to fetch metrics for client ${clientId}:`, error);
        return [];
      }
    },
    [],
  );

  // Ініціалізуємо стан анімацій при зміні selectedWorker
  useEffect(() => {
    if (selectedWorker) {
      setShowDetailedMetrics(false);
      setShowSystemMonitor(false);
      setShowClientSelection(false);

      // Показуємо секції поступово
      const timeouts = [
        setTimeout(() => setShowDetailedMetrics(true), 100),
        setTimeout(() => setShowSystemMonitor(true), 300),
        setTimeout(() => setShowClientSelection(true), 500),
      ];

      return () => timeouts.forEach(clearTimeout);
    } else {
      setShowDetailedMetrics(false);
      setShowSystemMonitor(false);
      setShowClientSelection(false);
    }
  }, [selectedWorker]);

  // Оновлюємо метрики для всіх клієнтів
  useEffect(() => {
    const updateMetrics = async () => {
      const newMetricsData: Record<string, WorkerMetricsData[]> = {};

      // Паралельно отримуємо метрики для всіх клієнтів
      const metricsPromises = allClients.map(async (client) => {
        const metrics = await fetchMetricsForClient(client.client_id);
        return { clientId: client.client_id, metrics };
      });

      try {
        const results = await Promise.all(metricsPromises);
        results.forEach(({ clientId, metrics }) => {
          newMetricsData[clientId] = metrics;
        });

        setMetricsData(newMetricsData);
      } catch (error) {
        console.error("Failed to fetch metrics for clients:", error);
        // У випадку помилки залишаємо поточні дані
      }
    };

    if (allClients.length > 0) {
      updateMetrics();

      // Оновлюємо метрики кожні 30 секунд
      const interval = setInterval(updateMetrics, 30000);
      return () => clearInterval(interval);
    }
  }, [allClients, timeRange, fetchMetricsForClient]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-secondary-900">
            {t("metrics.title")}
          </h1>
          <p className="text-secondary-600">{t("metrics.subtitle")}</p>
        </div>
        <div className="flex items-center space-x-4">
          <select
            value={timeRange}
            onChange={handleTimeRangeChange}
            className="px-3 py-2 border border-secondary-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition-all duration-300 hover:shadow-md hover:border-primary-300"
          >
            <option value="1h">{t("metrics.lastHour")}</option>
            <option value="6h">{t("metrics.last6Hours")}</option>
            <option value="24h">{t("metrics.last24Hours")}</option>
            <option value="7d">{t("metrics.lastWeek")}</option>
          </select>
        </div>
      </div>

      {/* Summary stats */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <div className="bg-white rounded-xl shadow-sm p-6 card-hover">
          <div className="flex items-center">
            <div className="p-3 rounded-lg bg-primary-100 text-primary-600">
              <CpuIcon size="lg" />
            </div>
            <div className="ml-4">
              <p className="text-sm font-medium text-secondary-600">
                {t("metrics.totalWorkers")}
              </p>
              <p className="text-2xl font-bold text-secondary-900">
                {workers.length}
              </p>
            </div>
          </div>
        </div>

        <div className="bg-white rounded-xl shadow-sm p-6 card-hover">
          <div className="flex items-center">
            <div className="p-3 rounded-lg bg-blue-100 text-blue-600">
              <svg className="w-6 h-6" fill="currentColor" viewBox="0 0 20 20">
                <path
                  fillRule="evenodd"
                  d="M6 6V5a3 3 0 013-3h2a3 3 0 013 3v1h2a2 2 0 012 2v3.57A22.952 22.952 0 0110 13a22.95 22.95 0 01-8-1.43V8a2 2 0 012-2h2zm2-1a1 1 0 011-1h2a1 1 0 011 1v1H8V5zm1 5a1 1 0 011-1h.01a1 1 0 110 2H10a1 1 0 01-1-1z"
                  clipRule="evenodd"
                />
                <path d="M2 13.692V16a2 2 0 002 2h12a2 2 0 002-2v-2.308A24.974 24.974 0 0110 15c-2.796 0-5.487-.46-8-1.308z" />
              </svg>
            </div>
            <div className="ml-4">
              <p className="text-sm font-medium text-secondary-600">
                {t("metrics.workers")}
              </p>
              <p className="text-2xl font-bold text-secondary-900">
                {regularWorkers.length}
              </p>
            </div>
          </div>
        </div>

        <div className="bg-white rounded-xl shadow-sm p-6 card-hover">
          <div className="flex items-center">
            <div className="p-3 rounded-lg bg-warning-100 text-warning-600">
              <AlertIcon size="lg" />
            </div>
            <div className="ml-4">
              <p className="text-sm font-medium text-secondary-600">
                {t("clients.workerApi")}
              </p>
              <p className="text-2xl font-bold text-secondary-900">
                {apiWorkers.length}
              </p>
            </div>
          </div>
        </div>

        <div className="bg-white rounded-xl shadow-sm p-6 card-hover">
          <div className="flex items-center">
            <div className="p-3 rounded-lg bg-purple-100 text-purple-600">
              <svg className="w-6 h-6" fill="currentColor" viewBox="0 0 20 20">
                <path
                  fillRule="evenodd"
                  d="M3 4a1 1 0 011-1h12a1 1 0 011 1v2a1 1 0 01-1 1H4a1 1 0 01-1-1V4zm0 4a1 1 0 011-1h12a1 1 0 011 1v2a1 1 0 01-1 1H4a1 1 0 01-1-1V8zm0 4a1 1 0 011-1h12a1 1 0 011 1v2a1 1 0 01-1 1H4a1 1 0 01-1-1v-2z"
                  clipRule="evenodd"
                />
              </svg>
            </div>
            <div className="ml-4">
              <p className="text-sm font-medium text-secondary-600">
                {t("metrics.activeBotServers")}
              </p>
              <p className="text-2xl font-bold text-secondary-900">
                {
                  bots.filter((bot) => bot.connection_status === "connected")
                    .length
                }
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Worker cards */}
      <div>
        <h2 className="text-xl font-semibold text-secondary-900 mb-4 animate-slide-down">
          <span className="bg-gradient-to-r from-blue-600 to-blue-800 bg-clip-text text-transparent">
            ⚙️ {t("clients.standardWorkers")}
          </span>
        </h2>
        {regularWorkers.length > 0 ? (
          <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-6">
            {regularWorkers.map((worker, index) => (
              <div
                key={`regular-${worker.client_id}`}
                className="card-entrance"
                style={{ animationDelay: `${index * 0.1}s` }}
              >
                <WorkerCard
                  client={worker}
                  metrics={metricsData[worker.client_id] || []}
                  onSelect={() => handleWorkerSelect(worker.client_id)}
                  isSelected={selectedWorker === worker.client_id}
                />
              </div>
            ))}
          </div>
        ) : (
          <div className="bg-white rounded-xl shadow-sm p-8 text-center">
            <p className="text-secondary-500">
              {t("metrics.noStandardWorkers")}
            </p>
          </div>
        )}
      </div>

      {/* API Worker cards */}
      <div>
        <h2 className="text-xl font-semibold text-secondary-900 mb-4 animate-slide-down">
          <span className="bg-gradient-to-r from-emerald-600 to-emerald-800 bg-clip-text text-transparent">
            🔧 {t("clients.apiWorkers")}
          </span>
        </h2>
        {apiWorkers.length > 0 ? (
          <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-6">
            {apiWorkers.map((worker, index) => (
              <div
                key={`api-${worker.client_id}`}
                className="card-entrance"
                style={{ animationDelay: `${index * 0.1}s` }}
              >
                <WorkerCard
                  client={worker}
                  metrics={metricsData[worker.client_id] || []}
                  onSelect={() => handleWorkerSelect(worker.client_id)}
                  isSelected={selectedWorker === worker.client_id}
                />
              </div>
            ))}
          </div>
        ) : (
          <div className="bg-white rounded-xl shadow-sm p-8 text-center">
            <p className="text-secondary-500">{t("metrics.noApiWorkers")}</p>
          </div>
        )}
      </div>

      {/* Detailed charts for selected client */}
      {selectedWorker && metricsData[selectedWorker] && (
        <div
          className={`metrics-section-enter ${showDetailedMetrics ? "opacity-100" : "opacity-0"}`}
        >
          <h2 className="text-xl font-semibold text-secondary-900 mb-6 flex items-center">
            <span className="bg-gradient-to-r from-primary-600 to-primary-800 bg-clip-text text-transparent">
              📊 Детальні метрики:
            </span>
            <span className="ml-2 px-3 py-1 bg-primary-100 text-primary-800 rounded-full text-sm font-medium">
              {allClients.find((c) => c.client_id === selectedWorker)
                ?.client_name || selectedWorker}
            </span>
          </h2>
          <div
            className={`metrics-charts-enter ${showDetailedMetrics ? "opacity-100" : "opacity-0"}`}
          >
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-8">
              <div className="metrics-chart-item">
                <MetricChart
                  key={`cpu-${selectedWorker}-${timeRange}`}
                  title="Використання CPU"
                  data={metricsData[selectedWorker]}
                  dataKey="cpu_usage"
                  color="#3b82f6"
                  unit="%"
                />
              </div>
              <div className="metrics-chart-item">
                <MetricChart
                  key={`memory-${selectedWorker}-${timeRange}`}
                  title="Використання пам'яті"
                  data={metricsData[selectedWorker]}
                  dataKey="memory_usage"
                  color="#10b981"
                  unit="%"
                />
              </div>
              <div className="metrics-chart-item">
                <MetricChart
                  key={`tasks-${selectedWorker}-${timeRange}`}
                  title="Активні задачі"
                  data={metricsData[selectedWorker]}
                  dataKey="active_tasks"
                  color="#f59e0b"
                />
              </div>
              <div className="metrics-chart-item">
                <MetricChart
                  key={`response-${selectedWorker}-${timeRange}`}
                  title="Час відповіді"
                  data={metricsData[selectedWorker]}
                  dataKey="response_time"
                  color="#ef4444"
                  unit="s"
                />
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Bots section */}
      {bots.length > 0 && (
        <div>
          <h2 className="text-xl font-semibold text-secondary-900 mb-4 animate-slide-down">
            <span className="bg-gradient-to-r from-orange-600 to-orange-800 bg-clip-text text-transparent">
              🤖 Боти
            </span>
          </h2>
          <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-6">
            {bots.map((bot, index) => (
              <div
                key={`bot-${bot.client_id}`}
                className="card-entrance"
                style={{ animationDelay: `${index * 0.1}s` }}
              >
                <WorkerCard
                  client={bot}
                  metrics={metricsData[bot.client_id] || []}
                  onSelect={() => handleWorkerSelect(bot.client_id)}
                  isSelected={selectedWorker === bot.client_id}
                />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Stream Hubs section */}
      {streamHubs.length > 0 && (
        <div>
          <h2 className="text-xl font-semibold text-secondary-900 mb-4 animate-slide-down">
            <span className="bg-gradient-to-r from-cyan-600 to-cyan-800 bg-clip-text text-transparent">
              🌊 Стрім-хаби
            </span>
          </h2>
          <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-6">
            {streamHubs.map((hub, index) => (
              <div
                key={`hub-${hub.client_id}`}
                className="card-entrance"
                style={{ animationDelay: `${index * 0.1}s` }}
              >
                <WorkerCard
                  client={hub}
                  metrics={metricsData[hub.client_id] || []}
                  onSelect={() => handleWorkerSelect(hub.client_id)}
                  isSelected={selectedWorker === hub.client_id}
                />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* System Resource Monitor */}
      {selectedWorker && showSystemMonitor && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="metrics-system-monitor">
            <SystemResourceMonitor
              selectedClient={allClients.find(
                (c) => c.client_id === selectedWorker,
              )}
            />
          </div>
          {/* Placeholder for additional system info */}
          <div className="metrics-system-info">
            <div className="bg-white rounded-xl shadow-sm border border-secondary-100 p-6 hover:shadow-lg transition-all duration-300">
              <h3 className="text-lg font-semibold text-secondary-900 mb-4 flex items-center">
                <span className="bg-gradient-to-r from-emerald-600 to-emerald-800 bg-clip-text text-transparent">
                  📈 Додаткова інформація
                </span>
              </h3>
              <div className="space-y-4">
                <div className="text-sm text-secondary-600 space-y-3">
                  <div className="flex items-center justify-between p-3 bg-secondary-50 rounded-lg">
                    <span>Тип клієнта:</span>
                    <span className="font-medium text-secondary-900 px-2 py-1 bg-white rounded shadow-sm">
                      {
                        allClients.find((c) => c.client_id === selectedWorker)
                          ?.client_type
                      }
                    </span>
                  </div>
                  <div className="flex items-center justify-between p-3 bg-secondary-50 rounded-lg">
                    <span>Статус з'єднання:</span>
                    <span
                      className={`font-medium px-2 py-1 rounded shadow-sm ${
                        allClients.find((c) => c.client_id === selectedWorker)
                          ?.connection_status === "connected"
                          ? "bg-success-100 text-success-800"
                          : "bg-error-100 text-error-800"
                      }`}
                    >
                      {
                        allClients.find((c) => c.client_id === selectedWorker)
                          ?.connection_status
                      }
                    </span>
                  </div>
                  <div className="flex items-center justify-between p-3 bg-secondary-50 rounded-lg">
                    <span>Активні завдання:</span>
                    <span className="font-medium text-secondary-900 px-2 py-1 bg-white rounded shadow-sm">
                      {allClients.find((c) => c.client_id === selectedWorker)
                        ?.active_tasks_count || 0}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Client selection */}
      {allClients.length > 0 && showClientSelection && (
        <div className="metrics-client-selection">
          <div className="bg-white rounded-xl shadow-sm p-6 hover:shadow-lg transition-all duration-300">
            <h3 className="text-lg font-semibold text-secondary-900 mb-6 flex items-center">
              <span className="bg-gradient-to-r from-purple-600 to-purple-800 bg-clip-text text-transparent">
                🎯 Вибрати клієнт для детального аналізу
              </span>
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {allClients.map((client, index) => (
                <button
                  key={`select-${client.client_id}`}
                  onClick={() => handleWorkerSelect(client.client_id)}
                  className={`client-select-button p-4 rounded-lg border-2 text-left ${
                    selectedWorker === client.client_id
                      ? "border-primary-500 bg-primary-50 selected"
                      : "border-secondary-200 hover:border-primary-300 hover:bg-primary-50"
                  }`}
                  style={{
                    animationDelay: `${index * 0.05}s`,
                    animation: "cascadeIn 0.5s ease-out forwards",
                  }}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex-1">
                      <p className="font-medium text-secondary-900 mb-1">
                        {client.client_name || client.client_id}
                      </p>
                      <p className="text-sm text-secondary-600 mb-2">
                        {client.client_type === "worker_api"
                          ? "🔧 API Worker"
                          : client.client_type === "worker"
                            ? "⚙️ Worker"
                            : client.client_type === "bot"
                              ? "🤖 Bot"
                              : client.client_type === "stream_hub"
                                ? "🌊 Stream Hub"
                                : client.client_type}
                      </p>
                      <div className="flex items-center space-x-2">
                        <div
                          className={`w-2 h-2 rounded-full ${
                            client.connection_status === "connected"
                              ? "bg-success-500"
                              : "bg-error-500"
                          }`}
                        />
                        <span
                          className={`text-xs font-medium ${
                            client.connection_status === "connected"
                              ? "text-success-700"
                              : "text-error-700"
                          }`}
                        >
                          {client.connection_status === "connected"
                            ? "Підключено"
                            : "Відключено"}
                        </span>
                      </div>
                    </div>
                    {selectedWorker === client.client_id && (
                      <div className="ml-3 text-primary-500">
                        <svg
                          className="w-5 h-5"
                          fill="currentColor"
                          viewBox="0 0 20 20"
                        >
                          <path
                            fillRule="evenodd"
                            d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                            clipRule="evenodd"
                          />
                        </svg>
                      </div>
                    )}
                  </div>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export { WorkerMetrics };
