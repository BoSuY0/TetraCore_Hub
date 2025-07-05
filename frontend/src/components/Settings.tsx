import React, { useState, useRef } from "react";
import { useSettings } from "../contexts/SettingsContext";
import { useI18n } from "../contexts/I18nContext";
import config from "../config";

interface TabButtonProps {
  id: string;
  label: string;
  icon: string;
  isActive: boolean;
  onClick: () => void;
}

const TabButton: React.FC<TabButtonProps> = ({
  id,
  label,
  icon,
  isActive,
  onClick,
}) => (
  <button
    onClick={onClick}
    className={`flex items-center gap-3 px-6 py-3 rounded-lg font-medium transition-all duration-200 ${
      isActive
        ? "bg-primary-600 text-white shadow-md"
        : "bg-secondary-100 text-secondary-700 hover:bg-secondary-200"
    }`}
  >
    <span className="text-lg">{icon}</span>
    {label}
  </button>
);

interface SettingCardProps {
  title: string;
  description?: string;
  children: React.ReactNode;
  className?: string;
}

const SettingCard: React.FC<SettingCardProps> = ({
  title,
  description,
  children,
  className = "",
}) => (
  <div
    className={`bg-white rounded-xl shadow-sm border border-secondary-100 p-6 ${className}`}
  >
    <div className="mb-4">
      <h3 className="text-lg font-semibold text-secondary-900 mb-1">{title}</h3>
      {description && (
        <p className="text-sm text-secondary-600">{description}</p>
      )}
    </div>
    {children}
  </div>
);

interface ModernInputProps {
  label: string;
  value: string | number;
  onChange: (value: string | number) => void;
  type?: "text" | "number" | "url";
  placeholder?: string;
  min?: number;
  max?: number;
  icon?: string;
}

const ModernInput: React.FC<ModernInputProps> = ({
  label,
  value,
  onChange,
  type = "text",
  placeholder,
  min,
  max,
  icon,
}) => (
  <div className="space-y-2">
    <label className="block text-sm font-medium text-secondary-700">
      {label}
    </label>
    <div className="relative">
      {icon && (
        <div className="absolute left-3 top-1/2 transform -translate-y-1/2 text-secondary-400">
          {icon}
        </div>
      )}
      <input
        type={type}
        value={value}
        onChange={(e) =>
          onChange(type === "number" ? Number(e.target.value) : e.target.value)
        }
        placeholder={placeholder}
        min={min}
        max={max}
        className={`w-full py-3 border border-secondary-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent transition-colors duration-200 ${
          icon ? "pl-10 pr-10" : "px-4 pr-10"
        }`}
      />
    </div>
  </div>
);

interface ModernSelectProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  icon?: string;
}

const ModernSelect: React.FC<ModernSelectProps> = ({
  label,
  value,
  onChange,
  options,
  icon,
}) => (
  <div className="space-y-2">
    <label className="block text-sm font-medium text-secondary-700">
      {label}
    </label>
    <div className="relative">
      {icon && (
        <div className="absolute left-3 top-1/2 transform -translate-y-1/2 text-secondary-400 z-10">
          {icon}
        </div>
      )}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={`w-full py-3 pr-12 border border-secondary-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent transition-colors duration-200 appearance-none bg-white ${
          icon ? "pl-10" : "pl-4"
        }`}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <div className="absolute right-3 top-1/2 transform -translate-y-1/2 pointer-events-none">
        <svg
          className="w-5 h-5 text-secondary-400"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M19 9l-7 7-7-7"
          />
        </svg>
      </div>
    </div>
  </div>
);

interface ModernToggleProps {
  label: string;
  description?: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  size?: "sm" | "md" | "lg";
}

