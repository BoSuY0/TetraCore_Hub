import React, { createContext, useContext, useEffect, ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useSettings } from './SettingsContext';

interface I18nContextType {
  currentLanguage: string;
  changeLanguage: (language: string) => void;
  t: (key: string, options?: any) => string;
  isReady: boolean;
}

const I18nContext = createContext<I18nContextType | undefined>(undefined);

export const useI18n = (): I18nContextType => {
  const context = useContext(I18nContext);
  if (!context) {
    throw new Error('useI18n must be used within an I18nProvider');
  }
  return context;
};

interface I18nProviderProps {
  children: ReactNode;
}

export const I18nProvider: React.FC<I18nProviderProps> = ({ children }) => {
  const { t, i18n, ready } = useTranslation();
  const { settings, updateSettings } = useSettings();

  // Синхронізація мови з налаштуваннями
  useEffect(() => {
    if (ready && settings.ui.language !== i18n.language) {
      i18n.changeLanguage(settings.ui.language);
    }
  }, [settings.ui.language, i18n, ready]);

  // Оновлення налаштувань при зміні мови
  useEffect(() => {
    if (ready && i18n.language !== settings.ui.language) {
      updateSettings('ui', { language: i18n.language as 'uk' | 'en' });
    }
  }, [i18n.language, settings.ui.language, updateSettings, ready]);

  const changeLanguage = async (language: string) => {
    try {
      await i18n.changeLanguage(language);
      updateSettings('ui', { language: language as 'uk' | 'en' });
    } catch (error) {
      console.error('Failed to change language:', error);
    }
  };

  const value: I18nContextType = {
    currentLanguage: i18n.language,
    changeLanguage,
    t,
    isReady: ready,
  };

  return (
    <I18nContext.Provider value={value}>
      {children}
    </I18nContext.Provider>
  );
}; 