// Configuration for API endpoints
// Using relative URLs to avoid CORS issues - requests will go to the same domain as frontend

// Check if we're in production environment
const isProduction = process.env.NODE_ENV === "production";

// Отримати базовий API URL
export const getApiBaseUrl = (): string => {
  if (!isProduction) {
    // Dev: використовуємо пустий рядок для відносних URL через Vite proxy
    return "";
  }

  // Prod: та ж схема й хост, що у фронтенду
  return window.location.origin;
};

// Отримати базовий WebSocket URL
export const getWebSocketUrl = (): string => {
  if (!isProduction) {
    // Dev: використовуємо Vite proxy на порту 3000 замість прямого з'єднання з 8000
    return "ws://localhost:3000";
  }

  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}`;
};

// Export configuration object with dynamic values
export const config = {
  api: {
    get baseUrl() {
      return getApiBaseUrl();
    },
    timeout: 30000,
    retryAttempts: 3,
    retryDelay: 1000,
  },
  websocket: {
    get url() {
      return getWebSocketUrl();
    },
    reconnectInterval: 3000,
    maxReconnectAttempts: 5,
    pingInterval: 30000,
  },
  features: {
    get enableDebugMode() {
      return !isProduction;
    },
    get enableAnalytics() {
      return isProduction;
    },
    get enableErrorReporting() {
      return isProduction;
    },
  },
  refresh: {
    healthCheckInterval: 10000,
    metricsInterval: 5000,
    clientsInterval: 3000,
    tasksInterval: 2000,
  },
};

// API endpoints - нова логічна структура
export const endpoints = {
  // Основні API ендпоінти
  health: "/api/health",
  metrics: "/api/metrics", 
  clients: "/api/clients",
  tasks: "/api/tasks",
  
  // Frontend-специфічні ендпоінти
  frontend: {
    status: "/api/frontend/status",
    health: "/api/frontend/health",
    realTimeMetrics: "/api/frontend/real-time-metrics",
    systemLogs: "/api/frontend/system-logs",
  },
  
  // Детальні ендпоінти
  clientsDetailed: "/api/clients/detailed",
  tasksStats: "/api/tasks/stats",
  
  // Адміністративні ендпоінти
  admin: {
    restartComponent: "/api/admin/restart-component",
    exportMetrics: "/api/admin/export/metrics",
  }
};

// Helper function for building full URLs
export const buildUrl = (path: string = "/"): string => {
  const baseUrl = config.api.baseUrl;
  // Якщо baseUrl порожній (dev режим), просто повертаємо path
  if (!baseUrl) {
    return path;
  }
  return `${baseUrl}${path}`;
};

// Helper function for WebSocket URL with path
export const buildWsUrl = (path: string = "/ws"): string => {
  return `${config.websocket.url}${path}`;
};

// Authenticated fetch function
export const authenticatedFetch = async (
  url: string,
  options: RequestInit = {},
): Promise<Response> => {
  const sessionId = localStorage.getItem("sessionId");

  const defaultHeaders: Record<string, string> = {
    "Content-Type": "application/json",
  };

  // Додаємо Authorization header якщо є валідний токен
  if (sessionId && sessionId !== "undefined" && sessionId !== "null" && sessionId.length > 10) {
    defaultHeaders["Authorization"] = `Bearer ${sessionId}`;
  }

  const mergedOptions: RequestInit = {
    ...options,
    headers: {
      ...defaultHeaders,
      ...options.headers,
    },
  };

  return fetch(url, mergedOptions);
};

// Export individual values for backward compatibility
export const API_BASE_URL = "";
export const WS_BASE_URL = getWebSocketUrl();

export default config;
