import type { Landing, TransferRow } from "../types";

/** What a mission needs from its landing. */
export interface Requirements {
  from: string;              // first TLI day, YYYY-MM-DD
  to: string;                // last TLI day
  minDaylightDays: number;   // sunlight at the site after touchdown
  maxWaitDays: number;       // days in lunar orbit before descent
  maxSurfaceMs: number | null;  // LOI + plane change + descent
  requireDsn: boolean;          // touchdown in view of a NASA DSN station
  minEnergyPct: number | null;  // solar energy over the first days on the surface, % of full Sun
}

export interface PlanOption {
  row: TransferRow;
  landing: Landing;
  landingMs: number;         // touchdown, ms since the Unix epoch (UTC)
}

export interface LaunchDay {
  day: string;
  tried: number;
  options: PlanOption[];
  best: PlanOption | null;
}

export interface LaunchWindow {
  first: string;             // first TLI day that meets the requirements
  last: string;
  spanDays: number;          // last - first + one grid step
  days: LaunchDay[];
  best: PlanOption;
}

export interface Plan {
  days: LaunchDay[];
  windows: LaunchWindow[];
  ranked: PlanOption[];      // best transfer of each qualifying launch date, best first
  gridDays: number;          // spacing of the database's TLI dates
  matching: number;          // transfers meeting the requirements
  considered: number;        // transfers with a TLI in the range
}

const DAY_MS = 86400e3;
export const dayOf = (iso: string) => iso.slice(0, 10);
export const dayMs = (day: string) => Date.parse(`${day}T00:00:00Z`);

export function landingTimeMs(row: TransferRow, l: Landing): number {
  return Date.parse(row.tli_utc) + (row.tof_actual_days + (l.waitDays ?? 0)) * DAY_MS;
}

export function meets(l: Landing | null, req: Requirements): l is Landing {
  if (!l?.feasible || l.waitDays === null || l.daylightDays === null || l.surfaceMs === null) return false;
  if (l.waitDays > req.maxWaitDays) return false;
  // Daylight capped at the look-ahead horizon counts as "at least" that much.
  if (l.daylightDays < req.minDaylightDays && !(l.daylightCapped && l.daylightDays >= req.minDaylightDays - 1e-9)) return false;
  if (req.maxSurfaceMs !== null && l.surfaceMs > req.maxSurfaceMs) return false;
  if (req.requireDsn && !l.dsn) return false;
  if (req.minEnergyPct !== null && (l.energyPct ?? 100) < req.minEnergyPct) return false;
  return true;
}

/** Cheapest first; ties go to more sunlight, then the shorter wait. */
export function better(a: PlanOption, b: PlanOption): number {
  return (a.landing.surfaceMs! - b.landing.surfaceMs!) ||
    (b.landing.daylightDays! - a.landing.daylightDays!) ||
    (a.landing.waitDays! - b.landing.waitDays!);
}

function gridOf(days: string[]): number {
  let g = Infinity;
  for (let i = 1; i < days.length; i++) g = Math.min(g, (dayMs(days[i]) - dayMs(days[i - 1])) / DAY_MS);
  return Number.isFinite(g) && g > 0 ? g : 1;
}

/** Reverse query: every transfer that lands at the site the way the mission needs,
 *  grouped by TLI day into launch windows (runs of consecutive database dates). */
export function plan(rows: TransferRow[], landingOf: (r: TransferRow) => Landing | null, req: Requirements): Plan {
  const inRange = rows.filter((r) => {
    const d = dayOf(r.tli_utc);
    return d >= req.from && d <= req.to;
  });
  const byDay = new Map<string, LaunchDay>();
  let matching = 0;
  for (const r of inRange) {
    const d = dayOf(r.tli_utc);
    let entry = byDay.get(d);
    if (!entry) byDay.set(d, (entry = { day: d, tried: 0, options: [], best: null }));
    entry.tried++;
    const l = landingOf(r);
    if (meets(l, req)) {
      const o = { row: r, landing: l, landingMs: landingTimeMs(r, l) };
      entry.options.push(o);
      matching++;
      if (!entry.best || better(o, entry.best) < 0) entry.best = o;
    }
  }
  const days = [...byDay.values()].sort((a, b) => (a.day < b.day ? -1 : 1));
  const gridDays = gridOf(days.map((d) => d.day));

  const windows: LaunchWindow[] = [];
  let run: LaunchDay[] = [];
  const close = () => {
    if (!run.length) return;
    const best = run.map((d) => d.best!).reduce((a, b) => (better(a, b) <= 0 ? a : b));
    const first = run[0].day, last = run[run.length - 1].day;
    windows.push({ first, last, spanDays: (dayMs(last) - dayMs(first)) / DAY_MS + gridDays, days: run, best });
    run = [];
  };
  for (const d of days) {
    const prev = run[run.length - 1];
    const contiguous = prev && (dayMs(d.day) - dayMs(prev.day)) / DAY_MS <= gridDays + 1e-6;
    if (d.best && (contiguous || !prev)) run.push(d);
    else {
      close();
      if (d.best) run.push(d);
    }
  }
  close();

  // One entry per launch date (its best transfer), so the list shows real alternatives.
  const ranked = days.flatMap((d) => (d.best ? [d.best] : [])).sort(better);
  return { days, windows, ranked, gridDays, matching, considered: inRange.length };
}

/** How far the launch of `row` can slip (later) and still meet the requirements. */
export function slipTolerance(p: Plan, row: TransferRow | null): { window: LaunchWindow; slipDays: number; earlyDays: number } | null {
  if (!row) return null;
  const d = dayOf(row.tli_utc);
  const w = p.windows.find((x) => x.first <= d && d <= x.last);
  if (!w) return null;
  return {
    window: w,
    slipDays: (dayMs(w.last) - dayMs(d)) / DAY_MS,
    earlyDays: (dayMs(d) - dayMs(w.first)) / DAY_MS,
  };
}
