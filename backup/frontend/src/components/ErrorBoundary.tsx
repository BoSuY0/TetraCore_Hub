import React, { Component, ErrorInfo, ReactNode } from 'react';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error?: Error;
  errorInfo?: ErrorInfo;
}

class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error: Error): State {
    // Оновлюємо стан, щоб показати fallback UI
    return {
      hasError: true,
      error,
    };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    // Логуємо помилку для debugging
    console.error('🚨 ErrorBoundary перехопив помилку:', error);
    console.error('📍 Стек помилки:', errorInfo.componentStack);
    
    // Зберігаємо детальну інформацію про помилку
    this.setState({
      error,
      errorInfo,
    });

    // Можна відправити помилку до сервісу моніторингу (Sentry, LogRocket тощо)
    if (process.env.NODE_ENV === 'production') {
      // Тут можна додати відправку до Sentry
      console.error('Production error captured:', {
        error: error.message,
        stack: error.stack,
        componentStack: errorInfo.componentStack,
        timestamp: new Date().toISOString(),
      });
    }
  }

  private handleRetry = () => {
    // Скидаємо стан помилки для повторної спроби
    this.setState({
      hasError: false,
      error: undefined,
      errorInfo: undefined,
    });
  };

  private handleReload = () => {
    // Перезавантажуємо сторінку
    window.location.reload();
  };

  render() {
    if (this.state.hasError) {
      // Показуємо fallback UI або кастомний компонент
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <div className="min-h-screen bg-gray-50 flex flex-col justify-center items-center px-4">
          <div className="max-w-md w-full bg-white rounded-lg shadow-lg p-6">
            {/* Header */}
            <div className="flex items-center mb-4">
              <div className="flex-shrink-0">
                <div className="w-10 h-10 bg-red-100 rounded-full flex items-center justify-center">
                  <svg
                    className="w-6 h-6 text-red-600"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L3.082 16.5c-.77.833.192 2.5 1.732 2.5z"
                    />
                  </svg>
                </div>
              </div>
              <div className="ml-4">
                <h2 className="text-lg font-semibold text-gray-900">
                  Щось пішло не так
                </h2>
                <p className="text-sm text-gray-600">
                  Виникла непередбачена помилка
                </p>
              </div>
            </div>

            {/* Error details (тільки в development) */}
            {process.env.NODE_ENV === 'development' && this.state.error && (
              <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded">
                <h3 className="text-sm font-medium text-red-800 mb-2">
                  Деталі помилки (dev mode):
                </h3>
                <p className="text-xs text-red-700 font-mono">
                  {this.state.error.message}
                </p>
                {this.state.error.stack && (
                  <details className="mt-2">
                    <summary className="text-xs text-red-600 cursor-pointer">
                      Показати стек помилки
                    </summary>
                    <pre className="text-xs text-red-700 mt-1 whitespace-pre-wrap">
                      {this.state.error.stack}
                    </pre>
                  </details>
                )}
              </div>
            )}

            {/* User-friendly message */}
            <div className="mb-6">
              <p className="text-gray-700 text-sm mb-2">
                Спробуйте оновити сторінку або повторіть спробу пізніше.
              </p>
              <p className="text-gray-500 text-xs">
                Якщо проблема повторюється, зверніться до адміністратора.
              </p>
            </div>

            {/* Action buttons */}
            <div className="flex space-x-3">
              <button
                onClick={this.handleRetry}
                className="flex-1 bg-blue-600 text-white py-2 px-4 rounded-md text-sm font-medium hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 transition-colors"
              >
                Спробувати знову
              </button>
              <button
                onClick={this.handleReload}
                className="flex-1 bg-gray-600 text-white py-2 px-4 rounded-md text-sm font-medium hover:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-gray-500 focus:ring-offset-2 transition-colors"
              >
                Перезавантажити
              </button>
            </div>
          </div>
          
          {/* Additional info */}
          <div className="mt-4 text-center">
            <p className="text-xs text-gray-400">
              Error ID: {this.state.error?.name || 'Unknown'} - {new Date().toISOString()}
            </p>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary; 