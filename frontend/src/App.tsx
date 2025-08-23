import React, { useState } from "react";
import { Dashboard } from "./components/Dashboard";
import { Sidebar } from "./components/Sidebar";
import { Header } from "./components/Header";
import { ClientsView } from "./components/ClientsView";
import { TasksView } from "./components/TasksView";
import { WorkerMetrics } from "./components/WorkerMetrics";
import { Settings } from "./components/Settings";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { StatusProvider, useStatus } from "./contexts/StatusContext";
import { SettingsProvider } from "./contexts/SettingsContext";
import { I18nProvider } from "./contexts/I18nContext";
import { AuthProvider } from "./contexts/AuthContext";
import { PageTransition } from "./components/PageTransition";
import ConsoleLogs from "./components/ConsoleLogs";
import ErrorBoundary from "./components/ErrorBoundary";

const AppContent: React.FC = () => {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [currentView, setCurrentView] = useState("dashboard");
  const { state } = useStatus();

  // Функція для рендерингу поточної сторінки з анімацією
  const renderCurrentPage = () => {
    switch (currentView) {
      case "dashboard":
        return (
          <PageTransition pageKey="dashboard" animationType="dashboard">
            <Dashboard />
          </PageTransition>
        );
      case "clients":
        return (
          <PageTransition pageKey="clients" animationType="clients">
            <ProtectedRoute requiredRole="admin" requiredPermissions={["clients.view"]}>
              <ClientsView />
            </ProtectedRoute>
          </PageTransition>
        );
      case "tasks":
        return (
          <PageTransition pageKey="tasks" animationType="tasks">
            <ProtectedRoute requiredRole="admin" requiredPermissions={["tasks.view"]}>
              <TasksView />
            </ProtectedRoute>
          </PageTransition>
        );
      case "metrics":
        return (
          <PageTransition pageKey="metrics" animationType="metrics">
            <ProtectedRoute requiredRole="admin" requiredPermissions={["metrics.view"]}>
              <WorkerMetrics clients={state.clients} />
            </ProtectedRoute>
          </PageTransition>
        );
      case "settings":
        return (
          <PageTransition pageKey="settings" animationType="settings">
            <ProtectedRoute
              requiredRole="admin"
              requiredPermissions={["settings.view"]}
            >
              <Settings />
            </ProtectedRoute>
          </PageTransition>
        );
      case "console":
        return (
          <PageTransition pageKey="console" animationType="tasks">
            <ProtectedRoute requiredRole="admin">
              <ConsoleLogs />
            </ProtectedRoute>
          </PageTransition>
        );
      default:
        return (
          <PageTransition pageKey="dashboard" animationType="dashboard">
            <Dashboard />
          </PageTransition>
        );
    }
  };

  return (
    <ProtectedRoute requiredRole="admin">
      <div className="min-h-screen bg-gradient-to-br from-slate-50 via-gray-50 to-slate-100">
        {/* Sidebar */}
        <Sidebar
          isOpen={sidebarOpen}
          isCollapsed={sidebarCollapsed}
          onToggle={() => setSidebarOpen(!sidebarOpen)}
          onCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
          currentView={currentView}
          onViewChange={setCurrentView}
        />

        {/* Main Content */}
        <div
          className={`content-shift ${
            sidebarCollapsed ? "lg:ml-20" : "lg:ml-64"
          }`}
        >
          {/* Header */}
          <Header
            sidebarOpen={sidebarOpen}
            setSidebarOpen={setSidebarOpen}
            sidebarCollapsed={sidebarCollapsed}
            setSidebarCollapsed={setSidebarCollapsed}
          />

          {/* Main Dashboard */}
          <main className="header-safe p-4 lg:p-8">
            <div className="max-w-7xl mx-auto space-y-6">
              <div className="content-safe">{renderCurrentPage()}</div>
            </div>
          </main>
        </div>

        {/* Mobile sidebar overlay */}
        {sidebarOpen && (
          <div
            className="fixed inset-0 bg-slate-900 bg-opacity-60 backdrop-blur-sm z-overlay lg:hidden sidebar-smooth animate-slide-in-left"
            onClick={() => setSidebarOpen(false)}
          />
        )}
      </div>
    </ProtectedRoute>
  );
};

function App() {
  return (
    <ErrorBoundary>
      <SettingsProvider>
        <I18nProvider>
          <AuthProvider>
            <StatusProvider>
              <AppContent />
            </StatusProvider>
          </AuthProvider>
        </I18nProvider>
      </SettingsProvider>
    </ErrorBoundary>
  );
}

export default App;
