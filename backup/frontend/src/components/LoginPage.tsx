import React, { useState, useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { useI18n } from '../contexts/I18nContext';

export const LoginPage: React.FC = () => {
  const { t } = useI18n();
  const { auth, login, clearError } = useAuth();
  const [isScriptLoaded, setIsScriptLoaded] = useState(false);
  const [loginAttempts, setLoginAttempts] = useState(0);
  const [isMounted, setIsMounted] = useState(false);

  useEffect(() => {
    setIsMounted(true);
  }, []);

  // Якщо вже авторизовані і знаходимося на /login — перенаправляємо на корінь
  useEffect(() => {
    if (auth.isAuthenticated && typeof window !== 'undefined' && window.location.pathname === '/login') {
      try {
        window.location.replace('/');
      } catch {
        window.location.href = '/';
      }
    }
  }, [auth.isAuthenticated]);

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');

  // Обробка входу з логіном та паролем
  const handleLogin = async () => {
    setLoginAttempts((prev) => prev + 1);
    const ok = await login(username, password);
    if (ok && typeof window !== 'undefined') {
      // Якщо ми справді знаходимося на окремому маршруті /login — виконаємо редірект.
      // Інакше (рендер через ProtectedRoute) просто даємо React перемалювати UI без перезавантаження.
      if (window.location.pathname === '/login') {
        try {
          window.location.replace('/');
        } catch {
          window.location.href = '/';
        }
      }
    }
  };

  // Submit форми
  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    await handleLogin();
  };

  // Очищення помилки при зміні спроб входу
  useEffect(() => {
    clearError();
  }, [loginAttempts, clearError]);

  // Рендеринг помилки
  const renderError = () => {
    if (!auth.error) return null;
    return (
      <div className="bg-red-900/20 border border-red-500/50 rounded-lg p-3 text-sm text-red-200 mt-4 animate-fadeIn">
        {auth.error}
      </div>
    );
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-900 text-gray-100 p-4">
      <div
        className={`w-full max-w-md bg-gray-800/50 rounded-xl shadow-lg p-8 border border-gray-700/50 backdrop-blur-sm transition-all duration-700 ease-in-out ${isMounted ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-10'}`}
      >
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-blue-400 mb-2">TetraCore Hub</h1>
          <p className="text-gray-400">Увійдіть для доступу до панелі управління</p>
        </div>

        {/* Форма для входу з логіном та паролем */}
        <form className="mb-6" onSubmit={handleSubmit}>
          <div className="mb-4">
            <label htmlFor="username" className="block text-gray-300 mb-2">Логін</label>
            <input
              type="text"
              id="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full bg-gray-700 text-white rounded-lg py-3 px-4 border border-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-transform duration-200 ease-out focus:scale-105"
              placeholder="Введіть логін"
              autoComplete="username"
              required
            />
          </div>
          <div className="mb-6">
            <label htmlFor="password" className="block text-gray-300 mb-2">Пароль</label>
            <input
              type="password"
              id="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full bg-gray-700 text-white rounded-lg py-3 px-4 border border-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-transform duration-200 ease-out focus:scale-105"
              placeholder="Введіть пароль"
              autoComplete="current-password"
              required
            />
          </div>
          <button
            type="submit"
            disabled={auth.isLoading}
            className={`w-full bg-blue-600 hover:bg-blue-700 text-white font-medium py-3 px-6 rounded-lg transition duration-200 disabled:opacity-50 disabled:cursor-not-allowed ${!username || !password ? 'animate-pulse' : ''}`}
          >
            {auth.isLoading ? (
              <span className="flex items-center justify-center">
                <span>Завантаження...</span>
              </span>
            ) : (
              <span className="text-white font-medium">Увійти</span>
            )}
          </button>
          {renderError()}
        </form>
      </div>
    </div>
  );
};