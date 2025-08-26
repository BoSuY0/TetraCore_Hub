// Фільтр для помилок DevTools та інших розширень браузера
export function setupDevToolsFilter() {
  // Фільтрація помилок source maps від React DevTools
  const originalError = console.error;
  console.error = (...args) => {
    const message = args[0];
    
    // Пропускаємо помилки від React DevTools та source maps
    if (typeof message === 'string' && (
      message.includes('installHook.js.map') ||
      message.includes('DevTools') ||
      message.includes('source-map') ||
      message.includes('Source map error') ||
      message.includes('JSON.parse: unexpected character') ||
      message.includes('Помилка карти джерела') ||
      message.includes('unexpected character at line 1 column 1') ||
      message.includes('.js.map') ||
      message.includes('sourcemap') ||
      message.includes('parseSourceMapInput') ||
      message.includes('source-map-loader') ||
      message.includes('fetchSourceMap') ||
      message.includes('util.js') ||
      message.includes('Stack in the worker:') ||
      message.includes('worker.js.map') ||
      message.includes('devtools.js.map') ||
      message.includes('Error: JSON.parse:') ||
      // Додаткові патерни з логів:
      message.includes('parseSourceMapInput') ||
      message.includes('Error: request to') ||
      message.includes('request timed out') ||
      message.includes('failed, reason:') ||
      message.includes('browser-extension://') ||
      message.includes('chrome-extension://') ||
      message.includes('moz-extension://') ||
      message.includes('safari-extension://') ||
      message.includes('ms-browser-extension://') ||
      // Firefox-специфічні помилки:
      message.includes('rv:139.0 Gecko') ||
      message.includes('Firefox') ||
      // React DevTools помилки:
      message.includes('react-devtools') ||
      message.includes('__REACT_DEVTOOLS_GLOBAL_HOOK__') ||
      // Hot Module Replacement помилки:
      message.includes('[HMR]') ||
      message.includes('hot update') ||
      // Vite source map помилки:
      message.includes('Failed to parse source map from') ||
      message.includes('Invalid SourceMap') ||
      // Додаткові патерни з нових логів:
      message.includes('Stack in the worker:parseSourceMapInput') ||
      message.includes('resource://devtools/client/shared/vendor/source-map/lib/util.js') ||
      message.includes('_factory@resource://devtools/client/shared/vendor/source-map/lib/source-map-consumer.js') ||
      message.includes('SourceMapConsumer@resource://devtools/client/shared/vendor/source-map/lib/source-map-consumer.js') ||
      message.includes('_fetch@resource://devtools/client/shared/source-map-loader/utils/fetchSourceMap.js') ||
      message.includes('URL джерела: http://localhost:3000/%3Canonymous%20code%3E') ||
      message.includes('URL карти джерела: installHook.js.map') ||
      // Повні Firefox DevTools stack traces:
      message.includes('resource://devtools/') ||
      message.includes('parseSourceMapInput@resource://devtools/client/shared/vendor/source-map/lib/util.js') ||
      message.includes('source-map-consumer.js:') ||
      message.includes('source-map/lib/util.js') ||
      message.includes('source-map-loader/utils/fetchSourceMap.js') ||
      message.includes('unexpected character at line 1 column 1 of the JSON data') ||
      message.includes('Стек у воркері:parseSourceMapInput') ||
      // Специфічні URL паттерни:
      message.includes('%%3Canonymous%20code%3E') ||
      message.includes('%3Canonymous%20code%3E') ||
      message.includes('<anonymous code>') ||
      message.includes('__webpack_hmr') ||
      // React DevTools специфічні помилки:
      message.includes('installHook') ||
      message.includes('__REACT_DEVTOOLS_') ||
      // Додаткові Vite/HMR помилки:
      message.includes('@vite/client') ||
      message.includes('vite:hmr') ||
      message.includes('[@vite/client]')
    )) {
      return;
    }
    
    // Виводимо всі інші помилки
    originalError.apply(console, args);
  };

  // Фільтрація попереджень
  const originalWarn = console.warn;
  console.warn = (...args) => {
    const message = args[0];
    
    if (typeof message === 'string' && (
      message.includes('DevTools') ||
      message.includes('source-map') ||
      message.includes('Source map error') ||
      message.includes('.js.map') ||
      message.includes('sourcemap') ||
      message.includes('parseSourceMapInput') ||
      message.includes('source-map-loader') ||
      message.includes('fetchSourceMap') ||
      message.includes('util.js') ||
      message.includes('Stack in the worker:') ||
      // Додаткові попередження:
      message.includes('browser-extension://') ||
      message.includes('chrome-extension://') ||
      message.includes('moz-extension://') ||
      message.includes('react-devtools') ||
      message.includes('[HMR]') ||
      message.includes('Failed to parse source map from') ||
      message.includes('Invalid SourceMap') ||
      // Firefox DevTools попередження:
      message.includes('resource://devtools/') ||
      message.includes('source-map-consumer.js:') ||
      message.includes('installHook') ||
      message.includes('__REACT_DEVTOOLS_') ||
      message.includes('@vite/client') ||
      message.includes('vite:hmr')
    )) {
      return;
    }
    
    originalWarn.apply(console, args);
  };
}

// Допоміжні функції для розробки
export function logDevInfo(message: string, data?: any) {
  if (process.env.NODE_ENV === 'development') {
    console.log(`🔧 [DEV] ${message}`, data || '');
  }
}

export function logDevError(message: string, error?: any) {
  if (process.env.NODE_ENV === 'development') {
    console.error(`❌ [DEV] ${message}`, error || '');
  }
}

export function logDevWarning(message: string, data?: any) {
  if (process.env.NODE_ENV === 'development') {
    console.warn(`⚠️ [DEV] ${message}`, data || '');
  }
} 