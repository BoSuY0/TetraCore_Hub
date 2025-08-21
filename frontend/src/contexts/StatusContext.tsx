import React, {
  createContext,
  useContext,
  useReducer,
  useEffect,
  useRef,
  useCallback,
} from "react";
import {
  StreamHubHealth,
  StreamHubMetrics,
  Client,
  TaskQueueStats,
  SystemAlert,
  DashboardData,
} from "../types/api";
import config, { buildUrl, buildWsUrl } from "../config";
import { useAuth } from "./AuthContext";

interface StatusState {
  health: StreamHubHealth | null;
  metrics: StreamHubMetrics | null;
  clients: Client[];
  taskStats: TaskQueueStats | null;
  alerts: SystemAlert[];
  isLoading: boolean;
  error: string | null;
  lastUpdated: Date | null;
  connectionStatus: "connected" | "disconnected" | "connecting" | "error";
  websocketError: WebSocketError | null;
  reconnectInfo: ReconnectInfo;
}

interface WebSocketError {
  type:
    | "connection"
    | "authentication"
    | "registration"
    | "network"
    | "timeout"
    | "unknown";
  code: number;
  reason: string;
  message: string;
  timestamp: Date;
  isRetryable: boolean;
}

interface ReconnectInfo {
  attempts: number;
  maxAttempts: number;
  nextAttemptIn: number;
  lastAttemptAt: Date | null;
  totalFailures: number;
}

type StatusAction =
  | { type: "SET_LOADING"; payload: boolean }
  | { type: "SET_ERROR"; payload: string | null }
  | { type: "SET_HEALTH"; payload: StreamHubHealth }
  | { type: "SET_METRICS"; payload: StreamHubMetrics }
  | { type: "SET_CLIENTS"; payload: Client[] }
  | { type: "SET_TASK_STATS"; payload: TaskQueueStats }
  | { type: "ADD_ALERT"; payload: SystemAlert }
  | { type: "REMOVE_ALERT"; payload: string }
  | {
      type: "SET_CONNECTION_STATUS";
      payload: "connected" | "disconnected" | "connecting" | "error";
    }
  | { type: "UPDATE_LAST_UPDATED" }
  | { type: "SET_WEBSOCKET_ERROR"; payload: WebSocketError | null }
  | { type: "UPDATE_RECONNECT_INFO"; payload: Partial<ReconnectInfo> }
  | { type: "RESET_RECONNECT_INFO" };

const initialState: StatusState = {
  health: null,
  metrics: null,
  clients: [],
  taskStats: null,
  alerts: [],
  isLoading: false,
  error: null,
  lastUpdated: null,
  connectionStatus: "connecting",
  websocketError: null,
  reconnectInfo: {
    attempts: 0,
    maxAttempts: 20, // Збільшено з 10 до 20 для кращої стійкості
    nextAttemptIn: 0,
    lastAttemptAt: null,
    totalFailures: 0,
  },
};

function statusReducer(state: StatusState, action: StatusAction): StatusState {
  switch (action.type) {
    case "SET_LOADING":
      return { ...state, isLoading: action.payload };
    case "SET_ERROR":
      return { ...state, error: action.payload, isLoading: false };
    case "SET_HEALTH":
      return {
        ...state,
        health: action.payload,
        error: null,
        lastUpdated: new Date(),
      };
    case "SET_METRICS":
      return {
        ...state,
        metrics: action.payload,
        error: null,
        lastUpdated: new Date(),
      };
    case "SET_CLIENTS":
      return {
        ...state,
        clients: action.payload,
        error: null,
        lastUpdated: new Date(),
      };
    case "SET_TASK_STATS":
      return {
        ...state,
        taskStats: action.payload,
        error: null,
        lastUpdated: new Date(),
      };
    case "ADD_ALERT":
      return {
        ...state,
        alerts: [action.payload, ...state.alerts.slice(0, 49)], // Keep max 50 alerts
      };
    case "REMOVE_ALERT":
      return {
        ...state,
        alerts: state.alerts.filter((alert) => alert.id !== action.payload),
      };
    case "SET_CONNECTION_STATUS":
      return { ...state, connectionStatus: action.payload };
    case "UPDATE_LAST_UPDATED":
      return { ...state, lastUpdated: new Date() };
    case "SET_WEBSOCKET_ERROR":
      return { ...state, websocketError: action.payload };
    case "UPDATE_RECONNECT_INFO":
      return {
        ...state,
        reconnectInfo: { ...state.reconnectInfo, ...action.payload },
      };
    case "RESET_RECONNECT_INFO":
      return {
        ...state,
        reconnectInfo: {
          attempts: 0,
          maxAttempts: 5,
          nextAttemptIn: 0,
          lastAttemptAt: null,
          totalFailures: 0,
        },
      };
    default:
      return state;
  }
}

interface StatusContextType {
  state: StatusState;
  dispatch: React.Dispatch<StatusAction>;
  refreshData: () => Promise<void>;
  connectWebSocket: () => void;
  disconnectWebSocket: () => void;
  resetReconnectionAttempts: () => void;
}

const StatusContext = createContext<StatusContextType | undefined>(undefined);

export const useStatus = () => {
  const context = useContext(StatusContext);
  if (context === undefined) {
    throw new Error("useStatus must be used within a StatusProvider");
  }
  return context;
};

interface StatusProviderProps {
  children: React.ReactNode;
  apiBaseUrl?: string;
  refreshInterval?: number;
}

