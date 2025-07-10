import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
} from "react";

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
  refreshToken: () => Promise<boolean>;
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
  refreshToken: async () => false,
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

          // Зберігаємо access_token як sessionId для WebSocket
          localStorage.setItem("sessionId", data.tokens.access_token);
          localStorage.setItem("accessToken", data.tokens.access_token);
          localStorage.setItem("refreshToken", data.tokens.refresh_token);
          return true;
        } else {
          throw new Error(data.message || "Login failed");
        }
      } catch (error) {
        console.error("Помилка входу:", error);
        setAuth((prev) => ({
          ...prev,
          error:
            error instanceof Error ? error.message : "Невідома помилка входу",
          isLoading: false,
        }));
        return false;
      }
    },
    [],
  );

  // Функція для очищення всіх даних авторизації
  const clearAuthData = useCallback(() => {
    console.log("🧹 Clearing all auth data");
    setAuth(initialAuthState);
    localStorage.removeItem("sessionId");
    localStorage.removeItem("accessToken");
    localStorage.removeItem("refreshToken");
  }, []);

  // Функція виходу
  const logout = useCallback(async (): Promise<void> => {
    setAuth((prev) => ({ ...prev, isLoading: true }));
    try {
      const sessionId = localStorage.getItem("sessionId");
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
      });

      if (!response.ok) {
        console.warn("Помилка при виході з системи", response.status);
      }

      // Очищення стану в будь-якому випадку
      clearAuthData();
    } catch (error) {
      console.error("Помилка при виході:", error);
      // Очищаємо стан навіть при помилці
      clearAuthData();
    }
  }, []);

  const refreshToken = useCallback(async (): Promise<boolean> => {
    console.log("🔄 Attempting token refresh");
    const refresh = localStorage.getItem("refreshToken");
    if (!refresh) {
      console.log("❌ No refresh token available");
      return false;
    }
    try {
      console.log(
        "📤 Sending refresh request with token:",
        refresh.substring(0, 20) + "...",
      );
      const response = await fetch("/api/auth/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refresh }),
      });
      console.log("📥 Refresh response status:", response.status);
      if (!response.ok) {
        console.log("❌ Refresh failed with status:", response.status);
        return false;
      }
      const data = await response.json();
      console.log("✅ Refresh successful, new access token received");
      if (data.tokens?.access_token) {
        localStorage.setItem("accessToken", data.tokens.access_token);
        localStorage.setItem("sessionId", data.tokens.access_token);
        setAuth((prev) => ({ ...prev, sessionId: data.tokens.access_token }));
        return true;
      }
      console.log("❌ No new access token in response");
      return false;
    } catch (error) {
      console.error("❌ Error during token refresh:", error);
      return false;
    }
  }, []);

  // Валідація сесії
  const validateSession = useCallback(async (): Promise<boolean> => {
    console.log("🔍 Starting session validation");
    const sessionId = localStorage.getItem("sessionId");
    if (!sessionId) {
      console.log("❌ No sessionId in localStorage");
      return false;
    }
    try {
      console.log(
        "📤 Sending validation request with token:",
        sessionId.substring(0, 20) + "...",
      );
      const response = await fetch("/api/auth/validate", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${sessionId}`,
        },
      });
      console.log("📥 Validation response status:", response.status);
      if (!response.ok) {
        console.log("⚠️ Validation failed with status:", response.status);
        if (response.status === 401) {
          console.log("🔄 Validation failed with 401, attempting refresh");
          const refreshed = await refreshToken();
          if (refreshed) {
            console.log("✅ Refresh successful, retrying validation");
            return await validateSession();
          } else {
            console.log("❌ Refresh failed, validation unsuccessful");
          }
        }
        // Очищаємо токени при невдалій валідації
        clearAuthData();
        return false;
      }
      const data = await response.json();
      console.log("✅ Validation successful");
      if (data.valid && data.user) {
        setAuth((prev) => ({
          ...prev,
          isAuthenticated: true,
          isLoading: false,
          user: data.user,
          error: null,
        }));
        return true;
      }
      // Якщо валідація не пройшла
      clearAuthData();
      return false;
    } catch (error) {
      console.error("❌ Error validating session:", error);
      // Очищаємо всі дані при помилці валідації
      clearAuthData();
      return false;
    }
  }, [refreshToken]);

  // Перевірка сесії при завантаженні (тільки один раз)
  useEffect(() => {
    const checkSession = async () => {
      const sessionId = localStorage.getItem("sessionId");
      if (sessionId) {
        console.log("🔍 Initial session check on mount");
        const isValid = await validateSession();
        if (!isValid) {
          console.log("❌ Session validation failed, clearing auth data");
          clearAuthData();
        }
      } else {
        console.log("❌ No session found on mount, staying logged out");
        // Очищаємо будь-які залишкові дані
        clearAuthData();
      }
    };

    checkSession();
  }, []); // Порожній масив залежностей - виконується тільки при монтуванні

  // Очищення помилки
  const clearError = useCallback(() => {
    setAuth((prev) => ({ ...prev, error: null }));
  }, []);

  return (
    <AuthContext.Provider
      value={{
        auth,
        login,
        logout,
        validateSession,
        clearError,
        refreshToken,
      }}
    >
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
