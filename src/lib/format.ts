/** Currency / number formatting helpers — used across cards, chat, charts. */

const LOCALE_FOR_CCY: Record<string, string> = {
  TRY: "tr-TR",
  EUR: "de-DE",
  USD: "en-US",
  GBP: "en-GB",
};

export function formatCurrency(value: number, currency = "USD") {
  const locale = LOCALE_FOR_CCY[currency.toUpperCase()] ?? "en-US";
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency,
    maximumFractionDigits: Math.abs(value) >= 100 ? 0 : 2,
  }).format(value);
}

export function formatPercent(value: number, digits = 1) {
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

/**
 * Format a holding quantity. Whole numbers render clean (no decimals);
 * fractional quantities (crypto) cap at 6 decimals and trim trailing zeros,
 * so 1.205690860857246 → "1.205691" instead of a 16-digit float.
 */
export function formatQuantity(value: number) {
  if (!Number.isFinite(value)) return "0";
  if (Number.isInteger(value)) return value.toLocaleString("en-US");
  return value.toLocaleString("en-US", { maximumFractionDigits: 6 });
}

export function formatCompact(value: number) {
  return new Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}
