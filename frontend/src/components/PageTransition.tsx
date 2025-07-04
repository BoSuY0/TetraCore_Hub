import React, { useEffect, useState, ReactNode } from 'react';

interface PageTransitionProps {
  children: ReactNode;
  pageKey: string;
  animationType?: 'dashboard' | 'clients' | 'tasks' | 'metrics' | 'settings' | 'default';
  className?: string;
}

export const PageTransition: React.FC<PageTransitionProps> = ({
  children,
  pageKey,
  animationType = 'default',
  className = ''
}) => {
  const [isVisible, setIsVisible] = useState(false);
  const [currentKey, setCurrentKey] = useState(pageKey);

  useEffect(() => {
    if (pageKey !== currentKey) {
      // Початок переходу - приховуємо поточний контент
      setIsVisible(false);
      
      // Після короткої затримки показуємо новий контент
      const timer = setTimeout(() => {
        setCurrentKey(pageKey);
        setIsVisible(true);
      }, 150);

      return () => clearTimeout(timer);
    } else if (!isVisible) {
      // Перший рендер або повернення до видимості
      setIsVisible(true);
    }
  }, [pageKey, currentKey, isVisible]);

  const getAnimationClass = () => {
    if (!isVisible) return 'page-transition-out';
    
    switch (animationType) {
      case 'dashboard':
        return 'page-enter-dashboard';
      case 'clients':
        return 'page-enter-clients';
      case 'tasks':
        return 'page-enter-tasks';
      case 'metrics':
        return 'page-enter-metrics';
      case 'settings':
        return 'page-enter-settings';
      default:
        return 'page-enter';
    }
  };

  return (
    <div 
      key={currentKey}
      className={`${getAnimationClass()} ${className}`}
      style={{ 
        minHeight: '200px',
        // Забезпечуємо плавність переходу
        willChange: 'transform, opacity'
      }}
    >
      {isVisible && children}
    </div>
  );
};

// Хук для легкого використання анімацій контенту
export const usePageAnimation = (delay: number = 0) => {
  const [isLoaded, setIsLoaded] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => {
      setIsLoaded(true);
    }, delay);

    return () => clearTimeout(timer);
  }, [delay]);

  return isLoaded;
};

// Компонент для анімації заголовків
export const AnimatedPageHeader: React.FC<{
  children: ReactNode;
  className?: string;
}> = ({ children, className = '' }) => {
  return (
    <div className={`page-header-enter ${className}`}>
      {children}
    </div>
  );
};

// Компонент для анімації карток з автоматичною затримкою
export const AnimatedCard: React.FC<{
  children: ReactNode;
  index?: number;
  className?: string;
  animationType?: 'card' | 'grid' | 'list' | 'chart';
}> = ({ children, index = 0, className = '', animationType = 'card' }) => {
  const getAnimationClass = () => {
    const delayClass = index < 6 ? `page-${animationType}-enter-${index + 1}` : '';
    return `page-${animationType}-enter ${delayClass}`;
  };

  return (
    <div className={`${getAnimationClass()} ${className}`}>
      {children}
    </div>
  );
};

// Компонент для анімації списків з послідовною появою елементів
export const AnimatedList: React.FC<{
  children: ReactNode[];
  className?: string;
  staggerDelay?: number;
}> = ({ children, className = '', staggerDelay = 100 }) => {
  return (
    <div className={className}>
      {children.map((child, index) => (
        <div 
          key={index}
          className="page-content-stagger"
          style={{ 
            animationDelay: `${index * staggerDelay}ms` 
          }}
        >
          {child}
        </div>
      ))}
    </div>
  );
}; 