import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import LanguageDetector from "i18next-browser-languagedetector";

import enCommon from "./locales/en/common.json";
import enAuth from "./locales/en/auth.json";
import enDashboard from "./locales/en/dashboard.json";
import enPortfolio from "./locales/en/portfolio.json";
import enBudget from "./locales/en/budget.json";
import enFunds from "./locales/en/funds.json";
import enGoals from "./locales/en/goals.json";
import enDiscover from "./locales/en/discover.json";
import enSettings from "./locales/en/settings.json";
import enChat from "./locales/en/chat.json";
import enOnboarding from "./locales/en/onboarding.json";
import enDocuments from "./locales/en/documents.json";

import trCommon from "./locales/tr/common.json";
import trAuth from "./locales/tr/auth.json";
import trDashboard from "./locales/tr/dashboard.json";
import trPortfolio from "./locales/tr/portfolio.json";
import trBudget from "./locales/tr/budget.json";
import trFunds from "./locales/tr/funds.json";
import trGoals from "./locales/tr/goals.json";
import trDiscover from "./locales/tr/discover.json";
import trSettings from "./locales/tr/settings.json";
import trChat from "./locales/tr/chat.json";
import trOnboarding from "./locales/tr/onboarding.json";
import trDocuments from "./locales/tr/documents.json";
import { getLanguageFromPath } from "@/lib/routing";

export const defaultNS = "common";
export const resources = {
  en: {
    common: enCommon,
    auth: enAuth,
    dashboard: enDashboard,
    portfolio: enPortfolio,
    budget: enBudget,
    funds: enFunds,
    goals: enGoals,
    discover: enDiscover,
    settings: enSettings,
    chat: enChat,
    onboarding: enOnboarding,
    documents: enDocuments,
  },
  tr: {
    common: trCommon,
    auth: trAuth,
    dashboard: trDashboard,
    portfolio: trPortfolio,
    budget: trBudget,
    funds: trFunds,
    goals: trGoals,
    discover: trDiscover,
    settings: trSettings,
    chat: trChat,
    onboarding: trOnboarding,
    documents: trDocuments,
  },
} as const;

const initialLanguage = typeof window !== "undefined" ? getLanguageFromPath(window.location.pathname) : null;

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources,
    defaultNS,
    lng: initialLanguage ?? undefined,
    fallbackLng: "en",
    supportedLngs: ["en", "tr"],
    detection: {
      order: ["localStorage", "navigator"],
      caches: ["localStorage"],
      lookupLocalStorage: "fincoach-lang",
    },
    interpolation: {
      escapeValue: false,
    },
  });

export default i18n;