const ModernToggle: React.FC<ModernToggleProps> = ({
  label,
  description,
  checked,
  onChange,
  size = "md",
}) => {
  const sizeClasses = {
    sm: "w-8 h-5",
    md: "w-11 h-6",
    lg: "w-14 h-7",
  };

  const thumbSizeClasses = {
    sm: "w-4 h-4",
    md: "w-5 h-5",
    lg: "w-6 h-6",
  };

  const translateClasses = {
    sm: checked ? "translate-x-3" : "translate-x-0",
    md: checked ? "translate-x-5" : "translate-x-0",
    lg: checked ? "translate-x-7" : "translate-x-0",
  };

  return (
    <div className="flex items-start justify-between">
      <div className="flex-1">
        <label className="block text-sm font-medium text-secondary-900 mb-1">
          {label}
        </label>
        {description && (
          <p className="text-sm text-secondary-600">{description}</p>
        )}
      </div>
      <button
        onClick={() => onChange(!checked)}
        className={`relative inline-flex items-center ${sizeClasses[size]} rounded-full transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 ${
          checked ? "bg-primary-600" : "bg-secondary-300"
        }`}
      >
        <span
          className={`inline-block ${thumbSizeClasses[size]} rounded-full bg-white shadow transform transition-transform duration-200 ${translateClasses[size]}`}
        />
      </button>
    </div>
  );
};

