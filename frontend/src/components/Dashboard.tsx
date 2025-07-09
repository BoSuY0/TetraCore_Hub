import React, {
  useState,
  useEffect,
  useMemo,
  useCallback,
  useRef,
} from "react";
import { useStatus } from "../contexts/StatusContext";
import { useI18n } from "../contexts/I18nContext";
import { useAuth } from "../contexts/AuthContext";
import { buildUrl } from "../config";
import {
  UsersIcon,
  TasksIcon,
  ClockIcon,
  CpuIcon,
  ArrowUpIcon,
  ArrowDownIcon,
  ErrorIcon,
  CheckIcon,
  AlertIcon,
  ProcessingIcon,
  MemoryIcon,
  SpeedIcon,
  AnimatedHeartIcon,
  WarningIcon,
  NetworkIcon,
} from "./Icons";
import "../animations.css";
import ConsoleLogs from "./ConsoleLogs";

// Інтерфейси для типізації
interface SystemMetrics {
  cpu_usage: number;
  memory_usage: number;
  disk_usage: number;
  network_in: number;
  network_out: number;
  uptime: number;
  active_connections: number;
  tasks_per_second: number;
  error_rate: number;
}

interface ClientStats {
  total: number;
  connected: number;
  workers: number;
  apiWorkers: number;
  bots: number;
  streamHubs: number;
}

interface TaskStats {
  total: number;
  completed: number;
  failed: number;
  pending: number;
  processing: number;
}

// Компонент героїчної метрики
interface HeroMetricProps {
  title: string;
  value: string | number;
  subtitle: string;
  icon: React.ReactNode;
  gradient: string;
  trend?: {
    value: string;
    isPositive: boolean;
  };
  onClick?: () => void;
}

const HeroMetric: React.FC<HeroMetricProps> = ({
  title,
  value,
  subtitle,
  icon,
  gradient,
  trend,
  onClick,
}) => {
  return (
    <div
      className={`relative overflow-hidden rounded-2xl p-8 text-white cursor-pointer transform transition-all duration-300 hover:scale-105 hover:shadow-2xl ${gradient} ${onClick ? "hover:brightness-110" : ""}`}
      onClick={onClick}
    >
      <div className="relative z-10">
        <div className="flex items-center justify-between mb-4">
          <div className="p-3 bg-white/20 rounded-xl backdrop-blur-sm">
            {icon}
          </div>
          {trend && (
            <div
              className={`flex items-center space-x-1 px-3 py-1 rounded-full text-sm font-medium ${
                trend.isPositive
                  ? "bg-green-500/20 text-green-100"
                  : "bg-red-500/20 text-red-100"
              }`}
            >
              {trend.isPositive ? (
                <ArrowUpIcon size="sm" />
              ) : (
                <ArrowDownIcon size="sm" />
              )}
              <span>{trend.value}</span>
            </div>
          )}
        </div>
        <div className="space-y-2">
          <h3 className="text-lg font-medium opacity-90">{title}</h3>
          <div className="text-4xl font-bold">{value}</div>
          <p className="text-sm opacity-75">{subtitle}</p>
        </div>
      </div>

      {/* Декоративні елементи */}
      <div className="absolute top-0 right-0 w-32 h-32 bg-white/10 rounded-full -translate-y-16 translate-x-16"></div>
      <div className="absolute bottom-0 left-0 w-24 h-24 bg-white/5 rounded-full translate-y-12 -translate-x-12"></div>
    </div>
  );
};

// Компонент статистичної картки
interface StatCardProps {
  title: string;
  value: string | number;
  change?: string;
  changeType?: "increase" | "decrease" | "neutral";
  icon: React.ReactNode;
  color: string;
  description?: string;
}

