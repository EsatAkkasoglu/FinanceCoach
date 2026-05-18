export const supportedLanguages = ["en", "tr"] as const;

export type SupportedLanguage = (typeof supportedLanguages)[number];

export function isSupportedLanguage(value: string | undefined | null): value is SupportedLanguage {
  return value === "en" || value === "tr";
}

export function getLanguageFromPath(pathname: string): SupportedLanguage | null {
  const firstSegment = pathname.split("/")[1];
  return isSupportedLanguage(firstSegment) ? firstSegment : null;
}

export function stripLanguagePrefix(pathname: string): string {
  const lang = getLanguageFromPath(pathname);
  if (!lang) return pathname;

  const remainder = pathname.slice(lang.length + 1);
  return remainder.length > 0 ? remainder : "/";
}

export function buildLocalizedPath(language: SupportedLanguage, pathname: string): string {
  const stripped = stripLanguagePrefix(pathname);
  if (stripped === "/") {
    return `/${language}/dashboard`;
  }
  return `/${language}${stripped.startsWith("/") ? stripped : `/${stripped}`}`;
}
