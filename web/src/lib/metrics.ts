import type { Landing, MetricKey, TransferRow } from "../types";

export interface Metric {
  key: MetricKey;
  label: string;        // short, for controls and axes
  long: string;         // sentence-case description
  unit: string;
  digits: number;
  better: "low" | "high";
  best: string;         // how the best cell is announced
  needsSite: boolean;
  /** null when the transfer has no value for this metric (no landing window). */
  value: (r: TransferRow, l: Landing | null) => number | null;
}

export const METRICS: Record<MetricKey, Metric> = {
  loi: {
    key: "loi", label: "LOI Δv", long: "Lunar orbit insertion burn", unit: "m/s", digits: 1,
    better: "low", best: "Lowest LOI Δv", needsSite: false, value: (r) => r.loi_dv_ms,
  },
  total: {
    key: "total", label: "Total Δv", long: "Trans-lunar injection plus lunar orbit insertion", unit: "m/s",
    digits: 1, better: "low", best: "Lowest total Δv", needsSite: false, value: (r) => r.total_dv_ms,
  },
  tli: {
    key: "tli", label: "TLI Δv", long: "Trans-lunar injection burn from the parking orbit", unit: "m/s",
    digits: 1, better: "low", best: "Lowest TLI Δv", needsSite: false, value: (r) => r.tli_dv_ms,
  },
  c3: {
    key: "c3", label: "C3", long: "Launch energy the vehicle has to deliver", unit: "km²/s²", digits: 3,
    better: "low", best: "Lowest C3", needsSite: false, value: (r) => r.c3_km2s2,
  },
  vinf: {
    key: "vinf", label: "v∞ at Moon", long: "Approach speed relative to the Moon", unit: "km/s", digits: 3,
    better: "low", best: "Slowest approach", needsSite: false, value: (r) => r.v_inf_kms,
  },
  surface: {
    key: "surface", label: "Δv to surface", long: "Lunar orbit insertion, plane change and descent to the site",
    unit: "m/s", digits: 0, better: "low", best: "Lowest Δv to surface", needsSite: true,
    value: (_r, l) => (l?.feasible ? l.surfaceMs : null),
  },
  wait: {
    key: "wait", label: "Wait in orbit", long: "Days in lunar orbit before the landing window opens",
    unit: "days", digits: 1, better: "low", best: "Shortest wait", needsSite: true,
    value: (_r, l) => (l?.feasible ? l.waitDays : null),
  },
  daylight: {
    key: "daylight", label: "Sunlight after landing", long: "Days of sunlight at the site after touchdown",
    unit: "days", digits: 1, better: "high", best: "Most sunlight", needsSite: true,
    value: (_r, l) => (l?.feasible ? l.daylightDays : null),
  },
};

export const TRANSFER_METRICS: MetricKey[] = ["loi", "total", "tli", "c3", "vinf"];
export const LANDING_METRICS: MetricKey[] = ["surface", "wait", "daylight"];

/** Negative when a is better than b. Missing values sort last. */
export function compareBy(metric: Metric, a: number | null, b: number | null): number {
  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  return metric.better === "low" ? a - b : b - a;
}
