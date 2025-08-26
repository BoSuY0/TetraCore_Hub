import React, { useEffect, useState, useRef, useCallback } from "react";

interface LogEntry {
  timestamp: string;
  level: "info" | "warn" | "error" | "debug";
  message: string;
  source: "backend" | "frontend";
  id: string; // Додаємо унікальний ID для кращого керування
}

// ---------------------------------------------------------------------------
// Local Storage helpers for log persistence
// ---------------------------------------------------------------------------

const LOGS_STORAGE_KEY = 'tetracore_console_logs';
const MAX_LOGS = 2000; // Збільшуємо ліміт логів

const saveLogsToStorage = (logs: LogEntry[]) => {
  try {
    localStorage.setItem(LOGS_STORAGE_KEY, JSON.stringify(logs));
  } catch (error) {
    console.warn('Failed to save logs to localStorage:', error);
  }
};

const loadLogsFromStorage = (): LogEntry[] => {
  try {
    const stored = localStorage.getItem(LOGS_STORAGE_KEY);
    return stored ? JSON.parse(stored) : [];
  } catch (error) {
    console.warn('Failed to load logs from localStorage:', error);
    return [];
  }
};

// ---------------------------------------------------------------------------
// Backend log fetching helper
// ---------------------------------------------------------------------------

const fetchBackendLogs = async (limit = 200): Promise<LogEntry[]> => {
  try {
    const res = await fetch(`/api/frontend/system-logs?limit=${limit}`);
    if (!res.ok) return [];
    const { logs = [] } = await res.json();
    return (logs as any[]).map((l) => ({
      id: `backend_${l.timestamp}_${Math.random().toString(36).substr(2, 9)}`,
      timestamp: l.timestamp ?? new Date().toISOString(),
      level: ((l.level ?? "info").toLowerCase() as LogEntry["level"]),
      message: l.message ?? "",
      source: "backend" as const,
    }));
  } catch {
    return [];
  }
};

// ---------------------------------------------------------------------------
// Console component
// ---------------------------------------------------------------------------

