import { useState, useEffect, useRef, useCallback } from "react";

/**
 * Hook для debounce значень - затримує оновлення значення на вказаний час
 * @param value - значення для debounce
 * @param delay - затримка в мілісекундах
 * @returns debounced значення
 */
export function useDebounce<T>(value: T, delay: number): T {
  const [debouncedValue, setDebouncedValue] = useState<T>(value);

  useEffect(() => {
    // Встановлюємо таймер для оновлення debounced значення
    const timer = setTimeout(() => {
      setDebouncedValue(value);
    }, delay);

    // Очищаємо таймер якщо значення змінюється або компонент unmount
    return () => {
      clearTimeout(timer);
    };
  }, [value, delay]);

  return debouncedValue;
}

/**
 * Hook для debounce callback функцій
 * @param callback - функція для виклику
 * @param delay - затримка в мілісекундах
 * @returns debounced функція
 */
export function useDebouncedCallback<T extends (...args: any[]) => any>(
  callback: T,
  delay: number,
): (...args: Parameters<T>) => void {
  const timerRef = useRef<NodeJS.Timeout | null>(null);
  const callbackRef = useRef(callback);

  // Оновлюємо callback ref при зміні callback
  useEffect(() => {
    callbackRef.current = callback;
  }, [callback]);

  // Очищаємо таймер при unmount або зміні delay
  useEffect(() => {
    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [delay]);

  const debouncedFunction = useCallback(
    (...args: Parameters<T>) => {
      // Очищаємо попередній таймер
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }

      // Встановлюємо новий таймер
      timerRef.current = setTimeout(() => {
        callbackRef.current(...args);
        timerRef.current = null;
      }, delay);
    },
    [delay],
  );

  return debouncedFunction;
}

export default useDebounce;
