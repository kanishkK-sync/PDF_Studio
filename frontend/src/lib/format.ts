const UNITS = ["B", "KB", "MB", "GB", "TB"] as const;

// Never uses Intl or toLocaleString, so server and browser always agree.
function trimTrailingZero(text: string): string {
  return text.replace(/\.0$/, "");
}

// Binary units (1 KB = 1024 B), matching what Windows Explorer shows.
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";

  const last = UNITS.length - 1;
  let value = bytes;
  let index = 0;
  // 1023.5 rather than 1024 so a value that would round up to "1024 KB"
  // moves to the next unit instead.
  while (index < last && value >= 1023.5) {
    value /= 1024;
    index += 1;
  }

  const digits = index === 0 ? 0 : value < 10 ? 1 : 0;
  return `${trimTrailingZero(value.toFixed(digits))} ${UNITS[index]}`;
}

// Input is a percentage (42.3 means 42.3%). Clamped to 0-100, one decimal.
export function formatPercent(percent: number): string {
  if (!Number.isFinite(percent)) return "0%";
  const clamped = Math.min(100, Math.max(0, percent));
  return `${trimTrailingZero(clamped.toFixed(1))}%`;
}