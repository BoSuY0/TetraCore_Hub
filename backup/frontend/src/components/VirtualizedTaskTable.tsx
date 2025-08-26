import React, { memo, useMemo } from "react";
import { FixedSizeList, VariableSizeList } from "react-window";
import { Task } from "../types/api";
import { useI18n } from "../contexts/I18nContext";

interface VirtualizedTaskTableProps {
  tasks: Task[];
  onCancelTask: (taskId: string) => void;
  onRetryTask: (taskId: string) => void;
  onShowDetails: (task: Task) => void;
  formatTimeAgo: (dateString: string) => string;
  getStatusColor: (status: string) => string;
  getPriorityColor: (priority: string) => string;
  isLoading?: boolean;
  height?: number;
  itemSize?: number;
  dynamicSizing?: boolean;
  newTaskIds?: Set<string>;
  updatedTaskIds?: Set<string>;
  animationSettings?: {
    isAnimationEnabled: boolean;
    getAnimationClass: (baseClass: string, animationClass?: string) => string;
  };
}

interface RowData {
  tasks: Task[];
  onCancelTask: (taskId: string) => void;
  onRetryTask: (taskId: string) => void;
  onShowDetails: (task: Task) => void;
  formatTimeAgo: (dateString: string) => string;
  getStatusColor: (status: string) => string;
  getPriorityColor: (priority: string) => string;
  t: (key: string) => string;
  newTaskIds: Set<string>;
  updatedTaskIds: Set<string>;
  animationSettings: {
    isAnimationEnabled: boolean;
    getAnimationClass: (baseClass: string, animationClass?: string) => string;
  };
}

interface RowProps {
  index: number;
  style: React.CSSProperties;
  data: RowData;
}

const TaskRow: React.FC<RowProps> = memo(({ index, style, data }) => {
  const {
    tasks,
    onCancelTask,
    onRetryTask,
    onShowDetails,
    formatTimeAgo,
    getStatusColor,
    getPriorityColor,
    t,
    newTaskIds,
    updatedTaskIds,
    animationSettings,
  } = data;

  const task = tasks[index];

  if (!task) {
    return <div style={style} />;
  }

  // Визначаємо анімаційні класи
  const isNew = newTaskIds.has(task.task_id);
  const isUpdated = updatedTaskIds.has(task.task_id);

  const baseClass =
    "flex items-center border-b border-secondary-200 hover:bg-secondary-50 transition-colors px-6 py-4";

  let animationClass = baseClass;
  if (animationSettings.isAnimationEnabled) {
    if (isNew) {
      animationClass = animationSettings.getAnimationClass(
        animationClass,
        "task-created new-task-slide-in",
      );
    } else if (isUpdated) {
      animationClass = animationSettings.getAnimationClass(
        animationClass,
        "task-updated status-changed",
      );
    }

    // Додаємо клас для статусу
    animationClass = animationSettings.getAnimationClass(
      animationClass,
      `task-status-${task.status}`,
    );

    // Додаємо анімації для пріоритету
    if (task.priority === "critical") {
      animationClass = animationSettings.getAnimationClass(
        animationClass,
        "priority-pulse priority-critical",
      );
    } else if (task.priority === "high") {
      animationClass = animationSettings.getAnimationClass(
        animationClass,
        "priority-high",
      );
    }

    // Додаємо hover анімації
    animationClass = animationSettings.getAnimationClass(
      animationClass,
      "task-row smooth-transition",
    );
  }

  return (
    <div style={style} className={animationClass}>
      {/* Task ID */}
      <div className="flex-shrink-0 w-48 pr-4">
        <span className="text-sm font-medium text-secondary-900 truncate block">
          {task.task_id}
        </span>
      </div>

      {/* Task Type */}
      <div className="flex-shrink-0 w-32 pr-4">
        <span className="text-sm text-secondary-600 truncate block">
          {task.task_type}
        </span>
      </div>

      {/* Status */}
      <div className="flex-shrink-0 w-28 pr-4">
        <span
          className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${getStatusColor(task.status)}`}
        >
          {task.status}
        </span>
      </div>

      {/* Priority */}
      <div className="flex-shrink-0 w-24 pr-4">
        <span
          className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${getPriorityColor(task.priority)}`}
        >
          {task.priority}
        </span>
      </div>

      {/* Worker */}
      <div className="flex-shrink-0 w-32 pr-4">
        <span className="text-sm text-secondary-600 truncate block">
          {task.worker_id || "Не призначено"}
        </span>
      </div>

      {/* Created At */}
      <div className="flex-shrink-0 w-28 pr-4">
        <span className="text-sm text-secondary-600">
          {formatTimeAgo(task.created_at)}
        </span>
      </div>

      {/* Actions */}
      <div className="flex-shrink-0 w-40">
        <div className="flex space-x-2">
          {task.status === "failed" && (
            <button
              onClick={() => onRetryTask(task.task_id)}
              className="text-blue-600 hover:text-blue-900 transition-colors text-sm"
            >
              Повторити
            </button>
          )}
          {(task.status === "pending" || task.status === "processing") && (
            <button
              onClick={() => onCancelTask(task.task_id)}
              className="text-red-600 hover:text-red-900 transition-colors text-sm"
            >
              Скасувати
            </button>
          )}
          <button
            onClick={() => onShowDetails(task)}
            className="text-primary-600 hover:text-primary-900 transition-colors text-sm"
          >
            Деталі
          </button>
        </div>
      </div>
    </div>
  );
});

