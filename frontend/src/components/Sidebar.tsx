import React, { useState, useEffect } from "react";
import { useI18n } from "../contexts/I18nContext";
import {
  DashboardIcon,
  UsersIcon,
  TasksIcon,
  MetricsIcon,
  SettingsIcon,
  CloseIcon,
} from "./Icons";

interface SidebarProps {
  isOpen: boolean;
  isCollapsed: boolean;
  onToggle: () => void;
  onCollapse: () => void;
  currentView: string;
  onViewChange: (view: string) => void;
}

const getMenuItems = (t: (key: string) => string) => [
  {
    id: "dashboard",
    name: t("navigation.dashboard"),
    icon: DashboardIcon,
  },
  {
    id: "clients",
    name: t("navigation.clients"),
    icon: UsersIcon,
  },
  {
    id: "tasks",
    name: t("navigation.tasks"),
    icon: TasksIcon,
  },
  {
    id: "metrics",
    name: t("navigation.metrics"),
    icon: MetricsIcon,
  },
  {
    id: "settings",
    name: t("navigation.settings"),
    icon: SettingsIcon,
  },
];

export const Sidebar: React.FC<SidebarProps> = ({
  isOpen,
  isCollapsed,
  onToggle,
  onCollapse,
  currentView,
  onViewChange,
}) => {
  const { t } = useI18n();
  const menuItems = getMenuItems(t);
  const [systemStatus, setSystemStatus] = useState({
    status: "operational" as "operational" | "warning" | "error",
    message: "All systems operational",
    color: "bg-green-500",
    bgColor: "bg-green-100",
  });

  // Простий статус без автоматичного перемикання
  useEffect(() => {
    // Можна додати реальну логіку перевірки статусу тут
    const currentStatus = {
      status: "operational" as const,
      message: "All systems operational",
      color: "bg-green-500",
      bgColor: "bg-green-100",
    };
    setSystemStatus(currentStatus);
  }, []);

  const renderSystemStatus = () => (
    <div className="group relative bg-gradient-to-r from-green-50 to-emerald-50 rounded-xl border border-green-200/50 shadow-sm transition-all duration-300 overflow-hidden hover:shadow-md">
      <div className="flex items-center p-3">
        {/* Статус індикатор */}
        <div className="flex-shrink-0 w-6 flex justify-center icon-no-animation">
          <div
            className={`w-3 h-3 bg-emerald-500 rounded-full animate-bounce-subtle`}
          ></div>
        </div>

        {/* Текстова інформація */}
        <div
          className={`min-w-0 flex-1 sidebar-text-typewriter text-stable sidebar-text-stable ml-3 ${
            isCollapsed ? "collapsed" : ""
          }`}
        >
          <p className="text-xs font-semibold text-slate-700 truncate">
            System Status
          </p>
          <p className="text-xs text-emerald-600 truncate font-medium">
            {systemStatus.message}
          </p>
        </div>
      </div>

      {/* Tooltip для згорнутого стану */}
      <div
        className={`absolute left-full ml-4 top-1/2 transform -translate-y-1/2 bg-slate-800 text-white text-xs rounded-lg px-3 py-2 group-hover:opacity-100 tooltip-delayed pointer-events-none z-50 whitespace-nowrap shadow-xl ${
          isCollapsed ? "opacity-0 visible delay-300" : "opacity-0 invisible"
        }`}
      >
        System Status: {systemStatus.message}
        <div className="absolute right-full top-1/2 transform -translate-y-1/2 w-0 h-0 border-l-0 border-r-4 border-r-slate-800 border-t-4 border-t-transparent border-b-4 border-b-transparent"></div>
      </div>
    </div>
  );

  return (
    <>
      {/* Desktop Sidebar */}
      <div
        className={`hidden lg:flex lg:flex-col lg:fixed lg:top-16 lg:bottom-0 sidebar-smooth z-sidebar ${
          isCollapsed ? "lg:w-20" : "lg:w-64"
        }`}
      >
        <div className="flex flex-col flex-grow bg-gradient-to-b from-slate-50 to-white shadow-xl border-r border-slate-200/50">
          {/* Navigation */}
          <nav className="flex-1 px-3 py-6 space-y-2">
            {menuItems.map((item) => {
              const isActive = currentView === item.id;
              const IconComponent = item.icon;

              return (
                <div key={item.id} className="relative group">
                  <button
                    onClick={() => onViewChange(item.id)}
                    className={`group w-full flex items-center text-sm font-medium rounded-xl sidebar-smooth sidebar-button-enhanced py-3 px-3 ${
                      isActive
                        ? "bg-gradient-to-r from-blue-500 to-blue-600 text-white shadow-lg shadow-blue-200/50"
                        : "text-slate-600 hover:bg-slate-100 hover:text-slate-900 hover:shadow-sm"
                    }`}
                  >
                    <div
                      className={`flex-shrink-0 w-6 flex justify-center icon-no-animation ${isActive ? "text-white" : "text-slate-400"}`}
                    >
                      <IconComponent size="lg" />
                    </div>
                    <span
                      className={`font-medium sidebar-text-typewriter text-stable sidebar-text-stable ml-3 ${
                        isCollapsed ? "collapsed" : ""
                      }`}
                    >
                      {item.name}
                    </span>
                  </button>

                  {/* Tooltip для згорнутого стану */}
                  <div
                    className={`absolute left-full ml-4 top-1/2 transform -translate-y-1/2 bg-slate-800 text-white text-sm rounded-lg px-3 py-2 group-hover:opacity-100 tooltip-delayed pointer-events-none z-50 whitespace-nowrap shadow-xl ${
                      isCollapsed
                        ? "opacity-0 visible delay-300"
                        : "opacity-0 invisible"
                    }`}
                  >
                    {item.name}
                    <div className="absolute right-full top-1/2 transform -translate-y-1/2 w-0 h-0 border-l-0 border-r-4 border-r-slate-800 border-t-4 border-t-transparent border-b-4 border-b-transparent"></div>
                  </div>
                </div>
              );
            })}
          </nav>

          {/* Footer */}
          <div className="flex-shrink-0 p-4 border-t border-slate-200/50">
            {renderSystemStatus()}
          </div>
        </div>
      </div>

      {/* Mobile Sidebar */}
      <div
        className={`lg:hidden fixed inset-0 z-mobile-sidebar sidebar-smooth ${
          isOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex">
          {/* Sidebar content */}
          <div className="flex flex-col w-64 bg-gradient-to-b from-slate-50 to-white shadow-xl sidebar-smooth">
            {/* Header with close button */}
            <div className="flex items-center justify-between flex-shrink-0 px-4 py-4 border-b border-slate-200/50">
              <h2 className="text-lg font-semibold text-slate-800 sidebar-text-fade">
                Menu
              </h2>
              <button
                onClick={onToggle}
                className="p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-xl sidebar-button-enhanced w-10 h-10 flex items-center justify-center"
              >
                <CloseIcon size="lg" />
              </button>
            </div>

            {/* Navigation */}
            <nav className="flex-1 px-4 py-6 space-y-2">
              {menuItems.map((item) => {
                const isActive = currentView === item.id;
                const IconComponent = item.icon;

                return (
                  <button
                    key={item.id}
                    onClick={() => {
                      onViewChange(item.id);
                      onToggle(); // Close mobile sidebar after selection
                    }}
                    className={`group flex items-center w-full px-4 py-4 text-sm font-medium rounded-xl sidebar-smooth sidebar-button-enhanced ${
                      isActive
                        ? "bg-gradient-to-r from-blue-500 to-blue-600 text-white shadow-lg shadow-blue-200/50"
                        : "text-slate-600 hover:bg-slate-100 hover:text-slate-900 hover:shadow-sm"
                    }`}
                  >
                    <div
                      className={`flex-shrink-0 w-6 flex justify-center mr-3 icon-no-animation ${isActive ? "text-white" : "text-slate-400"}`}
                    >
                      <IconComponent size="lg" />
                    </div>
                    <span className="font-medium">{item.name}</span>
                  </button>
                );
              })}
            </nav>

            {/* Footer */}
            <div className="flex-shrink-0 p-4 border-t border-slate-200/50">
              {renderSystemStatus()}
            </div>
          </div>
        </div>
      </div>
    </>
  );
};
