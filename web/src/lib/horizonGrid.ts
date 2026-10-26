/**
 * LOLA terrain horizons over a polar cap (south or north), from the grid that
 * scripts/build_horizon_grid.py writes: the four grid points around a point,
 * interpolated bilinearly (the same rule the script's check uses to measure the error).
 */
import type { Horizon } from "./siteAnalysis";

export interface HorizonGridMeta {
  generated_utc: string; dem: string; map_scale_m: number; pole: "south" | "north"; tiles_dir?: string; min_abs_lat: number; spacing_km: number;
  n: number; x0_km: number; radius_km: number; x_sign: number; y_sign: number; az_step_deg: number; n_az: number;
  scale_deg: number; missing: number; tile: number; tiles: [number, number][]; observer_m: number; max_dist_km: number;
  reach_km_min: number; method: string; ephemeris: string; relief_png?: string; relief_extent_km?: [number, number, number, number];
  check: {
    points: number; year: number;
    horizon_interp_minus_own_deg: Stat; sunlit_pct_interp_minus_own: Stat; sunlit_pct_flat_minus_own: Stat;
    fast_minus_full_horizon_deg: Stat; full_points: number;
  };
}
interface Stat { median: number; p90: number; p99: number; max: number }

export interface GridHorizon { elev: Float64Array; fn: Horizon; nodes: number; nearestKm: number }

const DEG = Math.PI / 180;

/** Plane coordinates (km) of a point, in the map's own convention (PolarGrid). */
const poleSign = (m: HorizonGridMeta) => (m.pole === "north" ? 1 : -1);
export const tilesDir = (m: HorizonGridMeta) => m.tiles_dir ?? "horizon_grid_s";

export function planeXY(m: HorizonGridMeta, lat: number, lon: number): [number, number] {
  const r = 2 * m.radius_km * Math.tan(Math.PI / 4 - (poleSign(m) * lat * DEG) / 2);
  return [m.x_sign * r * Math.sin(lon * DEG), m.y_sign * r * Math.cos(lon * DEG)];
}

/** Inverse of planeXY. */
export function latLonOfPlane(m: HorizonGridMeta, x: number, y: number): [number, number] {
  const rho = Math.hypot(x, y);
  const lat = poleSign(m) * (90 - (2 * Math.atan(rho / (2 * m.radius_km))) / DEG);
  return [lat, Math.atan2(m.x_sign * x, m.y_sign * y) / DEG];
}

export function covers(m: HorizonGridMeta, lat: number): boolean {
  return poleSign(m) * lat >= m.min_abs_lat;
}

/** Tiles (row, col of tiles) holding the four grid points around a point. */
export function tilesFor(m: HorizonGridMeta, lat: number, lon: number): [number, number][] {
  const [x, y] = planeXY(m, lat, lon);
  const c0 = Math.floor((x - m.x0_km) / m.spacing_km), r0 = Math.floor((y - m.x0_km) / m.spacing_km);
  const set = new Map<string, [number, number]>();
  for (const [r, c] of [[r0, c0], [r0, c0 + 1], [r0 + 1, c0], [r0 + 1, c0 + 1]]) {
    const t: [number, number] = [Math.floor(r / m.tile), Math.floor(c / m.tile)];
    if (m.tiles.some(([a, b]) => a === t[0] && b === t[1])) set.set(t.join(","), t);
  }
  return [...set.values()];
}

/** The interpolated horizon at a point, from loaded tiles ("row,col" -> int16 data). */
export function horizonAt(m: HorizonGridMeta, tiles: Map<string, Int16Array>, lat: number, lon: number): GridHorizon | null {
  const [x, y] = planeXY(m, lat, lon);
  const c = (x - m.x0_km) / m.spacing_km, r = (y - m.x0_km) / m.spacing_km;
  const c0 = Math.floor(c), r0 = Math.floor(r), fc = c - c0, fr = r - r0;
  const acc = new Float64Array(m.n_az);
  let wsum = 0, nodes = 0, nearest = Infinity;
  for (const [dr, dc, w] of [[0, 0, (1 - fc) * (1 - fr)], [0, 1, fc * (1 - fr)], [1, 0, (1 - fc) * fr], [1, 1, fc * fr]]) {
    const rr = r0 + dr, cc = c0 + dc;
    if (rr < 0 || cc < 0 || rr >= m.n || cc >= m.n || w <= 0) continue;
    const t = tiles.get(`${Math.floor(rr / m.tile)},${Math.floor(cc / m.tile)}`);
    if (!t) continue;
    const off = (((rr % m.tile) * m.tile) + (cc % m.tile)) * m.n_az;
    if (t[off] === m.missing) continue;
    for (let k = 0; k < m.n_az; k++) acc[k] += w * t[off + k] * m.scale_deg;
    wsum += w; nodes++;
    nearest = Math.min(nearest, Math.hypot(dr - fr, dc - fc) * m.spacing_km);
  }
  if (!wsum) return null;
  for (let k = 0; k < m.n_az; k++) acc[k] /= wsum;
  const step = m.az_step_deg, n = m.n_az;
  const fn: Horizon = (az) => {
    const a = ((az % 360) + 360) % 360 / step, i = Math.floor(a) % n, f = a - Math.floor(a);
    return acc[i] * (1 - f) + acc[(i + 1) % n] * f;
  };
  return { elev: acc, fn, nodes, nearestKm: nearest };
}
