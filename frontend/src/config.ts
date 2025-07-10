// Configuration for API endpoints
// Using relative URLs to avoid CORS issues - requests will go to the same domain as frontend

// Check if we're in production environment
const isProduction = process.env.NODE_ENV === "production";

// Get the base URL for API calls
export const getApiBaseUrl = (): string => {
  // In development, frontend runs on 3000, backend on 8000
  if (!isProduction && window.location.port === "3000") {
    const hostname = window.location.hostname;
    const protocol = window.location.protocol;
    return `${protocol}//${hostname}:8000`;
  }

  // In production or other environments, use same host (relative URLs)
  return "";
};

// Get WebSocket URL
export const getWebSocketUrl = (): string => {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";

  // In development, frontend runs on 3000, backend on 8000
  if (!isProduction && window.location.port === "3000") {
    const hostname = window.location.hostname;
    return `${protocol}//${hostname}:8000`;
  }

  // In production or other environments, use same host
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

// API endpoints
export const endpoints = {
  health: "/dashboard/api/health",
  metrics: "/dashboard/api/metrics",
  clients: "/dashboard/api/clients",
  tasks: "/dashboard/api/tasks",
  dashboard: {
    realTimeMetrics: "/dashboard/api/real-time-metrics",
    systemLogs: "/dashboard/api/system-logs",
  },
  api: {
    status: "/dashboard/api/status",
    metrics: "/dashboard/api/metrics",
  },
};

// Helper function for building full URLs
export const buildUrl = (path: string = "/"): string => {
  return `${config.api.baseUrl}${path}`;
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

  // Додаємо Authorization header якщо є токен
  if (sessionId) {
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
