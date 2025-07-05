// Configuration for API endpoints
// Using relative URLs to avoid CORS issues - requests will go to the same domain as frontend

// Get the base URL for API calls
export const getApiBaseUrl = (): string => {
  // Always use relative URLs - this ensures same-origin requests
  return "";
};

// Get WebSocket URL
export const getWebSocketUrl = (): string => {
  // For WebSocket, we need absolute URL
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
  // With relative URLs, just return the endpoint
  return endpoint;
};

// Helper function for WebSocket URL with path
export const buildWsUrl = (path: string = "/ws"): string => {
  return `${config.websocket.url}${path}`;
};

// Export individual values for backward compatibility
export const API_BASE_URL = "";
export const WS_BASE_URL = getWebSocketUrl();

export default config;
