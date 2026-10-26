/** The journey file (scripts/build_journeys.py) and interpolation along it. */
import { add, norm, scale, sub, unit, type V3 } from "./math";

export type Q = [number, number, number, number];     // x, y, z, w

export interface JourneyEvent { id: string; label: string; t: number; utc: string }
export interface Journey {
  id: string; name: string; kind: "flown" | "forecast"; site_name: string; story: string;
  facts: Record<string, string | number | boolean | null>;
  sources: [string, string][];
  t0_utc: string; tli_epoch: number;
  t: number[]; eci: V3[]; mci: V3[]; phase: number[]; phase_names: string[]; dsn: number[];
  events: JourneyEvent[];
  hourly: { t0: number; step: number; n: number; moon: V3[]; q_moon: Q[]; q_earth: Q[]; sun: V3[] };
  site: { lat: number; lon: number; name: string; height_m: number; fixed: V3 };
  orbit: { alt_km: number; inc_deg: number; period_min: number; node_drift_deg_per_day: number;
    phase_adjust_deg: number; phase_adjust_pct_of_motion: number; plane_turn_deg: number; plane_turn_ms: number };
  descent: { perilune_km: number; half_ellipse_min: number; braking_min: number; braking_arc_deg: number };
  stations: { name: string; ecef: V3; bit: number }[];
  radii: { earth: number; moon: number };
}
export interface CapMeta { file: string; n: number; step_km: number; x0_km: number; y0_km: number; scale_m: number; offset_m: number; dem: string; block: number }
export interface JourneysFile {
  meta: { generated_utc: string; engine_version: string; ephemeris: string; moon_cap: CapMeta | null; notes: string[] };
  missions: Journey[];
}

export async function loadJourneys(base: string): Promise<{ file: JourneysFile; cap: Float32Array | null } | null> {
  const r = await fetch(`${base}data/journeys.json`, { cache: "no-cache" });
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`journeys.json returned ${r.status}`);
  const file = (await r.json()) as JourneysFile;
  let cap: Float32Array | null = null;
  const m = file.meta.moon_cap;
  if (m) {
    const b = await fetch(`${base}data/${m.file}?v=${encodeURIComponent(file.meta.generated_utc)}`);
    if (b.ok) {
      const dn = new Int16Array(await b.arrayBuffer());
      cap = new Float32Array(dn.length);
      for (let i = 0; i < dn.length; i++) cap[i] = dn[i] === -32768 ? NaN : (dn[i] * m.scale_m + m.offset_m) / 1000;
    }
  }
  return { file, cap };
}

const lerp3 = (a: V3, b: V3, f: number): V3 => [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f];

function nlerpQ(a: Q, b: Q, f: number): Q {
  const d = a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3];
  const s = d < 0 ? -1 : 1;
  const q: Q = [a[0] + (s * b[0] - a[0]) * f, a[1] + (s * b[1] - a[1]) * f, a[2] + (s * b[2] - a[2]) * f, a[3] + (s * b[3] - a[3]) * f];
  const n = Math.hypot(...q);
  return [q[0] / n, q[1] / n, q[2] / n, q[3] / n];
}

/** Rotation matrix (row-major 3x3 as nested arrays) of a quaternion. */
export function quatMatrix([x, y, z, w]: Q): [V3, V3, V3] {
  return [
    [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
    [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
    [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
  ];
}
export const rotate = (m: [V3, V3, V3], v: V3): V3 => [
  m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
  m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
  m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2],
];
/** Column-major 3x3 for WebGL. */
export const mat3 = (m: [V3, V3, V3]) => new Float32Array([m[0][0], m[1][0], m[2][0], m[0][1], m[1][1], m[2][1], m[0][2], m[1][2], m[2][2]]);

export interface Context { moon: V3; qMoon: Q; qEarth: Q; sun: V3 }

/** Moon (Earth-centred J2000 km), Moon and Earth orientation (fixed -> J2000), Sun direction at t (s since TLI). */
export function contextAt(j: Journey, t: number): Context {
  const h = j.hourly, x = Math.min(Math.max((t - h.t0) / h.step, 0), h.n - 1);
  const i = Math.min(Math.floor(x), h.n - 2), f = x - i;
  return {
    moon: lerp3(h.moon[i], h.moon[i + 1], f),
    qMoon: nlerpQ(h.q_moon[i], h.q_moon[i + 1], f),
    qEarth: nlerpQ(h.q_earth[i], h.q_earth[i + 1], f),
    sun: unit(lerp3(h.sun[i], h.sun[i + 1], f)),
  };
}

export interface Craft { eci: V3; mci: V3; phase: number; dsn: number; vEarth: number; vMoon: number; i: number }

/** Spacecraft at t (s since TLI), linear between samples; speeds from the neighbouring samples. */
export function craftAt(j: Journey, t: number): Craft {
  const ts = j.t, n = ts.length;
  let lo = 0, hi = n - 1;
  if (t <= ts[0]) hi = 1;
  else if (t >= ts[n - 1]) lo = n - 2;
  else while (hi - lo > 1) { const m = (lo + hi) >> 1; if (ts[m] <= t) lo = m; else hi = m; }
  hi = lo + 1;
  const f = Math.min(Math.max((t - ts[lo]) / (ts[hi] - ts[lo]), 0), 1), dt = ts[hi] - ts[lo];
  // around the Moon, keep the radius between samples (a chord would dip ~3 km below a 100 km orbit)
  const ra = norm(j.mci[lo]), rb = norm(j.mci[hi]), m = lerp3(j.mci[lo], j.mci[hi], f), rm = norm(m);
  const mci = rm > 0 ? scale(m, (ra + (rb - ra) * f) / rm) : m;
  const eci = add(sub(lerp3(j.eci[lo], j.eci[hi], f), m), mci);
  return {
    eci, mci,
    phase: j.phase[f < 0.5 ? lo : hi], dsn: j.dsn[f < 0.5 ? lo : hi],
    vEarth: norm(sub(j.eci[hi], j.eci[lo])) / dt, vMoon: norm(sub(j.mci[hi], j.mci[lo])) / dt, i: lo,
  };
}

/** Event position on the path in either frame. */
export function pointAt(j: Journey, t: number, frame: "earth" | "moon"): V3 {
  const c = craftAt(j, t);
  return frame === "earth" ? c.eci : c.mci;
}

export const siteInertial = (j: Journey, ctx: Context): V3 =>
  scale(rotate(quatMatrix(ctx.qMoon), j.site.fixed), j.radii.moon + j.site.height_m / 1000);

