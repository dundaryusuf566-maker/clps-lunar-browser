/** Battery bookkeeping for the power-budget panel: pure functions, tested by web/tests/power.check.mjs. */
/** What the simulation reads: the series length and the sunlight (a thermal.json point, or a browser run). */
export interface Sunlight { surface_k: ArrayLike<number>; dni_w_m2?: ArrayLike<number>; sun_el_deg?: ArrayLike<number> }

export type Mount = "tracking" | "vertical" | "horizontal" | "facing";
export interface Params {
  area: number; eff: number; mount: Mount; battery: number; usable: number; dayLoad: number; nightLoad: number; days: number;
}
export const DEFAULTS: Params = { area: 2, eff: 28, mount: "tracking", battery: 1500, usable: 80, dayLoad: 150, nightLoad: 80, days: 14 };
export const MOUNTS: Record<Mount, string> = {
  tracking: "Vertical, turning to face the Sun",
  vertical: "Vertical, fixed (Sun from any side: average)",
  horizontal: "Horizontal, on the deck",
  facing: "Always facing the Sun (two-axis tracking)",
};

/** Panel power per m^2 of panel, from the sunlight reaching the site (disc share already in dni). */
export function panelFactor(mount: Mount, elDeg: number): number {
  const el = (Math.max(elDeg, 0) * Math.PI) / 180;
  if (mount === "tracking") return Math.cos(el);
  if (mount === "facing") return 1;
  if (mount === "vertical") return Math.cos(el) / Math.PI;          // flat vertical panel, Sun azimuth uniform over a turn
  return Math.sin(el);
}

export interface Run { soc: number[]; t: number[]; minSoc: number; minAt: number; survives: boolean; deadAt: number | null;
  darkH: number; energyIn: number; energyOut: number }

export function simulate(p: Sunlight, t0: number, stepH: number, startIdx: number, P: Params): Run {
  const n = Math.min(p.surface_k.length - startIdx, Math.round((P.days * 24) / stepH) + 1);
  const cap = P.battery, floor = cap * (1 - P.usable / 100);
  let e = cap, minSoc = cap, minAt = 0, deadAt: number | null = null, dark = 0, longest = 0, eIn = 0, eOut = 0;
  const soc: number[] = [], t: number[] = [];
  for (let i = 0; i < n; i++) {
    const k = startIdx + i;
    const dni = p.dni_w_m2?.[k] ?? 0, el = p.sun_el_deg?.[k] ?? 0;
    const pv = dni * panelFactor(P.mount, el) * P.area * (P.eff / 100);
    const load = dni > 1 ? P.dayLoad : P.nightLoad;
    dark = dni > 1 ? 0 : dark + stepH;
    longest = Math.max(longest, dark);
    t.push(t0 + k * stepH * 3600e3);
    if (i > 0) {
      const raw = e + (pv - load) * stepH;
      if (deadAt === null && raw < floor - 1e-9) deadAt = t[t.length - 1];
      e = Math.max(0, Math.min(cap, raw));      // an empty battery stays empty until the Sun returns
      eIn += pv * stepH;
      eOut += load * stepH;
    }
    soc.push(e);
    if (e < minSoc) { minSoc = e; minAt = t[t.length - 1]; }
  }
  return { soc, t, minSoc, minAt, survives: deadAt === null, deadAt, darkH: longest, energyIn: eIn, energyOut: eOut };
}

/** Smallest value of `key` (between lo and hi) that survives, by bisection; null if even hi does not. */
export function smallest(p: Sunlight, t0: number, stepH: number, startIdx: number, P: Params, key: "battery" | "area", lo: number, hi: number) {
  const ok = (v: number) => simulate(p, t0, stepH, startIdx, { ...P, [key]: v }).survives;
  if (!ok(hi)) return null;
  if (ok(lo)) return lo;
  for (let i = 0; i < 40; i++) {
    const m = (lo + hi) / 2;
    if (ok(m)) hi = m; else lo = m;
  }
  return hi;
}

