import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
} from "react";
import { logDevError, logDevWarning } from "../utils/devtools-filter";

// Типи даних для авторизації
export interface AuthUser {
  id: string;
  username: string;
  role: string;
  permissions: string[];
  sessionId: string;
  loginTime: string;
}

export interface AuthState {
  isAuthenticated: boolean;
  user: AuthUser | null;
  sessionId: string | null;
  error: string | null;
  isLoading: boolean;
}

export interface AuthContextType {
  auth: AuthState;
  login: (username: string, password: string) => Promise<boolean>;
  logout: () => Promise<void>;
  validateSession: () => Promise<boolean>;
  clearError: () => void;
  refreshToken: () => Promise<string | null>;
  refreshAccessToken: () => Promise<string | null>;
}

// Ініціалізація контексту з початковими значеннями
const initialAuthState: AuthState = {
  isAuthenticated: false,
  user: null,
  sessionId: null,
  error: null,
  isLoading: false,
};

const AuthContext = createContext<AuthContextType>({
  auth: initialAuthState,
  login: async () => false,
  logout: async () => {},
  validateSession: async () => false,
  clearError: () => {},
  refreshToken: async () => null,
  refreshAccessToken: async () => null,
});

// Провайдер контексту авторизації
export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const [auth, setAuth] = useState<AuthState>(initialAuthState);

  // Функція входу з логіном та паролем
  const login = useCallback(
    async (username: string, password: string): Promise<boolean> => {
      try {
        setAuth((prev) => ({ ...prev, isLoading: true, error: null }));
        const response = await fetch("/api/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username, password }),
          credentials: "include",
        });
        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(errorData.detail || "Authentication failed");
        }
        const data = await response.json();
        if (data.success && data.user && data.tokens) {
          // Створюємо користувача з правильними даними
          const userWithSession = {
            id: data.user.id,
            username: data.user.username,
            role: data.user.role,
            permissions: data.user.permissions,
            sessionId: data.tokens.access_token, // Використовуємо access_token як sessionId
            loginTime: new Date().toISOString(),
          };

          setAuth({
            isAuthenticated: true,
            user: userWithSession,
            sessionId: data.tokens.access_token,
            error: null,
            isLoading: false,
          });
          // No persistent storage: access token живе лише в пам'яті
          return true;
        } else {
          throw new Error(data.message || "Login failed");
        }
      } catch (error) {
        // Більш м'яка обробка мережевих помилок
        if (error instanceof TypeError && error.message.includes("NetworkError")) {
          logDevWarning("⚠️ Мережева помилка при вході:", error.message);
          setAuth((prev) => ({
            ...prev,
            error: "Проблема з мережею. Перевірте підключення до інтернету.",
            isLoading: false,
          }));
        } else {
          logDevError("❌ Помилка входу:", error);
          setAuth((prev) => ({
            ...prev,
            error:
              error instanceof Error ? error.message : "Невідома помилка входу",
            isLoading: false,
          }));
        }
        return false;
      }
    },
    [],
  );

  // Функція для очищення всіх даних авторизації
  const clearAuthData = useCallback(() => {
    setAuth(initialAuthState);
  }, []);

  // Функція виходу
  const logout = useCallback(async (): Promise<void> => {
    setAuth((prev) => ({ ...prev, isLoading: true }));
    try {
      const sessionId = auth.sessionId;
      if (!sessionId) {
        // Якщо немає сесії, просто очищаємо стан
        clearAuthData();
        return;
      }

      // Запит до API для завершення сесії
      const response = await fetch("/api/auth/logout", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${sessionId}`,
        },
        body: JSON.stringify({ sessionId }),
        credentials: "include", // гарантуємо надсилання httpOnly кукі для видалення на сервері
      });

      if (!response.ok) {
        logDevWarning("Помилка при виході з системи", response.status);
      }

      // Очищення стану в будь-якому випадку
      clearAuthData();
    } catch (error) {
      logDevError("Помилка при виході:", error);
      // Очищаємо стан навіть при помилці
      clearAuthData();
    }
  }, [auth.sessionId, clearAuthData]);

  // Функція оновлення токена (використовується при bootstrap і точково при необхідності)
  // Повертає новий access_token або null
  const refreshToken = useCallback(async (): Promise<string | null> => {
    const csrf = (document.cookie || "")
      .split(";")
      .map((s) => s.trim())
      .find((c) => c.startsWith("csrf_token="))
      ?.split("=")[1];
    if (!csrf) return null;
    try {
      const response = await fetch("/api/auth/refresh", {
        method: "POST",
        headers: { "X-CSRF-Token": csrf },
        credentials: "include",
      });
      if (!response.ok) return null;
      const data = await response.json();
      const newAccess = data?.tokens?.access_token;
      if (!newAccess) return null;
      setAuth((prev) => ({
        ...prev,
        isAuthenticated: true,
        sessionId: newAccess,
        user: prev.user ? { ...prev.user, sessionId: newAccess } : prev.user,
        isLoading: false,
      }));
      return newAccess;
    } catch (e) {
      return null;
    }
  }, []);

  // Валідація сесії
  const validateSession = useCallback(async (): Promise<boolean> => {
    const sessionId = auth.sessionId;
    if (!sessionId) {
      return false;
    }
    try {
      const response = await fetch("/api/auth/validate", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${sessionId}`,
        },
      });
      
      if (!response.ok) {
        if (response.status === 401) {
          // Токен прострочений або невалідний - повний logout
          logDevWarning("⚠️ Токен прострочений або невалідний, виконую logout");
          await logout();
          return false;
        } else if (response.status === 500) {
          // Помилка сервера - можливо після перезапуску
          logDevWarning("⚠️ Server error during session validation - server may have restarted");
          // Виконуємо logout при помилці сервера
          await logout();
          return false;
        }
        // Очищаємо токени при невдалій валідації
        await logout();
        return false;
      }
      
      const data = await response.json();
      if (data.valid && data.user) {
        // Додаємо sessionId до user та стану авторизації
        const userWithSession = {
          ...data.user,
          sessionId, // гарантуємо наявність sessionId у користувача
        };

        setAuth((prev) => ({
          ...prev,
          isAuthenticated: true,
          isLoading: false,
          user: userWithSession,
          sessionId, // зберігаємо токен у стані
          error: null,
        }));
        return true;
      }
      // Якщо валідація не пройшла
      await logout();
      return false;
    } catch (error) {
      // М'яка обробка мережевих помилок
      if (error instanceof TypeError && error.message.includes("NetworkError")) {
        logDevWarning("⚠️ Мережева помилка при валідації сесії");
        // При мережевих помилках також виконуємо logout для безпеки
        await logout();
        return false;
      }
      logDevError("❌ Помилка валідації сесії:", error);
      await logout();
      return false;
    }
  }, [auth.sessionId]); // Видаляємо залежність від refreshToken

  // Ініціалізація: намагаємось відновити сесію через httpOnly refresh cookie
  useEffect(() => {
    const bootstrap = async () => {
      setAuth((prev) => ({ ...prev, isLoading: true }));
      const newToken = await refreshToken();
      if (newToken) {
        await validateSession();
      } else {
        setAuth((prev) => ({ ...prev, isLoading: false }));
      }
    };
    bootstrap();
  }, []);

  // Перевірка сесії при зміні токена (без редиректів; роутінг вирішує ProtectedRoute)
  useEffect(() => {
    const verify = async () => {
      const sessionId = auth.sessionId;
      if (sessionId) {
        await validateSession();
      } else {
        clearAuthData();
      }
    };
    verify();
  }, [auth.sessionId]);

  // Очищення помилки
  const clearError = useCallback(() => {
    setAuth((prev) => ({ ...prev, error: null }));
  }, []);

  // Функція для оновлення access_token через refresh_token (БЛОКОВАНА)
  // Залишена тільки для ручного виклику через UI
  const refreshAccessToken = async (): Promise<string | null> => {
    const token = await refreshToken();
    return token;
  };

  return (
    <AuthContext.Provider value={{
      auth,
      login,
      logout,
      validateSession,
      clearError,
      refreshToken,
      refreshAccessToken
    }}>
      {children}
    </AuthContext.Provider>
  );
};

// Хук для використання контексту авторизації
export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth має використовуватися в межах AuthProvider");
  }
  return context;
};
