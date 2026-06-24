/**
 * Feature flags — narrow the primary surface to the hero loop described in
 * docs/URUN_ODAK.md: Onboarding → Portfolio/funds tracking → weekly brief +
 * proactive news alert → "ask the coach" → return.
 *
 * Deferred surfaces (Budget/transactions, Document OCR) stay in the codebase and
 * remain deep-linkable by URL — they're only dropped from the primary nav to cut
 * cognitive load ("kullanıcı 5 şey görünce 1'ini anlar; 12 şey görünce 0'ını").
 *
 * Static (compile-time) on purpose: flip a value and rebuild. List only the
 * paths we hide; everything else is enabled by default.
 */
export const DISABLED_NAV_PATHS: Record<string, true> = {
  "/budget": true,
  "/documents": true,
};

/** True unless the base path (no language prefix) is explicitly disabled above. */
export function isNavEnabled(path: string): boolean {
  return DISABLED_NAV_PATHS[path] !== true;
}