export const StatusProvider: React.FC<StatusProviderProps> = ({
  children,
  apiBaseUrl = config.api.baseUrl,
  refreshInterval = 15000, // Збільшено з 10 до 15 секунд для зменшення навантаження
}) => {
  const [state, dispatch] = useReducer(statusReducer, initialState);
  const [socket, setSocket] = React.useState<WebSocket | null>(null);
  const [reconnectTimeout, setReconnectTimeout] =
    React.useState<NodeJS.Timeout | null>(null);
  const [heartbeatInterval, setHeartbeatInterval] =
    React.useState<NodeJS.Timeout | null>(null);
  // Using a ref instead of state for the connection timeout ensures we always have
  // the latest timeout ID inside asynchronous WebSocket callbacks without relying
  // on React's asynchronous state updates.
  const connectionTimeoutRef = React.useRef<NodeJS.Timeout | null>(null);
  const { auth: authState } = useAuth();

  // Додаємо рефи для відстеження стану підключення
  const isConnectingRef = useRef(false);
  const mountedRef = useRef(true);
  const lastAuthStateRef = useRef(authState.isAuthenticated);
  const dataRefreshIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const sessionSyncAttemptsRef = useRef(0);
  const maxSessionSyncAttempts = 3;
  
  // Додаємо відстеження останнього WebSocket update
  const lastWebSocketUpdateRef = useRef<Date | null>(null);
  const websocketTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const websocketUpdateTimeoutMs = 30000; // 30 секунд без updates = форсуємо HTTP refresh

  const maxReconnectAttempts = 5;
  const reconnectDelay = 5000;
  const connectionTimeoutMs = 30000; // Збільшено до 30 секунд
  const heartbeatIntervalMs = 60000; // Збільшено з 30000 до 60000 мс (60 секунд)

  // Enhanced error classification
  const classifyWebSocketError = (event: CloseEvent): WebSocketError => {
    const timestamp = new Date();

    // Класифікуємо помилки за кодом
    switch (event.code) {
      case 1000:
        return {
          type: "connection",
          code: event.code,
          reason: event.reason || "Normal closure",
          message: "З'єднання закрито нормально",
          timestamp,
          isRetryable: false,
        };

      case 1001:
        return {
          type: "connection",
          code: event.code,
          reason: event.reason || "Going away",
          message: "Сервер або клієнт залишає з'єднання",
          timestamp,
          isRetryable: true,
        };

      case 1002:
        return {
          type: "connection",
          code: event.code,
          reason: event.reason || "Protocol error",
          message: "Помилка протоколу WebSocket",
          timestamp,
          isRetryable: false,
        };

      case 1003:
        return {
          type: "connection",
          code: event.code,
          reason: event.reason || "Unsupported data",
          message: "Отримано непідтримуваний тип даних",
          timestamp,
          isRetryable: false,
        };

      case 1006:
        return {
          type: "network",
          code: event.code,
          reason: event.reason || "Abnormal closure",
          message: "Аномальне закриття з'єднання (можливо, проблеми з мережею)",
          timestamp,
          isRetryable: true,
        };

      case 1007:
        return {
          type: "connection",
          code: event.code,
          reason: event.reason || "Invalid frame payload data",
          message: "Некоректні дані в кадрі",
          timestamp,
          isRetryable: false,
        };

      case 1008:
        return {
          type: "authentication",
          code: event.code,
          reason: event.reason || "Policy violation",
          message: "Помилка автентифікації або порушення політики",
          timestamp,
          isRetryable: false,
        };

      case 1009:
        return {
          type: "connection",
          code: event.code,
          reason: event.reason || "Message too big",
          message: "Повідомлення занадто велике",
          timestamp,
          isRetryable: true,
        };

      case 1011:
        return {
          type: "connection",
          code: event.code,
          reason: event.reason || "Internal server error",
          message: "Внутрішня помилка сервера",
          timestamp,
          isRetryable: true,
        };

      case 1012:
        return {
          type: "connection",
          code: event.code,
          reason: event.reason || "Service restart",
          message: "Сервіс перезапускається",
          timestamp,
          isRetryable: true,
        };

      case 1013:
        return {
          type: "connection",
          code: event.code,
          reason: event.reason || "Try again later",
          message: "Спробуйте пізніше - сервер тимчасово недоступний",
          timestamp,
          isRetryable: true,
        };

      case 1014:
        return {
          type: "connection",
          code: event.code,
          reason: event.reason || "Bad gateway",
          message: "Помилка шлюзу",
          timestamp,
          isRetryable: true,
        };

      case 1015:
        return {
          type: "connection",
          code: event.code,
          reason: event.reason || "TLS handshake",
          message: "Помилка TLS handshake",
          timestamp,
          isRetryable: true,
        };

      // Кастомні коди помилок
      case 4000:
        return {
          type: "authentication",
          code: event.code,
          reason: event.reason || "Authentication required",
          message: "Необхідна автентифікація",
          timestamp,
          isRetryable: false,
        };

      case 4001:
        return {
          type: "registration",
          code: event.code,
          reason: event.reason || "Registration failed",
          message: "Помилка реєстрації клієнта",
          timestamp,
          isRetryable: true,
        };

      case 4002:
        return {
          type: "authentication",
          code: event.code,
          reason: event.reason || "Invalid token",
          message: "Недійсний токен автентифікації",
          timestamp,
          isRetryable: false,
        };

      case 4003:
        return {
          type: "authentication",
          code: event.code,
          reason: event.reason || "Token expired",
          message: "Токен автентифікації застарів",
          timestamp,
          isRetryable: false,
        };

      default:
        return {
          type: "unknown",
          code: event.code,
          reason: event.reason || "Unknown error",
          message: `Невідома помилка з кодом ${event.code}`,
          timestamp,
          isRetryable: event.code >= 1000 && event.code < 4000,
        };
    }
  };

  // Create system alert for WebSocket errors
  const createWebSocketAlert = (error: WebSocketError): SystemAlert => {
    const severityMap = {
      connection: "warning" as const,
      authentication: "error" as const,
      registration: "warning" as const,
      network: "info" as const,
      timeout: "warning" as const,
      unknown: "error" as const,
    };

    return {
      id: `ws-error-${error.timestamp.getTime()}`,
      type: severityMap[error.type],
      title: `WebSocket ${error.type === "authentication" ? "Автентифікація" : "З'єднання"}`,
      message: error.message,
      timestamp: error.timestamp.toISOString(),
      acknowledged: false,
      source: "WebSocket",
    };
  };

  // Enhanced connection timeout handler
  const handleConnectionTimeout = () => {
    console.error("⏰ WebSocket connection timeout");

    const timeoutError: WebSocketError = {
      type: "timeout",
      code: 0,
      reason: "Connection timeout",
      message: "Таймаут підключення до WebSocket",
      timestamp: new Date(),
      isRetryable: true,
    };

    dispatch({ type: "SET_WEBSOCKET_ERROR", payload: timeoutError });
    dispatch({ type: "SET_CONNECTION_STATUS", payload: "error" });
    dispatch({
      type: "ADD_ALERT",
      payload: createWebSocketAlert(timeoutError),
    });

    if (socket) {
      socket.close(1000, "Connection timeout");
      setSocket(null);
    }

    // Reset the stored timeout reference (it has already fired)
    connectionTimeoutRef.current = null;
  };

  // Enhanced heartbeat mechanism
  const startHeartbeat = (ws: WebSocket) => {
    const interval = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        const pingMsg = {
          type: "ping",
          timestamp: new Date().toISOString(),
        };
        if (!pingMsg.type) {
          console.error(
            "❌ Відправка WebSocket-повідомлення без type!",
            pingMsg,
          );
          return;
        }
        // Замість ws.send(JSON.stringify(pingMsg)), використовуємо safeSend
        safeSend(ws, pingMsg);
      } else {
        console.warn("💔 WebSocket not open, stopping heartbeat");
        clearInterval(interval);
      }
    }, heartbeatIntervalMs);

    setHeartbeatInterval(interval);
  };

  const stopHeartbeat = () => {
    if (heartbeatInterval) {
      clearInterval(heartbeatInterval);
      setHeartbeatInterval(null);
    }
  };

  const startWebSocketTimeout = () => {
    // Очищуємо попередній timeout
    if (websocketTimeoutRef.current) {
      clearTimeout(websocketTimeoutRef.current);
    }
    
    // Встановлюємо новий timeout для форсування HTTP refresh
    websocketTimeoutRef.current = setTimeout(() => {
      console.log("⏰ WebSocket timeout - no updates received, forcing HTTP refresh");
      refreshData();
    }, websocketUpdateTimeoutMs);
  };

  const stopWebSocketTimeout = () => {
    if (websocketTimeoutRef.current) {
      clearTimeout(websocketTimeoutRef.current);
      websocketTimeoutRef.current = null;
    }
  };

  // Universal safe send for WebSocket
  const safeSend = (ws: WebSocket, msg: any) => {
    if (!msg || typeof msg !== "object" || !msg.type) {
      console.error(
        "❌ Спроба відправити WebSocket-повідомлення без type!",
        msg,
      );
      return;
    }
    ws.send(JSON.stringify(msg));
  };

  // API calls з кращим обробленням помилок
  const createApiHeaders = (): HeadersInit => {
    const headers: HeadersInit = {
      "Content-Type": "application/json",
      Accept: "application/json",
      "Cache-Control": "no-cache",
    };

    // Додаємо токен авторизації.
    const token = authState.sessionId;
    if (
      token &&
      token !== "undefined" &&
      token !== "null" &&
      token.length > 10
    ) {
      headers.Authorization = `Bearer ${token}`;
    }

    return headers;
  };

  const authenticatedFetch = async (
    url: string,
    options: RequestInit = {},
    retries: number = 1, // Зменшено з 3 до 1 для запобігання спаму при 429
    delay: number = 1000,
  ): Promise<Response> => {
    let lastError: Error | null = null;

    for (let attempt = 1; attempt <= retries; attempt++) {
      try {
        console.log(`📤 API Request: ${options.method || "GET"} ${url} (attempt ${attempt}/${retries})`);
        
        let response = await fetch(url, {
          ...options,
          headers: { ...createApiHeaders(), ...options.headers },
        });
        
        console.log(`📥 API Response: ${response.status} ${url}`);

        if (response.status === 401) {
          console.log(`🔒 Authentication failed for ${url} - redirecting to login`);
          // Перенаправляємо без маніпуляції localStorage (токени не зберігаються у storage)
          window.location.href = "/login";
          throw new Error("Authentication required");
        } else if (response.status === 429) {
          // Rate limit - не робимо retries, тільки логуємо
          console.warn(`⏳ Rate limited for ${url} - skipping retries to prevent spam`);
          throw new Error("Rate limited - too many requests");
        } else if (response.status === 503) {
          // Backend недоступний через Vite proxy fallback
          console.log(`⚠️ Backend unavailable (503) for ${url} - backend may be starting`);
          if (attempt < retries) {
            console.log(`⏳ Waiting ${delay * attempt}ms before retry...`);
            await new Promise((resolve) => setTimeout(resolve, delay * attempt));
            continue; // Повторити запит
          }
        } else if (response.status === 500) {
          console.log(
            `⚠️ Server error ${response.status} for ${url} - server may have restarted`,
          );
          if (attempt < retries) {
            console.log(`⏳ Waiting ${delay * attempt}ms before retry...`);
            await new Promise((resolve) => setTimeout(resolve, delay * attempt));
            continue; // Повторити запит
          }
        } else if (response.status === 404 && url.includes('/api/')) {
          // API ендпоінт не знайдено - можливо proxy проблема
          console.log(`❌ API endpoint not found (404) for ${url} - proxy may not be working`);
          if (attempt < retries) {
            console.log(`⏳ Waiting ${delay * attempt}ms before retry...`);
            await new Promise((resolve) => setTimeout(resolve, delay * attempt));
            continue; // Повторити запит
          }
        }

        // Успішний запит або неретраяльна помилка
        return response;

      } catch (error) {
        lastError = error instanceof Error ? error : new Error(String(error));
        console.error(`❌ API Request failed (attempt ${attempt}/${retries}): ${url}`, error);
        
        // Якщо це мережева помилка і не останній запит (але тільки не 429)
        if (attempt < retries && !(error instanceof Error && error.message.includes("Rate limited"))) {
          console.log(`⏳ Network error, waiting ${delay * attempt}ms before retry...`);
          await new Promise((resolve) => setTimeout(resolve, delay * attempt));
          continue;
        }
      }
    }

    // Всі спроби не вдалися
    throw lastError || new Error(`Failed to fetch ${url} after ${retries} attempts`);
  };

  // Покращуємо handleApiError для правильного парсингу помилок
  const handleApiError = async (response: Response, endpoint: string) => {
    let errorMessage = `HTTP ${response.status}`;
    
    // Спеціальна обробка для 429 (Rate Limiting)
    if (response.status === 429) {
      console.warn(`⚠️ Rate limit для ${endpoint} - зменшуємо частоту запитів`);
      // Повертаємо null замість викидання помилки для graceful handling
      return null;
    }
    
    try {
      const errorBody = await response.text();
      if (errorBody) {
        try {
          const parsed = JSON.parse(errorBody);
          // Якщо detail - масив, перетворюємо в рядок
          errorMessage = parsed.detail ? JSON.stringify(parsed.detail) : (parsed.message || parsed.error || errorMessage);
        } catch (parseError) {
          errorMessage = errorBody.length > 100 ? errorBody.substring(0, 100) + "..." : errorBody;
        }
      }
    } catch (textError) {
      console.warn(`Failed to read response body for ${endpoint}:`, textError);
    }

    const error = new Error(`${endpoint} failed: ${response.status} - ${errorMessage}`);
    console.error(`❌ ${error.message}`);
    throw error;
  };

  const fetchWithTimeout = async (
    url: string,
    options: RequestInit = {},
    timeoutMs: number = 10000,
  ): Promise<Response> => {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

    try {
      const response = await fetch(url, {
        ...options,
        signal: controller.signal,
      });
      clearTimeout(timeoutId);
      return response;
    } catch (error) {
      clearTimeout(timeoutId);
      throw error;
    }
  };

  const fetchHealth = async (): Promise<StreamHubHealth | null> => {
    try {
      const response = await authenticatedFetch(buildUrl("/api/health"));

      if (!response.ok) {
        return await handleApiError(response, "Health check");
      }

      const data = await response.json();
      return data;
    } catch (error) {
      if (
        error instanceof Error &&
        error.message.includes("Authentication failed")
      ) {
        return null; // Handled by handleApiError
      }
      console.error("❌ Error fetching health:", error);
      throw error;
    }
  };

  const fetchMetrics = async (): Promise<StreamHubMetrics | null> => {
    try {
      const response = await authenticatedFetch(buildUrl("/api/metrics"));

      if (!response.ok) {
        return await handleApiError(response, "Metrics");
      }

      const data = await response.json();
      return data;
    } catch (error) {
      if (
        error instanceof Error &&
        error.message.includes("Authentication failed")
      ) {
        return null; // Handled by handleApiError
      }
      console.error("❌ Error fetching metrics:", error);
      throw error;
    }
  };

  const fetchClients = async (): Promise<Client[]> => {
    try {
      const response = await authenticatedFetch(buildUrl("/api/clients"));
      if (!response.ok) {
        await handleApiError(response, "Clients");
        return [];
      }
      const data: Client[] = await response.json();
      return data;
    } catch (error) {
      if (
        error instanceof Error &&
        error.message.includes("Authentication failed")
      ) {
        return []; // Handled by handleApiError
      }
      console.error("❌ Error fetching clients:", error);
      return [];
    }
  };

  // Кеш для task stats
  const taskStatsCache = useRef<{
    data: TaskQueueStats | null;
    timestamp: number;
    ttl: number; // Time To Live в мілісекундах
  }>({
    data: null,
    timestamp: 0,
    ttl: 15000 // 15 секунд кеш
  });

  // У функції fetchTaskStats додаємо default params та кешування
  const fetchTaskStats = async (): Promise<TaskQueueStats | null> => {
    try {
      // Перевіряємо кеш
      const now = Date.now();
      const cache = taskStatsCache.current;
      
      if (cache.data && (now - cache.timestamp) < cache.ttl) {
        console.log("📋 Використовуємо кешовані task stats");
        return cache.data;
      }

      const url = buildUrl("/api/tasks?page=1&limit=50&sort=created_at&order=desc");
      const response = await authenticatedFetch(url);
      if (!response.ok) {
        return await handleApiError(response, "Task stats");
      }
      const data: TaskQueueStats = await response.json();
      
      // Оновлюємо кеш
      taskStatsCache.current = {
        data,
        timestamp: now,
        ttl: 15000
      };
      
      return data;
    } catch (error) {
      if (
        error instanceof Error &&
        error.message.includes("Authentication failed")
      ) {
        return null; // Handled by handleApiError
      }
      console.error("❌ Error fetching task stats:", error);
      return null;
    }
  };

  const connectWebSocket = useCallback(async () => {
    // Перевіряємо чи компонент все ще змонтований
    if (!mountedRef.current) {
      console.log("🚫 Component unmounted, skipping WebSocket connection");
      return;
    }

    // Перевіряємо чи вже підключаємося
    if (isConnectingRef.current) {
      console.log("🔄 WebSocket connection already in progress, skipping");
      return;
    }

    if (socket) {
      console.log("✅ WebSocket already exists, skipping connection");
      return;
    }

    // Перевіряємо, чи користувач все ще автентифікований
    if (!authState.isAuthenticated) {
      console.warn("🔒 User not authenticated, skipping WebSocket connection");
      dispatch({ type: "SET_CONNECTION_STATUS", payload: "disconnected" });
      dispatch({ type: "RESET_RECONNECT_INFO" });
      return;
    }

    // Отримуємо токен лише з auth state
    let sessionId = authState.sessionId;
    let tokenToCheck = sessionId;
    
    // Якщо токен відсутній, не можемо підключитися
    if (!tokenToCheck) {
      console.warn("🔒 No authentication token available, skipping WebSocket connection");
      dispatch({ type: "SET_CONNECTION_STATUS", payload: "disconnected" });
      dispatch({ type: "RESET_RECONNECT_INFO" });
      return;
    }
    
    // Перевіряємо чи access_token протух (JWT exp)
    let isExpired = false;
    try {
      const payload = JSON.parse(atob(tokenToCheck.split(".")[1]));
      if (payload.exp && Date.now() / 1000 > payload.exp) {
        isExpired = true;
      }
    } catch (e) {
      console.warn("⚠️ Не вдалося декодувати JWT для перевірки exp", e);
      isExpired = true; // На всякий випадок вважаємо протерміновим
    }
    
    if (isExpired) {
      console.warn("🔒 Access token протух, WebSocket підключення неможливе");
      dispatch({ type: "SET_CONNECTION_STATUS", payload: "error" });
      dispatch({
        type: "SET_WEBSOCKET_ERROR",
        payload: {
          type: "authentication",
          code: 401,
          reason: "Token expired",
          message: "Токен автентифікації протерміновий, потрібен повторний вхід",
          timestamp: new Date(),
          isRetryable: false,
        },
      });
      // Очищаємо токени та перенаправляємо на логін
      // Токени не зберігаються у localStorage, просто редіректимо на логін
      window.location.href = "/login";
      return;
    }

    console.log("🔌 Initiating WebSocket connection...");
    isConnectingRef.current = true;
    dispatch({ type: "SET_CONNECTION_STATUS", payload: "connecting" });
    dispatch({ type: "SET_WEBSOCKET_ERROR", payload: null });

    // Перевіряємо, чи sessionId відповідає sessionId із auth стану
    if (authState.sessionId && sessionId !== authState.sessionId) {
      // Захист від нескінченної петлі session sync
      sessionSyncAttemptsRef.current += 1;

      if (sessionSyncAttemptsRef.current > maxSessionSyncAttempts) {
        console.error(
          "❌ Too many session sync attempts, stopping WebSocket connection",
        );
        isConnectingRef.current = false;
        const syncError: WebSocketError = {
          type: "authentication",
          code: 4002,
          reason: "Session sync loop detected",
          message: "Забагато спроб синхронізації сесії, з'єднання припинено",
          timestamp: new Date(),
          isRetryable: false,
        };

        dispatch({ type: "SET_WEBSOCKET_ERROR", payload: syncError });
        dispatch({ type: "SET_CONNECTION_STATUS", payload: "error" });
        dispatch({
          type: "ADD_ALERT",
          payload: createWebSocketAlert(syncError),
        });
        return;
      }

      console.warn(
        `⚠️ Session ID mismatch (attempt ${sessionSyncAttemptsRef.current}/${maxSessionSyncAttempts}), using AuthContext sessionId`,
      );
      // Повторно викликаємо connectWebSocket з оновленим токеном після короткої затримки
      isConnectingRef.current = false;
      setTimeout(() => connectWebSocket(), 500);
      return;
    }

    // Будуємо URL з токеном
    const wsUrl = `${buildWsUrl("/ws")}?token=${encodeURIComponent(sessionId || "")}`;
    console.log(
      "🔌 Connecting to WebSocket:",
      wsUrl.replace(/token=[^&]+/, "token=***"),
    );
    console.log("🔍 WebSocket URL details:", {
      baseWsUrl: buildWsUrl("/ws"),
      hasToken: !!sessionId,
      environment: process.env.NODE_ENV,
    });

    // Встановлюємо таймаут з'єднання
    const timeoutId = setTimeout(handleConnectionTimeout, connectionTimeoutMs);
    connectionTimeoutRef.current = timeoutId;

    dispatch({
      type: "UPDATE_RECONNECT_INFO",
      payload: { lastAttemptAt: new Date() },
    });

    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      if (!mountedRef.current) {
        console.log(
          "🚫 Component unmounted during connection, closing WebSocket",
        );
        ws.close(1000, "Component unmounted");
        return;
      }

      console.log("✅ WebSocket connected successfully (onopen)");
      isConnectingRef.current = false;

      // Очищаємо таймаут з'єднання
      if (connectionTimeoutRef.current) {
        clearTimeout(connectionTimeoutRef.current);
        connectionTimeoutRef.current = null;
      }

      dispatch({ type: "SET_CONNECTION_STATUS", payload: "connected" });
      dispatch({ type: "SET_WEBSOCKET_ERROR", payload: null });
      dispatch({ type: "RESET_RECONNECT_INFO" });

      // Скидаємо лічильник session sync при успішному підключенні
      sessionSyncAttemptsRef.current = 0;

      // Запускаємо heartbeat
      startHeartbeat(ws);

      // Send registration message
      const registrationMessage = {
        type: "client_registration",
        client_type: "monitor",
        client_id: "dashboard-" + Date.now(),
        client_name: "React Dashboard",
        client_version: "1.0.0",
        capabilities: [],
        max_concurrent_tasks: 1,
        auth_token: sessionId,
        client_info: {
          userAgent: navigator.userAgent,
          timestamp: new Date().toISOString(),
        },
      };
      console.log(
        "➡️ Готуюсь відправити client_registration:",
        registrationMessage,
      );
      // Замість ws.send(JSON.stringify(registrationMessage)), використовуємо safeSend
      safeSend(ws, registrationMessage);
      console.log("✅ Відправлено client_registration");
    };

    ws.onmessage = (event) => {
      if (!mountedRef.current) return;

      try {
        const message = JSON.parse(event.data);
        console.log("📨 Received WebSocket message:", message);

        // Перевіряємо чи є type
        const msgType = message.type || message.message_type;
        if (!msgType) {
          console.log("📨 Received message without type:", message);
          return;
        }

        console.log("📨 Processing message type:", msgType);

        // Handle different message types
        switch (msgType) {
          case "registration_ack":
            console.log("✅ Client registration acknowledged", message);

            // Створюємо alert про успішне підключення тільки один раз
            const successAlert: SystemAlert = {
              id: `ws-success-${Date.now()}`,
              type: "success",
              title: "WebSocket підключено",
              message: "Успішно підключено до системи моніторингу",
              timestamp: new Date().toISOString(),
              acknowledged: false,
              source: "WebSocket",
            };
            dispatch({ type: "ADD_ALERT", payload: successAlert });
            break;

          case "registration_error":
            console.error("❌ Client registration failed", message);
            const regError: WebSocketError = {
              type: "registration",
              code: 4001,
              reason: message.error || "Registration failed",
              message: `Помилка реєстрації: ${message.error || "Невідома помилка"}`,
              timestamp: new Date(),
              isRetryable: true,
            };

            dispatch({ type: "SET_WEBSOCKET_ERROR", payload: regError });
            dispatch({
              type: "ADD_ALERT",
              payload: createWebSocketAlert(regError),
            });
            break;

          case "stats_update":
            dispatch({ type: "UPDATE_LAST_UPDATED" });
            break;

          case "component_status_update":
            console.log("🔧 Received component status update:", message);
            if (message.data && state.health) {
              const updatedHealth = {
                ...state.health,
                components: {
                  ...state.health.components,
                  ...message.data,
                },
              };
              dispatch({ type: "SET_HEALTH", payload: updatedHealth });
            }
            break;

          case "metrics_update":
            // Живі системні/хаб метрики через WS
            if (message.data) {
              const payload = message.data;
              dispatch({ type: "SET_METRICS", payload });
              lastWebSocketUpdateRef.current = new Date();
              startWebSocketTimeout();
            }
            break;

          case "clients_update":
            console.log("👥 Received clients update:", message);
            if (message.data && Array.isArray(message.data)) {
              dispatch({ type: "SET_CLIENTS", payload: message.data });
            }
            break;

          case "task_stats_update":
            console.log("📋 Received task stats update:", message);
            if (message.data) {
              dispatch({ type: "SET_TASK_STATS", payload: message.data });
              // Оновлюємо час останнього WebSocket update
              lastWebSocketUpdateRef.current = new Date();
              startWebSocketTimeout();
            }
            break;

          case "task_updated":
            console.log("📝 Received task update:", message);
            if (message.data) {
              // Перевіряємо чи змінився статус завдання на finalized (completed/failed/cancelled)
              const statusChanged = ["completed", "failed", "cancelled"].includes(message.data.status);
              
              if (statusChanged) {
                // Якщо статус змінився на фінальний, оновлюємо всю статистику
                fetchTaskStats().then((taskStats) => {
                  if (taskStats) {
                    dispatch({ type: "SET_TASK_STATS", payload: taskStats });
                  }
                });
              } else if (state.taskStats) {
                // Інакше просто оновлюємо конкретне завдання в списку
                const updatedTasks =
                  state.taskStats.tasks?.map((task) =>
                    task.task_id === message.data.task_id
                      ? { ...task, ...message.data }
                      : task,
                  ) || [];

                const updatedTaskStats = {
                  ...state.taskStats,
                  tasks: updatedTasks,
                };
                dispatch({ type: "SET_TASK_STATS", payload: updatedTaskStats });
              }
              
              // Оновлюємо час останнього WebSocket update
              lastWebSocketUpdateRef.current = new Date();
              startWebSocketTimeout();
            }
            break;

          case "task_created":
            console.log("➕ Received task created:", message);
            // При створенні нового завдання принудительно оновлюємо статистику завдань
            if (message.data) {
              // Негайно перезавантажуємо актуальні статистики завдань
              fetchTaskStats().then((taskStats) => {
                if (taskStats) {
                  dispatch({ type: "SET_TASK_STATS", payload: taskStats });
                }
              });
              
              dispatch({ type: "UPDATE_LAST_UPDATED" });
              // Оновлюємо час останнього WebSocket update
              lastWebSocketUpdateRef.current = new Date();
              startWebSocketTimeout();
            }
            break;

          case "task_completed":
            console.log("✅ Received task completed:", message);
            if (message.data) {
              // Оновлюємо статистики завдань після завершення
              fetchTaskStats().then((taskStats) => {
                if (taskStats) {
                  dispatch({ type: "SET_TASK_STATS", payload: taskStats });
                }
              });
              
              // Оновлюємо час останнього WebSocket update
              lastWebSocketUpdateRef.current = new Date();
              startWebSocketTimeout();
            }
            break;

          case "task_failed":
            console.log("❌ Received task failed:", message);
            if (message.data) {
              // Оновлюємо статистики завдань після збою
              fetchTaskStats().then((taskStats) => {
                if (taskStats) {
                  dispatch({ type: "SET_TASK_STATS", payload: taskStats });
                }
              });
              
              // Оновлюємо час останнього WebSocket update
              lastWebSocketUpdateRef.current = new Date();
              startWebSocketTimeout();
            }
            break;

          case "system_notification":
            const alert: SystemAlert = {
              id: Date.now().toString(),
              type: message.severity || "info",
              title: message.title || "Системне повідомлення",
              message: message.message || "Немає повідомлення",
              timestamp: new Date().toISOString(),
              acknowledged: false,
              source: "StreamHub",
            };
            dispatch({ type: "ADD_ALERT", payload: alert });
            break;

          case "error":
            console.error("❌ WebSocket error from server:", message);
            const serverError: WebSocketError = {
              type: "connection",
              code: message.error_code || 0,
              reason: message.error || "Server error",
              message: `Помилка сервера: ${message.error || "Невідома помилка"}`,
              timestamp: new Date(),
              isRetryable:
                message.error_code !== 4000 && message.error_code !== 4002,
            };

            dispatch({ type: "SET_WEBSOCKET_ERROR", payload: serverError });
            dispatch({
              type: "ADD_ALERT",
              payload: createWebSocketAlert(serverError),
            });
            break;

          case "ping":
            // Respond to ping with pong
            try {
              if (ws.readyState === WebSocket.OPEN) {
                ws.send(
                  JSON.stringify({
                    type: "pong",
                    correlation_id: message.correlation_id,
                    timestamp: new Date().toISOString(),
                  }),
                );
                console.log("🏓 Responded to ping with pong");
              }
            } catch (error) {
              console.error("❌ Failed to send pong response:", error);
            }
            break;

          case "pong":
            console.log("🏓 Received pong response");
            break;

          default:
            console.log("📨 Received unknown message type:", msgType);
        }
      } catch (error) {
        console.error("❌ Error parsing WebSocket message:", error);
        const parseError: WebSocketError = {
          type: "connection",
          code: 0,
          reason: "Message parse error",
          message: "Помилка парсингу повідомлення WebSocket",
          timestamp: new Date(),
          isRetryable: false,
        };

        dispatch({ type: "SET_WEBSOCKET_ERROR", payload: parseError });
        dispatch({
          type: "ADD_ALERT",
          payload: createWebSocketAlert(parseError),
        });
      }
    };

    ws.onclose = (event) => {
      isConnectingRef.current = false;
      console.log("🔌 WebSocket closed (onclose):", event.code, event.reason);

      // Очищаємо таймаут з'єднання
      if (connectionTimeoutRef.current) {
        clearTimeout(connectionTimeoutRef.current);
        connectionTimeoutRef.current = null;
      }

      // Зупиняємо heartbeat
      stopHeartbeat();

      // ПОКРАЩЕННЯ: Спеціальна обробка для timeout від хабу (code 1001)
      const isHubTimeout = event.code === 1001 && 
        (event.reason === "Connection timeout" || event.reason === "Client inactive" || event.reason === "");
      
      if (isHubTimeout) {
        console.log("⏰ Hub timeout detected - attempting token refresh before reconnect");
        
        // Спробуємо оновити токен перед реконнектом
        const attemptTokenRefreshAndReconnect = async () => {
          try {
            // Отримуємо refresh token
            const refreshToken = localStorage.getItem("refreshToken");
            if (!refreshToken) {
              console.warn("🔒 No refresh token available for timeout recovery");
              handleWebSocketAuthError();
              return;
            }
            
            // Спробуємо оновити токени
            const response = await fetch(buildUrl("/api/auth/refresh"), {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
              },
              body: JSON.stringify({ refresh_token: refreshToken }),
            });
            
            if (response.ok) {
              const data = await response.json();
              
              // Оновлюємо токени в localStorage
              localStorage.setItem("sessionId", data.access_token);
              localStorage.setItem("refreshToken", data.refresh_token);
              
              console.log("✅ Token refreshed successfully - attempting reconnect");
              
              // Скидаємо лічильник реконнектів для свіжого старту
              dispatch({ type: "RESET_RECONNECT_INFO" });
              
              // Спробуємо реконнект через коротку затримку
              setTimeout(() => {
                if (mountedRef.current && authState.isAuthenticated) {
                  connectWebSocket();
                }
              }, 1000);
              
              return; // Не продовжуємо стандартну обробку
              
            } else {
              console.warn("⚠️ Token refresh failed during timeout recovery");
              // Продовжуємо зі стандартною обробкою timeout
            }
            
          } catch (error) {
            console.error("❌ Error during token refresh for timeout recovery:", error);
            // Продовжуємо зі стандартною обробкою timeout
          }
          
          // Якщо token refresh не вдався, обробляємо як звичайний timeout
          handleStandardTimeoutReconnect();
        };
        
        const handleStandardTimeoutReconnect = () => {
          console.log("🔄 Handling hub timeout with standard reconnect logic");
          
          const timeoutError: WebSocketError = {
            type: "connection",
            code: event.code,
            reason: event.reason || "Hub timeout",
            message: "Хаб закрив з'єднання через неактивність - спроба реконнекту",
            timestamp: new Date(),
            isRetryable: true,
          };
          
          dispatch({ type: "SET_WEBSOCKET_ERROR", payload: timeoutError });
          dispatch({ type: "SET_CONNECTION_STATUS", payload: "disconnected" });
          
          // Не додаємо alert для timeout - це нормальна поведінка
          setSocket(null);
          
          // Швидкий реконнект для timeout
          if (mountedRef.current && 
              authState.isAuthenticated && 
              localStorage.getItem("sessionId") &&
              state.reconnectInfo.attempts < 3) { // Обмежуємо кількість спроб для timeout
            
            const nextAttempt = state.reconnectInfo.attempts + 1;
            const delay = 2000; // Швидкий реконнект для timeout
            
            console.log(`⏰ Scheduling quick timeout reconnection attempt ${nextAttempt}/3 in ${delay}ms`);
            
            dispatch({
              type: "UPDATE_RECONNECT_INFO",
              payload: {
                attempts: nextAttempt,
                nextAttemptIn: delay,
              },
            });
            
            const timeoutId = setTimeout(() => {
              if (mountedRef.current && 
                  !socket && 
                  !isConnectingRef.current && 
                  authState.isAuthenticated &&
                  localStorage.getItem("sessionId")) {
                
                console.log(`🔄 Attempting timeout reconnection (${nextAttempt}/3)`);
                connectWebSocket();
              }
              setReconnectTimeout(null);
            }, delay);
            
            setReconnectTimeout(timeoutId);
          }
        };
        
        // Запускаємо спробу оновлення токена
        attemptTokenRefreshAndReconnect();
        return; // Не продовжуємо стандартну обробку
      }

      // Додаю обробку протухлого токена (окрім timeout)
      if (event.code === 4002 || event.code === 4003) {
        handleWebSocketAuthError();
        return;
      }

      const error = classifyWebSocketError(event);
      dispatch({ type: "SET_WEBSOCKET_ERROR", payload: error });
      dispatch({ type: "SET_CONNECTION_STATUS", payload: "disconnected" });
      dispatch({ type: "ADD_ALERT", payload: createWebSocketAlert(error) });

      setSocket(null);

      // ПОКРАЩЕННЯ: Більш детальне логування для всіх помилок
      console.log(`🔍 WebSocket Error Details:
        Type: ${error.type}
        Code: ${error.code}
        Reason: ${error.reason}
        Message: ${error.message}
        Retryable: ${error.isRetryable}
        Connection State: connected=${authState.isAuthenticated}, sessionId=${!!localStorage.getItem("sessionId")}
        Attempts: ${state.reconnectInfo.attempts}/${state.reconnectInfo.maxAttempts}
      `);

      // ПОКРАЩЕННЯ: Спеціальна обробка для code 1006 (мережева помилка)
      const isNetworkError = error.type === "network" || error.code === 1006;
      const isTemporaryError = [1012, 1013, 1014].includes(error.code); // Виключаємо 1001 з тимчасових
      
      // Для code 1006 завжди намагаємося реконнектитися
      const shouldReconnect =
        mountedRef.current &&
        authState.isAuthenticated &&
        authState.sessionId &&
        state.reconnectInfo.attempts < state.reconnectInfo.maxAttempts &&
        (error.isRetryable || isNetworkError || isTemporaryError);

      if (shouldReconnect) {
        const nextAttempt = state.reconnectInfo.attempts + 1;
        
        // ПОКРАЩЕННЯ: Інтелектуальний backoff з особливою обробкою мережевих помилок
        let delay;
        if (isNetworkError && error.code === 1006) {
          // Для code 1006 (мережева помилка) - агресивніший retry
          delay = Math.min(500 * Math.pow(1.2, state.reconnectInfo.attempts), 5000); // Max 5 seconds
          console.log("🌐 Network error (1006) detected - using aggressive retry strategy");
        } else if (isTemporaryError) {
          // Для тимчасових помилок - швидший retry
          delay = Math.min(1000 * Math.pow(1.5, state.reconnectInfo.attempts), 10000); // Max 10 seconds
        } else {
          // Стандартний exponential backoff
          delay = Math.min(
            reconnectDelay * Math.pow(2, state.reconnectInfo.attempts),
            30000,
          ); // Max 30 seconds
        }

        console.log(
          `⏰ Scheduling WebSocket reconnection attempt ${nextAttempt}/${state.reconnectInfo.maxAttempts} in ${delay}ms... (${error.type} error, code ${error.code})`,
        );

        dispatch({
          type: "UPDATE_RECONNECT_INFO",
          payload: {
            attempts: nextAttempt,
            nextAttemptIn: delay,
            totalFailures: state.reconnectInfo.totalFailures + 1,
          },
        });

        const timeoutId = setTimeout(() => {
          // Перевіряємо ще раз перед переконнектуванням
          if (
            mountedRef.current &&
            !socket &&
            !isConnectingRef.current &&
            authState.isAuthenticated &&
            authState.sessionId
          ) {
            console.log(
              `🔄 Attempting WebSocket reconnection (${nextAttempt}/${state.reconnectInfo.maxAttempts})... (Previous error: ${error.type}, code ${error.code})`,
            );
            connectWebSocket();
          } else {
            console.log(
              "🚫 Skipping WebSocket reconnection - conditions no longer met",
              {
                mounted: mountedRef.current,
                hasSocket: !!socket,
                connecting: isConnectingRef.current,
                authenticated: authState.isAuthenticated,
                hasSession: !!authState.sessionId
              }
            );
          }
          setReconnectTimeout(null);
        }, delay);

        setReconnectTimeout(timeoutId);
      } else {
        if (state.reconnectInfo.attempts >= state.reconnectInfo.maxAttempts) {
          console.error("❌ Maximum reconnection attempts reached, giving up");
          dispatch({ type: "SET_CONNECTION_STATUS", payload: "error" });

          const maxAttemptsError: WebSocketError = {
            type: "connection",
            code: 0,
            reason: "Max reconnection attempts reached",
            message: "Досягнуто максимальної кількості спроб підключення",
            timestamp: new Date(),
            isRetryable: false,
          };

          dispatch({ type: "SET_WEBSOCKET_ERROR", payload: maxAttemptsError });
          dispatch({
            type: "ADD_ALERT",
            payload: createWebSocketAlert(maxAttemptsError),
          });
        } else if (!error.isRetryable) {
          console.log(
            `🚫 Not scheduling WebSocket reconnection - error not retryable (${error.type}, code ${error.code})`,
          );
        } else {
          console.log(
            "🚫 Not scheduling WebSocket reconnection - user not authenticated or component unmounted",
            {
              authenticated: authState.isAuthenticated,
              mounted: mountedRef.current,
              hasSession: !!localStorage.getItem("sessionId")
            }
          );
        }

        // Автоматичне скидання лічильника через деякий час
        setTimeout(() => {
          if (mountedRef.current && authState.isAuthenticated) {
            dispatch({ type: "RESET_RECONNECT_INFO" });
            console.log("🔄 Auto-reset reconnection attempts after delay");
          }
        }, 60000); // Скидаємо через 1 хвилину
      }
    };

    ws.onerror = (event) => {
      isConnectingRef.current = false;
      console.error("❌ WebSocket error (onerror):", event);

      // Очищаємо таймаут з'єднання
      if (connectionTimeoutRef.current) {
        clearTimeout(connectionTimeoutRef.current);
        connectionTimeoutRef.current = null;
      }

      const wsError: WebSocketError = {
        type: "connection",
        code: 0,
        reason: "WebSocket error event",
        message: "Помилка WebSocket з'єднання",
        timestamp: new Date(),
        isRetryable: true,
      };

      dispatch({ type: "SET_WEBSOCKET_ERROR", payload: wsError });
      dispatch({ type: "SET_CONNECTION_STATUS", payload: "error" });
      dispatch({ type: "ADD_ALERT", payload: createWebSocketAlert(wsError) });
    };

    setSocket(ws);
  }, [
    authState.isAuthenticated,
    authState.sessionId,
    socket,
    state.reconnectInfo.attempts,
  ]);

  const disconnectWebSocket = useCallback(() => {
    isConnectingRef.current = false;

    if (socket) {
      socket.close(1000, "User disconnection");
      setSocket(null);
    }

    // Clear all timeouts and intervals
    if (reconnectTimeout) {
      clearTimeout(reconnectTimeout);
      setReconnectTimeout(null);
    }

    if (connectionTimeoutRef.current) {
      clearTimeout(connectionTimeoutRef.current);
      connectionTimeoutRef.current = null;
    }

    stopHeartbeat();

    // Reset reconnect info and session sync attempts
    dispatch({ type: "RESET_RECONNECT_INFO" });
    dispatch({ type: "SET_WEBSOCKET_ERROR", payload: null });
    sessionSyncAttemptsRef.current = 0;
  }, [socket, reconnectTimeout]);

  // Рефи для контролю помилок та пауз
  const errorCountRef = useRef(0);
  const isPausedRef = useRef(false);
  const maxErrorsBeforePause = 3;
  const pauseDuration = 30000; // 30 секунд пауза при багатьох помилках
  const rateLimitPauseDuration = 60000; // 1 хвилина пауза при rate limit

  const refreshData = useCallback(async () => {
    if (!authState.isAuthenticated || isPausedRef.current) {
      return;
    }

    // Якщо WebSocket підключений, зменшуємо частоту HTTP запитів
    if (state.connectionStatus === "connected" && state.lastUpdated) {
      const timeSinceLastUpdate = Date.now() - state.lastUpdated.getTime();
      if (timeSinceLastUpdate < 30000) { // 30 секунд
        console.log("📡 WebSocket активний - пропускаємо HTTP refresh");
        return;
      }
    }

    if (errorCountRef.current >= maxErrorsBeforePause) {
      console.warn(`⏸️ Pausing data refresh due to repeated errors. Resuming in ${pauseDuration / 1000} seconds`);
      isPausedRef.current = true;
      setTimeout(() => {
        errorCountRef.current = 0;
        isPausedRef.current = false;
        console.log("📡 Resuming data refresh after error pause");
      }, pauseDuration);
      return;
    }

    dispatch({ type: "SET_LOADING", payload: true });

    try {
      const [healthData, metricsData, clientsData, taskStatsData] = await Promise.all([
        fetchHealth(),
        fetchMetrics(),
        fetchClients(),
        fetchTaskStats(),
      ]);

      if (!mountedRef.current) return;

      if (healthData) dispatch({ type: "SET_HEALTH", payload: healthData });
      if (metricsData) dispatch({ type: "SET_METRICS", payload: metricsData });
      dispatch({ type: "SET_CLIENTS", payload: clientsData });
      if (taskStatsData) dispatch({ type: "SET_TASK_STATS", payload: taskStatsData });

      dispatch({ type: "UPDATE_LAST_UPDATED" });
      errorCountRef.current = 0; // Скидаємо лічільник помилок при успіху
    } catch (error) {
      errorCountRef.current++;
      const errorMsg = error instanceof Error ? error.message : "Unknown error";
      
      // Спеціальна обробка rate limit помилок
      if (errorMsg.includes("Rate limited") || errorMsg.includes("429")) {
        console.warn(`⏸️ Rate limited! Pausing requests for ${rateLimitPauseDuration / 1000} seconds to prevent further limiting`);
        isPausedRef.current = true;
        setTimeout(() => {
          errorCountRef.current = 0;
          isPausedRef.current = false;
          console.log("📡 Resuming after rate limit pause");
        }, rateLimitPauseDuration);
        
        dispatch({ type: "SET_ERROR", payload: "Занадто багато запитів. Зачекайте хвилину..." });
      } else {
        dispatch({ type: "SET_ERROR", payload: errorMsg });
      }
      console.error("Error fetching data:", error);
    } finally {
      dispatch({ type: "SET_LOADING", payload: false });
    }
  }, [authState.isAuthenticated]);

  // Cleanup on unmount
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      isConnectingRef.current = false;

      // Очищаємо інтервал data refresh
      if (dataRefreshIntervalRef.current) {
        clearInterval(dataRefreshIntervalRef.current);
        dataRefreshIntervalRef.current = null;
      }
      
      // Очищаємо WebSocket timeout
      stopWebSocketTimeout();
    };
  }, []);

  // Auto-refresh data - покращена логіка з затримкою
  useEffect(() => {
    // Очищаємо попередній інтервал
    if (dataRefreshIntervalRef.current) {
      clearInterval(dataRefreshIntervalRef.current);
      dataRefreshIntervalRef.current = null;
    }

    if (
      authState.isAuthenticated &&
      mountedRef.current &&
      !authState.isLoading
    ) {
      // Додаємо невелику затримку щоб дати час сесії встановитися
      const startDataRefresh = () => {
        refreshData(); // Виконуємо одразу

        // Адаптивний інтервал залежно від стану WebSocket
        const getRefreshInterval = () => {
          if (state.connectionStatus === "connected") {
            return refreshInterval * 2; // Подвоюємо інтервал при активному WebSocket
          }
          return refreshInterval;
        };

        const interval = setInterval(() => {
          if (
            mountedRef.current &&
            authState.isAuthenticated &&
            !authState.isLoading
          ) {
            refreshData();
          }
        }, getRefreshInterval());

        dataRefreshIntervalRef.current = interval;
      };

      // Додаємо невелику затримку щоб дати час сесії встановитися та уникнути race conditions
      const sessionId = localStorage.getItem("sessionId");
      const delay = sessionId ? 500 : 1500; // Менша затримка якщо сесія вже є
      
      setTimeout(() => {
        if (
          mountedRef.current &&
          authState.isAuthenticated &&
          !isPausedRef.current &&
          authState.sessionId
        ) {
          startDataRefresh();
        }
      }, delay);
    }

    return () => {
      if (dataRefreshIntervalRef.current) {
        clearInterval(dataRefreshIntervalRef.current);
        dataRefreshIntervalRef.current = null;
      }
    };
  }, [
    authState.isAuthenticated,
    authState.isLoading,
    refreshInterval,
    refreshData,
  ]);

  // Connect WebSocket when authenticated - покращена логіка
  useEffect(() => {
    const authChanged = lastAuthStateRef.current !== authState.isAuthenticated;
    lastAuthStateRef.current = authState.isAuthenticated;

    if (authState.isAuthenticated && authState.sessionId) {
      if (authChanged || !socket) {
        connectWebSocket();
      }
    } else {
      if (socket || isConnectingRef.current) {
        disconnectWebSocket();
      }
    }
  }, [
    authState.isAuthenticated,
    authState.sessionId,
    connectWebSocket,
    disconnectWebSocket,
  ]);

  // Функція для ручного скидання лічильника переподключень
  const resetReconnectionAttempts = useCallback(() => {
    dispatch({ type: "RESET_RECONNECT_INFO" });
    dispatch({ type: "SET_WEBSOCKET_ERROR", payload: null });
    console.log("🔄 Reconnection attempts reset manually");
  }, []);

  // Обробка помилки автентифікації WebSocket - logout замість refresh
  const handleWebSocketAuthError = useCallback(async () => {
    console.warn("🔒 WebSocket authentication failed - logging out");
    
    // Очищаємо всі токени
    localStorage.removeItem("sessionId");
    localStorage.removeItem("accessToken");
    localStorage.removeItem("refreshToken");
    
    dispatch({ type: "SET_CONNECTION_STATUS", payload: "error" });
    dispatch({
      type: "SET_WEBSOCKET_ERROR",
      payload: {
        type: "authentication",
        code: 401,
        reason: "Authentication failed",
        message: "Помилка автентифікації, потрібен повторний вхід",
        timestamp: new Date(),
        isRetryable: false,
      },
    });
    
    // Перенаправляємо на логін
    window.location.href = "/login";
  }, [dispatch]);

  const value: StatusContextType = {
    state,
    dispatch,
    refreshData,
    connectWebSocket,
    disconnectWebSocket,
    resetReconnectionAttempts,
  };

  return (
    <StatusContext.Provider value={value}>{children}</StatusContext.Provider>
  );
};