export const Settings: React.FC = () => {
  const { settings, updateSettings } = useSettings();
  const { t } = useI18n();
  const [activeTab, setActiveTab] = useState("connection");
  const [notification, setNotification] = useState<{
    message: string;
    type: "success" | "error";
  } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const tabs = [
    { id: "connection", label: t("settings.tabs.connection"), icon: "🔗" },
    { id: "interface", label: t("settings.tabs.interface"), icon: "🎨" },
    { id: "monitoring", label: t("settings.tabs.monitoring"), icon: "📊" },
    { id: "security", label: t("settings.tabs.security"), icon: "🔒" },
    { id: "export", label: t("settings.tabs.export"), icon: "💾" },
  ];

  const showNotification = (
    message: string,
    type: "success" | "error" = "success",
  ) => {
    setNotification({ message, type });
    setTimeout(() => setNotification(null), 3000);
  };

  const handleExport = () => {
    try {
      const dataStr = JSON.stringify(settings, null, 2);
      const dataUri =
        "data:application/json;charset=utf-8," + encodeURIComponent(dataStr);
      const exportFileDefaultName = "tetracore-hub-settings.json";

      const linkElement = document.createElement("a");
      linkElement.setAttribute("href", dataUri);
      linkElement.setAttribute("download", exportFileDefaultName);
      linkElement.click();

      showNotification(t("settings.notifications.exportSuccess"));
    } catch (error) {
      showNotification(t("settings.notifications.exportError"), "error");
    }
  };

  const handleImport = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const importedSettings = JSON.parse(e.target?.result as string);
        Object.keys(importedSettings).forEach((key) => {
          if (settings.hasOwnProperty(key)) {
            updateSettings(key as keyof typeof settings, importedSettings[key]);
          }
        });
        showNotification(t("settings.notifications.importSuccess"));
      } catch (error) {
        showNotification(t("settings.notifications.importError"), "error");
      }
    };
    reader.readAsText(file);
  };

  const handleReset = (category?: keyof typeof settings) => {
    try {
      // Reset logic would go here
      showNotification(t("settings.notifications.resetSuccess"));
    } catch (error) {
      showNotification(t("settings.notifications.resetError"), "error");
    }
  };

  const renderConnectionSettings = () => (
    <div className="space-y-6">
      <SettingCard
        title={t("settings.connection.websocketConnection.title")}
        description={t("settings.connection.websocketConnection.description")}
      >
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <ModernInput
            label={t("settings.connection.websocketConnection.serverUrl")}
            value={settings.connection.websocketUrl}
            onChange={(value) =>
              updateSettings("connection", { websocketUrl: value })
            }
            type="url"
            placeholder="ws://localhost"
            icon="🌐"
          />
          <ModernInput
            label={t("settings.connection.websocketConnection.port")}
            value={settings.connection.websocketPort}
            onChange={(value) =>
              updateSettings("connection", { websocketPort: value })
            }
            type="number"
            min={1}
            max={65535}
            icon="🔌"
          />
        </div>
      </SettingCard>

      <SettingCard
        title={t("settings.connection.apiSettings.title")}
        description={t("settings.connection.apiSettings.description")}
      >
        <ModernInput
          label={t("settings.connection.apiSettings.endpoint")}
          value={settings.connection.apiEndpoint}
          onChange={(value) =>
            updateSettings("connection", { apiEndpoint: value })
          }
          type="url"
          placeholder={`${config.api.baseUrl}/api`}
          icon="⚡"
        />
      </SettingCard>

      <SettingCard
        title={t("settings.connection.timeoutsRetries.title")}
        description={t("settings.connection.timeoutsRetries.description")}
      >
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <ModernInput
            label={t("settings.connection.timeoutsRetries.timeout")}
            value={settings.connection.connectionTimeout}
            onChange={(value) =>
              updateSettings("connection", { connectionTimeout: value })
            }
            type="number"
            min={1000}
            max={30000}
            icon="⏱️"
          />
          <ModernInput
            label={t("settings.connection.timeoutsRetries.retryInterval")}
            value={settings.connection.reconnectInterval}
            onChange={(value) =>
              updateSettings("connection", { reconnectInterval: value })
            }
            type="number"
            min={1000}
            max={60000}
            icon="🔄"
          />
          <ModernInput
            label={t("settings.connection.timeoutsRetries.maxAttempts")}
            value={settings.connection.maxReconnectAttempts}
            onChange={(value) =>
              updateSettings("connection", { maxReconnectAttempts: value })
            }
            type="number"
            min={1}
            max={20}
            icon="🎯"
          />
        </div>
      </SettingCard>
    </div>
  );

  const renderInterfaceSettings = () => (
    <div className="space-y-6">
      <SettingCard
        title={t("settings.interface.appearance.title")}
        description={t("settings.interface.appearance.description")}
      >
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <ModernSelect
            label={t("settings.interface.appearance.theme")}
            value={settings.ui.theme}
            onChange={(value) => updateSettings("ui", { theme: value })}
            options={[
              {
                value: "light",
                label: `☀️ ${t("settings.interface.appearance.themes.light")}`,
              },
              {
                value: "dark",
                label: `🌙 ${t("settings.interface.appearance.themes.dark")}`,
              },
              {
                value: "system",
                label: `🖥️ ${t("settings.interface.appearance.themes.system")}`,
              },
            ]}
            icon="🎨"
          />
          <ModernSelect
            label={t("settings.interface.appearance.language")}
            value={settings.ui.language}
            onChange={(value) => updateSettings("ui", { language: value })}
            options={[
              {
                value: "uk",
                label: `🇺🇦 ${t("settings.interface.appearance.languages.ukrainian")}`,
              },
              {
                value: "en",
                label: `🇺🇸 ${t("settings.interface.appearance.languages.english")}`,
              },
            ]}
            icon="🌍"
          />
        </div>
      </SettingCard>

      <SettingCard
        title={t("settings.interface.displayFormats.title")}
        description={t("settings.interface.displayFormats.description")}
      >
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <ModernSelect
            label={t("settings.interface.displayFormats.dateFormat")}
            value={settings.ui.dateFormat}
            onChange={(value) => updateSettings("ui", { dateFormat: value })}
            options={[
              {
                value: "dd/mm/yyyy",
                label: t(
                  "settings.interface.displayFormats.dateFormats.ddmmyyyy",
                ),
              },
              {
                value: "mm/dd/yyyy",
                label: t(
                  "settings.interface.displayFormats.dateFormats.mmddyyyy",
                ),
              },
              {
                value: "yyyy-mm-dd",
                label: t(
                  "settings.interface.displayFormats.dateFormats.yyyymmdd",
                ),
              },
            ]}
            icon="📅"
          />
          <ModernSelect
            label={t("settings.interface.displayFormats.timeFormat")}
            value={settings.ui.timeFormat}
            onChange={(value) => updateSettings("ui", { timeFormat: value })}
            options={[
              {
                value: "24h",
                label: t("settings.interface.displayFormats.timeFormats.24h"),
              },
              {
                value: "12h",
                label: t("settings.interface.displayFormats.timeFormats.12h"),
              },
            ]}
            icon="🕐"
          />
          <ModernInput
            label={t("settings.interface.displayFormats.refreshInterval")}
            value={settings.ui.refreshInterval}
            onChange={(value) =>
              updateSettings("ui", { refreshInterval: value })
            }
            type="number"
            min={1000}
            max={60000}
            icon="🔄"
          />
        </div>
      </SettingCard>

      <SettingCard title={t("settings.interface.displayMode.title")}>
        <ModernToggle
          label={t("settings.interface.displayMode.compactMode")}
          description={t(
            "settings.interface.displayMode.compactModeDescription",
          )}
          checked={settings.ui.compactMode}
          onChange={(checked) => updateSettings("ui", { compactMode: checked })}
        />
      </SettingCard>
    </div>
  );

  const renderMonitoringSettings = () => (
    <div className="space-y-6">
      <SettingCard
        title={t("settings.monitoring.notifications.title")}
        description={t("settings.monitoring.notifications.description")}
      >
        <div className="space-y-4">
          <ModernToggle
            label={t("settings.monitoring.notifications.enable")}
            description={t(
              "settings.monitoring.notifications.enableDescription",
            )}
            checked={settings.monitoring.enableNotifications}
            onChange={(checked) =>
              updateSettings("monitoring", { enableNotifications: checked })
            }
          />
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <ModernToggle
              label={t("settings.monitoring.notifications.errors")}
              description={t(
                "settings.monitoring.notifications.errorsDescription",
              )}
              checked={settings.monitoring.notifyOnErrors}
              onChange={(checked) =>
                updateSettings("monitoring", { notifyOnErrors: checked })
              }
            />
            <ModernToggle
              label={t("settings.monitoring.notifications.newClients")}
              description={t(
                "settings.monitoring.notifications.newClientsDescription",
              )}
              checked={settings.monitoring.notifyOnNewClients}
              onChange={(checked) =>
                updateSettings("monitoring", { notifyOnNewClients: checked })
              }
            />
            <ModernToggle
              label={t("settings.monitoring.notifications.disconnects")}
              description={t(
                "settings.monitoring.notifications.disconnectsDescription",
              )}
              checked={settings.monitoring.notifyOnDisconnects}
              onChange={(checked) =>
                updateSettings("monitoring", { notifyOnDisconnects: checked })
              }
            />
          </div>
        </div>
      </SettingCard>

      <SettingCard
        title={t("settings.monitoring.logging.title")}
        description={t("settings.monitoring.logging.description")}
      >
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <ModernSelect
            label={t("settings.monitoring.logging.logLevel")}
            value={settings.monitoring.logLevel}
            onChange={(value) =>
              updateSettings("monitoring", { logLevel: value })
            }
            options={[
              {
                value: "debug",
                label: `🐛 ${t("settings.monitoring.logging.levels.debug")}`,
              },
              {
                value: "info",
                label: `ℹ️ ${t("settings.monitoring.logging.levels.info")}`,
              },
              {
                value: "warn",
                label: `⚠️ ${t("settings.monitoring.logging.levels.warn")}`,
              },
              {
                value: "error",
                label: `❌ ${t("settings.monitoring.logging.levels.error")}`,
              },
            ]}
            icon="📝"
          />
          <ModernInput
            label={t("settings.monitoring.logging.maxEntries")}
            value={settings.monitoring.maxLogEntries}
            onChange={(value) =>
              updateSettings("monitoring", { maxLogEntries: value })
            }
            type="number"
            min={100}
            max={10000}
            icon="📊"
          />
        </div>
      </SettingCard>

      <SettingCard
        title={t("settings.monitoring.performanceMetrics.title")}
        description={t("settings.monitoring.performanceMetrics.description")}
      >
        <div className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <ModernToggle
              label={t("settings.monitoring.performanceMetrics.enable")}
              description={t(
                "settings.monitoring.performanceMetrics.enableDescription",
              )}
              checked={settings.monitoring.enableMetrics}
              onChange={(checked) =>
                updateSettings("monitoring", { enableMetrics: checked })
              }
            />
            <ModernInput
              label={t(
                "settings.monitoring.performanceMetrics.collectionInterval",
              )}
              value={settings.monitoring.metricsInterval}
              onChange={(value) =>
                updateSettings("monitoring", { metricsInterval: value })
              }
              type="number"
              min={1000}
              max={60000}
              icon="🔄"
            />
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <ModernToggle
              label={t("settings.monitoring.performanceMetrics.cpu")}
              description={t(
                "settings.monitoring.performanceMetrics.cpuDescription",
              )}
              checked={settings.monitoring.showCpuUsage}
              onChange={(checked) =>
                updateSettings("monitoring", { showCpuUsage: checked })
              }
            />
            <ModernToggle
              label={t("settings.monitoring.performanceMetrics.memory")}
              description={t(
                "settings.monitoring.performanceMetrics.memoryDescription",
              )}
              checked={settings.monitoring.showMemoryUsage}
              onChange={(checked) =>
                updateSettings("monitoring", { showMemoryUsage: checked })
              }
            />
            <ModernToggle
              label={t("settings.monitoring.performanceMetrics.network")}
              description={t(
                "settings.monitoring.performanceMetrics.networkDescription",
              )}
              checked={settings.monitoring.showNetworkUsage}
              onChange={(checked) =>
                updateSettings("monitoring", { showNetworkUsage: checked })
              }
            />
          </div>
        </div>
      </SettingCard>
    </div>
  );

  const renderSecuritySettings = () => (
    <div className="space-y-6">
      <SettingCard
        title={t("settings.security.authentication.title")}
        description={t("settings.security.authentication.description")}
      >
        <div className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <ModernToggle
              label={t("settings.security.authentication.enable")}
              description={t(
                "settings.security.authentication.enableDescription",
              )}
              checked={settings.security.enableAuth}
              onChange={(checked) =>
                updateSettings("security", { enableAuth: checked })
              }
            />
            <ModernInput
              label={t("settings.security.authentication.sessionTimeout")}
              value={settings.security.sessionTimeout}
              onChange={(value) =>
                updateSettings("security", { sessionTimeout: value })
              }
              type="number"
              min={300}
              max={86400}
              icon="⏰"
            />
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <ModernToggle
              label={t("settings.security.authentication.twoFactor")}
              description={t(
                "settings.security.authentication.twoFactorDescription",
              )}
              checked={settings.security.requireTwoFactor}
              onChange={(checked) =>
                updateSettings("security", { requireTwoFactor: checked })
              }
            />
            <ModernToggle
              label={t("settings.security.authentication.auditLog")}
              description={t(
                "settings.security.authentication.auditLogDescription",
              )}
              checked={settings.security.enableAuditLog}
              onChange={(checked) =>
                updateSettings("security", { enableAuditLog: checked })
              }
            />
          </div>
        </div>
      </SettingCard>

      <SettingCard
        title={t("settings.security.passwordPolicy.title")}
        description={t("settings.security.passwordPolicy.description")}
      >
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <ModernInput
            label={t("settings.security.passwordPolicy.minLength")}
            value={settings.security.passwordPolicy.minLength}
            onChange={(value) =>
              updateSettings("security", {
                passwordPolicy: {
                  ...settings.security.passwordPolicy,
                  minLength: value,
                },
              })
            }
            type="number"
            min={4}
            max={50}
            icon="🔢"
          />
          <div className="space-y-3">
            <ModernToggle
              label={t("settings.security.passwordPolicy.requireUppercase")}
              checked={settings.security.passwordPolicy.requireUppercase}
              onChange={(checked) =>
                updateSettings("security", {
                  passwordPolicy: {
                    ...settings.security.passwordPolicy,
                    requireUppercase: checked,
                  },
                })
              }
              size="sm"
            />
            <ModernToggle
              label={t("settings.security.passwordPolicy.requireNumbers")}
              checked={settings.security.passwordPolicy.requireNumbers}
              onChange={(checked) =>
                updateSettings("security", {
                  passwordPolicy: {
                    ...settings.security.passwordPolicy,
                    requireNumbers: checked,
                  },
                })
              }
              size="sm"
            />
            <ModernToggle
              label={t("settings.security.passwordPolicy.requireSymbols")}
              checked={settings.security.passwordPolicy.requireSymbols}
              onChange={(checked) =>
                updateSettings("security", {
                  passwordPolicy: {
                    ...settings.security.passwordPolicy,
                    requireSymbols: checked,
                  },
                })
              }
              size="sm"
            />
          </div>
        </div>
      </SettingCard>

      <SettingCard
        title={t("settings.security.allowedIPs.title")}
        description={t("settings.security.allowedIPs.description")}
      >
        <div className="space-y-3">
          {settings.security.allowedIPs.map((ip, index) => (
            <div key={index} className="flex items-center gap-3">
              <div className="flex-1">
                <ModernInput
                  label=""
                  value={ip}
                  onChange={(value) => {
                    const newIPs = [...settings.security.allowedIPs];
                    newIPs[index] = value as string;
                    updateSettings("security", { allowedIPs: newIPs });
                  }}
                  placeholder="192.168.1.1"
                  icon="🌐"
                />
              </div>
              <button
                onClick={() => {
                  const newIPs = settings.security.allowedIPs.filter(
                    (_, i) => i !== index,
                  );
                  updateSettings("security", { allowedIPs: newIPs });
                }}
                className="mt-6 px-4 py-2 bg-red-100 text-red-700 rounded-lg hover:bg-red-200 transition-colors duration-200"
              >
                🗑️
              </button>
            </div>
          ))}
          <button
            onClick={() => {
              const newIPs = [...settings.security.allowedIPs, ""];
              updateSettings("security", { allowedIPs: newIPs });
            }}
            className="w-full py-2 border-2 border-dashed border-secondary-300 rounded-lg text-secondary-500 hover:border-primary-300 hover:text-primary-600 transition-colors duration-200"
          >
            ➕ {t("settings.addIpAddress")}
          </button>
        </div>
      </SettingCard>
    </div>
  );

  const renderExportSettings = () => (
    <div className="space-y-6">
      <SettingCard
        title={t("settings.exportSettings.autoExport.title")}
        description={t("settings.exportSettings.autoExport.description")}
      >
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <ModernToggle
            label={t("settings.exportSettings.autoExport.enable")}
            description={t(
              "settings.exportSettings.autoExport.enableDescription",
            )}
            checked={settings.export.autoExportLogs}
            onChange={(checked) =>
              updateSettings("export", { autoExportLogs: checked })
            }
          />
          <ModernInput
            label={t("settings.exportSettings.autoExport.maxSize")}
            value={settings.export.maxExportSize}
            onChange={(value) =>
              updateSettings("export", { maxExportSize: value })
            }
            type="number"
            min={1}
            max={1000}
            icon="💾"
          />
        </div>
      </SettingCard>

      <SettingCard
        title={t("settings.exportSettings.formatFrequency.title")}
        description={t("settings.exportSettings.formatFrequency.description")}
      >
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <ModernSelect
            label={t("settings.exportSettings.formatFrequency.fileFormat")}
            value={settings.export.exportFormat}
            onChange={(value) =>
              updateSettings("export", { exportFormat: value })
            }
            options={[
              {
                value: "json",
                label: `📄 ${t("settings.exportSettings.formatFrequency.formats.json")}`,
              },
              {
                value: "csv",
                label: `📊 ${t("settings.exportSettings.formatFrequency.formats.csv")}`,
              },
              {
                value: "xml",
                label: `📋 ${t("settings.exportSettings.formatFrequency.formats.xml")}`,
              },
            ]}
            icon="📁"
          />
          <ModernSelect
            label={t("settings.exportSettings.formatFrequency.frequency")}
            value={settings.export.exportInterval}
            onChange={(value) =>
              updateSettings("export", { exportInterval: value })
            }
            options={[
              {
                value: "daily",
                label: `📅 ${t("settings.exportSettings.formatFrequency.frequencies.daily")}`,
              },
              {
                value: "weekly",
                label: `📆 ${t("settings.exportSettings.formatFrequency.frequencies.weekly")}`,
              },
              {
                value: "monthly",
                label: `🗓️ ${t("settings.exportSettings.formatFrequency.frequencies.monthly")}`,
              },
            ]}
            icon="⏰"
          />
        </div>
      </SettingCard>

      <SettingCard
        title={t("settings.exportSettings.dataSelection.title")}
        description={t("settings.exportSettings.dataSelection.description")}
      >
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <ModernToggle
            label={t("settings.exportSettings.dataSelection.metrics")}
            description={t(
              "settings.exportSettings.dataSelection.metricsDescription",
            )}
            checked={settings.export.includeMetrics}
            onChange={(checked) =>
              updateSettings("export", { includeMetrics: checked })
            }
          />
          <ModernToggle
            label={t("settings.exportSettings.dataSelection.logs")}
            description={t(
              "settings.exportSettings.dataSelection.logsDescription",
            )}
            checked={settings.export.includeLogs}
            onChange={(checked) =>
              updateSettings("export", { includeLogs: checked })
            }
          />
          <ModernToggle
            label={t("settings.exportSettings.dataSelection.clientData")}
            description={t(
              "settings.exportSettings.dataSelection.clientDataDescription",
            )}
            checked={settings.export.includeClientData}
            onChange={(checked) =>
              updateSettings("export", { includeClientData: checked })
            }
          />
        </div>
      </SettingCard>
    </div>
  );

  const renderActiveTab = () => {
    switch (activeTab) {
      case "connection":
        return renderConnectionSettings();
      case "interface":
        return renderInterfaceSettings();
      case "monitoring":
        return renderMonitoringSettings();
      case "security":
        return renderSecuritySettings();
      case "export":
        return renderExportSettings();
      default:
        return renderConnectionSettings();
    }
  };

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div className="text-center py-8">
        <h1 className="text-4xl font-bold text-secondary-900 mb-3">
          ⚙️ {t("settings.title")}
        </h1>
        <p className="text-lg text-secondary-600">{t("settings.subtitle")}</p>
      </div>

      {/* Notification */}
      {notification && (
        <div
          className={`rounded-xl p-4 border-l-4 ${
            notification.type === "success"
              ? "bg-green-50 border-green-400 text-green-800"
              : "bg-red-50 border-red-400 text-red-800"
          }`}
        >
          <div className="flex items-center">
            <span className="text-xl mr-3">
              {notification.type === "success" ? "✅" : "❌"}
            </span>
            {notification.message}
          </div>
        </div>
      )}

      {/* Action Bar */}
      <div className="bg-white rounded-xl shadow-sm border border-secondary-100 p-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <h3 className="text-lg font-semibold text-secondary-900">
            🛠️ {t("settings.management")}
          </h3>
          <div className="flex flex-wrap gap-3">
            <button
              onClick={handleExport}
              className="inline-flex items-center px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition-colors duration-200 shadow-sm hover:shadow-md"
            >
              <span className="mr-2">💾</span>
              {t("settings.export")}
            </button>
            <button
              onClick={() => fileInputRef.current?.click()}
              className="inline-flex items-center px-4 py-2 bg-secondary-600 text-white rounded-lg hover:bg-secondary-700 transition-colors duration-200 shadow-sm hover:shadow-md"
            >
              <span className="mr-2">📁</span>
              {t("settings.import")}
            </button>
            <button
              onClick={() => handleReset()}
              className="inline-flex items-center px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors duration-200 shadow-sm hover:shadow-md"
            >
              <span className="mr-2">🔄</span>
              {t("settings.reset")}
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".json"
              onChange={handleImport}
              className="hidden"
            />
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="bg-white rounded-xl shadow-sm border border-secondary-100 p-2">
        <div className="flex flex-wrap gap-2">
          {tabs.map((tab) => (
            <TabButton
              key={tab.id}
              id={tab.id}
              label={tab.label}
              icon={tab.icon}
              isActive={activeTab === tab.id}
              onClick={() => setActiveTab(tab.id)}
            />
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="min-h-[600px]">{renderActiveTab()}</div>

      {/* Reset Section Button */}
      <div className="text-center py-4">
        <button
          onClick={() => handleReset(activeTab as keyof typeof settings)}
          className="inline-flex items-center px-6 py-3 border-2 border-red-200 text-red-700 rounded-lg hover:bg-red-50 hover:border-red-300 transition-colors duration-200"
        >
          <span className="mr-2">🗑️</span>
          {t("settings.resetCurrentSection")}
        </button>
      </div>
    </div>
  );
};
