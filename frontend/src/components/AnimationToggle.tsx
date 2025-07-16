import React, { useState } from "react";
import { useAnimationSettings } from "../hooks/useAnimationSettings";
import { useI18n } from "../contexts/I18nContext";
import AnimationSettingsPanel from "./AnimationSettingsPanel";

interface AnimationToggleProps {
  className?: string;
  showLabel?: boolean;
  size?: "sm" | "md" | "lg";
  variant?: "switch" | "button";
}

const AnimationToggle: React.FC<AnimationToggleProps> = ({
  className = "",
  showLabel = true,
  size = "md",
  variant = "switch",
}) => {
  const { t } = useI18n();
  const { settings, isAnimationEnabled, toggleAnimations, updateSetting } =
    useAnimationSettings();
  const [isSettingsPanelOpen, setIsSettingsPanelOpen] = useState(false);

  const sizeClasses = {
    sm: "w-8 h-4",
    md: "w-10 h-5",
    lg: "w-12 h-6",
  };

  const thumbSizeClasses = {
    sm: "w-3 h-3",
    md: "w-4 h-4",
    lg: "w-5 h-5",
  };

  const openSettingsPanel = () => {
    setIsSettingsPanelOpen(true);
  };

  const closeSettingsPanel = () => {
    setIsSettingsPanelOpen(false);
  };

  if (variant === "button") {
    return (
      <>
        <button
          onClick={toggleAnimations}
          className={`
            inline-flex items-center px-3 py-2 border border-secondary-300
            rounded-md shadow-sm text-sm font-medium
            ${
              isAnimationEnabled
                ? "bg-primary-50 text-primary-700 border-primary-300"
                : "bg-white text-secondary-700 hover:bg-secondary-50"
            }
            transition-colors duration-200 focus:outline-none focus:ring-2
            focus:ring-primary-500 focus:border-primary-500
            ${className}
          `}
          title={
            isAnimationEnabled
              ? t("animations.disable")
              : t("animations.enable")
          }
        >
          <svg
            className={`w-4 h-4 ${showLabel ? "mr-2" : ""}`}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            {isAnimationEnabled ? (
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M5.636 5.636l12.728 12.728m0-12.728L5.636 18.364M12 2l3.09 6.26L22 9.27l-5 4.87L18.18 22 12 18.77 5.82 22 7 14.14 2 9.27l6.91-1.01L12 2z"
              />
            ) : (
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z"
              />
            )}
          </svg>
          {showLabel && (
            <span>
              {isAnimationEnabled
                ? t("animations.enabled")
                : t("animations.disabled")}
            </span>
          )}
        </button>
        <AnimationSettingsPanel
          isOpen={isSettingsPanelOpen}
          onClose={closeSettingsPanel}
        />
      </>
    );
  }

  return (
    <>
      <div className={`flex items-center ${className}`}>
        {showLabel && (
          <label
            htmlFor="animation-toggle"
            className="text-sm font-medium text-secondary-700 mr-3 cursor-pointer"
          >
            {t("animations.label")}
          </label>
        )}

        <div className="flex items-center">
          <button
            id="animation-toggle"
            type="button"
            className={`
              relative inline-flex shrink-0 cursor-pointer rounded-full border-2
              border-transparent transition-colors duration-200 ease-in-out
              focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2
              ${sizeClasses[size]}
              ${
                isAnimationEnabled
                  ? "bg-primary-600"
                  : "bg-secondary-200"
              }
            `}
            role="switch"
            aria-checked={isAnimationEnabled}
            aria-labelledby="animation-toggle-label"
            onClick={toggleAnimations}
            title={
              isAnimationEnabled
                ? t("animations.disable")
                : t("animations.enable")
            }
          >
            <span
              aria-hidden="true"
              className={`
                pointer-events-none inline-block rounded-full bg-white shadow
                transform ring-0 transition duration-200 ease-in-out
                ${thumbSizeClasses[size]}
                ${
                  isAnimationEnabled
                    ? size === "sm"
                      ? "translate-x-4"
                      : size === "md"
                      ? "translate-x-5"
                      : "translate-x-6"
                    : "translate-x-0"
                }
              `}
            >
              <span
                className={`
                  absolute inset-0 h-full w-full flex items-center justify-center
                  transition-opacity duration-200 ease-in-out
                  ${
                    isAnimationEnabled
                      ? "opacity-0 ease-out duration-100"
                      : "opacity-100 ease-in duration-200"
                  }
                `}
                aria-hidden="true"
              >
                <svg
                  className={`w-3 h-3 text-secondary-400`}
                  fill="none"
                  viewBox="0 0 12 12"
                >
                  <path
                    d="M4 8l2-2m0 0l2-2M6 6L4 4m2 2l2 2"
                    stroke="currentColor"
                    strokeWidth={2}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </span>
              <span
                className={`
                  absolute inset-0 h-full w-full flex items-center justify-center
                  transition-opacity duration-200 ease-in-out
                  ${
                    isAnimationEnabled
                      ? "opacity-100 ease-in duration-200"
                      : "opacity-0 ease-out duration-100"
                  }
                `}
                aria-hidden="true"
              >
                <svg
                  className={`w-3 h-3 text-primary-600`}
                  fill="currentColor"
                  viewBox="0 0 12 12"
                >
                  <path d="M3.707 5.293a1 1 0 00-1.414 1.414l1.414-1.414zM5 8l-.707.707a1 1 0 001.414 0L5 8zm4.707-3.293a1 1 0 00-1.414-1.414l1.414 1.414zm-7.414 2l2 2 1.414-1.414-2-2-1.414 1.414zm3.414 2l4-4-1.414-1.414-4 4 1.414 1.414z" />
                </svg>
              </span>
            </span>
          </button>

          {/* System preference indicator */}
          {settings.respectSystemPreference && (
            <div className="ml-2 text-xs text-secondary-500 flex items-center">
              <svg
                className="w-3 h-3 mr-1"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"
                />
              </svg>
              <span title={t("animations.systemPreference")}>
                {t("animations.system")}
              </span>
            </div>
          )}
        </div>

        {/* Additional settings button */}
        <div className="ml-2">
          <button
            type="button"
            className="text-secondary-400 hover:text-secondary-600 transition-colors p-1 touch-manipulation"
            onClick={openSettingsPanel}
            title={t("animations.moreSettings")}
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"
              />
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
              />
            </svg>
          </button>
        </div>
      </div>

      {/* Settings Panel */}
      <AnimationSettingsPanel
        isOpen={isSettingsPanelOpen}
        onClose={closeSettingsPanel}
      />
    </>
  );
};

export default AnimationToggle;
