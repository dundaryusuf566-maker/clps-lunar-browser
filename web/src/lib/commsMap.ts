/**
 * Communication maps: where on the Moon the Earth is above the horizon, how often together with the
 * Sun, and with a Deep Space Network complex in view.
 *
 *  - Polar caps, LOLA terrain: precomputed by the engine (scripts/build_earth_visibility.py) for
 *    every point of the 5 km horizon grid over twelve months; read here (earth_vis_s.json + .bin).
 *  - Whole Moon, level ground: computed here for the chosen period, from the ephemeris table, by the
 *    same rules as the point analysis (siteAnalysis.ts): Earth's centre seen from the point
 *    (parallax included) above the horizon, Sun's centre above it.
 *
 * Pure functions; tested by web/tests/earthvis.check.mjs.
 */
import { dsnElevations, DSN, DSN_MIN_ELEV_DEG, MOON_R_KM, moonState, utcToTdb, type Ephem, type Frame } from "./sky";

export type CommsLayer = "earth" | "sun_earth" | "dsn";
export const COMMS_LAYERS: { id: CommsLayer; label: string; short: string }[] = [
  { id: "earth", label: "Earth above the horizon", short: "Earth in view" },
  { id: "sun_earth", label: "Sun and Earth above the horizon together", short: "Sun + Earth" },
  { id: "dsn", label: "Earth above the horizon and a DSN complex in view", short: "DSN contact" },
];

export interface EarthVisMeta {
  generated_utc: string; engine_version: string; ephemeris: string; dem: string; pole: "south" | "north";
  period_utc: [string, string]; step_h: number; n: number; x0_km: number; spacing_km: number; radius_km: number;
  x_sign: number; y_sign: number; min_abs_lat: number; layers: { id: CommsLayer; label: string }[];
  step_pp: number; missing: number; bin: string;
  stats: { points: number; earth_median_pct: number; earth_never_points: number; earth_always_points: number; sun_earth_median_pct: number };
  check_a: { earth_in_view_pct: Record<string, number>; pass: boolean; criterion: string };
  check_b: null | { median_pp: number; p90_pp: number; max_pp: number; flat_median_pp: number; flat_p90_pp: number; pass: boolean; criterion: string; points: number };
  check_b_note: string | null;
  samples: { row: number; col: number; lat: number; lon: number; earth: number; sun_earth: number; dsn: number }[];
  uncertain_spread_pp?: number; hatched_share?: number;
  check_c?: null | { spread_pp: number; flagged_share: number; unflagged_p90_pp: number; flagged_p90_pp: number | null;
    large_errors: number; large_errors_flagged: number; pass: boolean; criterion: string };
  hatch_samples?: [number, number, boolean][];
}
export interface EarthVis { meta: EarthVisMeta; data: Uint8Array }

const DEG = Math.PI / 180;
const poleSign = (m: EarthVisMeta) => (m.pole === "north" ? 1 : -1);

/** Value (%) of a layer at a grid node, or null where there is no grid point. */
export function nodeValue(v: EarthVis, layer: CommsLayer, row: number, col: number): number | null {
  const m = v.meta, k = m.layers.findIndex((l) => l.id === layer);
  if (k < 0 || row < 0 || col < 0 || row >= m.n || col >= m.n) return null;
  const b = v.data[(k * m.n + row) * m.n + col];
  return b === m.missing ? null : b * m.step_pp;
}

export function nodeLatLon(m: EarthVisMeta, row: number, col: number): [number, number] {
  const X = m.x0_km + col * m.spacing_km, Y = m.x0_km + row * m.spacing_km;
  const rho = Math.hypot(X, Y);
  return [poleSign(m) * (90 - (2 * Math.atan(rho / (2 * m.radius_km))) / DEG), Math.atan2(m.x_sign * X, m.y_sign * Y) / DEG];
}

/** The map's value at the grid point nearest to a point, and how far that grid point is (km). */
export function valueNear(v: EarthVis, layer: CommsLayer, lat: number, lon: number): { pct: number; km: number } | null {
  const m = v.meta;
  if (poleSign(m) * lat < m.min_abs_lat) return null;
  const r = 2 * m.radius_km * Math.tan(Math.PI / 4 - (poleSign(m) * lat * DEG) / 2);
  const X = m.x_sign * r * Math.sin(lon * DEG), Y = m.y_sign * r * Math.cos(lon * DEG);
  const col = Math.round((X - m.x0_km) / m.spacing_km), row = Math.round((Y - m.x0_km) / m.spacing_km);
  const pct = nodeValue(v, layer, row, col);
  if (pct === null) return null;
  return { pct, km: Math.hypot(X - (m.x0_km + col * m.spacing_km), Y - (m.x0_km + row * m.spacing_km)) };
}

// --- the uncertainty flag (check C, engine/surface/earth_visibility.py) ---------------------------
export const spreadLimit = (m: EarthVisMeta) => m.uncertain_spread_pp ?? 25;

/** Earth-in-view range (%) of the four grid points a point's horizon is blended from (horizonGrid.ts),
 * as the engine's neighbour_spread; null outside the grid. */
