import React, { useState, useEffect, useMemo, useCallback, useRef } from "react";
import ReactDOM from "react-dom";
import { useI18n } from "../contexts/I18nContext";
import { Task, TaskQueueStats } from "../types/api";
import { useStatus } from "../contexts/StatusContext";
import VirtualizedTaskTable from "./VirtualizedTaskTable";
import { useDebounce } from "../hooks/useDebounce";
import { useAnimationSettings } from "../hooks/useAnimationSettings";
import AnimationToggle from "./AnimationToggle";
import "../animations.css";
import {
  TasksIcon,
  ClockIcon,
  ProcessingIcon,
  CheckIcon,
  AlertIcon,
  CloseIcon,
  RefreshIcon,
} from "./Icons";
import {
  AnimatedPageHeader,
  AnimatedCard,
  AnimatedList,
  usePageAnimation,
} from "./PageTransition";

interface TasksViewProps {}

interface TaskWithDetails extends Task {
  progress?: number;
  estimated_completion?: string;
}

interface TaskFilters {
  status: string;
  priority: string;
  task_type: string;
  worker: string;
  search: string;
}

const TasksView: React.FC<TasksViewProps> = () => {
  const { t } = useI18n();
  const [tasks, setTasks] = useState<TaskWithDetails[]>([]);
  const [queueStats, setQueueStats] = useState<TaskQueueStats | null>(null);

  const [error, setError] = useState<string | null>(null);
  const [refreshInterval, setRefreshInterval] = useState<number>(5000);
  const [selectedTask, setSelectedTask] = useState<TaskWithDetails | null>(
    null,
  );

  // Refs для оптимізації логування та відстеження
  const lastConnectionStatus = useRef<string>("");
  const effectExecutionCount = useRef<number>(0);
  const intervalRef = useRef<NodeJS.Timeout | null>(null);
  const diagnosticStartTime = useRef<number>(Date.now());
  const [showTaskModal, setShowTaskModal] = useState<boolean>(false);
  const [isInitialLoad, setIsInitialLoad] = useState<boolean>(true);
  const [isLoading, setIsLoading] = useState<boolean>(false);

  // Стейти для пагінації та сортування
  const [currentPage, setCurrentPage] = useState<number>(1);
  const [sortField, setSortField] = useState<string>("created_at");
  const [sortOrder, setSortOrder] = useState<string>("desc");
  const [pagination, setPagination] = useState({
    page: 1,
    limit: 50,
    total_items: 0,
    total_pages: 0,
    has_next: false,
    has_prev: false,
  });

  const [filters, setFilters] = useState<TaskFilters>({
    status: "all",
    priority: "all",
    task_type: "all",
    worker: "all",
    search: "",
  });
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [updatedTaskIds, setUpdatedTaskIds] = useState<Set<string>>(new Set());
  const [newTaskIds, setNewTaskIds] = useState<Set<string>>(new Set());
  const [useVirtualizedTable, setUseVirtualizedTable] = useState<boolean>(false);
  const isLoaded = usePageAnimation(100);

  // Debounced значення для оптимізації запитів
  const debouncedSearchQuery = useDebounce(searchQuery, 1000); // Збільшено з 500ms до 1000ms
  const debouncedFilters = useDebounce(filters, 800); // Збільшено з 300ms до 800ms
  const debouncedSortField = useDebounce(sortField, 600); // Збільшено з 400ms до 600ms
  const debouncedSortOrder = useDebounce(sortOrder, 600); // Збільшено з 400ms до 600ms

  // Стан для кешування останнього запиту
  const [lastFetchTime, setLastFetchTime] = useState<Date | null>(null);
  const [cachedParams, setCachedParams] = useState<string>("");

  // Налаштування анімацій
  const { isAnimationEnabled, getAnimationClass } = useAnimationSettings();

  // StatusContext для оновлень в реальному часі
  const { state: statusState, connectWebSocket } = useStatus();

  // Функція для отримання порожніх статистик
  const getEmptyQueueStats = useCallback((): TaskQueueStats => {
    return {
      total_tasks: 0,
      pending_tasks: 0,
      processing_tasks: 0,
      completed_tasks: 0,
      failed_tasks: 0,
      average_processing_time: 0,
      queue_sizes: {
        critical: 0,
        high: 0,
        normal: 0,
        low: 0,
      },
      worker_distribution: {},
      active_tasks: 0,
      workers_count: 0,
      tasks: [],
    };
  }, []);

  // Функція для повтору завантаження даних
  const retryFetch = useCallback(() => {
    setError(null);
    fetchTasksData(false);
  }, []);

  const fetchTasksData = useCallback(
    async (isRefresh = false) => {
      try {
        if (!isRefresh) {
          setIsLoading(true);
        }

        // Будуємо URL з параметрами фільтрації
        const params = new URLSearchParams({
          page: currentPage.toString(),
          limit: "50",
          sort: debouncedSortField,
          order: debouncedSortOrder,
        });

        // Додаємо фільтри до URL якщо вони не "all"
        if (debouncedFilters.status !== "all") {
          params.append("status", debouncedFilters.status);
        }
        if (debouncedFilters.priority !== "all") {
          params.append("priority", debouncedFilters.priority);
        }
        if (debouncedFilters.task_type !== "all") {
          params.append("task_type", debouncedFilters.task_type);
        }
        if (debouncedFilters.worker !== "all") {
          params.append("worker", debouncedFilters.worker);
        }
        if (debouncedSearchQuery) {
          params.append("search", debouncedSearchQuery);
        }

        // Перевіряємо чи потрібен запит (кешування)
        const currentParams = params.toString();
        const now = new Date();
        const timeSinceLastFetch = lastFetchTime ? now.getTime() - lastFetchTime.getTime() : 0;
        
        // Пропускаємо запит якщо:
        // 1. WebSocket підключений і дані свіжі (менше 3 секунд)
        // 2. Параметри не змінилися і запит був недавно
        // 3. НЕ пропускаємо якщо кеш був очищений (lastFetchTime === null)
        if (isRefresh && 
            statusState.connectionStatus === "connected" && 
            lastFetchTime !== null &&
            timeSinceLastFetch < 3000 && 
            currentParams === cachedParams) {
          console.log("🚀 Пропускаємо запит - WebSocket активний і дані свіжі");
          return;
        }

        // Отримуємо реальні дані з API
        try {
          const [tasksResponse, statsResponse] = await Promise.all([
            fetch(`/api/tasks?${params.toString()}`),
            fetch("/api/tasks/stats"),
          ]);

          if (tasksResponse.ok && statsResponse.ok) {
            const tasksData = await tasksResponse.json();
            const statsData = await statsResponse.json();

            setTasks(tasksData.tasks || []);
            setQueueStats(statsData);
            setPagination(tasksData.pagination || pagination);
            setError(null);
            
            // Оновлюємо кеш
            setLastFetchTime(now);
            setCachedParams(currentParams);
          } else {
            // API повернув помилку
            setTasks([]);
            setQueueStats(getEmptyQueueStats());
            setError(
              `${t("errors.serverError")}: ${tasksResponse.status} ${tasksResponse.statusText}`,
            );
          }
        } catch (apiError) {
          console.error("Помилка підключення до API:", apiError);
          setTasks([]);
          setQueueStats(getEmptyQueueStats());
          setError(
            `${t("errors.connectionFailed")}: ${apiError instanceof Error ? apiError.message : String(apiError)}`,
          );
        }
      } catch (err) {
        setError(
          `${t("errors.loadingFailed")}: ${err instanceof Error ? err.message : String(err)}`,
        );
        setTasks([]);
        setQueueStats(getEmptyQueueStats());
      } finally {
        if (!isRefresh) {
          setIsInitialLoad(false);
          setIsLoading(false);
        }
      }
    },
    [
      currentPage,
      debouncedSortField,
      debouncedSortOrder,
      debouncedFilters,
      debouncedSearchQuery,
      pagination,
      getEmptyQueueStats,
      t,
    ],
  );

  // Стабільна версія fetchTasksData для залежностей
  const stableFetchTasksData = useCallback(() => {
    fetchTasksData(true);
  }, [fetchTasksData]);

  useEffect(() => {
    // Трекінг виконань для діагностики
    effectExecutionCount.current += 1;
    if (process.env.NODE_ENV === 'development') {
      console.debug(`🔄 TasksView useEffect execution #${effectExecutionCount.current}`);
    }

    // Перше завантаження тільки при першому рендері
    if (effectExecutionCount.current === 1) {
      fetchTasksData(false);
    }

    // Очищуємо попередній інтервал
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }

    // Логування тільки при зміні статусу підключення
    const currentStatus = statusState.connectionStatus;
    if (lastConnectionStatus.current !== currentStatus) {
      if (currentStatus === "connected") {
        console.log("📡 WebSocket підключений - рідкий polling (60s)");
      } else {
        console.log("🔄 WebSocket відключений - звичайний polling (" + refreshInterval/1000 + "s)");
      }
      lastConnectionStatus.current = currentStatus;
    }

    // Налаштовуємо новий інтервал
    if (currentStatus === "connected") {
      // При підключеному WebSocket рідко polling (60 секунд) для fallback
      intervalRef.current = setInterval(stableFetchTasksData, 60000);
    } else {
      // Без WebSocket - звичайний polling
      intervalRef.current = setInterval(stableFetchTasksData, refreshInterval);
    }
    
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [stableFetchTasksData, refreshInterval, statusState.connectionStatus]);

  // Debounce для пошуку (збільшено таймер)
  useEffect(() => {
    const timer = setTimeout(() => {
      setSearchQuery(filters.search);
    }, 1000); // Збільшено з 500ms до 1000ms

    return () => clearTimeout(timer);
  }, [filters.search]);

  // Автоматичне оновлення при зміні статистики завдань через StatusContext з анімаціями
  useEffect(() => {
    if (statusState.taskStats) {
      // Оновлюємо загальну статистику
      setQueueStats(statusState.taskStats);

      // Перевіряємо чи змінилася загальна кількість завдань - це означає що створене нове завдання
      const newTotalTasks = statusState.taskStats.total_tasks;
      const currentTotalTasks = queueStats?.total_tasks || 0;
      
      // Якщо кількість завдань змінилася, примусово завантажуємо оновлені дані
      if (newTotalTasks !== currentTotalTasks) {
        console.log(`📈 Кількість завдань змінилася: ${currentTotalTasks} → ${newTotalTasks}, примусово оновлюємо список`);
        console.log(`🔄 Поточний список завдань: ${tasks.length}, WebSocket статус: ${statusState.connectionStatus}`);
        // Очищуємо кеш щоб дозволити оновлення
        setLastFetchTime(null);
        setCachedParams("");
        // Принудительно завантажуємо дані
        fetchTasksData(true);
        return;
      }

      // Додаткова перевірка: якщо статистика показує завдання, але список порожній
      if (newTotalTasks > 0 && tasks.length === 0 && statusState.connectionStatus === "connected") {
        console.log(`🚨 Виявлено розбіжність: статистика показує ${newTotalTasks} завдань, але список порожній`);
        setLastFetchTime(null);
        setCachedParams("");
        fetchTasksData(true);
        return;
      }

      // Якщо є завдання в статистиці і вони відрізняються від поточних, оновлюємо
      if (
        statusState.taskStats.tasks &&
        Array.isArray(statusState.taskStats.tasks) &&
        statusState.taskStats.tasks.length > 0
      ) {
        const newTasks = statusState.taskStats.tasks;
        const currentTaskIds = new Set(tasks.map(t => t.task_id));
        const newTaskIdSet = new Set(newTasks.map(t => t.task_id));

        // Знаходимо нові завдання
        const justCreatedTasks = newTasks.filter(task => !currentTaskIds.has(task.task_id));
        if (justCreatedTasks.length > 0) {
          setNewTaskIds(new Set(justCreatedTasks.map(t => t.task_id)));
          const newTaskTimer = setTimeout(() => setNewTaskIds(new Set()), 1500);

          // Cleanup попереднього таймера якщо існує
          return () => {
            clearTimeout(newTaskTimer);
          };
        }

        // Знаходимо оновлені завдання
        const changedTasks = newTasks.filter(newTask => {
          const oldTask = tasks.find(t => t.task_id === newTask.task_id);
          return oldTask && (
            oldTask.status !== newTask.status ||
            oldTask.priority !== newTask.priority ||
            oldTask.worker_id !== newTask.worker_id
          );
        });

        if (changedTasks.length > 0) {
          setUpdatedTaskIds(new Set(changedTasks.map(t => t.task_id)));
          const updatedTaskTimer = setTimeout(() => setUpdatedTaskIds(new Set()), 2000);

          // Cleanup попереднього таймера якщо існує
          return () => {
            clearTimeout(updatedTaskTimer);
          };
        }

        setTasks(newTasks);

        // Визначаємо чи потрібна віртуалізація
        setUseVirtualizedTable(newTasks.length > 100);
      }
    }
  }, [statusState.taskStats, queueStats?.total_tasks]);

  // Перезавантажуємо дані при зміні стану підключення
  useEffect(() => {
    if (statusState.connectionStatus === "connected") {
      // При підключенні WebSocket перезавантажуємо дані
      fetchTasksData(true);
    }
  }, [statusState.connectionStatus, fetchTasksData]);

  // Окремий useEffect для скидання сторінки при зміні фільтрів
  useEffect(() => {
    if (currentPage !== 1) {
      setCurrentPage(1);
    }
  }, [
    filters.status,
    filters.priority,
    filters.task_type,
    filters.worker,
    searchQuery,
    sortField,
    sortOrder,
  ]);

  // Всі фільтри тепер на сервері, повертаємо таски як є
  const filteredTasks = useMemo(() => {
    return tasks;
  }, [tasks]);

  // Отримання унікальних значень для фільтрів
  const uniqueWorkers = useMemo(() => {
    const workers = tasks.map((t) => t.worker_id).filter(Boolean) as string[];
    return Array.from(new Set(workers));
  }, [tasks]);


  const uniqueTaskTypes = useMemo(() => {
    return Array.from(new Set(tasks.map((t) => t.task_type)));
  }, [tasks]);

  // Функції для управління завданнями
  const handleCancelTask = async (taskId: string) => {
    try {
      const response = await fetch(`/api/tasks/${taskId}/cancel`, {
        method: "POST",
      });
      if (response.ok) {
        setTasks((prev) =>
          prev.map((task) =>
            task.task_id === taskId
              ? { ...task, status: "cancelled" as const }
              : task,
          ),
        );
      } else {
        console.error("Помилка скасування завдання:", response.statusText);
      }
    } catch (err) {
      console.error("Помилка скасування завдання:", err);
    }
  };

  const handleRetryTask = async (taskId: string) => {
    try {
      const response = await fetch(`/api/tasks/${taskId}/retry`, {
        method: "POST",
      });
      if (response.ok) {
        setTasks((prev) =>
          prev.map((task) =>
            task.task_id === taskId
              ? {
                  ...task,
                  status: "pending" as const,
                  attempt: task.attempt + 1,
                }
              : task,
          ),
        );
      } else {
        console.error("Помилка повтору завдання:", response.statusText);
      }
    } catch (err) {
      console.error("Помилка повтору завдання:", err);
    }
  };

  const handleClearQueue = async (priority: string) => {
    try {
      const response = await fetch(`/api/tasks/clear-queue`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ priority }),
      });
      if (response.ok) {
        setTasks((prev) =>
          prev.filter(
            (task) =>
              !(
                task.priority === priority &&
                ["pending", "assigned"].includes(task.status)
              ),
          ),
        );
      } else {
        console.error("Помилка очищення черги:", response.statusText);
      }
    } catch (err) {
      console.error("Помилка очищення черги:", err);
    }
  };

  // Функції для отримання стилів
  const getStatusColor = (status: string) => {
    switch (status) {
      case "pending":
        return "bg-yellow-100 text-yellow-800";
      case "assigned":
        return "bg-blue-100 text-blue-800";
      case "processing":
        return "bg-purple-100 text-purple-800";
      case "completed":
        return "bg-green-100 text-green-800";
      case "failed":
        return "bg-red-100 text-red-800";
      case "timeout":
        return "bg-orange-100 text-orange-800";
      case "retry":
        return "bg-indigo-100 text-indigo-800";
      case "cancelled":
        return "bg-gray-100 text-gray-800";
      default:
        return "bg-gray-100 text-gray-800";
    }
  };

  const getPriorityColor = (priority: string) => {
    switch (priority) {
      case "critical":
        return "bg-red-500";
      case "high":
        return "bg-orange-500";
      case "normal":
        return "bg-blue-500";
      case "low":
        return "bg-green-500";
      default:
        return "bg-gray-500";
    }
  };

  const formatDuration = (ms: number) => {
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    return `${(ms / 60000).toFixed(1)}m`;
  };

  const formatTimeAgo = (dateString: string) => {
    const now = new Date();
    const date = new Date(dateString);
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMins / 60);
    const diffDays = Math.floor(diffHours / 24);

    if (diffMins < 1) return "щойно";
    if (diffMins < 60) return `${diffMins}хв тому`;
    if (diffHours < 24) return `${diffHours}год тому`;
    return `${diffDays}д тому`;
  };

  if (error) {
    return (
      <div className="text-center py-12">
        <AlertIcon className="w-12 h-12 text-error-500 mx-auto mb-4" />
        <h3 className="text-lg font-semibold text-secondary-900 mb-2">
          {t("errors.loadingFailed")}
        </h3>
        <p className="text-secondary-600 mb-4">{error}</p>
        <div className="flex space-x-3 justify-center">
          <button
            onClick={retryFetch}
            disabled={isLoading}
            className="px-4 py-2 bg-primary-500 text-white rounded-lg hover:bg-primary-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center space-x-2"
          >
            {isLoading ? (
              <>
                <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                <span>Завантаження...</span>
              </>
            ) : (
              <span>Спробувати знову</span>
            )}
          </button>
          <button
            onClick={() => window.location.reload()}
            className="px-4 py-2 bg-secondary-500 text-white rounded-lg hover:bg-secondary-600 transition-colors"
          >
            Перезавантажити сторінку
          </button>
        </div>
      </div>
    );
  }

  const stats = queueStats || getEmptyQueueStats();

  // Діагностичне логування ефективності оптимізацій
  useEffect(() => {
    if (process.env.NODE_ENV === 'development') {
      const runTimeMinutes = (Date.now() - diagnosticStartTime.current) / 60000;
      const effectsPerMinute = effectExecutionCount.current / Math.max(runTimeMinutes, 0.01);
      
      console.log(`📊 TasksView Diagnostic Report:
        - Total useEffect executions: ${effectExecutionCount.current}
        - Runtime: ${runTimeMinutes.toFixed(1)} minutes
        - Effects per minute: ${effectsPerMinute.toFixed(1)}
        - Current connection status: ${statusState.connectionStatus}
        - Last known connection status: ${lastConnectionStatus.current}
      `);
    }
  }, [statusState.connectionStatus]);

  return (
    <div className="space-y-8">
      {/* Page Header */}
      <AnimatedPageHeader>
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold text-gradient mb-2">
              ⚡ {t("tasks.title")}
            </h1>
            <p className="text-lg text-secondary-600">{t("tasks.subtitle")}</p>
          </div>
          <div className="text-right">
            <p className="text-2xl font-bold text-primary-600">
              {stats.total_tasks}
            </p>
            <div className="text-sm text-secondary-500 mt-1">
              {statusState.connectionStatus === "connected" ? (
                <span className="text-green-600 websocket-connected realtime-indicator">
                  🟢 WebSocket підключено {useVirtualizedTable && `(${filteredTasks.length} завдань)`}
                </span>
              ) : statusState.connectionStatus === "connecting" ? (
                <span className="text-yellow-600">🟡 Підключення...</span>
              ) : statusState.connectionStatus === "error" || statusState.connectionStatus === "disconnected" ? (
                <div className="flex items-center space-x-2">
                  <span className="text-red-600 websocket-disconnected">
                    🔴 {statusState.connectionStatus === "error" ? "Помилка підключення" : "З'єднання розірвано"}
                  </span>
                  <button
                    onClick={connectWebSocket}
                    className="px-2 py-1 text-xs bg-red-500 text-white rounded hover:bg-red-600 transition-colors"
                    title="Спробувати підключитися знову"
                  >
                    🔄 Reconnect
                  </button>
                </div>
              ) : (
                <span className="text-gray-600">
                  ⏱️ {refreshInterval / 1000}s {useVirtualizedTable && "(Віртуальна таблиця)"}
                </span>
              )}
            </div>

            {/* Animation Toggle */}
            <div className="ml-4">
              <AnimationToggle
                size="sm"
                showLabel={true}
                variant="switch"
                className="flex items-center"
              />
            </div>
          </div>
        </div>
      </AnimatedPageHeader>

      {/* Statistics Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <AnimatedCard index={0} animationType="card">
          <div className="bg-white rounded-xl shadow-sm p-6">
            <div className="flex items-center">
              <div className="p-3 rounded-lg bg-blue-100 text-blue-600">
                <TasksIcon size="lg" />
              </div>
              <div className="ml-4">
                <p className="text-sm font-medium text-secondary-600">
                  {t("tasks.pendingTasks")}
                </p>
                <p className="text-2xl font-bold text-secondary-900">
                  {stats.pending_tasks}
                </p>
              </div>
            </div>
          </div>
        </AnimatedCard>

        <AnimatedCard index={1} animationType="card">
          <div className="bg-white rounded-xl shadow-sm p-6">
            <div className="flex items-center">
              <div className="p-3 rounded-lg bg-yellow-100 text-yellow-600">
                <ProcessingIcon size="lg" />
              </div>
              <div className="ml-4">
                <p className="text-sm font-medium text-secondary-600">
                  {t("tasks.processingTasks")}
                </p>
                <p className="text-2xl font-bold text-secondary-900">
                  {stats.processing_tasks}
                </p>
              </div>
            </div>
          </div>
        </AnimatedCard>

        <AnimatedCard index={2} animationType="card">
          <div className="bg-white rounded-xl shadow-sm p-6">
            <div className="flex items-center">
              <div className="p-3 rounded-lg bg-green-100 text-green-600">
                <CheckIcon size="lg" />
              </div>
              <div className="ml-4">
                <p className="text-sm font-medium text-secondary-600">
                  {t("tasks.completedTasks")}
                </p>
                <p className="text-2xl font-bold text-secondary-900">
                  {stats.completed_tasks}
                </p>
              </div>
            </div>
          </div>
        </AnimatedCard>

        <AnimatedCard index={3} animationType="card">
          <div className="bg-white rounded-xl shadow-sm p-6">
            <div className="flex items-center">
              <div className="p-3 rounded-lg bg-red-100 text-red-600">
                <AlertIcon size="lg" />
              </div>
              <div className="ml-4">
                <p className="text-sm font-medium text-secondary-600">
                  {t("tasks.failedTasks")}
                </p>
                <p className="text-2xl font-bold text-secondary-900">
                  {stats.failed_tasks}
                </p>
              </div>
            </div>
          </div>
        </AnimatedCard>
      </div>

      {/* Filters and Controls */}
      <AnimatedCard index={0} animationType="grid">
        <div className="bg-white rounded-xl shadow-sm p-6">
          <h3 className="text-lg font-semibold text-secondary-900 mb-4">
            🔍 {t("tasks.filtersAndManagement")}
          </h3>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-6 gap-4">
            {/* Search */}
            <div
              className="page-content-stagger"
              style={{ animationDelay: "100ms" }}
            >
              <input
                type="text"
                placeholder={t("tasks.searchPlaceholder")}
                value={filters.search}
                onChange={(e) =>
                  setFilters((prev) => ({ ...prev, search: e.target.value }))
                }
                className="w-full px-3 py-2 border border-secondary-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
              />
            </div>

            {/* Status Filter */}
            <div
              className="page-content-stagger"
              style={{ animationDelay: "200ms" }}
            >
              <select
                value={filters.status}
                onChange={(e) =>
                  setFilters((prev) => ({ ...prev, status: e.target.value }))
                }
                className="w-full px-3 py-2 border border-secondary-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
              >
                <option value="all">{t("tasks.allStatuses")}</option>
                <option value="pending">{t("tasks.status.pending")}</option>
                <option value="processing">
                  {t("tasks.status.processing")}
                </option>
                <option value="completed">{t("tasks.status.completed")}</option>
                <option value="failed">{t("tasks.status.failed")}</option>
                <option value="cancelled">{t("tasks.status.cancelled")}</option>
              </select>
            </div>

            {/* Priority Filter */}
            <div
              className="page-content-stagger"
              style={{ animationDelay: "300ms" }}
            >
              <select
                value={filters.priority}
                onChange={(e) =>
                  setFilters((prev) => ({ ...prev, priority: e.target.value }))
                }
                className="w-full px-3 py-2 border border-secondary-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
              >
                <option value="all">{t("tasks.allPriorities")}</option>
                <option value="critical">{t("tasks.priority.critical")}</option>
                <option value="high">{t("tasks.priority.high")}</option>
                <option value="normal">{t("tasks.priority.normal")}</option>
                <option value="low">{t("tasks.priority.low")}</option>
              </select>
            </div>

            {/* Task Type Filter */}
            <div
              className="page-content-stagger"
              style={{ animationDelay: "400ms" }}
            >
              <select
                value={filters.task_type}
                onChange={(e) =>
                  setFilters((prev) => ({ ...prev, task_type: e.target.value }))
                }
                className="w-full px-3 py-2 border border-secondary-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
              >
                <option value="all">{t("tasks.allTypes")}</option>
                {uniqueTaskTypes.map((type) => (
                  <option key={type} value={type}>
                    {type}
                  </option>
                ))}
              </select>
            </div>

            {/* Worker ID Filter */}
            <div
              className="page-content-stagger"
              style={{ animationDelay: "500ms" }}
            >
              <select
                value={filters.worker}
                onChange={(e) =>
                  setFilters((prev) => ({ ...prev, worker: e.target.value }))
                }
                className="w-full px-3 py-2 border border-secondary-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
              >
                <option value="all">Всі Worker ID</option>
                {uniqueWorkers.map((worker) => (
                  <option key={worker} value={worker}>
                    {worker}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>
      </AnimatedCard>

      {/* Tasks List */}
      <AnimatedCard index={0} animationType="list">
        <div className="bg-white rounded-xl shadow-sm overflow-hidden">
          <div className="px-6 py-4 border-b border-secondary-200">
            <div className="flex justify-between items-center mb-6">
              <h3 className="text-lg font-semibold text-secondary-900">
                📋 {t("tasks.taskList")} ({filteredTasks.length})
              </h3>
              <div className="flex items-center space-x-4">
                <select
                  value={sortField}
                  onChange={(e) => setSortField(e.target.value)}
                  className="px-3 py-2 border border-secondary-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
                >
                  <option value="created_at">Дата створення</option>
                  <option value="priority">Пріоритет</option>
                  <option value="status">Статус</option>
                  <option value="task_type">Тип</option>
                </select>
                <select
                  value={sortOrder}
                  onChange={(e) => setSortOrder(e.target.value)}
                  className="px-3 py-2 border border-secondary-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
                >
                  <option value="desc">Спадання</option>
                  <option value="asc">Зростання</option>
                </select>
              </div>
            </div>
          </div>

          {filteredTasks.length > 0 ? (
            <div>
              <div className="overflow-x-auto">
                {useVirtualizedTable ? (
                  <VirtualizedTaskTable
                    tasks={filteredTasks}
                    onCancelTask={handleCancelTask}
                    onRetryTask={handleRetryTask}
                    onShowDetails={(task) => {
                      setSelectedTask(task);
                      setShowTaskModal(true);
                    }}
                    formatTimeAgo={formatTimeAgo}
                    getStatusColor={getStatusColor}
                    getPriorityColor={getPriorityColor}
                    isLoading={isLoading}
                    height={600}
                    dynamicSizing={true}
                    newTaskIds={newTaskIds}
                    updatedTaskIds={updatedTaskIds}
                    animationSettings={{ isAnimationEnabled, getAnimationClass }}
                  />
                ) : (
                  <div className="bg-white rounded-xl shadow-sm overflow-hidden">
                    <table className="min-w-full divide-y divide-secondary-200">
                      <thead className="bg-secondary-50">
                        <tr>
                          <th className="px-6 py-3 text-left text-xs font-medium text-secondary-500 uppercase tracking-wider">
                            ID завдання
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-secondary-500 uppercase tracking-wider">
                            Тип
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-secondary-500 uppercase tracking-wider">
                            Статус
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-secondary-500 uppercase tracking-wider">
                            Пріоритет
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-secondary-500 uppercase tracking-wider">
                            Воркер
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-secondary-500 uppercase tracking-wider">
                            Час створення
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-secondary-500 uppercase tracking-wider">
                            Дії
                          </th>
                        </tr>
                      </thead>
                      <tbody className="bg-white divide-y divide-secondary-200">
                        {isLoading ? (
                          <tr>
                            <td colSpan={7} className="px-6 py-12 text-center">
                              <div className="flex flex-col items-center justify-center">
                                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600 mb-4"></div>
                                <p className="text-secondary-600">
                                  {t("common.loading")}
                                </p>
                              </div>
                            </td>
                          </tr>
                        ) : (
                          filteredTasks.map((task, index) => {
                            const isUpdated = updatedTaskIds.has(task.task_id);
                            const isNew = newTaskIds.has(task.task_id);

                            let animationClass = "task-row page-content-stagger hover:bg-secondary-50";
                            if (isNew) animationClass += " task-created";
                            else if (isUpdated) animationClass += " task-updated";

                            // Додаємо класи для статусу
                            animationClass += ` task-status-${task.status}`;

                            return (
                              <tr
                                key={task.task_id}
                                className={animationClass}
                                style={{ animationDelay: `${index * 50}ms` }}
                              >
                                <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-secondary-900">
                                  {task.task_id}
                                </td>
                                <td className="px-6 py-4 whitespace-nowrap text-sm text-secondary-600">
                                  {task.task_type}
                                </td>
                                <td className="px-6 py-4 whitespace-nowrap">
                                  <span
                                    className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${getStatusColor(task.status)} ${isUpdated ? 'status-changed' : ''}`}
                                  >
                                    {task.status}
                                  </span>
                                </td>
                                <td className="px-6 py-4 whitespace-nowrap">
                                  <span
                                    className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${getPriorityColor(task.priority)} priority-${task.priority} ${task.priority === 'critical' ? 'priority-pulse' : ''}`}
                                  >
                                    {task.priority}
                                  </span>
                                </td>
                                <td className="px-6 py-4 whitespace-nowrap text-sm text-secondary-600">
                                  {task.worker_id || "Не призначено"}
                                </td>
                                <td className="px-6 py-4 whitespace-nowrap text-sm text-secondary-600">
                                  {formatTimeAgo(task.created_at)}
                                </td>
                                <td className="px-6 py-4 whitespace-nowrap text-sm font-medium">
                                  <div className="flex space-x-2">
                                    {task.status === "failed" && (
                                      <button
                                        onClick={() => handleRetryTask(task.task_id)}
                                        className="text-blue-600 hover:text-blue-900 transition-colors"
                                      >
                                        Повторити
                                      </button>
                                    )}
                                    {(task.status === "pending" ||
                                      task.status === "processing") && (
                                      <button
                                        onClick={() => handleCancelTask(task.task_id)}
                                        className="text-red-600 hover:text-red-900 transition-colors"
                                      >
                                        Скасувати
                                      </button>
                                    )}
                                    <button
                                      onClick={() => {
                                        setSelectedTask(task);
                                        setShowTaskModal(true);
                                      }}
                                      className="text-primary-600 hover:text-primary-900 transition-colors"
                                    >
                                      Деталі
                                    </button>
                                  </div>
                                </td>
                              </tr>
                            );
                          })
                        )}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              {/* Пагінація */}
              {pagination.total_pages > 1 && (
                <div className="flex justify-center items-center mt-6 space-x-2">
                  <button
                    onClick={() => setCurrentPage(currentPage - 1)}
                    disabled={!pagination.has_prev}
                    className="px-4 py-2 border border-secondary-300 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed hover:bg-secondary-50 transition-colors"
                  >
                    Попередня
                  </button>

                  <span className="px-4 py-2 text-sm text-secondary-600">
                    Сторінка {pagination.page} з {pagination.total_pages}
                  </span>

                  <span className="px-4 py-2 text-sm text-secondary-600">
                    Всього: {pagination.total_items}
                  </span>

                  <button
                    onClick={() => setCurrentPage(currentPage + 1)}
                    disabled={!pagination.has_next}
                    className="px-4 py-2 border border-secondary-300 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed hover:bg-secondary-50 transition-colors"
                  >
                    Наступна
                  </button>
                </div>
              )}
            </div>
          ) : (
            <div className="text-center py-12">
              <TasksIcon className="w-12 h-12 text-secondary-400 mx-auto mb-4" />
              <h3 className="text-lg font-medium text-secondary-900 mb-2">
                {t("tasks.noTasksFound")}
              </h3>
              <p className="text-secondary-600">
                {tasks.length === 0
                  ? "Немає завдань в системі"
                  : "Спробуйте змінити фільтри пошуку"}
              </p>
            </div>
          )}
        </div>
      </AnimatedCard>

      {/* Task Details Modal */}
      {showTaskModal && selectedTask && ReactDOM.createPortal(
        <div 
          className="modal-backdrop"
          onClick={(e) => {
            if (e.target === e.currentTarget) {
              setShowTaskModal(false);
            }
          }}
        >
          <div 
            className="modal-content-wrapper max-w-2xl w-full"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="px-6 py-4 border-b border-secondary-200 flex items-center justify-between">
              <h3 className="text-lg font-semibold text-secondary-900">
                Деталі завдання: {selectedTask.task_id}
              </h3>
              <button
                onClick={() => setShowTaskModal(false)}
                className="text-secondary-400 hover:text-secondary-600"
              >
                <CloseIcon size="lg" />
              </button>
            </div>
            <div className="px-6 py-4 space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-secondary-700">
                    Статус
                  </label>
                  <span
                    className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${getStatusColor(selectedTask.status)}`}
                  >
                    {selectedTask.status}
                  </span>
                </div>
                <div>
                  <label className="block text-sm font-medium text-secondary-700">
                    Пріоритет
                  </label>
                  <div className="flex items-center">
                    <div
                      className={`w-2 h-2 rounded-full mr-2 ${getPriorityColor(selectedTask.priority)}`}
                    ></div>
                    <span className="text-sm text-secondary-900 capitalize">
                      {selectedTask.priority}
                    </span>
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-secondary-700">
                    Створено
                  </label>
                  <p className="text-sm text-secondary-900">
                    {formatTimeAgo(selectedTask.created_at)}
                  </p>
                </div>
                <div>
                  <label className="block text-sm font-medium text-secondary-700">
                    Воркер
                  </label>
                  <p className="text-sm text-secondary-900">
                    {selectedTask.worker_id || "Не призначено"}
                  </p>
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-secondary-700">
                  Дані завдання
                </label>
                <pre className="mt-1 text-xs bg-secondary-50 rounded-md p-3 overflow-auto max-h-60">
                  {JSON.stringify(selectedTask.task_data, null, 2)}
                </pre>
              </div>

              {selectedTask.metadata && (
                <div>
                  <label className="block text-sm font-medium text-secondary-700">
                    Метадані
                  </label>
                  <pre className="mt-1 text-xs bg-secondary-50 rounded-md p-3 overflow-auto max-h-60">
                    {JSON.stringify(selectedTask.metadata, null, 2)}
                  </pre>
                </div>
              )}
            </div>

            {/* Modal Actions */}
            <div className="px-6 py-4 border-t border-secondary-200 flex space-x-3">
              {selectedTask.status === "failed" && (
                <button
                  onClick={() => {
                    handleRetryTask(selectedTask.task_id);
                    setShowTaskModal(false);
                  }}
                  className="px-4 py-2 bg-yellow-600 text-white rounded-lg hover:bg-yellow-700 transition-colors"
                >
                  Повторити
                </button>
              )}
              {["pending", "assigned", "processing"].includes(
                selectedTask.status,
              ) && (
                <button
                  onClick={() => {
                    handleCancelTask(selectedTask.task_id);
                    setShowTaskModal(false);
                  }}
                  className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors"
                >
                  Скасувати
                </button>
              )}
              <button
                onClick={() => setShowTaskModal(false)}
                className="px-4 py-2 bg-secondary-600 text-white rounded-lg hover:bg-secondary-700 transition-colors"
              >
                Закрити
              </button>
            </div>
          </div>
        </div>,
        document.body
      )}
    </div>
  );
};

export { TasksView };
