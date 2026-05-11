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

export function formatCompact(value: number) {
  return new Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}
