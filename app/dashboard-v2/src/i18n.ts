import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import en from "./locales/en.json";
import fa from "./locales/fa.json";
import ru from "./locales/ru.json";
import zh from "./locales/zh.json";

export const LANGUAGES = [
  { code: "en", label: "English", dir: "ltr", flag: "🇬🇧" },
  { code: "fa", label: "فارسی", dir: "rtl", flag: "🇮🇷" },
  { code: "ru", label: "Русский", dir: "ltr", flag: "🇷🇺" },
  { code: "zh", label: "中文", dir: "ltr", flag: "🇨🇳" },
] as const;

const LS_KEY = "nx_lang";

export function getStoredLang(): string {
  const stored = localStorage.getItem(LS_KEY);
  if (stored && LANGUAGES.some((l) => l.code === stored)) return stored;
  const nav = navigator.language?.slice(0, 2);
  return LANGUAGES.some((l) => l.code === nav) ? nav : "en";
}

export function applyDir(lang: string) {
  const meta = LANGUAGES.find((l) => l.code === lang);
  const dir = meta?.dir || "ltr";
  document.documentElement.setAttribute("dir", dir);
  document.documentElement.setAttribute("lang", lang);
}

export function setLanguage(lang: string) {
  localStorage.setItem(LS_KEY, lang);
  i18n.changeLanguage(lang);
  applyDir(lang);
}

const initial = getStoredLang();

i18n.use(initReactI18next).init({
  resources: {
    en: { translation: en },
    fa: { translation: fa },
    ru: { translation: ru },
    zh: { translation: zh },
  },
  lng: initial,
  fallbackLng: "en",
  interpolation: { escapeValue: false },
});

applyDir(initial);

export default i18n;