export function spreadNear(v: EarthVis, lat: number, lon: number): { min: number; max: number; spread: number } | null {
  const m = v.meta;
  if (poleSign(m) * lat < m.min_abs_lat) return null;
  const r = 2 * m.radius_km * Math.tan(Math.PI / 4 - (poleSign(m) * lat * DEG) / 2);
  const X = m.x_sign * r * Math.sin(lon * DEG), Y = m.y_sign * r * Math.cos(lon * DEG);
  const c0 = Math.floor((X - m.x0_km) / m.spacing_km), r0 = Math.floor((Y - m.x0_km) / m.spacing_km);
  const vals = [[r0, c0], [r0, c0 + 1], [r0 + 1, c0], [r0 + 1, c0 + 1]]
    .map(([rr, cc]) => nodeValue(v, "earth", rr, cc)).filter((x): x is number => x !== null);
  if (!vals.length) return null;
  const min = Math.min(...vals), max = Math.max(...vals);
  return { min, max, spread: max - min };
}

/** Hatched on the map: the grid point's 3 x 3 neighbourhood spans more than the limit (any quad
 * touching it would flag a point inside). */
export function nodeUncertain(v: EarthVis, row: number, col: number): boolean {
  if (nodeValue(v, "earth", row, col) === null) return false;
  let lo = Infinity, hi = -Infinity;
  for (let dr = -1; dr <= 1; dr++) for (let dc = -1; dc <= 1; dc++) {
    const x = nodeValue(v, "earth", row + dr, col + dc);
    if (x !== null) { lo = Math.min(lo, x); hi = Math.max(hi, x); }
  }
  return hi - lo > spreadLimit(v.meta);
}

// --- whole Moon, level ground -----------------------------------------------------------------
export interface WorldGrid {
  stepDeg: number; rows: number; cols: number; stepH: number; samples: number;
  /** row 0 = northernmost band; cell centres at 90 - (row + 0.5) * step, -180 + (col + 0.5) * step */
  earth: Float32Array; sun_earth: Float32Array; dsn: Float32Array;
}

/** Time step (h) for a period: about 1,500 samples at most, never under an hour. */
export const worldStepH = (days: number) => Math.max(1, Math.round((days * 24) / 1500));

/** Share of the period (%) with the Earth up, Sun and Earth up, Earth up and a DSN complex in view,
 * on level ground, for every cell of a stepDeg grid; samples at startMs + k * stepH, k = 0..days*24/stepH
 * (as siteAnalysis with stepMin = 60 * stepH). DSN for the Moon's centre (it changes by under 0.3 deg
 * of station elevation across the Moon). */
export function worldGrid(e: Ephem, startMs: number, days: number, stepDeg = 2, stepH = worldStepH(days)): WorldGrid {
  const rows = Math.round(180 / stepDeg), cols = Math.round(360 / stepDeg), nCells = rows * cols;
  const ux = new Float64Array(nCells), uy = new Float64Array(nCells), uz = new Float64Array(nCells);
  for (let r = 0; r < rows; r++) {
    const p = (90 - (r + 0.5) * stepDeg) * DEG;
    for (let c = 0; c < cols; c++) {
      const l = (-180 + (c + 0.5) * stepDeg) * DEG, k = r * cols + c;
      ux[k] = Math.cos(p) * Math.cos(l); uy[k] = Math.cos(p) * Math.sin(l); uz[k] = Math.sin(p);
    }
  }
  const ce = new Uint32Array(nCells), cse = new Uint32Array(nCells), cd = new Uint32Array(nCells);
  const n = Math.floor((days * 24) / stepH) + 1;
  const centre: Frame = { up: [0, 0, 1], north: [0, 1, 0], east: [1, 0, 0] };   // only used with rKm = 0
  for (let i = 0; i < n; i++) {
    const ms = startMs + i * stepH * 3600e3, tdb = utcToTdb(ms);
    const st = moonState(e, tdb);
    const el = dsnElevations(st, centre, tdb, 0);
    const dsn = DSN.some((s) => el[s.id] >= DSN_MIN_ELEV_DEG);
    const [ex, ey, ez] = st.earth, [sx, sy, sz] = st.sun;
    for (let k = 0; k < nCells; k++) {
      // Earth seen from the point: (earth - R up) . up >= 0  <=>  earth . up >= R
      if (ex * ux[k] + ey * uy[k] + ez * uz[k] >= MOON_R_KM) {
        ce[k]++;
        if (sx * ux[k] + sy * uy[k] + sz * uz[k] >= 0) cse[k]++;
        if (dsn) cd[k]++;
      }
    }
  }
  const pct = (a: Uint32Array) => Float32Array.from(a, (v) => (100 * v) / n);
  return { stepDeg, rows, cols, stepH, samples: n, earth: pct(ce), sun_earth: pct(cse), dsn: pct(cd) };
}

export function worldValue(g: WorldGrid, layer: CommsLayer, lat: number, lon: number): number {
  const r = Math.min(g.rows - 1, Math.max(0, Math.floor((90 - lat) / g.stepDeg)));
  const c = ((Math.floor((lon + 180) / g.stepDeg) % g.cols) + g.cols) % g.cols;
  return g[layer][r * g.cols + c];
}
