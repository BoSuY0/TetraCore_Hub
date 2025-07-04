import React from "react";

interface IconProps {
  className?: string;
  size?: "sm" | "md" | "lg" | "xl";
}

const sizeClasses = {
  sm: "w-4 h-4",
  md: "w-5 h-5",
  lg: "w-6 h-6",
  xl: "w-8 h-8",
};

// Dashboard Icon - простий і зрозумілий варіант з квадратами
export const DashboardIcon: React.FC<IconProps> = ({
  className = "",
  size = "lg",
}) => (
  <svg
    className={`${sizeClasses[size]} ${className}`}
    fill="none"
    stroke="currentColor"
    viewBox="0 0 24 24"
    strokeWidth={2}
  >
    <rect
      x="3"
      y="3"
      width="7"
      height="7"
      rx="1"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <rect
      x="14"
      y="3"
      width="7"
      height="7"
      rx="1"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <rect
      x="14"
      y="14"
      width="7"
      height="7"
      rx="1"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <rect
      x="3"
      y="14"
      width="7"
      height="7"
      rx="1"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

// Users/Clients Icon - простіша і зрозуміліша іконка людей
export const UsersIcon: React.FC<IconProps> = ({
  className = "",
  size = "lg",
}) => (
  <svg
    className={`${sizeClasses[size]} ${className}`}
    fill="none"
    stroke="currentColor"
    viewBox="0 0 24 24"
    strokeWidth={2}
  >
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"
    />
    <circle cx="9" cy="7" r="4" strokeLinecap="round" strokeLinejoin="round" />
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="m22 21-3-3m0 0a2 2 0 0 0 0-4 2 2 0 0 0 0 4Z"
    />
  </svg>
);

// Tasks Icon - простіша іконка зі списком завдань
export const TasksIcon: React.FC<IconProps> = ({
  className = "",
  size = "lg",
}) => (
  <svg
    className={`${sizeClasses[size]} ${className}`}
    fill="none"
    stroke="currentColor"
    viewBox="0 0 24 24"
    strokeWidth={2}
  >
    <rect
      x="3"
      y="5"
      width="18"
      height="14"
      rx="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <path strokeLinecap="round" strokeLinejoin="round" d="m9 11 2 2 4-4" />
  </svg>
);

// Metrics/Charts Icon - простіша іконка з графіком
export const MetricsIcon: React.FC<IconProps> = ({
  className = "",
  size = "lg",
}) => (
  <svg
    className={`${sizeClasses[size]} ${className}`}
    fill="none"
    stroke="currentColor"
    viewBox="0 0 24 24"
    strokeWidth={2}
  >
    <path strokeLinecap="round" strokeLinejoin="round" d="M3 3v18h18" />
    <path strokeLinecap="round" strokeLinejoin="round" d="m19 9-5 5-4-4-3 3" />
  </svg>
);

// Settings Icon - простіша іконка налаштувань
export const SettingsIcon: React.FC<IconProps> = ({
  className = "",
  size = "lg",
}) => (
  <svg
    className={`${sizeClasses[size]} ${className}`}
    fill="none"
    stroke="currentColor"
    viewBox="0 0 24 24"
    strokeWidth={2}
  >
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M12 20a8 8 0 1 0 0-16 8 8 0 0 0 0 16Z"
    />
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M12 14a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z"
    />
    <path strokeLinecap="round" strokeLinejoin="round" d="M12 2v2" />
    <path strokeLinecap="round" strokeLinejoin="round" d="M12 20v2" />
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="m4.93 4.93 1.41 1.41"
    />
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="m17.66 17.66 1.41 1.41"
    />
    <path strokeLinecap="round" strokeLinejoin="round" d="M2 12h2" />
    <path strokeLinecap="round" strokeLinejoin="round" d="M20 12h2" />
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="m6.34 17.66-1.41 1.41"
    />
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="m19.07 4.93-1.41 1.41"
    />
  </svg>
);

// Bot Icon - більш сучасна іконка робота
export const BotIcon: React.FC<IconProps> = ({
  className = "",
  size = "lg",
}) => (
  <svg
    className={`${sizeClasses[size]} ${className}`}
    fill="none"
    stroke="currentColor"
    viewBox="0 0 24 24"
    strokeWidth={2}
  >
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M12 2a2 2 0 0 1 2 2c0 .74-.4 1.39-1 1.73V7h4a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2h4V5.73c-.6-.34-1-.99-1-1.73a2 2 0 0 1 2-2Z"
    />
    <circle cx="9" cy="12" r="1" />
    <circle cx="15" cy="12" r="1" />
    <path strokeLinecap="round" strokeLinejoin="round" d="M9 16h6" />
  </svg>
);

// Worker Icon - іконка працівника/інструментів
export const WorkerIcon: React.FC<IconProps> = ({
  className = "",
  size = "lg",
}) => (
  <svg
    className={`${sizeClasses[size]} ${className}`}
    fill="none"
    stroke="currentColor"
    viewBox="0 0 24 24"
    strokeWidth={2}
  >
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"
    />
  </svg>
);

// API Worker Icon - іконка API/хмари
export const ApiWorkerIcon: React.FC<IconProps> = ({
  className = "",
  size = "lg",
}) => (
  <svg
    className={`${sizeClasses[size]} ${className}`}
    fill="none"
    stroke="currentColor"
    viewBox="0 0 24 24"
    strokeWidth={2}
  >
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"
    />
    <path strokeLinecap="round" strokeLinejoin="round" d="M12 12h.01" />
    <path strokeLinecap="round" strokeLinejoin="round" d="M8 12h.01" />
    <path strokeLinecap="round" strokeLinejoin="round" d="M16 12h.01" />
  </svg>
);

// Stream Hub Icon - іконка потоку/мережі
export const StreamHubIcon: React.FC<IconProps> = ({
  className = "",
  size = "lg",
}) => (
  <svg
    className={`${sizeClasses[size]} ${className}`}
    fill="none"
    stroke="currentColor"
    viewBox="0 0 24 24"
    strokeWidth={2}
  >
    <circle cx="12" cy="12" r="3" />
    <path strokeLinecap="round" strokeLinejoin="round" d="M12 1v6m0 6v6" />
    <path strokeLinecap="round" strokeLinejoin="round" d="m21 5-6 6 6 6" />
    <path strokeLinecap="round" strokeLinejoin="round" d="m3 5 6 6-6 6" />
  </svg>
);

// Monitor Icon - іконка монітора
export const MonitorIcon: React.FC<IconProps> = ({
  className = "",
  size = "lg",
}) => (
  <svg
    className={`${sizeClasses[size]} ${className}`}
    fill="none"
    stroke="currentColor"
    viewBox="0 0 24 24"
    strokeWidth={2}
  >
    <rect
      x="2"
      y="3"
      width="20"
      height="14"
      rx="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <path strokeLinecap="round" strokeLinejoin="round" d="m8 21 4-4 4 4" />
  </svg>
);

// Admin Icon - іконка адміністратора
export const AdminIcon: React.FC<IconProps> = ({
  className = "",
  size = "lg",
}) => (
  <svg
    className={`${sizeClasses[size]} ${className}`}
    fill="none"
    stroke="currentColor"
    viewBox="0 0 24 24"
    strokeWidth={2}
  >
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z"
    />
    <path strokeLinecap="round" strokeLinejoin="round" d="M12 2v2" />
    <path strokeLinecap="round" strokeLinejoin="round" d="M12 20v2" />
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="m4.93 4.93 1.41 1.41"
    />
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="m17.66 17.66 1.41 1.41"
    />
    <path strokeLinecap="round" strokeLinejoin="round" d="M2 12h2" />
    <path strokeLinecap="round" strokeLinejoin="round" d="M20 12h2" />
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="m6.34 17.66-1.41 1.41"
    />
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="m19.07 4.93-1.41 1.41"
    />
  </svg>
);

// Status Icons
export const CheckIcon: React.FC<IconProps> = ({
  className = "",
  size = "lg",
}) => (
  <svg
    className={`${sizeClasses[size]} ${className}`}
    fill="none"
    stroke="currentColor"
    viewBox="0 0 24 24"
    strokeWidth={2}
  >
    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
  </svg>
);

export const ClockIcon: React.FC<IconProps> = ({
  className = "",
  size = "lg",
}) => (
  <svg
    className={`${sizeClasses[size]} ${className}`}
    fill="none"
    stroke="currentColor"
    viewBox="0 0 24 24"
    strokeWidth={2}
  >
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
    />
  </svg>
);

export const AlertIcon: React.FC<IconProps> = ({
  className = "",
  size = "lg",
}) => (
  <svg
    className={`${sizeClasses[size]} ${className}`}
    fill="none"
    stroke="currentColor"
    viewBox="0 0 24 24"
    strokeWidth={2}
  >
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
    />
  </svg>
);

export const ProcessingIcon: React.FC<IconProps> = ({
  className = "",
  size = "lg",
}) => (
  <svg
    className={`${sizeClasses[size]} ${className}`}
    fill="none"
    stroke="currentColor"
    viewBox="0 0 24 24"
    strokeWidth={2}
  >
    <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6l4 2" />
    <circle cx="12" cy="12" r="10" />
  </svg>
);

// Utility Icons
export const RefreshIcon: React.FC<IconProps> = ({
  className = "",
  size = "lg",
}) => (
  <svg
    className={`${sizeClasses[size]} ${className}`}
    fill="none"
    stroke="currentColor"
    viewBox="0 0 24 24"
    strokeWidth={2}
  >
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"
    />
    <path strokeLinecap="round" strokeLinejoin="round" d="M21 3v5h-5" />
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"
    />
    <path strokeLinecap="round" strokeLinejoin="round" d="M8 16H3v5" />
  </svg>
);

export const NotificationIcon: React.FC<IconProps> = ({
  className = "",
  size = "lg",
}) => (
  <svg
    className={`${sizeClasses[size]} ${className}`}
    fill="none"
    stroke="currentColor"
    viewBox="0 0 24 24"
    strokeWidth={2}
  >
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M14.857 17.082a23.848 23.848 0 0 0 5.454-1.31A8.967 8.967 0 0 1 18 9.75V9A6 6 0 0 0 6 9v.75a8.967 8.967 0 0 1-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 0 1-5.714 0m5.714 0a3 3 0 1 1-5.714 0"
    />
  </svg>
);

export const MenuIcon: React.FC<IconProps> = ({
  className = "",
  size = "lg",
}) => (
  <svg
    className={`${sizeClasses[size]} ${className}`}
    fill="none"
    stroke="currentColor"
    viewBox="0 0 24 24"
    strokeWidth={2}
  >
    <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5" />
    <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 12h16.5" />
    <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 17.25h16.5" />
  </svg>
);

export const CloseIcon: React.FC<IconProps> = ({
  className = "",
  size = "lg",
}) => (
  <svg
    className={`${sizeClasses[size]} ${className}`}
    fill="none"
    stroke="currentColor"
    viewBox="0 0 24 24"
    strokeWidth={2}
  >
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M6 18 18 6M6 6l12 12"
    />
  </svg>
);

// CPU/Performance Icon - покращена іконка процесора
export const CpuIcon: React.FC<IconProps> = ({
  className = "",
  size = "lg",
}) => (
  <svg
    className={`${sizeClasses[size]} ${className}`}
    fill="none"
    stroke="currentColor"
    viewBox="0 0 24 24"
    strokeWidth={2}
  >
    <rect x="4" y="4" width="16" height="16" rx="2" />
    <rect x="9" y="9" width="6" height="6" />
    <path strokeLinecap="round" strokeLinejoin="round" d="M9 2v2" />
    <path strokeLinecap="round" strokeLinejoin="round" d="M15 2v2" />
    <path strokeLinecap="round" strokeLinejoin="round" d="M9 20v2" />
    <path strokeLinecap="round" strokeLinejoin="round" d="M15 20v2" />
    <path strokeLinecap="round" strokeLinejoin="round" d="M2 9h2" />
    <path strokeLinecap="round" strokeLinejoin="round" d="M2 15h2" />
    <path strokeLinecap="round" strokeLinejoin="round" d="M20 9h2" />
    <path strokeLinecap="round" strokeLinejoin="round" d="M20 15h2" />
  </svg>
);

// Arrow Up Icon (for increases)
export const ArrowUpIcon: React.FC<IconProps> = ({
  className = "",
  size = "lg",
}) => (
  <svg
    className={`${sizeClasses[size]} ${className}`}
    fill="none"
    stroke="currentColor"
    viewBox="0 0 24 24"
    strokeWidth={2}
  >
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M7 17l9.2-9.2M17 17V7H7"
    />
  </svg>
);

// Arrow Down Icon (for decreases)
export const ArrowDownIcon: React.FC<IconProps> = ({
  className = "",
  size = "lg",
}) => (
  <svg
    className={`${sizeClasses[size]} ${className}`}
    fill="none"
    stroke="currentColor"
    viewBox="0 0 24 24"
    strokeWidth={2}
  >
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M17 7l-9.2 9.2M7 7v10h10"
    />
  </svg>
);

// Error Icon (for error states)
export const ErrorIcon: React.FC<IconProps> = ({
  className = "",
  size = "lg",
}) => (
  <svg
    className={`${sizeClasses[size]} ${className}`}
    fill="none"
    stroke="currentColor"
    viewBox="0 0 24 24"
    strokeWidth={2}
  >
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
    />
  </svg>
);

// Success Icon (for success states)
export const SuccessIcon: React.FC<IconProps> = ({
  className = "",
  size = "lg",
}) => (
  <svg
    className={`${sizeClasses[size]} ${className}`}
    fill="none"
    stroke="currentColor"
    viewBox="0 0 24 24"
    strokeWidth={2}
  >
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"
    />
  </svg>
);

// Warning Icon (for warning states)
export const WarningIcon: React.FC<IconProps> = ({
  className = "",
  size = "lg",
}) => (
  <svg
    className={`${sizeClasses[size]} ${className}`}
    fill="none"
    stroke="currentColor"
    viewBox="0 0 24 24"
    strokeWidth={2}
  >
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"
    />
  </svg>
);

// Info Icon (for information states)
export const InfoIcon: React.FC<IconProps> = ({
  className = "",
  size = "lg",
}) => (
  <svg
    className={`${sizeClasses[size]} ${className}`}
    fill="none"
    stroke="currentColor"
    viewBox="0 0 24 24"
    strokeWidth={2}
  >
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M11.25 11.25l.041-.02a.75.75 0 011.063.852l-.708 2.836a.75.75 0 001.063.853l.041-.021M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9-3.75h.008v.008H12V8.25z"
    />
  </svg>
);

// Loading/Spinner Icon (for loading states)
export const LoadingIcon: React.FC<IconProps> = ({
  className = "",
  size = "lg",
}) => (
  <svg
    className={`${sizeClasses[size]} ${className} animate-spin`}
    fill="none"
    stroke="currentColor"
    viewBox="0 0 24 24"
    strokeWidth={2}
  >
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
    />
  </svg>
);

// Network/Connection Icon (for connectivity states)
export const NetworkIcon: React.FC<IconProps> = ({
  className = "",
  size = "lg",
}) => (
  <svg
    className={`${sizeClasses[size]} ${className}`}
    fill="none"
    stroke="currentColor"
    viewBox="0 0 24 24"
    strokeWidth={2}
  >
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M8.288 15.038a5.25 5.25 0 017.424 0M5.106 11.856c3.807-3.808 9.98-3.808 13.788 0M1.924 8.674c5.565-5.565 14.587-5.565 20.152 0M12.53 18.22l-.53.53-.53-.53a.75.75 0 011.06 0z"
    />
  </svg>
);

// Database Icon (for storage/data states)
export const DatabaseIcon: React.FC<IconProps> = ({
  className = "",
  size = "lg",
}) => (
  <svg
    className={`${sizeClasses[size]} ${className}`}
    fill="none"
    stroke="currentColor"
    viewBox="0 0 24 24"
    strokeWidth={2}
  >
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375m16.5 0v3.75m-16.5-3.75v3.75m16.5 0v3.75C20.25 16.153 16.556 18 12 18s-8.25-1.847-8.25-4.125v-3.75m16.5 0c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125"
    />
  </svg>
);

// Memory Icon (for memory/RAM states)
export const MemoryIcon: React.FC<IconProps> = ({
  className = "",
  size = "lg",
}) => (
  <svg
    className={`${sizeClasses[size]} ${className}`}
    fill="none"
    stroke="currentColor"
    viewBox="0 0 24 24"
    strokeWidth={2}
  >
    <rect x="2" y="6" width="20" height="12" rx="2" />
    <path strokeLinecap="round" strokeLinejoin="round" d="M6 10h4m4 0h4" />
    <path strokeLinecap="round" strokeLinejoin="round" d="M6 14h8" />
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M2 10h-1m1 4h-1m22-4h1m-1 4h1"
    />
  </svg>
);

// Speed/Performance Icon (for performance metrics)
export const SpeedIcon: React.FC<IconProps> = ({
  className = "",
  size = "lg",
}) => (
  <svg
    className={`${sizeClasses[size]} ${className}`}
    fill="none"
    stroke="currentColor"
    viewBox="0 0 24 24"
    strokeWidth={2}
  >
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z"
    />
  </svg>
);

// Heart Icon (for health status)
export const HeartIcon: React.FC<IconProps> = ({
  className = "",
  size = "lg",
}) => (
  <svg
    className={`${sizeClasses[size]} ${className}`}
    fill="none"
    stroke="currentColor"
    viewBox="0 0 24 24"
    strokeWidth={2}
  >
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12z"
    />
  </svg>
);

// Shield Icon (for security/protection)
export const ShieldIcon: React.FC<IconProps> = ({
  className = "",
  size = "lg",
}) => (
  <svg
    className={`${sizeClasses[size]} ${className}`}
    fill="none"
    stroke="currentColor"
    viewBox="0 0 24 24"
    strokeWidth={2}
  >
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z"
    />
  </svg>
);

// Animated Icons with Hover Effects
export const AnimatedRefreshIcon: React.FC<IconProps> = ({
  className = "",
  size = "lg",
}) => (
  <svg
    className={`${sizeClasses[size]} ${className} transition-transform duration-300 hover:rotate-180 cursor-pointer`}
    fill="none"
    stroke="currentColor"
    viewBox="0 0 24 24"
    strokeWidth={2}
  >
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"
    />
    <path strokeLinecap="round" strokeLinejoin="round" d="M21 3v5h-5" />
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"
    />
    <path strokeLinecap="round" strokeLinejoin="round" d="M8 16H3v5" />
  </svg>
);

export const AnimatedHeartIcon: React.FC<IconProps> = ({
  className = "",
  size = "lg",
}) => (
  <svg
    className={`${sizeClasses[size]} ${className} transition-all duration-300 hover:scale-110 hover:text-red-500 cursor-pointer animate-pulse`}
    fill="none"
    stroke="currentColor"
    viewBox="0 0 24 24"
    strokeWidth={2}
  >
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12z"
    />
  </svg>
);

export const AnimatedNotificationIcon: React.FC<IconProps> = ({
  className = "",
  size = "lg",
}) => (
  <svg
    className={`${sizeClasses[size]} ${className} transition-all duration-300 hover:scale-110 hover:rotate-12 cursor-pointer`}
    fill="none"
    stroke="currentColor"
    viewBox="0 0 24 24"
    strokeWidth={2}
  >
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M14.857 17.082a23.848 23.848 0 0 0 5.454-1.31A8.967 8.967 0 0 1 18 9.75V9A6 6 0 0 0 6 9v.75a8.967 8.967 0 0 1-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 0 1-5.714 0m5.714 0a3 3 0 1 1-5.714 0"
    />
  </svg>
);

// Floating Action Button Icon
export const FloatingActionIcon: React.FC<IconProps> = ({
  className = "",
  size = "lg",
}) => (
  <svg
    className={`${sizeClasses[size]} ${className} transition-all duration-300 hover:scale-125 hover:rotate-90 cursor-pointer`}
    fill="none"
    stroke="currentColor"
    viewBox="0 0 24 24"
    strokeWidth={2}
  >
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M12 4.5v15m7.5-7.5h-15"
    />
  </svg>
);
