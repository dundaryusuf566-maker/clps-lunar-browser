/** The 3D scene file (scripts/build_scene3d.py) and the geometry shared by the
 *  renderer and the page: map plane <-> Moon-fixed <-> local scene frame. */
import { add, cross, dot, norm, scale, sub, unit, type V3 } from "./math";

export interface SceneGridMeta {
  x0_km: number; y0_km: number; step_km: number; nx: number; ny: number;
  scale_m: number; offset_m: number; block: number; section: string;
}
export interface Agreement {
  n: number; near_horizon: number; median_abs_deg: number | null; p95_abs_deg: number | null;
  lit_agree_pct: number | null; lit_compared: number; mean_abs_disc_pct: number | null;
  clamp_deg: number; edge_deg: number;
}
export interface CheckPoint {
  label: string; kind: "reference" | "top" | "extra"; rank?: number; lat: number; lon: number;
  horizon?: string | null; height_m: number; python_vs_engine: Agreement;
}
export interface SceneMeta {
  generated_utc: string; engine_version: string; ephemeris: string; dem: string; mission: string;
  forecast_sha256: string | null; moon_radius_km: number; solar_semi_diameter_deg: number; observer_m: number;
  march: { t0_km: number; grow: number; min_step_km: number; max_step_km: number; max_km: number };
  frame: { lat: number; lon: number; east: V3; north: V3; up: V3 };
  region: { center_lat: number; center_lon: number; half_km: number; step_km: number; landing_period_utc: [string, string] };
  grids: SceneGridMeta[];
  height_range_m: [number, number, number];
  time: { t0_utc: string; step_s: number; n: number };
  checks: { points: CheckPoint[]; time_index: [number, number, number]; mask_az_step_deg: number;
    python_vs_engine: Agreement; method: string };
  binary: { file: string; sections: Record<string, { offset: number; dtype: "int16" | "float32"; shape: number[] }> };
}

export const INVALID_KM = -1000;          // marks "no map data" in the height textures

export interface Grid { meta: SceneGridMeta; h: Float32Array }    // heights in km, INVALID_KM where missing

export interface Scene {
  meta: SceneMeta;
  grids: Grid[];
  series: Float32Array;     // n x 7: sun unit (3), earth unit (3), earth distance km
  masks: Int16Array;        // points x azimuths, centi-degrees
  engineClear: Int16Array;  // points x check times, centi-degrees
  R: number;
  C: V3;                    // scene origin, Moon-fixed km
  E: [V3, V3, V3];          // east, north, up
  t0Ms: number;
  hTopKm: number;
}

export async function loadScene(base: string): Promise<Scene | null> {
  const r = await fetch(`${base}data/scene3d.json`, { cache: "no-cache" });
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`scene3d.json returned ${r.status}`);
  const meta = (await r.json()) as SceneMeta;
  // the binary is cached by the server for an hour: tie it to this build of the scene
  const b = await fetch(`${base}data/${meta.binary.file}?v=${encodeURIComponent(meta.generated_utc)}`);
  if (!b.ok) throw new Error(`${meta.binary.file} returned ${b.status}`);
  const buf = await b.arrayBuffer();
  const sec = (name: string) => {
    const s = meta.binary.sections[name];
    const n = s.shape.reduce((a, c) => a * c, 1);
    return s.dtype === "int16" ? new Int16Array(buf, s.offset, n) : new Float32Array(buf, s.offset, n);
  };
  const grids = meta.grids.map((g) => {
    const dn = sec(g.section) as Int16Array;
    const h = new Float32Array(dn.length);
    for (let i = 0; i < dn.length; i++) h[i] = dn[i] === -32768 ? INVALID_KM : (dn[i] * g.scale_m + g.offset_m) / 1000;
    return { meta: g, h };
  });
  const R = meta.moon_radius_km;
  const up = meta.frame.up;
  return {
    meta, grids, R,
    series: sec("series") as Float32Array,
    masks: sec("masks") as Int16Array,
    engineClear: sec("engine_clear") as Int16Array,
    C: scale(up, R), E: [meta.frame.east, meta.frame.north, up],
    t0Ms: Date.parse(meta.time.t0_utc),
    hTopKm: Math.max(...meta.height_range_m.slice(1)) / 1000,
  };
}

