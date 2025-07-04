import React, { createContext, useContext, useReducer, useEffect } from "react";
import {
  StreamHubHealth,
  StreamHubMetrics,
  Client,
  TaskQueueStats,
  SystemAlert,
  DashboardData,
} from "../types/api";

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
  connectionStatus: "disconnected",
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
  apiBaseUrl = "http://localhost:8000",
  refreshInterval = 10000,
}) => {
  const [state, dispatch] = useReducer(statusReducer, initialState);
  const [socket, setSocket] = React.useState<WebSocket | null>(null);

  // API calls
  const fetchHealth = async (): Promise<StreamHubHealth | null> => {
    try {
      const response = await fetch(`${apiBaseUrl}/health`);
      if (!response.ok) throw new Error("Health check failed");
      return await response.json();
    } catch (error) {
      console.error("Error fetching health:", error);
      return null;
    }
  };

  const fetchMetrics = async (): Promise<StreamHubMetrics | null> => {
    try {
      const response = await fetch(`${apiBaseUrl}/metrics`);
      if (!response.ok) throw new Error("Metrics fetch failed");
      return await response.json();
    } catch (error) {
      console.error("Error fetching metrics:", error);
      return null;
    }
  };

  const fetchClients = async (): Promise<Client[]> => {
    try {
      const response = await fetch(`${apiBaseUrl}/clients`);
      if (!response.ok) {
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
      const response = await fetch(`${apiBaseUrl}/tasks`);
      if (!response.ok) throw new Error("Task stats fetch failed");
      return await response.json();
    } catch (error) {
      console.error("Error fetching task stats:", error);
      return null;
    }
  };

  const refreshData = async () => {
    dispatch({ type: "SET_LOADING", payload: true });

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
    if (socket) return;

    dispatch({ type: "SET_CONNECTION_STATUS", payload: "connecting" });

    const wsUrl = apiBaseUrl
      .replace("http://", "ws://")
      .replace("https://", "wss://");
    const ws = new WebSocket(`${wsUrl}/ws`);

    ws.onopen = () => {
      dispatch({ type: "SET_CONNECTION_STATUS", payload: "connected" });

      // Send registration message
      const registrationMessage = {
        message_type: "client_registration",
        client_type: "monitor",
        client_id: "dashboard-" + Date.now(),
        client_name: "React Dashboard",
        client_version: "1.0.0",
      };

      ws.send(JSON.stringify(registrationMessage));
    };

    ws.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);

        // Handle real-time updates
        if (message.message_type === "stats_update") {
          dispatch({ type: "UPDATE_LAST_UPDATED" });
        } else if (message.message_type === "system_notification") {
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
        }
      } catch (error) {
        console.error("Error parsing WebSocket message:", error);
      }
    };

    ws.onclose = () => {
      dispatch({ type: "SET_CONNECTION_STATUS", payload: "disconnected" });
      setSocket(null);

      // Attempt to reconnect after 5 seconds
      setTimeout(() => {
        if (!socket) connectWebSocket();
      }, 10000);
    };

    ws.onerror = (error) => {
      console.error("WebSocket error:", error);
      dispatch({ type: "SET_CONNECTION_STATUS", payload: "error" });
    };

    setSocket(ws);
  };

  const disconnectWebSocket = () => {
    if (socket) {
      socket.close();
      setSocket(null);
    }
  };

  // Auto-refresh data
  useEffect(() => {
    refreshData();
    const interval = setInterval(refreshData, refreshInterval);
    return () => clearInterval(interval);
  }, [refreshInterval]);

  // Connect WebSocket on mount
  useEffect(() => {
    connectWebSocket();
    return () => disconnectWebSocket();
  }, []);

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
