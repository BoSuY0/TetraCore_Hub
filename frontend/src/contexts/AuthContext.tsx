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
  firstName: string;
  lastName?: string;
  photoUrl?: string;
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
});

// Провайдер контексту авторизації
export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const [auth, setAuth] = useState<AuthState>(initialAuthState);

  // Функція входу з логіном та паролем
  const login = useCallback(async (username: string, password: string): Promise<boolean> => {
    try {
      setAuth((prev) => ({ ...prev, isLoading: true, error: null }));
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || 'Authentication failed');
      }
      const data = await response.json();
      if (data.success && data.session) {
        setAuth({
          isAuthenticated: true,
          user: data.session.user,
          sessionId: data.session.sessionId,
          error: null,
          isLoading: false,
        });
        localStorage.setItem('sessionId', data.session.sessionId);
        return true;
      } else {
        throw new Error(data.message || 'Login failed');
      }
    } catch (error) {
      console.error('Помилка входу:', error);
      setAuth((prev) => ({ 
        ...prev, 
        error: error instanceof Error ? error.message : 'Невідома помилка входу',
        isLoading: false 
      }));
      return false;
    }
  }, []);

  // Функція виходу
  const logout = useCallback(async (): Promise<void> => {
    setAuth((prev) => ({ ...prev, isLoading: true }));
    try {
      const sessionId = localStorage.getItem("sessionId");
      if (!sessionId) {
        // Якщо немає сесії, просто очищаємо стан
        setAuth(initialAuthState);
        localStorage.removeItem('sessionId');
        return;
      }

      // Запит до API для завершення сесії
      const response = await fetch('/api/auth/logout', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ sessionId }),
      });

      if (!response.ok) {
        console.warn('Помилка при виході з системи', response.status);
      }

      // Очищення стану в будь-якому випадку
      setAuth(initialAuthState);
      localStorage.removeItem("sessionId");
    } catch (error) {
      console.error("Помилка при виході:", error);
      // Очищаємо стан навіть при помилці
      setAuth(initialAuthState);
      localStorage.removeItem("sessionId");
    }
  }, []);

  // Валідація сесії
  const validateSession = useCallback(async (): Promise<boolean> => {
    const sessionId = localStorage.getItem('sessionId');
    console.log('🔍 validateSession called', { 
      sessionId: sessionId ? sessionId.substring(0, 8) + '...' : null, 
      hasLocalStorageSessionId: !!sessionId 
    });

    if (!sessionId) {
      console.log('❌ No sessionId found, clearing auth state');
      setAuth(initialAuthState);
      return false;
    }

    setAuth((prev) => ({ ...prev, isLoading: true }));
    try {
      console.log('📤 Sending validation request for sessionId:', sessionId.substring(0, 8) + '...');
      const response = await fetch('/api/auth/validate', {
        method: 'POST',
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ sessionId }),
      });

      if (!response.ok) {
        console.log(
          "❌ Validation failed with status:",
          response.status,
          response.statusText,
        );
        setAuth(initialAuthState);
        localStorage.removeItem('sessionId');
        // Перенаправлення на логін при 401
        if (response.status === 401 && window.location.pathname !== '/') {
          console.log('🔄 Redirecting to login due to invalid session');
          window.location.href = '/';
        }
        return false;
      }

      const data = await response.json();
      if (!data.valid) {
        console.log("❌ Session marked as invalid by server");
        setAuth(initialAuthState);
        localStorage.removeItem('sessionId');
        // Перенаправлення на логін при невалідній сесії
        if (window.location.pathname !== '/') {
          console.log('🔄 Redirecting to login due to invalid session');
          window.location.href = '/';
        }
        return false;
      }

      console.log(
        "✅ Session validation successful for user:",
        data.user?.username,
      );
      // Оновлення стану при валідній сесії
      setAuth({
        isAuthenticated: true,
        user: data.user,
        sessionId,
        error: null,
        isLoading: false,
      });
      return true;
    } catch (error) {
      console.error("Помилка валідації сесії:", error);
      setAuth(initialAuthState);
      localStorage.removeItem("sessionId");
      return false;
    }
  }, []);

  // Очищення помилки
  const clearError = useCallback(() => {
    setAuth((prev) => ({ ...prev, error: null }));
  }, []);

  // Перевірка сесії при завантаженні (тільки один раз)
  useEffect(() => {
    const checkSession = async () => {
      const sessionId = localStorage.getItem('sessionId');
      if (sessionId) {
        console.log('🔍 Initial session check on mount');
        await validateSession();
      } else {
        console.log('❌ No session found on mount, staying logged out');
      }
    };
    
    checkSession();
  }, []); // Порожній масив залежностей - виконується тільки при монтуванні

  return (
    <AuthContext.Provider
      value={{
        auth,
        login,
        logout,
        validateSession,
        clearError,
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