// --- projections -------------------------------------------------------------------------
/** Map plane (km) of the point below a Moon-fixed vector (any length). */
export function planeOf(v: V3, R: number): [number, number] {
  const d = norm(v) - v[2];
  return [(2 * R * v[1]) / d, (-2 * R * v[0]) / d];
}

/** Moon-fixed unit vector of a map-plane point (inverse stereographic, no trigonometry). */
export function upOf(X: number, Y: number, R: number): V3 {
  const rr = X * X + Y * Y, k = 4 * R * R;
  return [(-4 * R * Y) / (rr + k), (4 * R * X) / (rr + k), (rr - k) / (rr + k)];
}

export function upOfLatLon(lat: number, lon: number): V3 {
  const p = (lat * Math.PI) / 180, l = (lon * Math.PI) / 180;
  return [Math.cos(p) * Math.cos(l), Math.cos(p) * Math.sin(l), Math.sin(p)];
}

export function latLonOf(v: V3): [number, number] {
  const u = unit(v);
  return [(Math.asin(u[2]) * 180) / Math.PI, (Math.atan2(u[1], u[0]) * 180) / Math.PI];
}

export const toScene = (s: Scene, pMf: V3): V3 => {
  const d = sub(pMf, s.C);
  return [dot(d, s.E[0]), dot(d, s.E[1]), dot(d, s.E[2])];
};
export const toFixed = (s: Scene, p: V3): V3 => add(s.C, add(scale(s.E[0], p[0]), add(scale(s.E[1], p[1]), scale(s.E[2], p[2]))));
/** Direction (unit) from Moon-fixed to scene axes. */
export const dirToScene = (s: Scene, d: V3): V3 => [dot(d, s.E[0]), dot(d, s.E[1]), dot(d, s.E[2])];

/** Bilinear height (km) on one grid; null outside it or on missing data. */
export function gridHeight(g: Grid, X: number, Y: number): number | null {
  const { x0_km, y0_km, step_km, nx, ny } = g.meta;
  const c = (X - x0_km) / step_km, r = (Y - y0_km) / step_km;
  if (!(c >= 0 && r >= 0 && c <= nx - 1 && r <= ny - 1)) return null;
  const c0 = Math.min(Math.floor(c), nx - 2), r0 = Math.min(Math.floor(r), ny - 2);
  const fc = c - c0, fr = r - r0, h = g.h, i = r0 * nx + c0;
  const a = h[i], b = h[i + 1], cc = h[i + nx], d = h[i + nx + 1];
  if (a <= INVALID_KM || b <= INVALID_KM || cc <= INVALID_KM || d <= INVALID_KM) return null;
  return a * (1 - fc) * (1 - fr) + b * fc * (1 - fr) + cc * (1 - fc) * fr + d * fc * fr;
}

/** Height (km) from the finest grid that covers the point. */
export function heightAt(s: Scene, X: number, Y: number): number | null {
  for (const g of s.grids) {
    const h = gridHeight(g, X, Y);
    if (h !== null) return h;
  }
  return null;
}

/** Terrain point (scene km) at a map-plane point, `above_km` over the ground. */
export function surfacePoint(s: Scene, X: number, Y: number, aboveKm = 0): V3 | null {
  const h = heightAt(s, X, Y);
  if (h === null) return null;
  return toScene(s, scale(upOf(X, Y, s.R), s.R + h + aboveKm));
}

// --- Sun and Earth ------------------------------------------------------------------------
export const tEndMs = (s: Scene) => s.t0Ms + (s.meta.time.n - 1) * s.meta.time.step_s * 1000;

