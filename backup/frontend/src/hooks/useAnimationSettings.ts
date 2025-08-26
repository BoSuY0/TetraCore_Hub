import { useState, useEffect, useMemo } from 'react';

interface AnimationSettings {
  enabled: boolean;
  respectSystemPreference: boolean;
  taskAnimations: boolean;
  statusAnimations: boolean;
  priorityAnimations: boolean;
  hoverEffects: boolean;
  tableAnimations: boolean;
}

interface UseAnimationSettingsReturn {
  settings: AnimationSettings;
  isAnimationEnabled: boolean;
  updateSetting: <K extends keyof AnimationSettings>(key: K, value: AnimationSettings[K]) => void;
  toggleAnimations: () => void;
  resetToDefaults: () => void;
  getAnimationClass: (baseClass: string, animationClass?: string) => string;
}

const DEFAULT_SETTINGS: AnimationSettings = {
  enabled: true,
  respectSystemPreference: true,
  taskAnimations: true,
  statusAnimations: true,
  priorityAnimations: true,
  hoverEffects: true,
  tableAnimations: true,
};

const STORAGE_KEY = 'tetra-core-animation-settings';

/**
 * Hook для керування налаштуваннями анімацій
 * Зберігає налаштування в localStorage та враховує системні преференції
 */
export function useAnimationSettings(): UseAnimationSettingsReturn {
  const [settings, setSettings] = useState<AnimationSettings>(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        return { ...DEFAULT_SETTINGS, ...JSON.parse(stored) };
      }
    } catch (error) {
      console.warn('Failed to load animation settings from localStorage:', error);
    }
    return DEFAULT_SETTINGS;
  });

  // Перевіряємо системні налаштування prefers-reduced-motion
  const systemPrefersReducedMotion = useMemo(() => {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }, []);

  // Визначаємо чи анімації повинні бути увімкнені
  const isAnimationEnabled = useMemo(() => {
    if (!settings.enabled) return false;
    if (settings.respectSystemPreference && systemPrefersReducedMotion) return false;
    return true;
  }, [settings.enabled, settings.respectSystemPreference, systemPrefersReducedMotion]);

  // Зберігаємо налаштування в localStorage при зміні
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
    } catch (error) {
      console.warn('Failed to save animation settings to localStorage:', error);
    }
  }, [settings]);

  // Додаємо слухач для зміни системних налаштувань
  useEffect(() => {
    const mediaQuery = window.matchMedia('(prefers-reduced-motion: reduce)');

    const handleChange = () => {
      // Примусово перерендерюємо компонент при зміні системних налаштувань
      setSettings(prev => ({ ...prev }));
    };

    mediaQuery.addEventListener('change', handleChange);
    return () => mediaQuery.removeEventListener('change', handleChange);
  }, []);

  // Функція для оновлення окремого налаштування
  const updateSetting = <K extends keyof AnimationSettings>(
    key: K,
    value: AnimationSettings[K]
  ) => {
    setSettings(prev => ({
      ...prev,
      [key]: value
    }));
  };

  // Функція для переключення всіх анімацій
  const toggleAnimations = () => {
    setSettings(prev => ({
      ...prev,
      enabled: !prev.enabled
    }));
  };

  // Функція для скидання до дефолтних налаштувань
  const resetToDefaults = () => {
    setSettings(DEFAULT_SETTINGS);
  };

  // Функція для отримання CSS класу з урахуванням налаштувань анімацій
  const getAnimationClass = (baseClass: string, animationClass?: string): string => {
    if (!isAnimationEnabled || !animationClass) {
      return baseClass;
    }

    // Перевіряємо специфічні налаштування для різних типів анімацій
    if (animationClass.includes('task-') && !settings.taskAnimations) {
      return baseClass;
    }
    if (animationClass.includes('status-') && !settings.statusAnimations) {
      return baseClass;
    }
    if (animationClass.includes('priority-') && !settings.priorityAnimations) {
      return baseClass;
    }
    if (animationClass.includes('hover') && !settings.hoverEffects) {
      return baseClass;
    }
    if (animationClass.includes('table-') && !settings.tableAnimations) {
      return baseClass;
    }

    return `${baseClass} ${animationClass}`;
  };

  return {
    settings,
    isAnimationEnabled,
    updateSetting,
    toggleAnimations,
    resetToDefaults,
    getAnimationClass,
  };
}

export default useAnimationSettings;
