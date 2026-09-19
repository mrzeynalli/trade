/** Presentation helpers. Missing data is rendered as missing, never as zero. */

const MAGNITUDES: [number, string][] = [
  [1e12, "T"],
  [1e9, "B"],
  [1e6, "M"],
  [1e3, "K"],
];

/** Compact currency: 1,240,000,000 -> $1.24B */
export function compactUsd(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const sign = value < 0 ? "-" : "";
  const magnitude = Math.abs(value);
  for (const [threshold, suffix] of MAGNITUDES) {
    if (magnitude >= threshold) {
      return `${sign}$${(magnitude / threshold).toFixed(digits)}${suffix}`;
    }
  }
  return `${sign}$${magnitude.toFixed(0)}`;
}

/** Full precision for tooltips. */
export function exactUsd(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "No reported data";
  return value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
}

/**
 * Percent from a fraction. A tiny non-zero share gets two decimals rather than
 * being rounded to a misleading 0.0%.
 */
export function percent(fraction: number | null | undefined, digits = 1): string {
  if (fraction === null || fraction === undefined || Number.isNaN(fraction)) return "—";
  const value = fraction * 100;
  // A non-zero share must never be shown as 0.00%: fall back to two decimals,
  // then to an explicit "smaller than" once even that would round to zero.
  if (value !== 0 && Math.abs(value) < 0.005) return value > 0 ? "<0.01%" : ">-0.01%";
  if (value !== 0 && Math.abs(value) < 0.05) return `${value.toFixed(2)}%`;
  return `${value.toFixed(digits)}%`;
}

export function signedPercent(fraction: number | null | undefined, digits = 1): string {
  if (fraction === null || fraction === undefined || Number.isNaN(fraction)) return "—";
  const formatted = percent(fraction, digits);
  return fraction > 0 ? `+${formatted}` : formatted;
}

const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "202506" -> "Jun 2025"; "2025" stays "2025". */
export function periodLabel(period: string | number | null | undefined): string {
  if (period === null || period === undefined) return "—";
  const text = String(period);
  if (text.length === 6 && /^\d+$/.test(text)) {
    return `${MONTH_NAMES[Number(text.slice(4)) - 1]} ${text.slice(0, 4)}`;
  }
  return text;
}

export function shortPeriodLabel(period: string | number | null | undefined): string {
  const text = String(period ?? "");
  if (text.length === 6 && /^\d+$/.test(text)) {
    const month = Number(text.slice(4));
    return month === 1 ? `${MONTH_NAMES[0]} ${text.slice(2, 4)}` : MONTH_NAMES[month - 1];
  }
  return text;
}

/** HS codes carry meaning in their leading zeros: "01", never 1. */
export function hsLabel(code: string | number): string {
  return String(code);
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" }).format(date);
}

export function unitValue(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  if (value >= 1000) return `$${(value / 1000).toFixed(1)}k/kg`;
  if (value >= 1) return `$${value.toFixed(2)}/kg`;
  return `$${value.toFixed(3)}/kg`;
}

/** Population and other plain counts: 10,202,830 -> 10.2M */
export function compactNumber(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const magnitude = Math.abs(value);
  for (const [threshold, suffix] of MAGNITUDES) {
    if (magnitude >= threshold) return `${(value / threshold).toFixed(digits)}${suffix}`;
  }
  return value.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

/** Per-capita and per-unit money, where cents are noise but dollars are not. */
export function plainUsd(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `$${Math.round(value).toLocaleString("en-US")}`;
}
