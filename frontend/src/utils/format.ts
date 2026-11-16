/**
 * Defensive Data Formatting Utilities.
 * Strictly prevents runtime crashes from NaN, null, undefined, or unparsed numeric types.
 * NEVER invoke raw .toFixed() or .toLocaleString() in component JSX!
 */

/**
 * Format a price value with configurable decimal places.
 */
export function fmtPrice(val: unknown, digits: number = 2): string {
  if (val === null || val === undefined || val === "") return "-";
  const num = typeof val === "number" ? val : parseFloat(String(val));
  if (!Number.isFinite(num)) return "-";
  return num.toFixed(digits);
}

/**
 * Format currency in USD ($0.00 or +$0.00 / -$0.00).
 */
export function fmtUsd(val: unknown, showSign: boolean = false): string {
  if (val === null || val === undefined || val === "") return "$0.00";
  const num = typeof val === "number" ? val : parseFloat(String(val));
  if (!Number.isFinite(num)) return "$0.00";

  const prefix = num < 0 ? "-$" : showSign && num > 0 ? "+$" : "$";
  const absFormatted = Math.abs(num).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return `${prefix}${absFormatted}`;
}

/**
 * Format percentage (0.00% or +0.00% / -0.00%).
 */
export function fmtPct(val: unknown, showSign: boolean = false): string {
  if (val === null || val === undefined || val === "") return "0.00%";
  const num = typeof val === "number" ? val : parseFloat(String(val));
  if (!Number.isFinite(num)) return "0.00%";

  const sign = showSign && num > 0 ? "+" : "";
  return `${sign}${num.toFixed(2)}%`;
}

/**
 * Format confidence percentage.
 * Intelligently scales decimal fractions (0.0 - 1.0) to full percent (0.0% - 100.0%).
 */
export function fmtConfidence(val: unknown): string {
  if (val === null || val === undefined || val === "") return "0.0%";
  const num = typeof val === "number" ? val : parseFloat(String(val));
  if (!Number.isFinite(num)) return "0.0%";
  const pct = num <= 1.0 && num > 0.0 ? num * 100 : num;
  return `${pct.toFixed(1)}%`;
}

/**
 * Format lot sizing (e.g. 0.01 or 0.10).
 */
export function fmtLots(val: unknown): string {
  if (val === null || val === undefined || val === "") return "0.01";
  const num = typeof val === "number" ? val : parseFloat(String(val));
  if (!Number.isFinite(num)) return "0.01";
  return num.toFixed(2);
}

/**
 * Guard array mapping and filtering against non-array values.
 */
export function safeArr<T>(val: unknown): T[] {
  if (!val || !Array.isArray(val)) return [];
  return val;
}

/**
 * Safely format string with fallback.
 */
export function safeStr(val: unknown, fallback: string = "-"): string {
  if (val === null || val === undefined) return fallback;
  const s = String(val).trim();
  return s.length > 0 ? s : fallback;
}

