import React, { useEffect, useState, useRef } from "react";

interface LogEntry {
  timestamp: string;
  level: string;
  message: string;
}

const fetchLogs = async (): Promise<LogEntry[]> => {
  try {
    const res = await fetch("/dashboard/api/system-logs");
    if (!res.ok) return [];
    const data = await res.json();
    return data.logs || [];
  } catch {
    return [];
  }
};

const ConsoleLogs: React.FC = () => {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const logsEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let mounted = true;
    const loadLogs = async () => {
      setLoading(true);
      const data = await fetchLogs();
      if (mounted) setLogs(data);
      setLoading(false);
    };
    loadLogs();
    const interval = setInterval(loadLogs, 5000); // Оновлення кожні 5 сек
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  return (
    <div className="bg-black rounded-xl shadow-lg p-4 h-[60vh] overflow-y-auto text-xs text-green-200 font-mono">
      <div className="mb-2 text-slate-200 font-bold">Console Logs</div>
      {loading && <div className="text-slate-400">Завантаження логів...</div>}
      {logs.map((log, idx) => (
        <div key={idx} className="whitespace-pre-wrap">
          <span className="text-slate-400">[{log.timestamp}]</span> <span className={
            log.level === "error"
              ? "text-red-400"
              : log.level === "warn"
              ? "text-yellow-300"
              : "text-green-200"
          }>[{log.level.toUpperCase()}]</span> {log.message}
        </div>
      ))}
      <div ref={logsEndRef} />
    </div>
  );
};

export default ConsoleLogs;