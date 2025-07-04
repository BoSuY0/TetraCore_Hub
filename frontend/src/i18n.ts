import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import LanguageDetector from "i18next-browser-languagedetector";

// Імпортуємо ресурси для перекладу
import translationEN from "./locales/en/translation.json";
import translationUK from "./locales/uk/translation.json";

// Ресурси для кожної мови
const resources = {
  en: {
    translation: translationEN,
  },
  uk: {
    translation: translationUK,
  },
};

i18n
  // Виявлення мови з локальних налаштувань браузера
  .use(LanguageDetector)
  // Ініціалізація модуля react-i18next
  .use(initReactI18next)
  // Ініціалізація i18next
  .init({
    resources,
    fallbackLng: 'uk', // Мова за замовчуванням
    debug: false, // Вимикаємо debug щоб зменшити кількість логів
    lng: 'uk', // Явно встановлюємо початкову мову

    interpolation: {
      escapeValue: false, // Не екранувати HTML
    },
    
    // Опції для визначення мови
    detection: {
      order: ['localStorage', 'navigator'], // Спочатку перевіряємо localStorage, потім браузер
      lookupLocalStorage: 'tetracore-hub-language', // Ключ для localStorage
      caches: ['localStorage'], // Зберігати вибір у localStorage
    },
    
    // Інші опції можна налаштувати за необхідності
    react: {
      useSuspense: false, // Не використовувати React Suspense для завантаження перекладів
    },
    
    // Додаткові налаштування для стабільності
    initImmediate: true,
    load: 'languageOnly',
  });

export default i18n; 