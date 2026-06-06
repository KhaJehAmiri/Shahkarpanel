export type DataLimitUnit = "GB" | "MB";

const MB = 1024 ** 2;
const GB = 1024 ** 3;

/** Pick the most natural unit when loading an existing byte limit. */
export function detectDataLimitUnit(bytes: number): DataLimitUnit {
  if (!bytes) return "GB";
  if (bytes % GB === 0) return "GB";
  if (bytes % MB === 0) return "MB";
  return bytes >= GB ? "GB" : "MB";
}

export function bytesToDataLimitValue(bytes: number, unit: DataLimitUnit): string {
  if (!bytes) return "";
  const divisor = unit === "GB" ? GB : MB;
  const val = bytes / divisor;
  if (unit === "MB") return String(Math.round(val));
  const s = val.toFixed(3);
  return s.replace(/\.?0+$/, "");
}

export function dataLimitToBytes(value: string, unit: DataLimitUnit): number {
  const n = parseFloat(value);
  if (!Number.isFinite(n) || n <= 0) return 0;
  const mult = unit === "GB" ? GB : MB;
  return Math.round(n * mult);
}
