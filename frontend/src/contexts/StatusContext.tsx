import React, { createContext, useContext, useReducer, useEffect } from "react";
import {
  StreamHubHealth,
  StreamHubMetrics,
  Client,
  TaskQueueStats,
  SystemAlert,
  DashboardData,
} from "../types/api";
import config, { buildUrl, buildWsUrl } from "../config";
import { useAuth } from './AuthContext';

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
  | { type: "UPDATE_LAST_UPDATED" };

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
        connectionStatus: "connected",
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
  const [reconnectAttempts, setReconnectAttempts] = React.useState(0);
  const [reconnectTimeout, setReconnectTimeout] = React.useState<NodeJS.Timeout | null>(null);
  const { auth } = useAuth();
  
  const maxReconnectAttempts = 5;
  const reconnectDelay = 5000;

  // API calls
  const fetchHealth = async (): Promise<StreamHubHealth | null> => {
    try {
      const sessionId = localStorage.getItem('sessionId');
      const headers: HeadersInit = {
        'Content-Type': 'application/json',
      };
      
      if (sessionId) {
        headers.Authorization = `Bearer ${sessionId}`;
      }
      
      const response = await fetch(buildUrl("/health"), {
        headers,
      });
      if (!response.ok) {
        if (response.status === 401) {
          // Redirect to login on authentication failure
          window.location.href = '/';
          return null;
        }
        throw new Error("Health check failed");
      }
      return await response.json();
    } catch (error) {
      console.error("Error fetching health:", error);
      return null;
    }
  };

  const fetchMetrics = async (): Promise<StreamHubMetrics | null> => {
    try {
      const sessionId = localStorage.getItem('sessionId');
      const headers: HeadersInit = {
        'Content-Type': 'application/json',
      };
      
      if (sessionId) {
        headers.Authorization = `Bearer ${sessionId}`;
      }
      
      const response = await fetch(buildUrl("/metrics"), {
        headers,
      });
      if (!response.ok) {
        if (response.status === 401) {
          // Redirect to login on authentication failure
          window.location.href = '/';
          return null;
        }
        throw new Error("Metrics fetch failed");
      }
      return await response.json();
    } catch (error) {
      console.error("Error fetching metrics:", error);
      return null;
    }
  };

  const fetchClients = async (): Promise<Client[]> => {
    try {
      const sessionId = localStorage.getItem('sessionId');
      const headers: HeadersInit = {
        'Content-Type': 'application/json',
      };
      
      if (sessionId) {
        headers.Authorization = `Bearer ${sessionId}`;
      }
      
      const response = await fetch(buildUrl("/clients"), {
        headers,
      });
      if (!response.ok) {
        if (response.status === 401) {
          // Redirect to login on authentication failure
          window.location.href = '/';
          return [];
        }
        // Return empty array if service unavailable (no clients connected)
        if (response.status === 503) return [];
        throw new Error("Clients fetch failed");
      }
      const data = await response.json();
      return data.clients || [];
    } catch (error) {
      console.error("Error fetching clients:", error);
      return [];
    }
  };

  const fetchTaskStats = async (): Promise<TaskQueueStats | null> => {
    try {
      const sessionId = localStorage.getItem('sessionId');
      const headers: HeadersInit = {
        'Content-Type': 'application/json',
      };
      
      if (sessionId) {
        headers.Authorization = `Bearer ${sessionId}`;
      }
      
      const response = await fetch(buildUrl("/tasks"), {
        headers,
      });
      if (!response.ok) {
        if (response.status === 401) {
          // Redirect to login on authentication failure
          window.location.href = '/';
          return null;
        }
        throw new Error("Task stats fetch failed");
      }
      return await response.json();
    } catch (error) {
      console.error("Error fetching task stats:", error);
      return null;
    }
  };

  const refreshData = async () => {
    // Only refresh data if user is authenticated
    if (!auth.isAuthenticated) {
      dispatch({ type: "SET_CONNECTION_STATUS", payload: "disconnected" });
      return;
    }

    dispatch({ type: "SET_LOADING", payload: true });
    dispatch({ type: "SET_CONNECTION_STATUS", payload: "connecting" });

    try {
      const [health, metrics, clients, taskStats] = await Promise.all([
        fetchHealth(),
        fetchMetrics(),
        fetchClients(),
        fetchTaskStats(),
      ]);

      if (health) dispatch({ type: "SET_HEALTH", payload: health });
      if (metrics) dispatch({ type: "SET_METRICS", payload: metrics });
      dispatch({ type: "SET_CLIENTS", payload: clients });
      if (taskStats) dispatch({ type: "SET_TASK_STATS", payload: taskStats });

      dispatch({ type: "SET_ERROR", payload: null });
      dispatch({ type: "SET_CONNECTION_STATUS", payload: "connected" });
    } catch (error) {
      dispatch({
        type: "SET_ERROR",
        payload: error instanceof Error ? error.message : "Unknown error",
      });
      dispatch({ type: "SET_CONNECTION_STATUS", payload: "error" });
    } finally {
      dispatch({ type: "SET_LOADING", payload: false });
    }
  };

  const connectWebSocket = () => {
    if (socket) {
      console.log('WebSocket already exists, skipping connection');
      return;
    }

    // Перевіряємо, чи користувач все ще автентифікований
    if (!auth.isAuthenticated) {
      console.warn('🔒 User not authenticated, skipping WebSocket connection');
      dispatch({ type: "SET_CONNECTION_STATUS", payload: "disconnected" });
      setReconnectAttempts(0);
      return;
    }

    console.log('🔌 Initiating WebSocket connection...');
    dispatch({ type: "SET_CONNECTION_STATUS", payload: "connecting" });

    // Отримуємо токен із localStorage
    const sessionId = localStorage.getItem('sessionId');
    if (!sessionId) {
      console.warn('❌ No session ID found, skipping WebSocket connection');
      dispatch({ type: "SET_CONNECTION_STATUS", payload: "disconnected" });
      setReconnectAttempts(0);
      return;
    }

    // Перевіряємо, чи sessionId відповідає sessionId із auth стану
    if (auth.sessionId && sessionId !== auth.sessionId) {
      console.warn('⚠️ Session ID mismatch, skipping WebSocket connection');
      dispatch({ type: "SET_CONNECTION_STATUS", payload: "disconnected" });
      setReconnectAttempts(0);
      return;
    }

    // Будуємо URL з токеном
    const wsUrl = `${buildWsUrl("/ws")}?token=${encodeURIComponent(sessionId)}`;
    console.log('🔌 Connecting to WebSocket with token:', sessionId.substring(0, 8) + '...');

    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.log('✅ WebSocket connected successfully');
      dispatch({ type: "SET_CONNECTION_STATUS", payload: "connected" });
      setReconnectAttempts(0); // Reset reconnect attempts on successful connection

      // Send registration message
      const registrationMessage = {
        message_type: "client_registration",
        client_type: "monitor",
        client_id: "dashboard-" + Date.now(),
        client_name: "React Dashboard",
        client_version: "1.0.0",
        capabilities: [],
        max_concurrent_tasks: 1,
        client_info: {}
      };

      ws.send(JSON.stringify(registrationMessage));
    };

    ws.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);

        // Handle different message types
        switch (message.message_type) {
          case "registration_ack":
            console.log('✅ Client registration acknowledged', message);
            break;
          case "registration_error":
            console.error('❌ Client registration failed', message);
            break;
          case "stats_update":
            dispatch({ type: "UPDATE_LAST_UPDATED" });
            break;
          case "system_notification":
            const alert: SystemAlert = {
              id: Date.now().toString(),
              type: message.severity || "info",
              title: message.title || "System Notification",
              message: message.message || "No message",
              timestamp: new Date().toISOString(),
              acknowledged: false,
              source: "StreamHub",
            };
            dispatch({ type: "ADD_ALERT", payload: alert });
            break;
          case "error":
            console.error('❌ WebSocket error from server:', message);
            break;
          case "ping":
            // Respond to ping with pong
            ws.send(JSON.stringify({
              message_type: "pong",
              correlation_id: message.correlation_id
            }));
            break;
          default:
            console.log('📨 Received message:', message);
        }
      } catch (error) {
        console.error("Error parsing WebSocket message:", error);
      }
    };

    ws.onclose = (event) => {
      console.log('🔌 WebSocket closed:', event.code, event.reason);
      dispatch({ type: "SET_CONNECTION_STATUS", payload: "disconnected" });
      setSocket(null);

      // Детальна обробка закриття WebSocket
      if (event.code === 1006) {
        console.warn('⚠️ WebSocket closed abnormally, possibly due to authentication issues');
      } else if (event.code === 1000) {
        console.log('✅ WebSocket closed normally');
      } else if (event.code === 1008) {
        console.error('❌ WebSocket closed due to policy violation (likely authentication failed)');
      } else if (event.code === 4001) {
        console.error('❌ WebSocket closed due to registration failure');
      }

      // Attempt to reconnect with exponential backoff
      const shouldReconnect = auth.isAuthenticated && 
                            localStorage.getItem('sessionId') && 
                            reconnectAttempts < maxReconnectAttempts &&
                            event.code !== 1008 && // Don't reconnect on auth failure
                            event.code !== 4001;   // Don't reconnect on registration failure

      if (shouldReconnect) {
        const nextAttempt = reconnectAttempts + 1;
        const delay = Math.min(reconnectDelay * Math.pow(2, reconnectAttempts), 30000); // Max 30 seconds
        
        console.log(`⏰ Scheduling WebSocket reconnection attempt ${nextAttempt}/${maxReconnectAttempts} in ${delay}ms...`);
        
        const timeoutId = setTimeout(() => {
          // Перевіряємо ще раз перед переконнектуванням
          if (!socket && auth.isAuthenticated && localStorage.getItem('sessionId')) {
            console.log(`🔄 Attempting WebSocket reconnection (${nextAttempt}/${maxReconnectAttempts})...`);
            setReconnectAttempts(nextAttempt);
            connectWebSocket();
          } else {
            console.log('🚫 Skipping WebSocket reconnection - conditions no longer met');
          }
          setReconnectTimeout(null);
        }, delay);
        
        setReconnectTimeout(timeoutId);
      } else {
        if (reconnectAttempts >= maxReconnectAttempts) {
          console.error('❌ Maximum reconnection attempts reached, giving up');
          dispatch({ type: "SET_CONNECTION_STATUS", payload: "error" });
        } else {
          console.log('🚫 Not scheduling WebSocket reconnection - user not authenticated or auth failed');
        }
      }
    };

    ws.onerror = (error) => {
      console.error("❌ WebSocket error:", error);
      dispatch({ type: "SET_CONNECTION_STATUS", payload: "error" });
    };

    setSocket(ws);
  };

  const disconnectWebSocket = () => {
    if (socket) {
      console.log('🔌 Disconnecting WebSocket...');
      socket.close();
      setSocket(null);
    }
    
    // Clear reconnect timeout
    if (reconnectTimeout) {
      clearTimeout(reconnectTimeout);
      setReconnectTimeout(null);
    }
    
    // Reset reconnect attempts
    setReconnectAttempts(0);
  };

  // Auto-refresh data
  useEffect(() => {
    if (auth.isAuthenticated) {
      console.log('📊 Starting data refresh interval');
      refreshData();
      const interval = setInterval(refreshData, refreshInterval);
      return () => {
        console.log('📊 Stopping data refresh interval');
        clearInterval(interval);
      };
    }
  }, [refreshInterval, auth.isAuthenticated]);

  // Connect WebSocket when authenticated
  useEffect(() => {
    if (auth.isAuthenticated && localStorage.getItem('sessionId')) {
      console.log('🔐 User authenticated, connecting WebSocket');
      connectWebSocket();
    } else {
      console.log('🔒 User not authenticated, disconnecting WebSocket');
      disconnectWebSocket();
    }
    return () => {
      disconnectWebSocket();
      // Clear any pending reconnect timeout
      if (reconnectTimeout) {
        clearTimeout(reconnectTimeout);
      }
    };
  }, [auth.isAuthenticated]);

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
