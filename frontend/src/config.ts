// Configuration for API endpoints

// Determine if we're in production based on the hostname
const isProduction =
  window.location.hostname !== "localhost" &&
  window.location.hostname !== "127.0.0.1" &&
  !window.location.hostname.startsWith("192.168.");

// Get the base URL for API calls
export const getApiBaseUrl = (): string => {
  // If API_URL is set in environment variables (for development)
  if (process.env.REACT_APP_API_URL) {
    return process.env.REACT_APP_API_URL;
  }

  // In production, use the same host as the frontend
  if (isProduction) {
    return `${window.location.protocol}//${window.location.host}`;
  }

  // In development, default to localhost:8000
  return "http://localhost:8000";
};

// Get WebSocket URL
export const getWebSocketUrl = (): string => {
  const apiUrl = getApiBaseUrl();

  // Convert http/https to ws/wss
  return apiUrl.replace("http://", "ws://").replace("https://", "wss://");
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
  health: "/health",
  metrics: "/metrics",
  clients: "/clients",
  tasks: "/tasks",
  dashboard: {
    realTimeMetrics: "/dashboard/api/real-time-metrics",
  },
  api: {
    status: "/api/status",
    metrics: "/api/metrics",
  },
};

// Helper function to build full URL
export const buildUrl = (endpoint: string): string => {
  return `${config.api.baseUrl}${endpoint}`;
};

// Helper function for WebSocket URL with path
export const buildWsUrl = (path: string = "/ws"): string => {
  return `${config.websocket.url}${path}`;
};

// Export individual values for backward compatibility as getters
export const API_BASE_URL = getApiBaseUrl();
export const WS_BASE_URL = getWebSocketUrl();

export default config;
