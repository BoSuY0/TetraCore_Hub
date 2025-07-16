import React, { useState, useEffect } from "react";
import ReactDOM from "react-dom";
import { useAnimationSettings } from "../hooks/useAnimationSettings";
import { useI18n } from "../contexts/I18nContext";

interface AnimationSettingsPanelProps {
  isOpen: boolean;
  onClose: () => void;
  className?: string;
}

const AnimationSettingsPanel: React.FC<AnimationSettingsPanelProps> = ({
  isOpen,
  onClose,
  className = "",
}) => {
  const { t } = useI18n();
  const { settings, updateSetting, resetToDefaults } = useAnimationSettings();

  // Блокуємо прокрутку body коли модальне вікно відкрите
  useEffect(() => {
    if (isOpen) {
      document.body.classList.add('modal-open');
    } else {
      document.body.classList.remove('modal-open');
    }

    // Cleanup при демонтуванні компонента
    return () => {
      document.body.classList.remove('modal-open');
    };
  }, [isOpen]);

  if (!isOpen) return null;

  const handleBackdropClick = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget) {
      onClose();
    }
  };

  const settingItems = [
    {
      key: "taskAnimations" as const,
      title: t("animations.settings.taskAnimations.title", "Task Animations"),
      description: t(
        "animations.settings.taskAnimations.description",
        "Анімації для створення, оновлення та зміни статусу завдань"
      ),
    },
    {
      key: "statusAnimations" as const,
      title: t("animations.settings.statusAnimations.title", "Status Animations"),
      description: t(
        "animations.settings.statusAnimations.description",
        "Анімації для зміни статусів завдань"
      ),
    },
    {
      key: "priorityAnimations" as const,
      title: t("animations.settings.priorityAnimations.title", "Priority Animations"),
      description: t(
        "animations.settings.priorityAnimations.description",
        "Анімації для критичних та високопріоритетних завдань"
      ),
    },
    {
      key: "hoverEffects" as const,
      title: t("animations.settings.hoverEffects.title", "Hover Effects"),
      description: t(
        "animations.settings.hoverEffects.description",
        "Ефекти при наведенні миші на елементи"
      ),
    },
    {
      key: "tableAnimations" as const,
      title: t("animations.settings.tableAnimations.title", "Table Animations"),
      description: t(
        "animations.settings.tableAnimations.description",
        "Анімації для таблиці завдань та віртуалізованих списків"
      ),
    },
  ];

  const modalContent = (
    <div
      className="modal-backdrop"
      onClick={handleBackdropClick}
    >
      <div 
        className={`modal-content-wrapper max-w-2xl w-full animation-settings-panel ${className}`}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-4 sm:px-6 py-3 sm:py-4 border-b border-secondary-200 flex items-center justify-between">
          <h3 className="text-base sm:text-lg font-semibold text-secondary-900">
            ⚙️ {t("animations.settings.title", "Animation Settings")}
          </h3>
          <button
            onClick={onClose}
            className="text-secondary-400 hover:text-secondary-600 transition-colors p-1 touch-manipulation"
            title={t("common.close", "Close")}
          >
            <svg className="w-5 h-5 sm:w-6 sm:h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          </button>
        </div>

        {/* Settings */}
        <div className="px-4 sm:px-6 py-3 sm:py-4 space-y-4 sm:space-y-6">
          {/* Master Toggle */}
          <div className="flex items-center justify-between p-3 sm:p-4 bg-secondary-50 rounded-lg">
            <div>
              <h4 className="font-medium text-secondary-900 text-sm sm:text-base">
                {t("animations.settings.masterToggle.title", "Enable Animations")}
              </h4>
              <p className="text-xs sm:text-sm text-secondary-600 mt-1">
                {t(
                  "animations.settings.masterToggle.description",
                  "Глобальне увімкнення/вимкнення всіх анімацій"
                )}
              </p>
            </div>
            <label className="relative inline-flex items-center cursor-pointer touch-manipulation">
              <input
                type="checkbox"
                checked={settings.enabled}
                onChange={(e) => updateSetting("enabled", e.target.checked)}
                className="sr-only peer"
              />
              <div className="w-11 h-6 bg-secondary-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-primary-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-secondary-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-primary-600"></div>
            </label>
          </div>

          {/* System Preference */}
          <div className="flex items-center justify-between p-3 sm:p-4 border border-secondary-200 rounded-lg">
            <div>
              <h4 className="font-medium text-secondary-900 text-sm sm:text-base">
                {t("animations.settings.systemPreference.title", "Respect System Preference")}
              </h4>
              <p className="text-xs sm:text-sm text-secondary-600 mt-1">
                {t(
                  "animations.settings.systemPreference.description",
                  "Враховувати системні налаштування зменшення анімацій (prefers-reduced-motion)"
                )}
              </p>
            </div>
            <label className="relative inline-flex items-center cursor-pointer touch-manipulation">
              <input
                type="checkbox"
                checked={settings.respectSystemPreference}
                onChange={(e) => updateSetting("respectSystemPreference", e.target.checked)}
                className="sr-only peer"
              />
              <div className="w-11 h-6 bg-secondary-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-primary-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-secondary-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-primary-600"></div>
            </label>
          </div>

          {/* Detailed Settings */}
          <div className="space-y-3 sm:space-y-4">
            <h4 className="font-medium text-secondary-900 border-b border-secondary-200 pb-2 text-sm sm:text-base">
              {t("animations.settings.detailed.title", "Detailed Settings")}
            </h4>
            
            {settingItems.map((item) => (
              <div
                key={item.key}
                className={`flex items-center justify-between p-3 rounded-lg border transition-colors ${
                  settings.enabled
                    ? "border-secondary-200 bg-white"
                    : "border-secondary-100 bg-secondary-50"
                }`}
              >
                <div className={`flex-1 mr-3 ${settings.enabled ? "" : "opacity-50"}`}>
                  <h5 className="font-medium text-secondary-900 text-sm sm:text-base">{item.title}</h5>
                  <p className="text-xs sm:text-sm text-secondary-600 mt-1">{item.description}</p>
                </div>
                <label className="relative inline-flex items-center cursor-pointer touch-manipulation">
                  <input
                    type="checkbox"
                    checked={settings[item.key]}
                    onChange={(e) => updateSetting(item.key, e.target.checked)}
                    disabled={!settings.enabled}
                    className="sr-only peer"
                  />
                  <div className={`w-11 h-6 bg-secondary-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-primary-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-secondary-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-primary-600 ${
                    !settings.enabled ? "opacity-50 cursor-not-allowed" : ""
                  }`}></div>
                </label>
              </div>
            ))}
          </div>
        </div>

        {/* Footer */}
        <div className="px-4 sm:px-6 py-3 sm:py-4 border-t border-secondary-200 flex flex-col sm:flex-row justify-between gap-3 sm:gap-0">
          <button
            onClick={resetToDefaults}
            className="px-3 sm:px-4 py-2 text-secondary-600 hover:text-secondary-800 transition-colors touch-manipulation text-sm sm:text-base"
          >
            {t("animations.settings.resetToDefaults", "Reset to Defaults")}
          </button>
          <button
            onClick={onClose}
            className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition-colors touch-manipulation text-sm sm:text-base font-medium"
          >
            {t("common.close", "Close")}
          </button>
        </div>
      </div>
    </div>
  );

  return ReactDOM.createPortal(modalContent, document.body);
};

export default AnimationSettingsPanel; 