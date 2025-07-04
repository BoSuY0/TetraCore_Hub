import React, { useState, useEffect, useCallback } from "react";
import { useI18n } from "../contexts/I18nContext";
import {
  BotIcon,
  WorkerIcon,
  ApiWorkerIcon,
  StreamHubIcon,
  MonitorIcon,
  AdminIcon,
  CheckIcon,
  AlertIcon,
  ClockIcon,
  RefreshIcon,
} from "./Icons";
import { AnimatedPageHeader, AnimatedCard, AnimatedList, usePageAnimation } from "./PageTransition";

interface ClientStats {
  count: number;
  connected: number;
  available?: number;
  busy?: number;
}

interface ClientsStatsData {
  stats_by_type: {
    bot: ClientStats;
    worker: ClientStats;
    worker_api: ClientStats;
    stream_hub: ClientStats;
    monitor: ClientStats;
    admin: ClientStats;
  };
  total_clients: number;
  timestamp: string;
}

export const ClientsView: React.FC = () => {
  const { t } = useI18n();
  const [data, setData] = useState<ClientsStatsData | null>(null);

  const [error, setError] = useState<string | null>(null);
  const [refreshInterval, setRefreshInterval] = useState<number>(5000);
  const [detailedView, setDetailedView] = useState<boolean>(false);
  const [detailedData, setDetailedData] = useState<any>(null);
  const isLoaded = usePageAnimation(100);

  const fetchClientsData = useCallback(async () => {
    try {
      const response = await fetch("/dashboard/api/clients/detailed");
      if (!response.ok) {
        throw new Error(`${t("errors.serverError")}: ${response.status}`);
      }
      const data = await response.json();
      setData(data);
      if (detailedView) {
        setDetailedData(data.clients_by_type);
      }
      setError(null);
    } catch (err) {
      setError(
        `${t("errors.loadingFailed")}: ${err instanceof Error ? err.message : String(err)}`,
      );
    } finally {
      // Не змінюємо стан loading
    }
  }, [detailedView]);

  useEffect(() => {
    fetchClientsData();

    // Встановлення інтервалу оновлення
    const interval = setInterval(fetchClientsData, refreshInterval);
    return () => clearInterval(interval);
  }, [fetchClientsData, refreshInterval]);

  // Функція для відображення статусу
  const renderStatus = (count: number, connected: number) => {
    if (count === 0)
      return <span className="text-gray-400">{t("clients.noClients")}</span>;
    if (connected === 0)
      return <span className="text-red-500">{t("clients.allDisconnected")}</span>;
    if (connected === count)
      return <span className="text-green-500">{t("clients.allConnected")}</span>;
    return (
      <span className="text-yellow-500">
        {connected} {t("common.of")} {count} {t("clients.connected")}
      </span>
    );
  };

  // Функція для відображення статусу воркера
  const renderWorkerStatus = (stats: ClientStats) => {
    if (stats.count === 0)
      return <span className="text-gray-400">{t("clients.noWorkers")}</span>;
    if (stats.connected === 0)
      return <span className="text-red-500">{t("clients.allDisconnected")}</span>;

    return (
      <div className="flex flex-col">
        <span
          className={
            stats.connected === stats.count
              ? "text-green-500"
              : "text-yellow-500"
          }
        >
          {stats.connected} {t("common.of")} {stats.count} {t("clients.connected")}
        </span>
        {stats.available !== undefined &&
          stats.busy !== undefined &&
          stats.connected > 0 && (
            <span className="text-xs mt-1">
              <span className="text-green-500">{stats.available} {t("clients.available")}</span> /
              <span className="text-blue-500"> {stats.busy} {t("clients.busy")}</span>
            </span>
          )}
      </div>
    );
  };

  // Відображення картки для типу клієнта
  const renderClientTypeCard = (
    type: string,
    title: string,
    stats: ClientStats,
    icon: React.ReactNode,
  ) => {
    return (
      <div className="bg-white rounded-xl shadow-sm p-6 transition-all hover:shadow-md">
        <div className="flex items-start justify-between">
          <div>
            <h3 className="text-xl font-semibold text-secondary-900">
              {title}
            </h3>
            <div className="mt-2 text-lg font-bold text-secondary-800">
              {stats.count}{" "}
              <span className="text-sm font-normal text-secondary-500">
                {t("common.total")}
              </span>
            </div>
            <div className="mt-1">
              {type === "worker" || type === "worker_api"
                ? renderWorkerStatus(stats)
                : renderStatus(stats.count, stats.connected)}
            </div>
          </div>
          <div className="text-secondary-400">{icon}</div>
        </div>
      </div>
    );
  };

  // Відображення детальної інформації про клієнтів
  const renderDetailedClients = () => {
    if (!detailedData) return null;

    return (
      <div className="mt-6">
        <h3 className="text-lg font-semibold text-secondary-900 mb-3">
          {t("clients.detailedInfo")}
        </h3>
        <div className="bg-white rounded-xl shadow-sm overflow-hidden">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-secondary-200">
              <thead className="bg-secondary-50">
                <tr>
                  <th
                    scope="col"
                    className="px-6 py-3 text-left text-xs font-medium text-secondary-500 uppercase tracking-wider"
                  >
                    {t("common.id")}
                  </th>
                  <th
                    scope="col"
                    className="px-6 py-3 text-left text-xs font-medium text-secondary-500 uppercase tracking-wider"
                  >
                    {t("common.type")}
                  </th>
                  <th
                    scope="col"
                    className="px-6 py-3 text-left text-xs font-medium text-secondary-500 uppercase tracking-wider"
                  >
                    {t("common.status")}
                  </th>
                  <th
                    scope="col"
                    className="px-6 py-3 text-left text-xs font-medium text-secondary-500 uppercase tracking-wider"
                  >
                    {t("clients.ipAddress")}
                  </th>
                  <th
                    scope="col"
                    className="px-6 py-3 text-left text-xs font-medium text-secondary-500 uppercase tracking-wider"
                  >
                    {t("clients.activity")}
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-secondary-200">
                {Object.entries(detailedData).flatMap(([type, clients]) =>
                  Array.isArray(clients)
                    ? clients.map((client: any) => (
                        <tr key={client.client_id}>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-secondary-900">
                            {client.client_id}
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-secondary-900">
                            <span
                              className={`px-2 py-1 rounded-full text-xs font-medium
                          ${type === "bot" ? "bg-purple-100 text-purple-700" : ""}
                          ${type === "worker" ? "bg-blue-100 text-blue-700" : ""}
                          ${type === "worker_api" ? "bg-green-100 text-green-700" : ""}
                          ${type === "stream_hub" ? "bg-orange-100 text-orange-700" : ""}
                          ${type === "monitor" ? "bg-yellow-100 text-yellow-700" : ""}
                          ${type === "admin" ? "bg-red-100 text-red-700" : ""}
                        `}
                            >
                              {type === "worker_api"
                                ? "API Worker"
                                : type === "stream_hub"
                                  ? "Stream Hub"
                                  : type.charAt(0).toUpperCase() +
                                    type.slice(1)}
                            </span>
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap">
                            <span
                              className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium
                          ${client.connection_status === "connected" ? "bg-success-100 text-success-800" : "bg-error-100 text-error-800"}
                        `}
                            >
                              {client.connection_status === "connected"
                                ? "Підключений"
                                : "Відключений"}
                            </span>
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-secondary-500">
                            {client.remote_address || "N/A"}
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-secondary-500">
                            {client.last_activity
                              ? new Date(client.last_activity).toLocaleString(
                                  "uk-UA",
                                )
                              : t("time.never")}
                          </td>
                        </tr>
                      ))
                    : [],
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    );
  };



  if (error) {
    return (
      <div className="text-center py-12">
        <AlertIcon className="w-12 h-12 text-error-500 mx-auto mb-4" />
        <h3 className="text-lg font-semibold text-secondary-900 mb-2">{t("errors.loadingFailed")}</h3>
        <p className="text-secondary-600 mb-4">{error}</p>
        <button
          onClick={fetchClientsData}
          className="px-4 py-2 bg-primary-500 text-white rounded-lg hover:bg-primary-600 transition-colors"
        >
          {t("errors.tryAgain")}
        </button>
      </div>
    );
  }

  // Показуємо порожню структуру якщо даних немає
  const displayData: ClientsStatsData = data || {
    stats_by_type: {
      bot: { count: 0, connected: 0 },
      worker: { count: 0, connected: 0, available: 0, busy: 0 },
      worker_api: { count: 0, connected: 0, available: 0, busy: 0 },
      stream_hub: { count: 0, connected: 0 },
      monitor: { count: 0, connected: 0 },
      admin: { count: 0, connected: 0 },
    },
    total_clients: 0,
    timestamp: new Date().toISOString(),
  };

  // Іконки для типів клієнтів
  const icons = {
    bot: <BotIcon size="xl" className="text-secondary-400" />,
    worker: <WorkerIcon size="xl" className="text-secondary-400" />,
    worker_api: <ApiWorkerIcon size="xl" className="text-secondary-400" />,
    stream_hub: <StreamHubIcon size="xl" className="text-secondary-400" />,
    monitor: <MonitorIcon size="xl" className="text-secondary-400" />,
    admin: <AdminIcon size="xl" className="text-secondary-400" />,
  };

  const { stats_by_type } = displayData;

  const clientTypes = [
    { key: 'bot', title: t('clients.bot'), icon: <BotIcon size="lg" />, stats: stats_by_type.bot },
    { key: 'worker', title: t('clients.worker'), icon: <WorkerIcon size="lg" />, stats: stats_by_type.worker },
    { key: 'worker_api', title: t('clients.workerApi'), icon: <ApiWorkerIcon size="lg" />, stats: stats_by_type.worker_api },
    { key: 'stream_hub', title: t('clients.streamHub'), icon: <StreamHubIcon size="lg" />, stats: stats_by_type.stream_hub },
    { key: 'monitor', title: t('clients.monitor'), icon: <MonitorIcon size="lg" />, stats: stats_by_type.monitor },
    { key: 'admin', title: t('clients.admin'), icon: <AdminIcon size="lg" />, stats: stats_by_type.admin },
  ];

  return (
    <div className="space-y-8">
      {/* Page Header */}
      <AnimatedPageHeader>
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold text-gradient mb-2">
              👥 {t("clients.title")}
            </h1>
            <p className="text-lg text-secondary-600">
              {t("clients.subtitle")}
            </p>
          </div>
          <div className="text-right">
            <p className="text-2xl font-bold text-primary-600">{displayData.total_clients}</p>
            <p className="text-sm text-secondary-600">{t("clients.totalClients")}</p>
          </div>
        </div>
      </AnimatedPageHeader>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-6">
        {clientTypes.map((clientType, index) => (
          <AnimatedCard key={clientType.key} index={index} animationType="card">
            {renderClientTypeCard(
              clientType.key,
              clientType.title,
              clientType.stats,
              clientType.icon
            )}
          </AnimatedCard>
        ))}
      </div>

      {/* Detailed Information */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* Connection Status Overview */}
        <AnimatedCard index={0} animationType="grid">
          <div className="bg-white rounded-xl shadow-sm p-6">
            <h3 className="text-lg font-semibold text-secondary-900 mb-6">
              📊 {t("clients.connectionStatus")}
            </h3>
            
            <div className="space-y-4">
              {clientTypes.map((clientType, index) => (
                <div 
                  key={clientType.key}
                  className="page-content-stagger"
                  style={{ animationDelay: `${index * 100}ms` }}
                >
                  <div className="flex items-center justify-between p-3 bg-secondary-50 rounded-lg">
                    <div className="flex items-center space-x-3">
                      <div className="text-secondary-600">
                        {clientType.icon}
                      </div>
                      <span className="font-medium text-secondary-900">
                        {clientType.title}
                      </span>
                    </div>
                    <div className="flex items-center space-x-4">
                      {renderStatus(clientType.stats.count, clientType.stats.connected)}
                      <span className="text-sm font-medium text-secondary-700">
                        {clientType.stats.connected}/{clientType.stats.count}
                      </span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </AnimatedCard>

        {/* Worker Status Details */}
        <AnimatedCard index={1} animationType="grid">
          <div className="bg-white rounded-xl shadow-sm p-6">
            <h3 className="text-lg font-semibold text-secondary-900 mb-6">
              ⚡ {t("clients.workerStatus")}
            </h3>
            
            <div className="space-y-4">
              {['worker', 'worker_api'].map((workerType, index) => {
                const workerData = stats_by_type[workerType as keyof typeof stats_by_type];
                const title = workerType === 'worker' ? t('clients.standardWorkers') : t('clients.apiWorkers');
                
                return (
                  <div 
                    key={workerType}
                    className="page-content-stagger"
                    style={{ animationDelay: `${index * 150}ms` }}
                  >
                    <div className="p-4 border border-secondary-200 rounded-lg">
                      <h4 className="font-medium text-secondary-900 mb-3">{title}</h4>
                      {renderWorkerStatus(workerData)}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </AnimatedCard>
      </div>

      {/* Detailed Clients List */}
      <AnimatedCard index={0} animationType="list">
        <div className="bg-white rounded-xl shadow-sm p-6">
          <h3 className="text-lg font-semibold text-secondary-900 mb-6">
            📋 {t("clients.detailedInfo")}
          </h3>
          {renderDetailedClients()}
        </div>
      </AnimatedCard>

      {/* Last Updated */}
      <div className="text-center text-sm text-secondary-500 page-content-stagger">
{t("common.lastUpdated")}: {new Date(displayData.timestamp).toLocaleString()}
      </div>
    </div>
  );
};