/** Moon-fixed Sun and Earth unit vectors at a time (normalised linear interpolation of the hourly series). */
export function sunEarth(s: Scene, tMs: number): { sun: V3; earth: V3; earthKm: number } {
  const n = s.meta.time.n, x = Math.min(Math.max((tMs - s.t0Ms) / (s.meta.time.step_s * 1000), 0), n - 1);
  const i = Math.min(Math.floor(x), n - 2), f = x - i, a = s.series, o = i * 7, p = o + 7;
  const lerp = (k: number) => a[o + k] * (1 - f) + a[p + k] * f;
  return {
    sun: unit([lerp(0), lerp(1), lerp(2)]),
    earth: unit([lerp(3), lerp(4), lerp(5)]),
    earthKm: lerp(6),
  };
}

/** Local east, north, up at a Moon-fixed unit vector. */
export function enuAt(up: V3): [V3, V3, V3] {
  let east = cross([0, 0, 1], up);
  east = norm(east) < 1e-12 ? [0, 1, 0] : unit(east);
  return [east, cross(up, east), up];
}

/** Azimuth (deg from north, clockwise) and elevation (deg) of a Moon-fixed direction at a point. */
export function azEl(dir: V3, up: V3): { az: number; el: number } {
  const [e, n] = enuAt(up);
  const el = (Math.asin(Math.max(-1, Math.min(1, dot(dir, up)))) * 180) / Math.PI;
  const az = ((Math.atan2(dot(dir, e), dot(dir, n)) * 180) / Math.PI + 360) % 360;
  return { az, el };
}

export function dirFromAzEl(up: V3, azDeg: number, elDeg: number): V3 {
  const [e, n] = enuAt(up);
  const a = (azDeg * Math.PI) / 180, l = (elDeg * Math.PI) / 180;
  return unit(add(add(scale(e, Math.cos(l) * Math.sin(a)), scale(n, Math.cos(l) * Math.cos(a))), scale(up, Math.sin(l))));
}

export function discFraction(clearDeg: number, semiDeg: number): number {
  const x = Math.max(-1, Math.min(1, clearDeg / semiDeg));
  const th = Math.acos(-x);
  return (th - Math.sin(th) * Math.cos(th)) / Math.PI;
}

/** Same comparison as engine/surface/scene3d.py agreement(). */
export function agreement(a: ArrayLike<number>, b: ArrayLike<number>, semiDeg: number, clamp = 1, edge = 0.3): Agreement {
  const d: number[] = [];
  let n = 0, near = 0, litN = 0, litSame = 0, disc = 0;
  for (let i = 0; i < a.length; i++) {
    const ar = a[i], br = b[i];
    if (!Number.isFinite(ar) || !Number.isFinite(br)) continue;
    n++;
    const x = Math.max(-clamp, Math.min(clamp, ar)), y = Math.max(-clamp, Math.min(clamp, br));
    if (Math.abs(ar) < clamp || Math.abs(br) < clamp) { near++; d.push(Math.abs(x - y)); }
    if (Math.abs(y) > edge) { litN++; if ((x > 0) === (y > 0)) litSame++; }
    disc += Math.abs(discFraction(x, semiDeg) - discFraction(y, semiDeg));
  }
  d.sort((p, q) => p - q);
  const pct = (q: number) => {               // numpy's default linear interpolation
    if (!d.length) return null;
    const k = (d.length - 1) * q, lo = Math.floor(k), hi = Math.ceil(k);
    return d[lo] + (d[hi] - d[lo]) * (k - lo);
  };
  const r3 = (v: number | null) => (v === null ? null : Math.round(v * 1000) / 1000);
  return {
    n, near_horizon: near, median_abs_deg: r3(pct(0.5)), p95_abs_deg: r3(pct(0.95)),
    lit_agree_pct: litN ? Math.round((10000 * litSame) / litN) / 100 : null, lit_compared: litN,
    mean_abs_disc_pct: n ? Math.round((10000 * disc) / n) / 100 : null, clamp_deg: clamp, edge_deg: edge,
  };
}
