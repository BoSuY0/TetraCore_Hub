import React, { useEffect, useState, useRef, useCallback } from "react";

interface LogEntry {
  timestamp: string;
  level: "info" | "warn" | "error" | "debug";
  message: string;
  source: "backend" | "frontend";
}

// ---------------------------------------------------------------------------
// Backend log fetching helper
// ---------------------------------------------------------------------------

const fetchBackendLogs = async (limit = 200): Promise<LogEntry[]> => {
  try {
    const res = await fetch(`/dashboard/api/system-logs?limit=${limit}`);
    if (!res.ok) return [];
    const { logs = [] } = await res.json();
    return (logs as any[]).map((l) => ({
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

const MAX_LOGS = 1000;

const ConsoleLogs: React.FC = () => {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [autoScroll, setAutoScroll] = useState(true);
  const [showFrontend, setShowFrontend] = useState(true);
  const [showBackend, setShowBackend] = useState(true);
  const logsEndRef = useRef<HTMLDivElement>(null);

  // -----------------------------------------------------------------------
  // Helper to add new log entries (merging + truncating)
  // -----------------------------------------------------------------------

  const appendLogs = useCallback((newEntries: LogEntry[]) => {
    setLogs((prev) => {
      const combined = [...prev, ...newEntries];
      // Keep only the last MAX_LOGS items
      if (combined.length > MAX_LOGS) {
        return combined.slice(combined.length - MAX_LOGS);
      }
      return combined;
    });
  }, []);

  // -----------------------------------------------------------------------
  // Capture frontend console.* calls
  // -----------------------------------------------------------------------

  useEffect(() => {
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

        appendLogs([
          {
            timestamp: new Date().toISOString(),
            level:
              method === "log" || method === "info"
                ? "info"
                : (method as "warn" | "error" | "debug"),
            message,
            source: "frontend",
          },
        ]);

        // Call original
        (originalConsole as any)[method](...args);
      };
    });

    return () => {
      // Restore original console methods
      interceptedMethods.forEach((method) => {
        (console as any)[method] = originalConsole[method];
      });
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

      // We append only *new* backend logs (by comparing timestamp/message pairs)
      setLogs((prev) => {
        const seen = new Set(prev.map((l) => `${l.timestamp}|${l.message}`));
        const newOnes = backendLogs.filter(
          (l) => !seen.has(`${l.timestamp}|${l.message}`)
        );
        if (!newOnes.length) return prev;
        const combined = [...prev, ...newOnes];
        if (combined.length > MAX_LOGS) {
          return combined.slice(combined.length - MAX_LOGS);
        }
        return combined;
      });

      if (loading) setLoading(false);
    };

    loadBackendLogs();
    const interval = setInterval(loadBackendLogs, 5000); // кожні 5 секунд

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
  // Derived view (apply source filters)
  // -----------------------------------------------------------------------

  const visibleLogs = logs.filter((l) => {
    if (l.source === "backend" && !showBackend) return false;
    if (l.source === "frontend" && !showFrontend) return false;
    return true;
  });

  // -----------------------------------------------------------------------
  // Render
  // -----------------------------------------------------------------------

  const levelColor = (level: string) => {
    switch (level) {
      case "error":
        return "text-red-400";
      case "warn":
        return "text-yellow-300";
      case "debug":
        return "text-sky-400";
      default:
        return "text-green-200";
    }
  };

  return (
    <div className="bg-black rounded-xl shadow-lg p-4 h-[70vh] flex flex-col">
      {/* Toolbar */}
      <div className="flex items-center justify-between mb-3 text-xs text-slate-300">
        <div className="space-x-3">
          <label className="inline-flex items-center space-x-1 cursor-pointer">
            <input
              type="checkbox"
              checked={showBackend}
              onChange={(e) => setShowBackend(e.target.checked)}
            />
            <span>Backend</span>
          </label>
          <label className="inline-flex items-center space-x-1 cursor-pointer">
            <input
              type="checkbox"
              checked={showFrontend}
              onChange={(e) => setShowFrontend(e.target.checked)}
            />
            <span>Frontend</span>
          </label>
        </div>
        <div className="space-x-2">
          <button
            className="px-2 py-1 bg-slate-700 text-white rounded-md hover:bg-slate-600"
            onClick={() => setLogs([])}
          >
            Clear
          </button>
          <button
            className="px-2 py-1 bg-slate-700 text-white rounded-md hover:bg-slate-600"
            onClick={() => setAutoScroll((v) => !v)}
          >
            {autoScroll ? "Pause" : "Auto-scroll"}
          </button>
        </div>
      </div>

      {/* Log area */}
      <div className="flex-1 overflow-y-auto text-xs font-mono pr-1">
        {loading && (
          <div className="text-slate-400">Завантаження логів…</div>
        )}
        {visibleLogs.map((log, idx) => (
          <div key={idx} className="whitespace-pre-wrap break-all">
            <span className="text-slate-400">[{log.timestamp}]</span>{" "}
            <span className={`${levelColor(log.level)} font-semibold`}>
              [{log.level.toUpperCase()}]
            </span>{" "}
            <span
              className={
                log.source === "backend" ? "text-emerald-300" : "text-indigo-300"
              }
            >
              ({log.source})
            </span>{" "}
            {log.message}
          </div>
        ))}
        <div ref={logsEndRef} />
      </div>
    </div>
  );
};

export default ConsoleLogs;