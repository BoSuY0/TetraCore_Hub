import React, { useState, useEffect, useRef } from "react";
import { useStatus } from "../contexts/StatusContext";
import { useI18n } from "../contexts/I18nContext";
import { useAuth } from "../contexts/AuthContext";
import {
  MenuIcon,
  CloseIcon,
  NetworkIcon,
  LoadingIcon,
  RefreshIcon,
  NotificationIcon,
  SettingsIcon,
  AdminIcon,
  UsersIcon,
} from "./Icons";

interface HeaderProps {
  sidebarOpen: boolean;
  setSidebarOpen: (open: boolean) => void;
  sidebarCollapsed: boolean;
  setSidebarCollapsed: (collapsed: boolean) => void;
}

export const Header: React.FC<HeaderProps> = ({
  sidebarOpen,
  setSidebarOpen,
  sidebarCollapsed,
  setSidebarCollapsed,
}) => {
  const { state, disconnectWebSocket } = useStatus();
  const { t, currentLanguage, changeLanguage } = useI18n();
  const { auth, logout } = useAuth();
  const [languageDropdownOpen, setLanguageDropdownOpen] = useState(false);
  const [userDropdownOpen, setUserDropdownOpen] = useState(false);
  const userDropdownRef = useRef<HTMLDivElement>(null);
  const languageDropdownRef = useRef<HTMLDivElement>(null);

  // Закриваємо dropdown при кліку поза ними
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        userDropdownRef.current &&
        !userDropdownRef.current.contains(event.target as Node)
      ) {
        setUserDropdownOpen(false);
      }
      if (
        languageDropdownRef.current &&
        !languageDropdownRef.current.contains(event.target as Node)
      ) {
        setLanguageDropdownOpen(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const getStatusText = () => {
    switch (state.connectionStatus) {
      case "connected":
        return t("common.connected");
      case "connecting":
        return t("common.loading");
      case "disconnected":
        return t("common.disconnected");
      case "error":
        return t("common.error");
      default:
        return t("common.status");
    }
  };

  const getStatusColor = () => {
    switch (state.connectionStatus) {
      case "connected":
        return "text-success-600";
      case "connecting":
        return "text-warning-600";
      case "disconnected":
      case "error":
        return "text-error-600";
      default:
        return "text-secondary-600";
    }
  };

  return (
    <header className="bg-gradient-to-r from-white to-slate-50 shadow-lg border-b border-slate-200/50 h-16 fixed top-0 left-0 right-0 z-header backdrop-blur-sm">
      <div className="flex items-center justify-between h-full px-3">
        {/* Left side */}
        <div className="flex items-center space-x-2">
          {/* Mobile menu button */}
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="lg:hidden ml-3 p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-xl transition-all duration-300 w-10 h-10 flex items-center justify-center"
          >
            {sidebarOpen ? <CloseIcon size="lg" /> : <MenuIcon size="lg" />}
          </button>

          {/* Desktop sidebar toggle */}
          <button
            onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
            className="hidden lg:flex ml-3 p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-xl transition-all duration-300 w-10 h-10 items-center justify-center"
          >
            <MenuIcon size="lg" />
          </button>

          {/* Logo */}
          <div className="flex items-center space-x-3 ml-1">
            <div className="w-8 h-8 bg-gradient-to-r from-blue-500 to-blue-600 rounded-lg flex items-center justify-center text-white font-bold text-xs shadow-md">
              TC
            </div>
            <span className="hidden md:block text-base font-semibold text-slate-800">
              TetraCore Hub
            </span>
          </div>
        </div>

        {/* Right side */}
        <div className="flex items-center space-x-2">
          {/* Connection status */}
          <div className="hidden md:flex items-center space-x-2 px-3 py-2 bg-slate-50 rounded-xl border border-slate-200">
            {state.connectionStatus === "connecting" ? (
              <LoadingIcon size="sm" className="text-warning-500" />
            ) : (
              <NetworkIcon size="sm" className={getStatusColor()} />
            )}
            <span className={`text-sm font-medium ${getStatusColor()}`}>
              {getStatusText()}
            </span>
          </div>

          {/* Notifications */}
          <button className="p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-xl transition-all duration-300 relative w-10 h-10 flex items-center justify-center">
            <NotificationIcon size="lg" />
            {state.alerts.length > 0 && (
              <span className="absolute -top-1 -right-1 h-5 w-5 bg-red-500 text-white text-xs rounded-full flex items-center justify-center font-medium animate-pulse">
                {state.alerts.length > 9 ? "9+" : state.alerts.length}
              </span>
            )}
          </button>

          {/* Language Switcher */}
          <div className="relative" ref={languageDropdownRef}>
            <button
              onClick={() => setLanguageDropdownOpen(!languageDropdownOpen)}
              className="p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-xl transition-all duration-300 w-10 h-10 flex items-center justify-center font-semibold text-sm"
            >
              {currentLanguage.toUpperCase()}
            </button>

            {languageDropdownOpen && (
              <div className="absolute right-0 mt-2 w-32 bg-white rounded-xl shadow-lg border border-slate-200 py-1 z-50">
                <button
                  onClick={() => {
                    changeLanguage("uk");
                    setLanguageDropdownOpen(false);
                  }}
                  className={`w-full text-left px-3 py-2 text-sm hover:bg-slate-50 transition-colors ${
                    currentLanguage === "uk"
                      ? "text-blue-600 bg-blue-50"
                      : "text-slate-700"
                  }`}
                >
                  🇺🇦 Українська
                </button>
                <button
                  onClick={() => {
                    changeLanguage("en");
                    setLanguageDropdownOpen(false);
                  }}
                  className={`w-full text-left px-3 py-2 text-sm hover:bg-slate-50 transition-colors ${
                    currentLanguage === "en"
                      ? "text-blue-600 bg-blue-50"
                      : "text-slate-700"
                  }`}
                >
                  🇺🇸 English
                </button>
              </div>
            )}
          </div>

          {/* Refresh button */}
          <button
            onClick={() => window.location.reload()}
            className="p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-xl transition-all duration-300 w-10 h-10 flex items-center justify-center"
          >
            <RefreshIcon size="lg" />
          </button>

          {/* User Profile */}
          {auth.user && (
            <div className="relative" ref={userDropdownRef}>
              <button
                onClick={() => setUserDropdownOpen(!userDropdownOpen)}
                className="flex items-center space-x-3 px-3 py-2 text-slate-600 hover:bg-slate-100 rounded-xl transition-all duration-300 min-w-0"
              >
                <div className="w-9 h-9 bg-gradient-to-br from-blue-500 to-indigo-600 rounded-full flex items-center justify-center shadow-sm flex-shrink-0">
                  <span className="text-white text-sm font-bold">
                    {auth.user.username.charAt(0).toUpperCase()}
                  </span>
                </div>
                <div className="hidden lg:block text-left min-w-0 flex-1">
                  <p className="text-sm font-semibold text-slate-800 truncate">
                    {auth.user.username}
                  </p>
                  <div className="flex items-center space-x-1">
                    {auth.user.role === "admin" ? (
                      <AdminIcon
                        size="sm"
                        className="text-purple-500 flex-shrink-0"
                      />
                    ) : (
                      <UsersIcon
                        size="sm"
                        className="text-slate-400 flex-shrink-0"
                      />
                    )}
                    <span className="text-xs text-slate-500 truncate">
                      {auth.user.role === "admin" ? "Адміністратор" : ""}
                    </span>
                  </div>
                </div>
                <div className="hidden lg:block flex-shrink-0">
                  <svg
                    className="w-4 h-4 text-slate-400"
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
              </button>

              {userDropdownOpen && (
                <div className="absolute right-0 mt-2 w-72 bg-white rounded-xl shadow-xl border border-slate-200 overflow-hidden z-50">
                  {/* User Info */}
                  <div className="px-4 py-4 bg-gradient-to-r from-slate-50 to-blue-50 border-b border-slate-100">
                    <div className="flex items-center space-x-3">
                      <div className="w-12 h-12 bg-gradient-to-br from-blue-500 to-indigo-600 rounded-full flex items-center justify-center shadow-md">
                        <span className="text-white font-bold text-lg">
                          {auth.user.username.charAt(0).toUpperCase()}
                        </span>
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="font-semibold text-slate-800 text-base truncate">
                          {auth.user.username}
                        </p>
                        <p className="text-sm text-slate-600 truncate">
                          @{auth.user.username}
                        </p>
                        <div className="flex items-center space-x-2 mt-1">
                          {auth.user.role === "admin" ? (
                            <div className="flex items-center space-x-1 px-2 py-1 bg-purple-100 rounded-full">
                              <AdminIcon
                                size="sm"
                                className="text-purple-600"
                              />
                              <span className="text-xs font-medium text-purple-700">
                                Адміністратор
                              </span>
                            </div>
                          ) : (
                            <div className="flex items-center space-x-1 px-2 py-1 bg-slate-100 rounded-full">
                              <UsersIcon size="sm" className="text-slate-600" />
                              <span className="text-xs font-medium text-slate-700">
                                Глядач
                              </span>
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* User Actions */}
                  <div className="py-2">
                    <button
                      onClick={() => {
                        setUserDropdownOpen(false);
                        // Тут можна додати навігацію до профілю
                      }}
                      className="w-full text-left px-4 py-3 text-sm text-slate-700 hover:bg-slate-50 transition-all duration-200 flex items-center space-x-3 group"
                    >
                      <div className="w-8 h-8 bg-slate-100 rounded-lg flex items-center justify-center group-hover:bg-slate-200 transition-colors">
                        <SettingsIcon size="sm" className="text-slate-600" />
                      </div>
                      <span className="font-medium">Налаштування профілю</span>
                    </button>

                    <div className="border-t border-slate-100 my-2"></div>

                    <button
                      onClick={() => {
                        setUserDropdownOpen(false);
                        disconnectWebSocket();
                        logout();
                      }}
                      className="w-full text-left px-4 py-3 text-sm text-red-600 hover:bg-red-50 transition-all duration-200 flex items-center space-x-3 group"
                    >
                      <div className="w-8 h-8 bg-red-100 rounded-lg flex items-center justify-center group-hover:bg-red-200 transition-colors">
                        <CloseIcon size="sm" className="text-red-600" />
                      </div>
                      <span className="font-medium">Вийти з системи</span>
                    </button>
                  </div>

                  {/* Session Info */}
                  <div className="px-4 py-3 bg-slate-50 border-t border-slate-100">
                    <div className="space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-medium text-slate-500">
                          ID сесії:
                        </span>
                        <span className="text-xs font-mono text-slate-600 bg-white px-2 py-1 rounded">
                          {auth.user.sessionId
                            ? auth.user.sessionId.slice(0, 8) + "..."
                            : "N/A"}
                        </span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-medium text-slate-500">
                          Час входу:
                        </span>
                        <span className="text-xs text-slate-600">
                          {auth.user.loginTime
                            ? new Date(auth.user.loginTime).toLocaleString(
                                "uk-UA",
                                {
                                  day: "2-digit",
                                  month: "2-digit",
                                  hour: "2-digit",
                                  minute: "2-digit",
                                },
                              )
                            : "N/A"}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </header>
  );
};
