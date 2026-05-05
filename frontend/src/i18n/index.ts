/**
 * i18n bootstrap. Backend stores the user's UI language in `cfg.general.language`
 * and exposes it via /api/health → `language`. We init i18next synchronously
 * with English as the fallback, then async-fetch /api/health to switch to
 * the user's language. <html lang> is kept in sync so spell-check + screen
 * readers respect the choice.
 */

import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import en from "./en.json";
import zh from "./zh.json";

export const SUPPORTED_LANGUAGES = ["en", "zh"] as const;
export type SupportedLanguage = (typeof SUPPORTED_LANGUAGES)[number];

void i18n.use(initReactI18next).init({
  resources: {
    en: { translation: en },
    zh: { translation: zh },
  },
  lng: "en",
  fallbackLng: "en",
  interpolation: { escapeValue: false }, // React already escapes
  returnNull: false,
});

export async function syncLanguageFromBackend(): Promise<void> {
  try {
    const r = await fetch("/api/health");
    if (!r.ok) return;
    const data = (await r.json()) as { language?: string };
    const lang = data.language;
    if (
      typeof lang === "string" &&
      (SUPPORTED_LANGUAGES as readonly string[]).includes(lang)
    ) {
      await i18n.changeLanguage(lang);
      document.documentElement.lang = lang;
    }
  } catch {
    // Backend unreachable on first paint — stay on English fallback.
  }
}

export default i18n;
