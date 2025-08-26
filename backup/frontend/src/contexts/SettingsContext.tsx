import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  ReactNode,
} from "react";

export interface ConnectionSettings {
  websocketUrl: string;
  websocketPort: number;
  apiEndpoint: string;
  connectionTimeout: number;
  reconnectInterval: number;
  maxReconnectAttempts: number;
}

export interface UISettings {
  theme: "light" | "dark" | "system";
  language: "uk" | "en";
  refreshInterval: number;
  dateFormat: "dd/mm/yyyy" | "mm/dd/yyyy" | "yyyy-mm-dd";
  timeFormat: "12h" | "24h";
  compactMode: boolean;
}

export interface MonitoringSettings {
  enableNotifications: boolean;
  notifyOnErrors: boolean;
  notifyOnNewClients: boolean;
  notifyOnDisconnects: boolean;
  logLevel: "debug" | "info" | "warn" | "error";
  maxLogEntries: number;
  enableMetrics: boolean;
  metricsInterval: number;
  showCpuUsage: boolean;
  showMemoryUsage: boolean;
  showNetworkUsage: boolean;
}

export interface SecuritySettings {
  enableAuth: boolean;
  sessionTimeout: number;
  requireTwoFactor: boolean;
  allowedIPs: string[];
  enableAuditLog: boolean;
  passwordPolicy: {
    minLength: number;
    requireUppercase: boolean;
    requireNumbers: boolean;
    requireSymbols: boolean;
  };
}

export interface ExportSettings {
  autoExportLogs: boolean;
  exportFormat: "json" | "csv" | "xml";
  exportInterval: "daily" | "weekly" | "monthly";
  maxExportSize: number;
  includeMetrics: boolean;
  includeLogs: boolean;
  includeClientData: boolean;
}

export interface AppSettings {
  connection: ConnectionSettings;
  ui: UISettings;
  monitoring: MonitoringSettings;
  security: SecuritySettings;
  export: ExportSettings;
}

interface SettingsContextType {
  settings: AppSettings;
  updateSettings: (
    category: keyof AppSettings,
    newSettings: Partial<any>,
  ) => void;
  resetSettings: (category?: keyof AppSettings) => void;
  exportSettings: () => string;
  importSettings: (settingsJson: string) => boolean;
  saveSettings: () => void;
  loadSettings: () => void;
}

const defaultSettings: AppSettings = {
  connection: {
    websocketUrl: "", // Will be determined dynamically from window.location
    websocketPort: 8000,
    apiEndpoint: "/api", // Using relative URL
    connectionTimeout: 5000,
    reconnectInterval: 3000,
    maxReconnectAttempts: 5,
  },
  ui: {
    theme: "system",
    language: "uk",
    refreshInterval: 5000,
    dateFormat: "dd/mm/yyyy",
    timeFormat: "24h",
    compactMode: false,
  },
  monitoring: {
    enableNotifications: true,
    notifyOnErrors: true,
    notifyOnNewClients: true,
    notifyOnDisconnects: false,
    logLevel: "info",
    maxLogEntries: 1000,
    enableMetrics: true,
    metricsInterval: 1000,
    showCpuUsage: true,
    showMemoryUsage: true,
    showNetworkUsage: true,
  },
  security: {
    enableAuth: false,
    sessionTimeout: 3600,
    requireTwoFactor: false,
    allowedIPs: ["127.0.0.1", "::1"],
    enableAuditLog: true,
    passwordPolicy: {
      minLength: 8,
      requireUppercase: true,
      requireNumbers: true,
      requireSymbols: false,
    },
  },
  export: {
    autoExportLogs: false,
    exportFormat: "json",
    exportInterval: "daily",
    maxExportSize: 10,
    includeMetrics: true,
    includeLogs: true,
    includeClientData: false,
  },
};

const SettingsContext = createContext<SettingsContextType | undefined>(
  undefined,
);

export const useSettings = (): SettingsContextType => {
  const context = useContext(SettingsContext);
  if (!context) {
    throw new Error("useSettings must be used within a SettingsProvider");
  }
  return context;
};

interface SettingsProviderProps {
  children: ReactNode;
}

export const SettingsProvider: React.FC<SettingsProviderProps> = ({
  children,
}) => {
  const [settings, setSettings] = useState<AppSettings>(defaultSettings);

  const updateSettings = (
    category: keyof AppSettings,
    newSettings: Partial<any>,
  ) => {
    setSettings((prev) => ({
      ...prev,
      [category]: {
        ...prev[category],
        ...newSettings,
      },
    }));
  };

  const resetSettings = (category?: keyof AppSettings) => {
    if (category) {
      setSettings((prev) => ({
        ...prev,
        [category]: defaultSettings[category],
      }));
    } else {
      setSettings(defaultSettings);
    }
  };

  const exportSettings = (): string => {
    return JSON.stringify(settings, null, 2);
  };

  const importSettings = (settingsJson: string): boolean => {
    try {
      const imported = JSON.parse(settingsJson);
      // Валідація структури
      if (imported && typeof imported === "object") {
        setSettings({ ...defaultSettings, ...imported });
        return true;
      }
      return false;
    } catch {
      return false;
    }
  };

  const saveSettings = () => {
    try {
      localStorage.setItem("tetracore-settings", JSON.stringify(settings));
    } catch (error) {
      console.error("Failed to save settings:", error);
    }
  };

  const loadSettings = () => {
    try {
      const saved = localStorage.getItem("tetracore-settings");
      if (saved) {
        const parsed = JSON.parse(saved);
        setSettings({ ...defaultSettings, ...parsed });
      }
    } catch (error) {
      console.error("Failed to load settings:", error);
    }
  };

  useEffect(() => {
    loadSettings();
  }, []);

  useEffect(() => {
    saveSettings();
  }, [settings]);

  const value: SettingsContextType = {
    settings,
    updateSettings,
    resetSettings,
    exportSettings,
    importSettings,
    saveSettings,
    loadSettings,
  };

  return (
    <SettingsContext.Provider value={value}>
      {children}
    </SettingsContext.Provider>
  );
};
