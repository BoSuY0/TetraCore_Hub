import React, { useState, useEffect, useMemo, useCallback } from "react";
import { useI18n } from "../contexts/I18nContext";
import { Task, TaskQueueStats } from "../types/api";
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
import { AnimatedPageHeader, AnimatedCard, AnimatedList, usePageAnimation } from "./PageTransition";

interface TasksViewProps {}

interface TaskWithDetails extends Task {
  worker_name?: string;
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
  const [showTaskModal, setShowTaskModal] = useState<boolean>(false);
  const [isInitialLoad, setIsInitialLoad] = useState<boolean>(true);
  const [filters, setFilters] = useState<TaskFilters>({
    status: "all",
    priority: "all",
    task_type: "all",
    worker: "all",
    search: "",
  });
  const isLoaded = usePageAnimation(100);

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
    };
  }, []);

  useEffect(() => {
    const fetchTasksData = async (isRefresh = false) => {
      try {
        // Не показуємо loading екран

        // Отримуємо реальні дані з API
        try {
          const [tasksResponse, statsResponse] = await Promise.all([
            fetch("/dashboard/api/tasks"),
            fetch("/dashboard/api/tasks/stats"),
          ]);

          if (tasksResponse.ok && statsResponse.ok) {
            const tasksData = await tasksResponse.json();
            const statsData = await statsResponse.json();

            setTasks(tasksData.tasks || []);
            setQueueStats(statsData);
            setError(null);
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
          setIsInitialLoad(false); // Позначаємо, що початкове завантаження завершено
        }
      }
    };

    // Перше завантаження
    fetchTasksData(false);

    // Налаштовуємо інтервал для оновлення (без loading state)
    const interval = setInterval(() => fetchTasksData(true), refreshInterval);
    return () => clearInterval(interval);
  }, [refreshInterval, getEmptyQueueStats]);

  // Фільтрація завдань
  const filteredTasks = useMemo(() => {
    return tasks.filter((task) => {
      if (filters.status !== "all" && task.status !== filters.status)
        return false;
      if (filters.priority !== "all" && task.priority !== filters.priority)
        return false;
      if (filters.task_type !== "all" && task.task_type !== filters.task_type)
        return false;
      if (filters.worker !== "all" && task.assigned_worker !== filters.worker)
        return false;
      if (
        filters.search &&
        !task.task_id.toLowerCase().includes(filters.search.toLowerCase()) &&
        !task.task_type.toLowerCase().includes(filters.search.toLowerCase())
      )
        return false;
      return true;
    });
  }, [tasks, filters]);

  // Отримання унікальних значень для фільтрів
  const uniqueWorkers = useMemo(() => {
    const workers = tasks
      .map((t) => t.assigned_worker)
      .filter(Boolean) as string[];
    return Array.from(new Set(workers));
  }, [tasks]);

  const uniqueTaskTypes = useMemo(() => {
    return Array.from(new Set(tasks.map((t) => t.task_type)));
  }, [tasks]);

  // Функції для управління завданнями
  const handleCancelTask = async (taskId: string) => {
    try {
      const response = await fetch(`/dashboard/api/tasks/${taskId}/cancel`, {
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
      const response = await fetch(`/dashboard/api/tasks/${taskId}/retry`, {
        method: "POST",
      });
      if (response.ok) {
        setTasks((prev) =>
          prev.map((task) =>
            task.task_id === taskId
              ? {
                  ...task,
                  status: "pending" as const,
                  retry_count: task.retry_count + 1,
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
      const response = await fetch(`/dashboard/api/tasks/clear-queue`, {
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
  const getStatusColor = (status: Task["status"]) => {
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

  const getPriorityColor = (priority: Task["priority"]) => {
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
        <h3 className="text-lg font-semibold text-secondary-900 mb-2">{t("errors.loadingFailed")}</h3>
        <p className="text-secondary-600 mb-4">{error}</p>
        <button
          onClick={() => window.location.reload()}
          className="px-4 py-2 bg-primary-500 text-white rounded-lg hover:bg-primary-600 transition-colors"
        >
          {t("errors.reload")}
        </button>
      </div>
    );
  }

  const stats = queueStats || getEmptyQueueStats();

  return (
    <div className="space-y-8">
      {/* Page Header */}
      <AnimatedPageHeader>
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold text-gradient mb-2">
              ⚡ {t("tasks.title")}
            </h1>
            <p className="text-lg text-secondary-600">
              {t("tasks.subtitle")}
            </p>
          </div>
          <div className="text-right">
            <p className="text-2xl font-bold text-primary-600">{stats.total_tasks}</p>
            <p className="text-sm text-secondary-600">{t("tasks.totalTasks")}</p>
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
                <p className="text-sm font-medium text-secondary-600">{t("tasks.pendingTasks")}</p>
                <p className="text-2xl font-bold text-secondary-900">{stats.pending_tasks}</p>
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
                <p className="text-sm font-medium text-secondary-600">{t("tasks.processingTasks")}</p>
                <p className="text-2xl font-bold text-secondary-900">{stats.processing_tasks}</p>
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
                <p className="text-sm font-medium text-secondary-600">{t("tasks.completedTasks")}</p>
                <p className="text-2xl font-bold text-secondary-900">{stats.completed_tasks}</p>
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
                <p className="text-sm font-medium text-secondary-600">{t("tasks.failedTasks")}</p>
                <p className="text-2xl font-bold text-secondary-900">{stats.failed_tasks}</p>
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
          
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
            {/* Search */}
            <div className="page-content-stagger" style={{ animationDelay: '100ms' }}>
              <input
                type="text"
                placeholder={t("tasks.searchPlaceholder")}
                value={filters.search}
                onChange={(e) => setFilters(prev => ({ ...prev, search: e.target.value }))}
                className="w-full px-3 py-2 border border-secondary-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
              />
            </div>

            {/* Status Filter */}
            <div className="page-content-stagger" style={{ animationDelay: '200ms' }}>
              <select
                value={filters.status}
                onChange={(e) => setFilters(prev => ({ ...prev, status: e.target.value }))}
                className="w-full px-3 py-2 border border-secondary-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
              >
                <option value="all">{t("tasks.allStatuses")}</option>
                <option value="pending">{t("tasks.status.pending")}</option>
                <option value="processing">{t("tasks.status.processing")}</option>
                <option value="completed">{t("tasks.status.completed")}</option>
                <option value="failed">{t("tasks.status.failed")}</option>
                <option value="cancelled">{t("tasks.status.cancelled")}</option>
              </select>
            </div>

            {/* Priority Filter */}
            <div className="page-content-stagger" style={{ animationDelay: '300ms' }}>
              <select
                value={filters.priority}
                onChange={(e) => setFilters(prev => ({ ...prev, priority: e.target.value }))}
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
            <div className="page-content-stagger" style={{ animationDelay: '400ms' }}>
              <select
                value={filters.task_type}
                onChange={(e) => setFilters(prev => ({ ...prev, task_type: e.target.value }))}
                className="w-full px-3 py-2 border border-secondary-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
              >
                <option value="all">{t("tasks.allTypes")}</option>
                {uniqueTaskTypes.map(type => (
                  <option key={type} value={type}>{type}</option>
                ))}
              </select>
            </div>

            {/* Worker Filter */}
            <div className="page-content-stagger" style={{ animationDelay: '500ms' }}>
              <select
                value={filters.worker}
                onChange={(e) => setFilters(prev => ({ ...prev, worker: e.target.value }))}
                className="w-full px-3 py-2 border border-secondary-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
              >
                <option value="all">{t("tasks.allWorkers")}</option>
                {uniqueWorkers.map(worker => (
                  <option key={worker} value={worker}>{worker}</option>
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
            <h3 className="text-lg font-semibold text-secondary-900">
              📋 {t("tasks.taskList")} ({filteredTasks.length})
            </h3>
          </div>
          
          {filteredTasks.length > 0 ? (
            <div className="overflow-x-auto">
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
                  {filteredTasks.slice(0, 50).map((task, index) => (
                    <tr 
                      key={task.task_id}
                      className="page-content-stagger hover:bg-secondary-50"
                      style={{ animationDelay: `${index * 50}ms` }}
                    >
                      <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-secondary-900">
                        {task.task_id}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-secondary-600">
                        {task.task_type}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${getStatusColor(task.status)}`}>
                          {task.status}
                        </span>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${getPriorityColor(task.priority)}`}>
                          {task.priority}
                        </span>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-secondary-600">
                        {task.assigned_worker || 'Не призначено'}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-secondary-600">
                        {formatTimeAgo(task.created_at)}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm font-medium">
                        <div className="flex space-x-2">
                          {task.status === 'failed' && (
                            <button
                              onClick={() => handleRetryTask(task.task_id)}
                              className="text-blue-600 hover:text-blue-900 transition-colors"
                            >
                              Повторити
                            </button>
                          )}
                          {(task.status === 'pending' || task.status === 'processing') && (
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
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-center py-12">
              <TasksIcon className="w-12 h-12 text-secondary-400 mx-auto mb-4" />
                              <h3 className="text-lg font-medium text-secondary-900 mb-2">{t("tasks.noTasksFound")}</h3>
              <p className="text-secondary-600">
                {tasks.length === 0 
                  ? "Немає завдань в системі" 
                  : "Спробуйте змінити фільтри пошуку"
                }
              </p>
            </div>
          )}
        </div>
      </AnimatedCard>

      {/* Task Details Modal */}
      {showTaskModal && selectedTask && (
        <div className="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto">
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
                <div>
                  <label className="block text-sm font-medium text-secondary-700">
                    Тип завдання
                  </label>
                  <p className="text-sm text-secondary-900">
                    {selectedTask.task_type.replace("_", " ")}
                  </p>
                </div>
                <div>
                  <label className="block text-sm font-medium text-secondary-700">
                    Воркер
                  </label>
                  <p className="text-sm text-secondary-900">
                    {selectedTask.worker_name ||
                      selectedTask.assigned_worker ||
                      "Не призначено"}
                  </p>
                </div>
                <div>
                  <label className="block text-sm font-medium text-secondary-700">
                    Створено
                  </label>
                  <p className="text-sm text-secondary-900">
                    {new Date(selectedTask.created_at).toLocaleString("uk-UA")}
                  </p>
                </div>
                {selectedTask.started_at && (
                  <div>
                    <label className="block text-sm font-medium text-secondary-700">
                      Розпочато
                    </label>
                    <p className="text-sm text-secondary-900">
                      {new Date(selectedTask.started_at).toLocaleString(
                        "uk-UA",
                      )}
                    </p>
                  </div>
                )}
                {selectedTask.completed_at && (
                  <div>
                    <label className="block text-sm font-medium text-secondary-700">
                      Завершено
                    </label>
                    <p className="text-sm text-secondary-900">
                      {new Date(selectedTask.completed_at).toLocaleString(
                        "uk-UA",
                      )}
                    </p>
                  </div>
                )}
                {selectedTask.execution_time && (
                  <div>
                    <label className="block text-sm font-medium text-secondary-700">
                      Час виконання
                    </label>
                    <p className="text-sm text-secondary-900">
                      {formatDuration(selectedTask.execution_time)}
                    </p>
                  </div>
                )}
                <div>
                  <label className="block text-sm font-medium text-secondary-700">
                    Спроби
                  </label>
                  <p className="text-sm text-secondary-900">
                    {selectedTask.retry_count} / {selectedTask.max_retries}
                  </p>
                </div>
                <div>
                  <label className="block text-sm font-medium text-secondary-700">
                    Таймаут
                  </label>
                  <p className="text-sm text-secondary-900">
                    {selectedTask.timeout}с
                  </p>
                </div>
              </div>

              {selectedTask.error_message && (
                <div>
                  <label className="block text-sm font-medium text-secondary-700 mb-2">
                    Помилка
                  </label>
                  <div className="bg-red-50 border border-red-200 rounded-lg p-3">
                    <p className="text-sm text-red-800">
                      {selectedTask.error_message}
                    </p>
                  </div>
                </div>
              )}

              {selectedTask.task_data && (
                <div>
                  <label className="block text-sm font-medium text-secondary-700 mb-2">
                    Дані завдання
                  </label>
                  <div className="bg-secondary-50 border border-secondary-200 rounded-lg p-3">
                    <pre className="text-sm text-secondary-800 whitespace-pre-wrap">
                      {JSON.stringify(selectedTask.task_data, null, 2)}
                    </pre>
                  </div>
                </div>
              )}
            </div>
            <div className="px-6 py-4 border-t border-secondary-200 flex justify-end space-x-3">
              {selectedTask.status === "failed" &&
                selectedTask.retry_count < selectedTask.max_retries && (
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
        </div>
      )}
    </div>
  );
};

export { TasksView };