const StatCard: React.FC<StatCardProps> = ({
  title,
  value,
  change,
  changeType = "neutral",
  icon,
  color,
  description,
}) => {
  const changeColors = {
    increase: "text-emerald-600 bg-emerald-50",
    decrease: "text-red-600 bg-red-50",
    neutral: "text-slate-600 bg-slate-50",
  };

  return (
    <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 hover:shadow-lg transition-all duration-300 hover:border-slate-300 group">
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <div className="flex items-center space-x-3 mb-3">
            <div
              className={`p-2 rounded-lg ${color} group-hover:scale-110 transition-transform duration-300`}
            >
              {icon}
            </div>
            <h3 className="text-sm font-semibold text-slate-700 group-hover:text-slate-900 transition-colors">
              {title}
            </h3>
          </div>

          <div className="space-y-2">
            <div className="text-3xl font-bold text-slate-900">{value}</div>
            {description && (
              <p className="text-sm text-slate-500">{description}</p>
            )}
            {change && (
              <div
                className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-medium ${changeColors[changeType]}`}
              >
                {changeType === "increase" && (
                  <ArrowUpIcon size="sm" className="mr-1" />
                )}
                {changeType === "decrease" && (
                  <ArrowDownIcon size="sm" className="mr-1" />
                )}
                {change}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

// Компонент прогрес-бару з покращеним дизайном
interface AdvancedProgressProps {
  label: string;
  value: number;
  max: number;
  color: string;
  showPercentage?: boolean;
  size?: "sm" | "md" | "lg";
}

const AdvancedProgress: React.FC<AdvancedProgressProps> = ({
  label,
  value,
  max,
  color,
  showPercentage = true,
  size = "md",
}) => {
  // Перевіряємо чи value є валідним числом
  const safeValue = typeof value === "number" && !isNaN(value) ? value : 0;
  const safeMax = typeof max === "number" && max > 0 ? max : 1;
  const percentage = Math.min((safeValue / safeMax) * 100, 100);

  const sizeClasses = {
    sm: "h-2",
    md: "h-3",
    lg: "h-4",
  };

  return (
    <div className="space-y-2">
      <div className="flex justify-between items-center">
        <span className="text-sm font-medium text-slate-700">{label}</span>
        <div className="flex items-center space-x-2">
          {showPercentage && (
            <span className="text-sm font-semibold text-slate-900">
              {percentage.toFixed(1)}%
            </span>
          )}
          <span className="text-xs text-slate-500">
            {safeValue.toFixed(1)}/{safeMax}
          </span>
        </div>
      </div>
      <div className="w-full bg-slate-200 rounded-full overflow-hidden">
        <div
          className={`${sizeClasses[size]} rounded-full transition-all duration-500 ease-out ${color}`}
          style={{ width: `${percentage}%` }}
        />
      </div>
    </div>
  );
};

// Компонент системного здоров'я
const SystemHealthWidget: React.FC = () => {
  const { t } = useI18n();
  const { auth } = useAuth();
  const [metrics, setMetrics] = useState<SystemMetrics | null>(null);

  useEffect(() => {
    const fetchMetrics = async () => {
      // Only fetch if user is authenticated
      if (!auth.isAuthenticated) {
        return;
      }
      
      try {
        const sessionId = localStorage.getItem('sessionId');
        const headers: HeadersInit = {
          'Content-Type': 'application/json',
        };
        
        if (sessionId) {
          headers.Authorization = `Bearer ${sessionId}`;
        }
        
        const response = await fetch(
          buildUrl("/dashboard/api/real-time-metrics"),
          {
            headers,
          }
        );
        
        if (response.ok) {
          const data = await response.json();
          setMetrics(data.performance_data);
        } else if (response.status === 401) {
          // Redirect to login on authentication failure
          window.location.href = '/';
        }
      } catch (error) {
        console.error("Failed to fetch metrics:", error);
      }
    };

    fetchMetrics();
    const interval = setInterval(fetchMetrics, 5000);
    return () => clearInterval(interval);
  }, [auth.isAuthenticated]);

  const getHealthStatus = (cpu: number, memory: number) => {
    const safeCpu = cpu || 0;
    const safeMemory = memory || 0;

    if (safeCpu > 80 || safeMemory > 85)
      return { status: "critical", color: "text-red-600", bg: "bg-red-50" };
    if (safeCpu > 60 || safeMemory > 70)
      return { status: "warning", color: "text-amber-600", bg: "bg-amber-50" };
    return {
      status: "healthy",
      color: "text-emerald-600",
      bg: "bg-emerald-50",
    };
  };

  if (!metrics) {
    return (
      <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
        <div className="animate-pulse space-y-4">
          <div className="h-4 bg-slate-200 rounded w-1/3"></div>
          <div className="space-y-2">
            <div className="h-3 bg-slate-200 rounded"></div>
            <div className="h-3 bg-slate-200 rounded w-2/3"></div>
          </div>
        </div>
      </div>
    );
  }

  const health = getHealthStatus(
    metrics.cpu_usage || 0,
    metrics.memory_usage || 0,
  );

  return (
    <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
      <div className="flex items-center justify-between mb-6">
        <h3 className="text-lg font-semibold text-slate-900">
          Системне здоров'я
        </h3>
        <div
          className={`flex items-center space-x-2 px-3 py-1 rounded-full ${health.bg}`}
        >
          <div
            className={`w-2 h-2 rounded-full ${health.color.replace("text-", "bg-")}`}
          ></div>
          <span className={`text-sm font-medium ${health.color}`}>
            {health.status === "healthy"
              ? "Здорова"
              : health.status === "warning"
                ? "Попередження"
                : "Критично"}
          </span>
        </div>
      </div>

      <div className="space-y-4">
        <AdvancedProgress
          label="Використання CPU"
          value={metrics.cpu_usage || 0}
          max={100}
          color="bg-gradient-to-r from-blue-500 to-blue-600"
        />
        <AdvancedProgress
          label="Використання пам'яті"
          value={metrics.memory_usage || 0}
          max={100}
          color="bg-gradient-to-r from-emerald-500 to-emerald-600"
        />
        <AdvancedProgress
          label="Мережевий трафік"
          value={(metrics.network_in || 0) + (metrics.network_out || 0)}
          max={1000}
          color="bg-gradient-to-r from-purple-500 to-purple-600"
        />
      </div>
    </div>
  );
};

// Компонент активності в реальному часі
const RealTimeActivity: React.FC = () => {
  const { t } = useI18n();
  const { state } = useStatus();
  const [activities, setActivities] = useState<any[]>([]);
  const [lastClientCount, setLastClientCount] = useState(0);
  const [lastConnectionStatus, setLastConnectionStatus] = useState<string>("");
  const [lastUpdateTime, setLastUpdateTime] = useState<Date | null>(null);
  const activityIdCounterRef = useRef(0);

  // Генератор унікальних ID для активностей
  const generateUniqueId = useCallback(() => {
    const timestamp = Date.now();
    const counter = activityIdCounterRef.current++;
    const random = Math.random().toString(36).substr(2, 9);
    return `activity_${timestamp}_${counter}_${random}`;
  }, []);

  // Додаємо активність тільки при значущих змінах
  const addActivity = useCallback((activity: any) => {
    setActivities((prev) => [activity, ...prev.slice(0, 4)]);
  }, []);

  // Відстежуємо зміни статусу підключення
  useEffect(() => {
    if (
      state.connectionStatus &&
      state.connectionStatus !== lastConnectionStatus
    ) {
      const statusMessages = {
        connected: "Підключено до системи",
        disconnected: "Втрачено з'єднання",
        connecting: "Підключення до системи...",
        error: "Помилка підключення",
      };

      if (lastConnectionStatus !== "") {
        // Не показуємо перше підключення
        addActivity({
          id: generateUniqueId(),
          type: "connection_status",
          message: statusMessages[state.connectionStatus],
          timestamp: new Date(),
          severity:
            state.connectionStatus === "connected"
              ? "low"
              : state.connectionStatus === "error"
                ? "high"
                : "medium",
        });
      }

      setLastConnectionStatus(state.connectionStatus);
    }
  }, [state.connectionStatus, lastConnectionStatus, addActivity]);

  // Відстежуємо зміни кількості клієнтів
  useEffect(() => {
    if (state.clients) {
      const connectedCount = state.clients.filter(
        (c) => c.connection_status === "connected",
      ).length;

      if (connectedCount !== lastClientCount && lastClientCount > 0) {
        const change = connectedCount - lastClientCount;
        const message =
          change > 0
            ? `Підключився новий клієнт (всього: ${connectedCount})`
            : `Клієнт відключився (всього: ${connectedCount})`;

        addActivity({
          id: generateUniqueId(),
          type: "client_connected",
          message,
          timestamp: new Date(),
          severity: change > 0 ? "low" : "medium",
        });
      }

      setLastClientCount(connectedCount);
    }
  }, [state.clients?.length, lastClientCount, addActivity]);

  // Відстежуємо помилки
  useEffect(() => {
    if (state.error) {
      addActivity({
        id: generateUniqueId(),
        type: "error_occurred",
        message: `Помилка: ${state.error}`,
        timestamp: new Date(),
        severity: "high",
      });
    }
  }, [state.error, addActivity]);

  // Відстежуємо зміни здоров'я системи
  useEffect(() => {
    if (state.health?.status) {
      const healthMessages: Record<string, string> = {
        healthy: "Система працює нормально",
        degraded: "Погіршена продуктивність системи",
        unhealthy: "Критичні проблеми системи",
      };

      // Додаємо активність тільки при зміні статусу
      const currentTime = new Date();
      if (
        !lastUpdateTime ||
        currentTime.getTime() - lastUpdateTime.getTime() > 30000
      ) {
        // Раз на 30 секунд максимум
        addActivity({
          id: generateUniqueId(),
          type: "system_health",
          message:
            healthMessages[state.health.status] || "Оновлено статус системи",
          timestamp: currentTime,
          severity:
            state.health.status === "healthy"
              ? "low"
              : state.health.status === "degraded"
                ? "medium"
                : "high",
        });

        setLastUpdateTime(currentTime);
      }
    }
  }, [state.health?.status, lastUpdateTime, addActivity]);

  // Періодично додаємо інформацію про метрики (рідко)
  useEffect(() => {
    const interval = setInterval(() => {
      if (state.metrics?.system) {
        const { cpu_usage, memory_usage } = state.metrics.system;

        if (cpu_usage > 80 || memory_usage > 85) {
          addActivity({
            id: generateUniqueId(),
            type: "system_warning",
            message: `Високе навантаження: CPU ${Math.round(cpu_usage)}%, RAM ${Math.round(memory_usage)}%`,
            timestamp: new Date(),
            severity: "high",
          });
        } else if (Math.random() < 0.3) {
          // Рідко показуємо нормальні метрики
          addActivity({
            id: generateUniqueId(),
            type: "system_metrics",
            message: `Система стабільна: CPU ${Math.round(cpu_usage)}%, RAM ${Math.round(memory_usage)}%`,
            timestamp: new Date(),
            severity: "low",
          });
        }
      }
    }, 45000); // Кожні 45 секунд

    return () => clearInterval(interval);
  }, [state.metrics?.system, addActivity]);

  // Ініціалізація з початковими даними
  useEffect(() => {
    if (activities.length === 0 && state.connectionStatus === "connected") {
      addActivity({
        id: generateUniqueId(),
        type: "system_start",
        message: "Dashboard ініціалізовано",
        timestamp: new Date(),
        severity: "low",
      });
    }
  }, [activities.length, state.connectionStatus, addActivity]);

  const getActivityIcon = (type: string) => {
    switch (type) {
      case "client_connected":
        return <UsersIcon size="sm" className="text-emerald-600" />;
      case "task_completed":
        return <CheckIcon size="sm" className="text-blue-600" />;
      case "error_occurred":
        return <ErrorIcon size="sm" className="text-red-600" />;
      case "connection_status":
        return <NetworkIcon size="sm" className="text-purple-600" />;
      case "system_health":
        return <AnimatedHeartIcon size="sm" className="text-emerald-600" />;
      case "system_warning":
        return <WarningIcon size="sm" className="text-amber-600" />;
      case "system_metrics":
        return <CpuIcon size="sm" className="text-blue-600" />;
      case "system_start":
        return <CheckIcon size="sm" className="text-emerald-600" />;
      default:
        return <ProcessingIcon size="sm" className="text-slate-600" />;
    }
  };

  const getActivityColor = (severity: string) => {
    switch (severity) {
      case "high":
        return "border-l-red-500 bg-red-50";
      case "medium":
        return "border-l-amber-500 bg-amber-50";
      default:
        return "border-l-emerald-500 bg-emerald-50";
    }
  };

  return (
    <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
      <div className="flex items-center justify-between mb-6">
        <h3 className="text-lg font-semibold text-slate-900">
          Активність в реальному часі
        </h3>
        <div className="flex items-center space-x-2">
          <div className="w-2 h-2 bg-emerald-500 rounded-full animate-pulse"></div>
          <span className="text-sm text-slate-500">Live</span>
        </div>
      </div>

      <div className="space-y-3">
        {activities.length === 0 ? (
          <div className="text-center py-8">
            <div className="text-slate-400 mb-2">
              <ProcessingIcon size="lg" />
            </div>
            <p className="text-sm text-slate-500">Очікування активності...</p>
          </div>
        ) : (
          activities.map((activity, index) => (
            <div
              key={activity.id}
              className={`activity-item p-3 rounded-lg border-l-4 transition-all duration-300 ${getActivityColor(activity.severity)}`}
              style={{ animationDelay: `${index * 0.1}s` }}
            >
              <div className="flex items-center space-x-3">
                {getActivityIcon(activity.type)}
                <div className="flex-1">
                  <p className="text-sm font-medium text-slate-900">
                    {activity.message}
                  </p>
                  <p className="text-xs text-slate-500">
                    {activity.timestamp.toLocaleTimeString()}
                  </p>
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
};

// Компонент швидких дій
const QuickActions: React.FC = () => {
  const { t } = useI18n();

  const actions = [
    {
      id: "restart_system",
      title: "Перезапустити систему",
      description: "Безпечний перезапуск всіх сервісів",
      icon: <ProcessingIcon size="md" className="text-blue-600" />,
      color: "bg-blue-50 hover:bg-blue-100",
      action: () => console.log("Restart system"),
    },
    {
      id: "clear_cache",
      title: "Очистити кеш",
      description: "Видалити тимчасові файли",
      icon: <MemoryIcon size="md" className="text-emerald-600" />,
      color: "bg-emerald-50 hover:bg-emerald-100",
      action: () => console.log("Clear cache"),
    },
    {
      id: "export_logs",
      title: "Експорт логів",
      description: "Завантажити системні логи",
      icon: <TasksIcon size="md" className="text-amber-600" />,
      color: "bg-amber-50 hover:bg-amber-100",
      action: () => console.log("Export logs"),
    },
    {
      id: "settings",
      title: "Налаштування",
      description: "Конфігурація системи",
      icon: <CpuIcon size="md" className="text-purple-600" />,
      color: "bg-purple-50 hover:bg-purple-100",
      action: () => console.log("Settings"),
    },
  ];

  return (
    <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
      <h3 className="text-lg font-semibold text-slate-900 mb-6">Швидкі дії</h3>

      <div className="grid grid-cols-2 gap-3">
        {actions.map((action) => (
          <button
            key={action.id}
            onClick={action.action}
            className={`quick-action p-4 rounded-lg text-left transition-all duration-300 transform hover:scale-105 ${action.color}`}
          >
            <div className="flex items-center space-x-3 mb-2">
              {action.icon}
              <h4 className="text-sm font-semibold text-slate-900">
                {action.title}
              </h4>
            </div>
            <p className="text-xs text-slate-600">{action.description}</p>
          </button>
        ))}
      </div>
    </div>
  );
};

// Головний компонент Dashboard
export const Dashboard: React.FC = () => {
  const { t } = useI18n();
  const { state } = useStatus();
  const [timeRange, setTimeRange] = useState<"1h" | "6h" | "24h" | "7d">("24h");
  const [currentView, setCurrentView] = useState<string>("dashboard");

  // Обчислення статистики клієнтів
  const clientStats: ClientStats = useMemo(() => {
    const clients = state.clients || [];
    const connected = clients.filter(
      (c: any) => c.connection_status === "connected",
    );
    return {
      total: clients.length,
      connected: connected.length,
      workers: clients.filter((c: any) => c.client_type === "worker").length,
      apiWorkers: clients.filter((c: any) => c.client_type === "worker_api")
        .length,
      bots: clients.filter((c: any) => c.client_type === "bot").length,
      streamHubs: clients.filter((c: any) => c.client_type === "stream_hub")
        .length,
    };
  }, [state.clients]);

  // Реальні дані завдань з state
  const taskStats: TaskStats = useMemo(() => {
    const tasks = state.taskStats;
    return {
      total: tasks?.total_tasks || 0,
      completed: tasks?.completed_tasks || 0,
      failed: tasks?.failed_tasks || 0,
      pending: tasks?.pending_tasks || 0,
      processing: tasks?.processing_tasks || 0,
    };
  }, [state.taskStats]);

  // Реальні системні метрики
  const systemMetrics = useMemo(() => {
    const metrics = state.metrics?.system;
    return {
      cpu_usage: metrics?.cpu_usage || 0,
      memory_usage: metrics?.memory_usage || 0,
      disk_usage: metrics?.disk_usage || 0,
      uptime: metrics?.uptime || 0,
    };
  }, [state.metrics?.system]);

  // Реальні метрики Hub
  const hubMetrics = useMemo(() => {
    const hub = state.metrics?.hub;
    return {
      response_time: hub?.average_response_time || 0,
      throughput: hub?.tasks_per_second || 0,
      error_rate: hub?.error_rate || 0,
      total_connections: hub?.total_connections || 0,
      active_clients: hub?.active_clients || 0,
    };
  }, [state.metrics?.hub]);

  // Стан системи на основі реальних даних
  const systemHealth = useMemo(() => {
    const health = state.health;
    if (!health) return "Невідомо";

    if (health.status === "healthy") return "Здорова";
    if (health.status === "degraded") return "Погіршена";
    if (health.status === "unhealthy") return "Нездорова";
    return "Невідомо";
  }, [state.health]);

  // Відсоток онлайн клієнтів
  const connectionRate = useMemo(() => {
    if (clientStats.total === 0) return 100;
    return Math.round((clientStats.connected / clientStats.total) * 100);
  }, [clientStats.connected, clientStats.total]);

  const handleTimeRangeChange = useCallback(
    (range: "1h" | "6h" | "24h" | "7d") => {
      setTimeRange(range);
    },
    [],
  );

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-blue-50 to-indigo-50 p-6">
      <div className="max-w-7xl mx-auto space-y-8">
        {/* Заголовок */}
        <div className="text-center space-y-4">
          <h1 className="text-4xl font-bold bg-gradient-to-r from-blue-600 via-purple-600 to-indigo-600 bg-clip-text text-transparent">
            🏠 Панель керування TetraCore
          </h1>
          <p className="text-lg text-slate-600 max-w-2xl mx-auto">
            Моніторинг та управління системою в реальному часі
          </p>

          {/* Селектор часового діапазону */}
          <div className="flex justify-center">
            <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-1">
              {(["1h", "6h", "24h", "7d"] as const).map((range) => (
                <button
                  key={range}
                  onClick={() => handleTimeRangeChange(range)}
                  className={`px-4 py-2 rounded-lg text-sm font-medium transition-all duration-300 ${
                    timeRange === range
                      ? "bg-blue-500 text-white shadow-lg"
                      : "text-slate-600 hover:bg-slate-100"
                  }`}
                >
                  {range === "1h"
                    ? "Остання година"
                    : range === "6h"
                      ? "Останні 6 годин"
                      : range === "24h"
                        ? "Останні 24 години"
                        : "Останній тиждень"}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Героїчні метрики */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          <div className="cascade-in">
            <HeroMetric
              title="Активні клієнти"
              value={clientStats.connected}
              subtitle={`з ${clientStats.total} всього клієнтів`}
              icon={<UsersIcon size="lg" />}
              gradient="bg-gradient-to-br from-blue-500 via-blue-600 to-blue-700"
              trend={{
                value: `${connectionRate}% онлайн`,
                isPositive: connectionRate >= 80,
              }}
            />
          </div>

          <div className="cascade-in-delay-1">
            <HeroMetric
              title="Навантаження CPU"
              value={`${Math.round(systemMetrics.cpu_usage)}%`}
              subtitle="Середнє використання"
              icon={<CpuIcon size="lg" />}
              gradient="bg-gradient-to-br from-emerald-500 via-emerald-600 to-emerald-700"
              trend={{
                value:
                  systemMetrics.cpu_usage > 70
                    ? "Високе"
                    : systemMetrics.cpu_usage > 40
                      ? "Помірне"
                      : "Низьке",
                isPositive: systemMetrics.cpu_usage <= 70,
              }}
            />
          </div>

          <div className="cascade-in-delay-2">
            <HeroMetric
              title="Використання пам'яті"
              value={`${Math.round(systemMetrics.memory_usage)}%`}
              subtitle="Оперативна пам'ять"
              icon={<MemoryIcon size="lg" />}
              gradient="bg-gradient-to-br from-amber-500 via-amber-600 to-amber-700"
              trend={{
                value:
                  systemMetrics.memory_usage > 80
                    ? "Критично"
                    : systemMetrics.memory_usage > 60
                      ? "Помірно"
                      : "Стабільно",
                isPositive: systemMetrics.memory_usage <= 80,
              }}
            />
          </div>

          <div className="cascade-in-delay-3">
            <HeroMetric
              title="Стан системи"
              value={systemHealth}
              subtitle="Загальний статус"
              icon={<AnimatedHeartIcon size="lg" />}
              gradient={
                systemHealth === "Здорова"
                  ? "bg-gradient-to-br from-emerald-500 via-emerald-600 to-emerald-700"
                  : systemHealth === "Погіршена"
                    ? "bg-gradient-to-br from-amber-500 via-amber-600 to-amber-700"
                    : "bg-gradient-to-br from-red-500 via-red-600 to-red-700"
              }
              trend={
                systemHealth === "Здорова"
                  ? { value: "Відмінно", isPositive: true }
                  : systemHealth === "Погіршена"
                    ? { value: "Потребує уваги", isPositive: false }
                    : { value: "Критично", isPositive: false }
              }
            />
          </div>
        </div>

        {/* Основний контент */}
        {currentView === "console" ? (
          <ConsoleLogs />
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
            {/* Ліва колонка - статистика */}
            <div className="lg:col-span-2 space-y-6">
              {/* Статистика клієнтів */}
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                <StatCard
                  title="Всі воркери"
                  value={clientStats.workers + clientStats.apiWorkers}
                  icon={<CpuIcon size="md" />}
                  color="bg-blue-100 text-blue-600"
                  description="Загальна кількість"
                />

                <StatCard
                  title="Воркери"
                  value={clientStats.workers}
                  icon={<ProcessingIcon size="md" />}
                  color="bg-emerald-100 text-emerald-600"
                  description="Стандартні воркери"
                />

                <StatCard
                  title="API-воркери"
                  value={clientStats.apiWorkers}
                  icon={<AlertIcon size="md" />}
                  color="bg-amber-100 text-amber-600"
                  description="API обробники"
                />

                <StatCard
                  title="Активні сервери Бота"
                  value={clientStats.bots}
                  icon={<UsersIcon size="md" />}
                  color="bg-purple-100 text-purple-600"
                  description="Підключені боти"
                />
              </div>

              {/* Системне здоров'я */}
              <SystemHealthWidget />
            </div>

            {/* Права колонка - активність та дії */}
            <div className="space-y-6">
              <RealTimeActivity />
              <QuickActions />
            </div>
          </div>
        )}

        {/* Нижня секція - стан системи */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          {/* Стан системи */}
          <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
            <h3 className="text-lg font-semibold text-slate-900 mb-6 flex items-center">
              <span className="bg-gradient-to-r from-slate-600 to-slate-800 bg-clip-text text-transparent">
                💻 Стан системи
              </span>
            </h3>

            <div className="grid grid-cols-2 gap-4">
              <div
                className={`flex items-center justify-between p-3 rounded-lg ${
                  state.health?.components?.websocket_manager
                    ? "bg-emerald-50"
                    : "bg-red-50"
                }`}
              >
                <div className="flex items-center space-x-2">
                  <div
                    className={`w-3 h-3 rounded-full ${
                      state.health?.components?.websocket_manager
                        ? "bg-emerald-500"
                        : "bg-red-500"
                    }`}
                  ></div>
                  <span className="text-sm font-medium text-slate-700">
                    WebSocket Server
                  </span>
                </div>
                <span
                  className={`text-xs font-semibold ${
                    state.health?.components?.websocket_manager
                      ? "text-emerald-600"
                      : "text-red-600"
                  }`}
                >
                  {state.health?.components?.websocket_manager
                    ? "Активний"
                    : "Неактивний"}
                </span>
              </div>

              <div
                className={`flex items-center justify-between p-3 rounded-lg ${
                  state.health?.components?.redis
                    ? "bg-emerald-50"
                    : "bg-red-50"
                }`}
              >
                <div className="flex items-center space-x-2">
                  <div
                    className={`w-3 h-3 rounded-full ${
                      state.health?.components?.redis
                        ? "bg-emerald-500"
                        : "bg-red-500"
                    }`}
                  ></div>
                  <span className="text-sm font-medium text-slate-700">
                    Redis Cache
                  </span>
                </div>
                <span
                  className={`text-xs font-semibold ${
                    state.health?.components?.redis
                      ? "text-emerald-600"
                      : "text-red-600"
                  }`}
                >
                  {state.health?.components?.redis
                    ? "Підключено"
                    : "Відключено"}
                </span>
              </div>

              <div
                className={`flex items-center justify-between p-3 rounded-lg ${
                  state.health?.components?.client_manager
                    ? "bg-emerald-50"
                    : "bg-red-50"
                }`}
              >
                <div className="flex items-center space-x-2">
                  <div
                    className={`w-3 h-3 rounded-full ${
                      state.health?.components?.client_manager
                        ? "bg-emerald-500"
                        : "bg-red-500"
                    }`}
                  ></div>
                  <span className="text-sm font-medium text-slate-700">
                    Client Manager
                  </span>
                </div>
                <span
                  className={`text-xs font-semibold ${
                    state.health?.components?.client_manager
                      ? "text-emerald-600"
                      : "text-red-600"
                  }`}
                >
                  {state.health?.components?.client_manager
                    ? "Працює"
                    : "Зупинено"}
                </span>
              </div>

              <div
                className={`flex items-center justify-between p-3 rounded-lg ${
                  state.health?.components?.task_router
                    ? "bg-emerald-50"
                    : "bg-red-50"
                }`}
              >
                <div className="flex items-center space-x-2">
                  <div
                    className={`w-3 h-3 rounded-full ${
                      state.health?.components?.task_router
                        ? "bg-emerald-500"
                        : "bg-red-500"
                    }`}
                  ></div>
                  <span className="text-sm font-medium text-slate-700">
                    Task Router
                  </span>
                </div>
                <span
                  className={`text-xs font-semibold ${
                    state.health?.components?.task_router
                      ? "text-emerald-600"
                      : "text-red-600"
                  }`}
                >
                  {state.health?.components?.task_router
                    ? "Активний"
                    : "Неактивний"}
                </span>
              </div>
            </div>

            <div className="mt-6 pt-4 border-t border-slate-200">
              <div className="flex items-center justify-between">
                <span className="text-sm text-slate-600">
                  Версія системи: {state.health?.version || "1.0.0"}
                </span>
                <div className="flex items-center space-x-2">
                  <span className="text-sm text-slate-600">
                    Статус з'єднання
                  </span>
                  <div className="flex items-center space-x-1">
                    <div
                      className={`w-2 h-2 rounded-full ${
                        state.connectionStatus === "connected"
                          ? "bg-emerald-500"
                          : "bg-red-500"
                      }`}
                    ></div>
                    <span
                      className={`text-sm font-medium ${
                        state.connectionStatus === "connected"
                          ? "text-emerald-600"
                          : "text-red-600"
                      }`}
                    >
                      {state.connectionStatus === "connected"
                        ? "Онлайн"
                        : "Офлайн"}
                    </span>
                    <span className="text-sm text-slate-500">
                      {clientStats.connected}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Метрики продуктивності */}
          <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
            <h3 className="text-lg font-semibold text-slate-900 mb-6 flex items-center">
              <span className="bg-gradient-to-r from-amber-600 to-amber-800 bg-clip-text text-transparent">
                ⚡ Метрики продуктивності
              </span>
            </h3>

            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-slate-700">
                  Час відповіді
                </span>
                <span className="text-2xl font-bold text-blue-600">
                  {Math.round(hubMetrics.response_time)}ms
                </span>
              </div>

              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-slate-700">
                  Пропускна здатність
                </span>
                <span className="text-2xl font-bold text-emerald-600">
                  {Math.round(hubMetrics.throughput)} req/s
                </span>
              </div>

              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-slate-700">
                  Рівень помилок
                </span>
                <span
                  className={`text-2xl font-bold ${
                    hubMetrics.error_rate > 2
                      ? "text-red-600"
                      : "text-emerald-600"
                  }`}
                >
                  {hubMetrics.error_rate.toFixed(1)}%
                </span>
              </div>

              {state.health?.uptime && (
                <div className="flex items-center justify-between pt-2 border-t border-slate-200">
                  <span className="text-sm font-medium text-slate-700">
                    Час роботи
                  </span>
                  <span className="text-lg font-bold text-purple-600">
                    {Math.floor(state.health.uptime / 3600)}г{" "}
                    {Math.floor((state.health.uptime % 3600) / 60)}хв
                  </span>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
