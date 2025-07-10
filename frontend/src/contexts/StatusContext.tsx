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
    maxAttempts: 5,
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
  refreshInterval = 10000,
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
  const { auth: authState, refreshToken } = useAuth();

  // Додаємо рефи для відстеження стану підключення
  const isConnectingRef = useRef(false);
  const mountedRef = useRef(true);
  const lastAuthStateRef = useRef(authState.isAuthenticated);
  const dataRefreshIntervalRef = useRef<NodeJS.Timeout | null>(null);

  const maxReconnectAttempts = 5;
  const reconnectDelay = 5000;
  const connectionTimeoutMs = 30000; // Збільшено до 30 секунд
  const heartbeatIntervalMs = 30000;

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
        console.log("💓 Sending heartbeat ping...");
        ws.send(
          JSON.stringify({
            type: "ping",
            timestamp: new Date().toISOString(),
          }),
        );
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

  // API calls з кращим обробленням помилок
  const createApiHeaders = (): HeadersInit => {
    const headers: HeadersInit = {
      "Content-Type": "application/json",
      Accept: "application/json",
      "Cache-Control": "no-cache",
    };

    if (authState.sessionId) {
      headers.Authorization = `Bearer ${authState.sessionId}`;
    }

    return headers;
  };

  const authenticatedFetch = async (url: string, options: RequestInit = {}): Promise<Response> => {
    let response = await fetch(url, { ...options, headers: { ...createApiHeaders(), ...options.headers } });
    if (response.status === 401) {
        const refreshed = await refreshToken();
        if (refreshed) {
            response = await fetch(url, { ...options, headers: { ...createApiHeaders(), ...options.headers } });
        }
    }
    return response;
};

  const handleApiError = async (response: Response, endpoint: string) => {
    if (response.status === 401) {
      console.warn(
        `🔒 Authentication failed for ${endpoint}, redirecting to login`,
      );
      window.location.href = "/";
      return null;
    }

    let errorMessage = `HTTP ${response.status}`;
    try {
      const errorBody = await response.text();
      if (errorBody) {
        try {
          const parsed = JSON.parse(errorBody);
          errorMessage = parsed.error || parsed.message || errorMessage;
        } catch {
          errorMessage = errorBody;
        }
      }
    } catch {
      // Ignore parsing errors
    }

    throw new Error(`${endpoint} failed: ${errorMessage}`);
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
      const response = await fetchWithTimeout(
        buildUrl("/health"),
        {
          headers: createApiHeaders(),
        },
      );

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
      const response = await fetchWithTimeout(
        buildUrl("/metrics"),
        {
          headers: createApiHeaders(),
        },
      );

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
        const response = await authenticatedFetch(`${apiBaseUrl}/clients`);
        if (!response.ok) {
            throw new Error(`Failed to fetch clients: ${response.status}`);
        }
        const data: Client[] = await response.json();
        return data;
    } catch (error) {
        console.error('❌ Error fetching clients:', error);
        return [];
    }
};

  const fetchTaskStats = async (): Promise<TaskQueueStats | null> => {
    try {
        const response = await authenticatedFetch(`${apiBaseUrl}/tasks`);
        if (!response.ok) {
            throw new Error(`Failed to fetch task stats: ${response.status}`);
        }
        const data: TaskQueueStats = await response.json();
        return data;
    } catch (error) {
        console.error('❌ Error fetching task stats:', error);
        return null;
    }
};

  const connectWebSocket = useCallback(() => {
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

    console.log("🔌 Initiating WebSocket connection...");
    isConnectingRef.current = true;
    dispatch({ type: "SET_CONNECTION_STATUS", payload: "connecting" });
    dispatch({ type: "SET_WEBSOCKET_ERROR", payload: null });

    // Отримуємо токен із localStorage
    const sessionId = localStorage.getItem("sessionId");
    if (!sessionId) {
      console.warn("❌ No session ID found, skipping WebSocket connection");
      isConnectingRef.current = false;
      const authError: WebSocketError = {
        type: "authentication",
        code: 4000,
        reason: "No session ID",
        message: "Відсутній ідентифікатор сесії",
        timestamp: new Date(),
        isRetryable: false,
      };

      dispatch({ type: "SET_WEBSOCKET_ERROR", payload: authError });
      dispatch({ type: "SET_CONNECTION_STATUS", payload: "disconnected" });
      dispatch({ type: "ADD_ALERT", payload: createWebSocketAlert(authError) });
      dispatch({ type: "RESET_RECONNECT_INFO" });
      return;
    }

    // Перевіряємо, чи sessionId відповідає sessionId із auth стану
    if (authState.sessionId && sessionId !== authState.sessionId) {
      console.warn("⚠️ Session ID mismatch, skipping WebSocket connection");
      isConnectingRef.current = false;
      const authError: WebSocketError = {
        type: "authentication",
        code: 4002,
        reason: "Session ID mismatch",
        message: "Невідповідність ідентифікатора сесії",
        timestamp: new Date(),
        isRetryable: false,
      };

      dispatch({ type: "SET_WEBSOCKET_ERROR", payload: authError });
      dispatch({ type: "SET_CONNECTION_STATUS", payload: "disconnected" });
      dispatch({ type: "ADD_ALERT", payload: createWebSocketAlert(authError) });
      dispatch({ type: "RESET_RECONNECT_INFO" });
      return;
    }

    // Будуємо URL з токеном
    const wsUrl = `${buildWsUrl("/ws")}?token=${encodeURIComponent(sessionId)}`;
    console.log(
      "🔌 Connecting to WebSocket:",
      wsUrl.replace(/token=[^&]+/, "token=***"),
    );

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

      console.log("✅ WebSocket connected successfully");
      isConnectingRef.current = false;

      // Очищаємо таймаут з'єднання
      if (connectionTimeoutRef.current) {
        clearTimeout(connectionTimeoutRef.current);
        connectionTimeoutRef.current = null;
      }

      dispatch({ type: "SET_CONNECTION_STATUS", payload: "connected" });
      dispatch({ type: "SET_WEBSOCKET_ERROR", payload: null });
      dispatch({ type: "RESET_RECONNECT_INFO" });

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

      try {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify(registrationMessage));
          console.log("📝 Registration message sent successfully");
        }
      } catch (error) {
        console.error("❌ Failed to send registration message:", error);
        const regError: WebSocketError = {
          type: "registration",
          code: 4001,
          reason: "Failed to send registration",
          message: "Не вдалося відправити повідомлення реєстрації",
          timestamp: new Date(),
          isRetryable: true,
        };

        dispatch({ type: "SET_WEBSOCKET_ERROR", payload: regError });
        dispatch({
          type: "ADD_ALERT",
          payload: createWebSocketAlert(regError),
        });
      }
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
            console.log("📊 Received metrics update:", message);
            if (message.data) {
              dispatch({ type: "SET_METRICS", payload: message.data });
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
      console.log("🔌 WebSocket closed:", event.code, event.reason);

      // Очищаємо таймаут з'єднання
      if (connectionTimeoutRef.current) {
        clearTimeout(connectionTimeoutRef.current);
        connectionTimeoutRef.current = null;
      }

      // Зупиняємо heartbeat
      stopHeartbeat();

      const error = classifyWebSocketError(event);
      dispatch({ type: "SET_WEBSOCKET_ERROR", payload: error });
      dispatch({ type: "SET_CONNECTION_STATUS", payload: "disconnected" });
      dispatch({ type: "ADD_ALERT", payload: createWebSocketAlert(error) });

      setSocket(null);

      // Детальне логування тільки для важливих помилок
      if (error.type !== "connection" || error.code !== 1000) {
        console.log(`🔍 WebSocket Error Details:
          Type: ${error.type}
          Code: ${error.code}
          Reason: ${error.reason}
          Message: ${error.message}
          Retryable: ${error.isRetryable}
        `);
      }

      // Attempt to reconnect with exponential backoff
      const shouldReconnect =
        mountedRef.current &&
        authState.isAuthenticated &&
        localStorage.getItem("sessionId") &&
        state.reconnectInfo.attempts < state.reconnectInfo.maxAttempts &&
        error.isRetryable;

      if (shouldReconnect) {
        const nextAttempt = state.reconnectInfo.attempts + 1;
        const delay = Math.min(
          reconnectDelay * Math.pow(2, state.reconnectInfo.attempts),
          30000,
        ); // Max 30 seconds

        console.log(
          `⏰ Scheduling WebSocket reconnection attempt ${nextAttempt}/${state.reconnectInfo.maxAttempts} in ${delay}ms...`,
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
            localStorage.getItem("sessionId")
          ) {
            console.log(
              `🔄 Attempting WebSocket reconnection (${nextAttempt}/${state.reconnectInfo.maxAttempts})...`,
            );
            connectWebSocket();
          } else {
            console.log(
              "🚫 Skipping WebSocket reconnection - conditions no longer met",
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
            `🚫 Not scheduling WebSocket reconnection - error not retryable (${error.type})`,
          );
        } else {
          console.log(
            "🚫 Not scheduling WebSocket reconnection - user not authenticated or component unmounted",
          );
        }
      }
    };

    ws.onerror = (error) => {
      isConnectingRef.current = false;
      console.error("❌ WebSocket error event:", error);

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
    console.log("🔌 Disconnecting WebSocket...");
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

    // Reset reconnect info
    dispatch({ type: "RESET_RECONNECT_INFO" });
    dispatch({ type: "SET_WEBSOCKET_ERROR", payload: null });
  }, [socket, reconnectTimeout]);

  // Покращена функція refreshData з меншим логуванням
  const refreshData = useCallback(async () => {
    if (!authState.isAuthenticated) {
      console.log('Skipping data refresh - user not authenticated');
      return;
    }

    dispatch({ type: "SET_LOADING", payload: true });

    try {
      const [health, metrics, clients, taskStats] = await Promise.all([
        fetchHealth(),
        fetchMetrics(),
        fetchClients(),
        fetchTaskStats(),
      ]);

      if (!mountedRef.current) return;

      if (health) dispatch({ type: "SET_HEALTH", payload: health });
      if (metrics) dispatch({ type: "SET_METRICS", payload: metrics });
      dispatch({ type: "SET_CLIENTS", payload: clients });
      if (taskStats) dispatch({ type: "SET_TASK_STATS", payload: taskStats });

      dispatch({ type: "SET_ERROR", payload: null });
    } catch (error) {
      if (!mountedRef.current) return;

      console.error("Error fetching data:", error);
      dispatch({
        type: "SET_ERROR",
        payload: error instanceof Error ? error.message : "Unknown error",
      });
    } finally {
      if (mountedRef.current) {
        dispatch({ type: "SET_LOADING", payload: false });
      }
    }
  }, [authState.isAuthenticated]);

  // Cleanup on unmount
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      console.log("🧹 StatusProvider unmounting - cleaning up");
      mountedRef.current = false;
      isConnectingRef.current = false;

      // Очищаємо інтервал data refresh
      if (dataRefreshIntervalRef.current) {
        clearInterval(dataRefreshIntervalRef.current);
        dataRefreshIntervalRef.current = null;
      }
    };
  }, []);

  // Auto-refresh data - покращена логіка з затримкою
  useEffect(() => {
    // Очищаємо попередній інтервал
    if (dataRefreshIntervalRef.current) {
      clearInterval(dataRefreshIntervalRef.current);
      dataRefreshIntervalRef.current = null;
    }

    if (authState.isAuthenticated && mountedRef.current && !authState.isLoading) {
      console.log("📊 Starting data refresh interval");

      // Додаємо невелику затримку щоб дати час сесії встановитися
      const startDataRefresh = () => {
        refreshData(); // Виконуємо одразу

        const interval = setInterval(() => {
          if (mountedRef.current && authState.isAuthenticated && !authState.isLoading) {
            refreshData();
          }
        }, refreshInterval);

        dataRefreshIntervalRef.current = interval;
      };

      // Якщо сесія вже є, запускаємо одразу, інакше чекаємо 1 секунду
      const sessionId = localStorage.getItem("sessionId");
      if (sessionId) {
        startDataRefresh();
      } else {
        setTimeout(() => {
          if (
            mountedRef.current &&
            authState.isAuthenticated &&
            localStorage.getItem("sessionId")
          ) {
            startDataRefresh();
          }
        }, 1000);
      }
    }

    return () => {
      if (dataRefreshIntervalRef.current) {
        console.log("📊 Stopping data refresh interval");
        clearInterval(dataRefreshIntervalRef.current);
        dataRefreshIntervalRef.current = null;
      }
    };
  }, [authState.isAuthenticated, authState.isLoading, refreshInterval, refreshData]);

  // Connect WebSocket when authenticated - покращена логіка
  useEffect(() => {
    const authChanged = lastAuthStateRef.current !== authState.isAuthenticated;
    lastAuthStateRef.current = authState.isAuthenticated;

    if (authState.isAuthenticated && localStorage.getItem("sessionId")) {
      if (authChanged || !socket) {
        console.log("🔐 User authenticated, connecting WebSocket");
        connectWebSocket();
      }
    } else {
      if (socket || isConnectingRef.current) {
        console.log("🔒 User not authenticated, disconnecting WebSocket");
        disconnectWebSocket();
      }
    }
  }, [
    authState.isAuthenticated,
    authState.sessionId,
    connectWebSocket,
    disconnectWebSocket,
  ]);

  const value: StatusContextType = {
    state,
    dispatch,
    refreshData,
    connectWebSocket,
    disconnectWebSocket,
  };

  return (
    <StatusContext.Provider value={value}>{children}</StatusContext.Provider>
  );
};
