import React from "react";
import { useAuth } from "../contexts/AuthContext";
import { LoginPage } from "./LoginPage";
import { LoadingIcon, ErrorIcon } from "./Icons";

interface ProtectedRouteProps {
  children: React.ReactNode;
  requiredRole?: "admin" | "user" | "viewer";
  requiredPermissions?: string[];
  fallback?: React.ReactNode;
}

export const ProtectedRoute: React.FC<ProtectedRouteProps> = ({
  children,
  requiredRole = "viewer",
  requiredPermissions = [],
  fallback,
}) => {
  const { auth } = useAuth();

  // Показуємо загрузку під час перевірки авторизації
  if (auth.isLoading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-900 via-blue-900 to-indigo-900 flex items-center justify-center">
        <div className="text-center text-white">
          <LoadingIcon size="lg" className="mx-auto mb-4 animate-spin" />
          <p className="text-xl">Перевірка доступу...</p>
        </div>
      </div>
    );
  }

  // Додаткова перевірка токена в localStorage
  const sessionId = localStorage.getItem("sessionId");

  // Якщо не авторизований або немає токена - показуємо сторінку входу
  if (!auth.isAuthenticated || !auth.user || !sessionId) {
    return <LoginPage />;
  }

  // Перевірка ролі користувача
  if (!hasRequiredRole(auth.user.role, requiredRole)) {
    return fallback ? (
      <div>{fallback}</div>
    ) : (
      <AccessDeniedPage requiredRole={requiredRole} userRole={auth.user.role} />
    );
  }

  // Перевірка дозволів
  if (
    requiredPermissions.length > 0 &&
    !hasRequiredPermissions(auth.user.permissions, requiredPermissions)
  ) {
    return fallback ? (
      <div>{fallback}</div>
    ) : (
      <AccessDeniedPage requiredPermissions={requiredPermissions} />
    );
  }

  // Користувач авторизований і має необхідні права
  return <div>{children}</div>;
};

// Функція перевірки ролі
const hasRequiredRole = (userRole: string, requiredRole: string): boolean => {
  const roleHierarchy = {
    viewer: 0,
    user: 1,
    admin: 2,
  };

  const userLevel = roleHierarchy[userRole as keyof typeof roleHierarchy] ?? -1;
  const requiredLevel =
    roleHierarchy[requiredRole as keyof typeof roleHierarchy] ?? 999;

  return userLevel >= requiredLevel;
};

// Функція перевірки дозволів
const hasRequiredPermissions = (
  userPermissions: string[],
  requiredPermissions: string[],
): boolean => {
  return requiredPermissions.every((permission) =>
    userPermissions.includes(permission),
  );
};

// Компонент для відображення помилки доступу
interface AccessDeniedPageProps {
  requiredRole?: string;
  userRole?: string;
  requiredPermissions?: string[];
}

const AccessDeniedPage: React.FC<AccessDeniedPageProps> = ({
  requiredRole,
  userRole,
  requiredPermissions,
}) => {
  const { logout } = useAuth();

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-blue-900 to-indigo-900 flex items-center justify-center p-4">
      <div className="max-w-md w-full text-center">
        <div className="bg-white/10 backdrop-blur-lg rounded-2xl shadow-2xl border border-white/20 p-8">
          <div className="mb-6">
            <ErrorIcon size="xl" className="mx-auto text-red-400 mb-4" />
            <h1 className="text-3xl font-bold text-white mb-2">
              Доступ заборонено
            </h1>
            <p className="text-blue-200">
              У вас немає прав для перегляду цієї сторінки
            </p>
          </div>

          <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4 mb-6">
            <div className="text-left space-y-2">
              {requiredRole && userRole && (
                <div>
                  <p className="text-red-200 text-sm">
                    <span className="font-medium">Необхідна роль:</span>{" "}
                    {getRoleDisplayName(requiredRole)}
                  </p>
                  <p className="text-red-300 text-sm">
                    <span className="font-medium">Ваша роль:</span>{" "}
                    {getRoleDisplayName(userRole)}
                  </p>
                </div>
              )}

              {requiredPermissions && requiredPermissions.length > 0 && (
                <div>
                  <p className="text-red-200 text-sm font-medium">
                    Необхідні дозволи:
                  </p>
                  <ul className="text-red-300 text-sm mt-1 space-y-1">
                    {requiredPermissions.map((permission, index) => (
                      <li key={index} className="flex items-center space-x-2">
                        <span className="w-1 h-1 bg-red-400 rounded-full"></span>
                        <span>{getPermissionDisplayName(permission)}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </div>

          <div className="space-y-3">
            <button
              onClick={() => window.history.back()}
              className="w-full py-3 px-4 bg-blue-600 text-white font-medium rounded-xl hover:bg-blue-700 transition-colors duration-300"
            >
              Повернутися назад
            </button>

            <button
              onClick={logout}
              className="w-full py-3 px-4 bg-white/10 text-white font-medium rounded-xl hover:bg-white/20 transition-colors duration-300 border border-white/20"
            >
              Вийти з системи
            </button>
          </div>

          <div className="mt-6 text-blue-200 text-sm">
            <p>Потрібна допомога? Зв'яжіться з адміністратором системи</p>
          </div>
        </div>
      </div>
    </div>
  );
};

// Функції для відображення назв ролей та дозволів
const getRoleDisplayName = (role: string): string => {
  const roleNames = {
    viewer: "Глядач",
    user: "Користувач",
    admin: "Адміністратор",
  };

  return roleNames[role as keyof typeof roleNames] || role;
};

const getPermissionDisplayName = (permission: string): string => {
  const permissionNames = {
    "dashboard.view": "Перегляд панелі",
    "clients.view": "Перегляд клієнтів",
    "clients.manage": "Управління клієнтами",
    "tasks.view": "Перегляд завдань",
    "tasks.manage": "Управління завданнями",
    "settings.view": "Перегляд налаштувань",
    "settings.manage": "Управління налаштуваннями",
    "users.view": "Перегляд користувачів",
    "users.manage": "Управління користувачами",
    "logs.view": "Перегляд логів",
    "metrics.view": "Перегляд метрик",
    "system.manage": "Управління системою",
  };

  return (
    permissionNames[permission as keyof typeof permissionNames] || permission
  );
};