TaskRow.displayName = "TaskRow";

const VirtualizedTaskTable: React.FC<VirtualizedTaskTableProps> = ({
  tasks,
  onCancelTask,
  onRetryTask,
  onShowDetails,
  formatTimeAgo,
  getStatusColor,
  getPriorityColor,
  isLoading = false,
  height = 600,
  itemSize = 80,
  dynamicSizing = false,
  newTaskIds = new Set(),
  updatedTaskIds = new Set(),
  animationSettings = {
    isAnimationEnabled: true,
    getAnimationClass: (baseClass: string, animationClass?: string) =>
      animationClass ? `${baseClass} ${animationClass}` : baseClass,
  },
}) => {
  const { t } = useI18n();

  // Функція для розрахунку динамічного розміру елемента
  const calculateItemSize = useMemo(() => {
    return (index: number) => {
      if (!dynamicSizing) return itemSize;
      const task = tasks[index];
      if (!task) return itemSize;

      let calculatedSize = 80; // базовий розмір

      // Додаємо висоту на основі довжини task_id
      if (task.task_id && task.task_id.length > 40) {
        calculatedSize += Math.ceil((task.task_id.length - 40) / 10) * 5;
      }

      // Додаємо висоту для довгого task_type
      if (task.task_type && task.task_type.length > 20) {
        calculatedSize += Math.ceil((task.task_type.length - 20) / 15) * 8;
      }

      // Додаємо висоту для довгого worker_id
      if (task.worker_id && task.worker_id.length > 25) {
        calculatedSize += 10;
      }

      // Додаємо висоту для анімацій
      const isNew = newTaskIds.has(task.task_id);
      const isUpdated = updatedTaskIds.has(task.task_id);
      if ((isNew || isUpdated) && animationSettings.isAnimationEnabled) {
        calculatedSize += 12; // більше місця для анімацій
      }

      // Додаємо висоту для критичного пріоритету з анімацією
      if (
        task.priority === "critical" &&
        animationSettings.isAnimationEnabled
      ) {
        calculatedSize += 10;
      }

      // Додаємо висоту для помилок у failed тасках
      if (task.status === "failed") {
        calculatedSize += 8;
      }

      // Додаємо висоту для прогресу (якщо є)
      if ((task as any).progress !== undefined) {
        calculatedSize += 15;
      }

      return Math.max(calculatedSize, 65); // мінімальний розмір 65px
    };
  }, [
    dynamicSizing,
    itemSize,
    tasks,
    newTaskIds,
    updatedTaskIds,
    animationSettings.isAnimationEnabled,
  ]);

  const rowData: RowData = useMemo(
    () => ({
      tasks,
      onCancelTask,
      onRetryTask,
      onShowDetails,
      formatTimeAgo,
      getStatusColor,
      getPriorityColor,
      t,
      newTaskIds,
      updatedTaskIds,
      animationSettings,
    }),
    [
      tasks,
      onCancelTask,
      onRetryTask,
      onShowDetails,
      formatTimeAgo,
      getStatusColor,
      getPriorityColor,
      t,
      newTaskIds,
      updatedTaskIds,
      animationSettings,
    ],
  );

  if (isLoading) {
    return (
      <div
        className="bg-white rounded-xl shadow-sm overflow-hidden"
        style={{ height }}
      >
        <div className="flex items-center justify-center h-full">
          <div className="flex flex-col items-center">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600 mb-4"></div>
            <p className="text-secondary-600">{t("common.loading")}</p>
          </div>
        </div>
      </div>
    );
  }

  if (tasks.length === 0) {
    return (
      <div
        className="bg-white rounded-xl shadow-sm overflow-hidden"
        style={{ height }}
      >
        <div className="flex items-center justify-center h-full">
          <div className="text-center">
            <h3 className="text-lg font-medium text-secondary-900 mb-2">
              {t("tasks.noTasksFound")}
            </h3>
            <p className="text-secondary-600">Немає завдань для відображення</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-xl shadow-sm overflow-hidden">
      {/* Table Header */}
      <div className="bg-secondary-50 border-b border-secondary-200">
        <div className="flex items-center px-6 py-3">
          <div className="flex-shrink-0 w-48 pr-4">
            <span className="text-xs font-medium text-secondary-500 uppercase tracking-wider">
              ID завдання
            </span>
          </div>
          <div className="flex-shrink-0 w-32 pr-4">
            <span className="text-xs font-medium text-secondary-500 uppercase tracking-wider">
              Тип
            </span>
          </div>
          <div className="flex-shrink-0 w-28 pr-4">
            <span className="text-xs font-medium text-secondary-500 uppercase tracking-wider">
              Статус
            </span>
          </div>
          <div className="flex-shrink-0 w-24 pr-4">
            <span className="text-xs font-medium text-secondary-500 uppercase tracking-wider">
              Пріоритет
            </span>
          </div>
          <div className="flex-shrink-0 w-32 pr-4">
            <span className="text-xs font-medium text-secondary-500 uppercase tracking-wider">
              Воркер
            </span>
          </div>
          <div className="flex-shrink-0 w-28 pr-4">
            <span className="text-xs font-medium text-secondary-500 uppercase tracking-wider">
              Створено
            </span>
          </div>
          <div className="flex-shrink-0 w-40">
            <span className="text-xs font-medium text-secondary-500 uppercase tracking-wider">
              Дії
            </span>
          </div>
        </div>
      </div>

      {/* Virtualized Rows */}
      {dynamicSizing ? (
        <VariableSizeList
          height={height - 60} // Subtract header height
          itemCount={tasks.length}
          itemSize={calculateItemSize}
          itemData={rowData}
          width="100%"
          style={{ outline: "none" }}
          overscanCount={15}
        >
          {TaskRow}
        </VariableSizeList>
      ) : (
        <FixedSizeList
          height={height - 60} // Subtract header height
          itemCount={tasks.length}
          itemSize={itemSize}
          itemData={rowData}
          width="100%"
          style={{ outline: "none" }}
          overscanCount={10}
        >
          {TaskRow}
        </FixedSizeList>
      )}

      {/* Footer with task count */}
      <div className="bg-secondary-50 border-t border-secondary-200 px-6 py-2">
        <span className="text-sm text-secondary-600">
          Показано {tasks.length} завдань
        </span>
      </div>
    </div>
  );
};

export default VirtualizedTaskTable;