const ConsoleLogs: React.FC = () => {
  const [logs, setLogs] = useState<LogEntry[]>(() => loadLogsFromStorage());
  const [loading, setLoading] = useState(true);
  const [autoScroll, setAutoScroll] = useState(true);
  const [showFrontend, setShowFrontend] = useState(true);
  const [showBackend, setShowBackend] = useState(true);
  const [searchTerm, setSearchTerm] = useState("");
  const [selectedLevel, setSelectedLevel] = useState<string>("all");
  const logsEndRef = useRef<HTMLDivElement>(null);
  const consoleIntercepted = useRef(false);

  // -----------------------------------------------------------------------
  // Helper to add new log entries with persistence
  // -----------------------------------------------------------------------

  const appendLogs = useCallback((newEntries: LogEntry[]) => {
    setLogs((prev) => {
      const combined = [...prev, ...newEntries];
      // Keep only the last MAX_LOGS items
      const trimmed = combined.length > MAX_LOGS 
        ? combined.slice(combined.length - MAX_LOGS)
        : combined;
      
      // Save to localStorage
      saveLogsToStorage(trimmed);
      return trimmed;
    });
  }, []);

  // -----------------------------------------------------------------------
  // Clear all logs
  // -----------------------------------------------------------------------

  const clearLogs = useCallback(() => {
    setLogs([]);
    saveLogsToStorage([]);
  }, []);

  // -----------------------------------------------------------------------
  // Capture frontend console.* calls
  // -----------------------------------------------------------------------

  useEffect(() => {
    if (consoleIntercepted.current) return;
    
    const originalConsole: Record<string, any> = {
      log: console.log,
      info: console.info,
      warn: console.warn,
      error: console.error,
      debug: console.debug,
    };

    const interceptedMethods: (keyof typeof originalConsole)[] = [
      "log",
      "info",
      "warn",
      "error",
      "debug",
    ];

    interceptedMethods.forEach((method) => {
      (console as any)[method] = (...args: unknown[]) => {
        // Stringify args similar to native console
        const message = args
          .map((a) => {
            if (typeof a === "string") return a;
            try {
              return JSON.stringify(a, null, 2);
            } catch {
              return String(a);
            }
          })
          .join(" ");

        const logEntry: LogEntry = {
          id: `frontend_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
          timestamp: new Date().toISOString(),
          level: method === "log" || method === "info" 
            ? "info" 
            : (method as "warn" | "error" | "debug"),
          message,
          source: "frontend",
        };

        appendLogs([logEntry]);

        // Call original
        (originalConsole as any)[method](...args);
      };
    });

    consoleIntercepted.current = true;

    return () => {
      // Restore original console methods
      interceptedMethods.forEach((method) => {
        (console as any)[method] = originalConsole[method];
      });
      consoleIntercepted.current = false;
    };
  }, [appendLogs]);

  // -----------------------------------------------------------------------
  // Periodically fetch backend logs
  // -----------------------------------------------------------------------

  useEffect(() => {
    let mounted = true;

    const loadBackendLogs = async () => {
      const backendLogs = await fetchBackendLogs();
      if (!mounted) return;

      // We append only *new* backend logs
      setLogs((prev) => {
        const seen = new Set(prev.map((l) => l.id));
        const newOnes = backendLogs.filter((l) => !seen.has(l.id));
        
        if (!newOnes.length) return prev;
        
        const combined = [...prev, ...newOnes];
        const trimmed = combined.length > MAX_LOGS 
          ? combined.slice(combined.length - MAX_LOGS)
          : combined;
        
        saveLogsToStorage(trimmed);
        return trimmed;
      });

      if (loading) setLoading(false);
    };

    loadBackendLogs();
    const interval = setInterval(loadBackendLogs, 5000);

    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, [loading]);

  // -----------------------------------------------------------------------
  // Auto-scroll handling
  // -----------------------------------------------------------------------

  useEffect(() => {
    if (autoScroll) {
      logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [logs, autoScroll]);

  // -----------------------------------------------------------------------
  // Filter logs based on search and level
  // -----------------------------------------------------------------------

  const filteredLogs = logs.filter((log) => {
    // Source filter
    if (log.source === "backend" && !showBackend) return false;
    if (log.source === "frontend" && !showFrontend) return false;
    
    // Level filter
    if (selectedLevel !== "all" && log.level !== selectedLevel) return false;
    
    // Search filter
    if (searchTerm && !log.message.toLowerCase().includes(searchTerm.toLowerCase())) {
      return false;
    }
    
    return true;
  });

  // -----------------------------------------------------------------------
  // Level colors with better contrast
  // -----------------------------------------------------------------------

  const getLevelStyles = (level: string) => {
    switch (level) {
      case "error":
        return "text-red-300 bg-red-900/20 border-red-500/30";
      case "warn":
        return "text-yellow-300 bg-yellow-900/20 border-yellow-500/30";
      case "debug":
        return "text-blue-300 bg-blue-900/20 border-blue-500/30";
      default:
        return "text-green-300 bg-green-900/20 border-green-500/30";
    }
  };

  const getSourceColor = (source: string) => {
    return source === "backend" 
      ? "text-emerald-400 bg-emerald-900/20" 
      : "text-indigo-400 bg-indigo-900/20";
  };

  // -----------------------------------------------------------------------
  // Format timestamp
  // -----------------------------------------------------------------------

  const formatTimestamp = (timestamp: string) => {
    try {
      return new Date(timestamp).toLocaleTimeString('uk-UA', {
        hour12: false,
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        fractionalSecondDigits: 3
      });
    } catch {
      return timestamp;
    }
  };

  return (
    <div className="bg-gray-900 border border-gray-700 rounded-xl shadow-2xl p-6 h-[85vh] flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between mb-4 pb-4 border-b border-gray-700">
        <h2 className="text-xl font-semibold text-white flex items-center gap-2">
          <span className="w-3 h-3 bg-green-400 rounded-full animate-pulse"></span>
          TetraCore Console
        </h2>
        <div className="text-sm text-gray-400">
          {filteredLogs.length} / {logs.length} логів
        </div>
      </div>

      {/* Filters and Controls */}
      <div className="flex flex-col sm:flex-row gap-3 mb-4 pb-4 border-b border-gray-700">
        {/* Search */}
        <div className="flex-1">
          <input
            type="text"
            placeholder="Пошук в логах..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full px-3 py-2 bg-gray-800 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
          />
        </div>

        {/* Level Filter */}
        <select
          value={selectedLevel}
          onChange={(e) => setSelectedLevel(e.target.value)}
          className="px-3 py-2 bg-gray-800 border border-gray-600 rounded-lg text-white focus:outline-none focus:border-blue-500"
        >
          <option value="all">Всі рівні</option>
          <option value="info">Info</option>
          <option value="warn">Warning</option>
          <option value="error">Error</option>
          <option value="debug">Debug</option>
        </select>

        {/* Source Filters */}
        <div className="flex gap-3 items-center">
          <label className="inline-flex items-center gap-2 cursor-pointer text-sm text-gray-300">
            <input
              type="checkbox"
              checked={showBackend}
              onChange={(e) => setShowBackend(e.target.checked)}
              className="rounded border-gray-600 bg-gray-800 text-emerald-500 focus:ring-emerald-500 focus:ring-offset-gray-900"
            />
            <span className="px-2 py-1 bg-emerald-900/20 text-emerald-400 rounded text-xs">Backend</span>
          </label>
          <label className="inline-flex items-center gap-2 cursor-pointer text-sm text-gray-300">
            <input
              type="checkbox"
              checked={showFrontend}
              onChange={(e) => setShowFrontend(e.target.checked)}
              className="rounded border-gray-600 bg-gray-800 text-indigo-500 focus:ring-indigo-500 focus:ring-offset-gray-900"
            />
            <span className="px-2 py-1 bg-indigo-900/20 text-indigo-400 rounded text-xs">Frontend</span>
          </label>
        </div>
      </div>

      {/* Action Buttons */}
      <div className="flex gap-2 mb-4">
        <button
          className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg transition-colors duration-200 text-sm font-medium"
          onClick={clearLogs}
        >
          🗑️ Очистити
        </button>
        <button
          className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors duration-200 text-sm font-medium"
          onClick={() => setAutoScroll((v) => !v)}
        >
          {autoScroll ? "⏸️ Пауза" : "▶️ Авто-скрол"}
        </button>
        <button
          className="px-4 py-2 bg-gray-600 hover:bg-gray-700 text-white rounded-lg transition-colors duration-200 text-sm font-medium"
          onClick={() => {
            const dataStr = JSON.stringify(logs, null, 2);
            const dataBlob = new Blob([dataStr], { type: 'application/json' });
            const url = URL.createObjectURL(dataBlob);
            const link = document.createElement('a');
            link.href = url;
            link.download = `tetracore-logs-${new Date().toISOString().split('T')[0]}.json`;
            link.click();
            URL.revokeObjectURL(url);
          }}
        >
          💾 Завантажити
        </button>
      </div>

      {/* Log Display Area */}
      <div className="flex-1 overflow-y-auto bg-gray-950 rounded-lg border border-gray-800 p-4">
        {loading && (
          <div className="text-gray-400 text-center py-8">
            <div className="animate-spin w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full mx-auto mb-2"></div>
            Завантаження логів…
          </div>
        )}
        
        {!loading && filteredLogs.length === 0 && (
          <div className="text-gray-500 text-center py-8">
            {logs.length === 0 ? "Логи поки що відсутні" : "Немає логів що відповідають фільтрам"}
          </div>
        )}

        <div className="space-y-1 font-mono text-sm">
          {filteredLogs.map((log) => (
            <div 
              key={log.id} 
              className={`p-2 rounded border-l-4 ${getLevelStyles(log.level)} hover:bg-gray-800/50 transition-colors duration-150`}
            >
              <div className="flex items-start gap-3">
                <span className="text-gray-400 text-xs whitespace-nowrap">
                  {formatTimestamp(log.timestamp)}
                </span>
                <span className={`px-2 py-0.5 rounded text-xs font-semibold ${getLevelStyles(log.level)}`}>
                  {log.level.toUpperCase()}
                </span>
                <span className={`px-2 py-0.5 rounded text-xs ${getSourceColor(log.source)}`}>
                  {log.source}
                </span>
                <div className="flex-1 whitespace-pre-wrap break-all text-gray-200 leading-relaxed">
                  {log.message}
                </div>
              </div>
            </div>
          ))}
        </div>
        <div ref={logsEndRef} />
      </div>
    </div>
  );
};

export default ConsoleLogs;