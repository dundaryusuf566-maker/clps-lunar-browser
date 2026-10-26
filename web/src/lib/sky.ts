/**
 * The Moon's sky in the browser: where the Sun and the Earth stand at any point of
 * the Moon, and which DSN stations see it, from the hourly table that
 * scripts/build_ephemeris_table.py writes (DE440). The same formulas as the engine
 * (engine/surface/geometry.py, engine/surface/ground.py, engine/core/time.py);
 * web/tests/sky.check.mjs compares the two at fixed points and times.
 *
 * Pure functions, no DOM: usable in a worker and in Node.
 */

export type Vec3 = [number, number, number];

export interface EphemMeta {
  t0_tdb: number; step_s: number; n: number; layout: string[]; ephemeris: string; span_utc: [string, string];
  moon_radius_km: number; generated_utc?: string; engine_version?: string;
}
export interface Ephem { meta: EphemMeta; data: Float32Array }

const DEG = Math.PI / 180;
const STRIDE = 11;
export const MOON_R_KM = 1737.4;

// --- time (engine/core/time.py) -------------------------------------------------------
const J2000_NOON_UTC_MS = Date.UTC(2000, 0, 1, 12);
const LEAPS: [number, number][] = [
  [Date.UTC(1999, 0, 1), 32], [Date.UTC(2006, 0, 1), 33], [Date.UTC(2009, 0, 1), 34],
  [Date.UTC(2012, 6, 1), 35], [Date.UTC(2015, 6, 1), 36], [Date.UTC(2017, 0, 1), 37],
];
function taiMinusUtc(ms: number): number {
  let v = LEAPS[0][1];
  for (const [start, off] of LEAPS) if (ms >= start) v = off;
  return v;
}
/** UTC (ms since 1970) -> TDB seconds past J2000. */
export function utcToTdb(ms: number): number {
  const tt = (ms - J2000_NOON_UTC_MS) / 1000 + taiMinusUtc(ms) + 32.184;
  const g = (357.53 + 0.98560028 * (tt / 86400)) * DEG;
  return tt + 0.001657 * Math.sin(g + 0.01671 * Math.sin(g));
}
/** TDB seconds past J2000 -> UTC ms (inverse of utcToTdb, to well under a millisecond). */
export function tdbToUtc(tdb: number): number {
  let ms = J2000_NOON_UTC_MS + (tdb - 69.184) * 1000;
  for (let i = 0; i < 3; i++) ms += (tdb - utcToTdb(ms)) * 1000;
  return ms;
}

// --- vectors ----------------------------------------------------------------------------
const dot = (a: Vec3, b: Vec3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const norm = (a: Vec3): Vec3 => { const l = Math.hypot(a[0], a[1], a[2]); return [a[0] / l, a[1] / l, a[2] / l]; };
const cross = (a: Vec3, b: Vec3): Vec3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];

// --- the table --------------------------------------------------------------------------
export function covers(e: Ephem, tdb: number): boolean {
  return tdb >= e.meta.t0_tdb && tdb <= e.meta.t0_tdb + (e.meta.n - 1) * e.meta.step_s;
}

function locate(e: Ephem, tdb: number): [number, number] {
  const x = (tdb - e.meta.t0_tdb) / e.meta.step_s;
  if (!(x >= 0 && x <= e.meta.n - 1)) throw new RangeError(`epoch outside the ephemeris table (${e.meta.span_utc.join(" .. ")} UTC)`);
  const i = Math.min(Math.floor(x), e.meta.n - 2);
  return [i, x - i];
}

const lerp = (d: Float32Array, i: number, s: number, k: number) => d[i * STRIDE + k] * (1 - s) + d[(i + 1) * STRIDE + k] * s;

export interface MoonState {
  sun: Vec3;        // unit, Moon-fixed
  sunAu: number;
  earth: Vec3;      // km from the Moon's centre, Moon-fixed
  q: [number, number, number, number];   // J2000 -> Moon-fixed (x, y, z, w)
}

export function moonState(e: Ephem, tdb: number): MoonState {
  const [i, s] = locate(e, tdb), d = e.data;
  const sun = norm([lerp(d, i, s, 0), lerp(d, i, s, 1), lerp(d, i, s, 2)]);
  const q0 = [7, 8, 9, 10].map((k) => lerp(d, i, s, k));
  const ql = Math.hypot(...q0);
  return {
    sun, sunAu: lerp(d, i, s, 3),
    earth: [lerp(d, i, s, 4), lerp(d, i, s, 5), lerp(d, i, s, 6)],
    q: [q0[0] / ql, q0[1] / ql, q0[2] / ql, q0[3] / ql],
  };
}

/** Rotation matrix (row-major) of quaternion q = (x, y, z, w). */
function quatMatrix([x, y, z, w]: [number, number, number, number]): number[] {
  return [
    1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w),
    2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w),
    2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y),
  ];
}
/** Moon-fixed -> J2000 (the transpose of the stored rotation). */
function fixedToJ2000(q: MoonState["q"], v: Vec3): Vec3 {
  const m = quatMatrix(q);
  return [m[0] * v[0] + m[3] * v[1] + m[6] * v[2], m[1] * v[0] + m[4] * v[1] + m[7] * v[2], m[2] * v[0] + m[5] * v[1] + m[8] * v[2]];
}

// --- a point on the Moon ------------------------------------------------------------------
export interface Frame { up: Vec3; north: Vec3; east: Vec3 }

export function siteFrame(latDeg: number, lonDeg: number): Frame {
  const p = latDeg * DEG, l = lonDeg * DEG;
  const up: Vec3 = [Math.cos(p) * Math.cos(l), Math.cos(p) * Math.sin(l), Math.sin(p)];
  const z = up[2];
  const north = norm([-z * up[0], -z * up[1], 1 - z * up[2]]);   // the pole projected on the local horizontal
  return { up, north, east: cross(north, up) };
}

export function azEl(v: Vec3, f: Frame): { az: number; el: number } {
  const u = norm(v);
  const el = Math.asin(Math.max(-1, Math.min(1, dot(u, f.up)))) / DEG;
  const az = ((Math.atan2(dot(u, f.east), dot(u, f.north)) / DEG) % 360 + 360) % 360;
  return { az, el };
}

export function sunAzEl(st: MoonState, f: Frame) {
  return azEl(st.sun, f);
}

/** Earth seen from the site itself (not the Moon's centre): the parallax matters, ~1 deg. */
export function earthAzEl(st: MoonState, f: Frame, rKm = MOON_R_KM) {
  const r = rKm;
  return azEl([st.earth[0] - r * f.up[0], st.earth[1] - r * f.up[1], st.earth[2] - r * f.up[2]], f);
}

// --- the Deep Space Network (engine/surface/ground.py) --------------------------------------
const ARCSEC = Math.PI / (180 * 3600);
const WGS84_A = 6378.137, WGS84_F = 1 / 298.257223563;
export const DSN = [
  { id: "goldstone", name: "Goldstone", lat: 35.42667, lon: -116.89, bit: 1 },
  { id: "madrid", name: "Madrid", lat: 40.43139, lon: -4.24806, bit: 2 },
  { id: "canberra", name: "Canberra", lat: -35.40139, lon: 148.98167, bit: 4 },
] as const;
export const DSN_MIN_ELEV_DEG = 10;

const rz = (a: number) => { const c = Math.cos(a), s = Math.sin(a); return [c, s, 0, -s, c, 0, 0, 0, 1]; };
const ry = (a: number) => { const c = Math.cos(a), s = Math.sin(a); return [c, 0, -s, 0, 1, 0, s, 0, c]; };
const mm = (a: number[], b: number[]) => {
  const o = new Array(9).fill(0);
  for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) for (let k = 0; k < 3; k++) o[i * 3 + j] += a[i * 3 + k] * b[k * 3 + j];
  return o;
};
const mv = (m: number[], v: Vec3): Vec3 => [m[0] * v[0] + m[1] * v[1] + m[2] * v[2], m[3] * v[0] + m[4] * v[1] + m[5] * v[2], m[6] * v[0] + m[7] * v[1] + m[8] * v[2]];

/** J2000 -> Earth-fixed: IAU 1976 precession and GMST (IAU 1982), as the engine. */
export function j2000ToEarthFixed(tdb: number): number[] {
  const t = tdb / (86400 * 36525);
  const zeta = (2306.2181 * t + 0.30188 * t ** 2 + 0.017998 * t ** 3) * ARCSEC;
  const zz = (2306.2181 * t + 1.09468 * t ** 2 + 0.018203 * t ** 3) * ARCSEC;
  const theta = (2004.3109 * t - 0.42665 * t ** 2 - 0.041833 * t ** 3) * ARCSEC;
  const prec = mm(mm(rz(-zz), ry(theta)), rz(-zeta));
  const d = (tdb - 69.184) / 86400, tu = d / 36525;
  const gmst = (((280.46061837 + 360.98564736629 * d + 0.000387933 * tu ** 2 - tu ** 3 / 38710000) % 360) + 360) % 360;
  return mm(rz(gmst * DEG), prec);
}

function stationEcef(lat: number, lon: number): { pos: Vec3; up: Vec3 } {
  const p = lat * DEG, l = lon * DEG, e2 = WGS84_F * (2 - WGS84_F);
  const n = WGS84_A / Math.sqrt(1 - e2 * Math.sin(p) ** 2);
  return {
    pos: [n * Math.cos(p) * Math.cos(l), n * Math.cos(p) * Math.sin(l), n * (1 - e2) * Math.sin(p)],
    up: [Math.cos(p) * Math.cos(l), Math.cos(p) * Math.sin(l), Math.sin(p)],
  };
}
const STATIONS = DSN.map((s) => ({ ...s, ...stationEcef(s.lat, s.lon) }));

/** Elevation of the site at every DSN station, degrees. */
export function dsnElevations(st: MoonState, f: Frame, tdb: number, rKm = MOON_R_KM): Record<string, number> {
  // the site from the Earth's centre, J2000: rotate (site - Earth) out of the Moon-fixed frame
  const rel: Vec3 = [rKm * f.up[0] - st.earth[0], rKm * f.up[1] - st.earth[1], rKm * f.up[2] - st.earth[2]];
  const r = mv(j2000ToEarthFixed(tdb), fixedToJ2000(st.q, rel));
  const out: Record<string, number> = {};
  for (const s of STATIONS) {
    const v: Vec3 = [r[0] - s.pos[0], r[1] - s.pos[1], r[2] - s.pos[2]];
    out[s.id] = Math.asin(Math.max(-1, Math.min(1, dot(v, s.up) / Math.hypot(...v)))) / DEG;
  }
  return out;
}

export function dsnMask(st: MoonState, f: Frame, tdb: number, minElevDeg = DSN_MIN_ELEV_DEG): number {
  const el = dsnElevations(st, f, tdb);
  let m = 0;
  for (const s of DSN) if (el[s.id] >= minElevDeg) m |= s.bit;
  return m;
}

// --- loading --------------------------------------------------------------------------------
export function ephemFromBuffers(meta: EphemMeta, buf: ArrayBuffer): Ephem {
  const data = new Float32Array(buf);
  if (data.length !== meta.n * STRIDE) throw new Error(`ephemeris table has ${data.length} values, expected ${meta.n * STRIDE}`);
  return { meta, data };
}

// --- eclipses: the Earth in front of the Sun, seen from the Moon ------------------------------
const AU_KM = 149597870.7, SUN_R_KM = 695700, EARTH_R_KM = 6378.137;

/** Share of the solar disc hidden by the Earth's disc (geometric: no atmosphere, which in reality
 * widens the shadow by ~2%). `f` null = from the Moon's centre. Also the separation and radii, degrees. */
export function sunCoverage(st: MoonState, f: Frame | null, rKm = MOON_R_KM) {
  const o: Vec3 = f ? [rKm * f.up[0], rKm * f.up[1], rKm * f.up[2]] : [0, 0, 0];
  const sunD = st.sunAu * AU_KM;
  const s: Vec3 = [st.sun[0] * sunD - o[0], st.sun[1] * sunD - o[1], st.sun[2] * sunD - o[2]];
  const e: Vec3 = [st.earth[0] - o[0], st.earth[1] - o[1], st.earth[2] - o[2]];
  const ls = Math.hypot(...s), le = Math.hypot(...e);
  const rs = Math.asin(SUN_R_KM / ls), re = Math.asin(EARTH_R_KM / le);
  const d = Math.acos(Math.max(-1, Math.min(1, dot(s, e) / (ls * le))));
  return { fraction: discOverlap(rs, re, d) / (Math.PI * rs * rs), sepDeg: d / DEG, sunRDeg: rs / DEG, earthRDeg: re / DEG };
}

/** Area of the overlap of two discs (radii a, b, centres d apart), small-angle plane geometry. */
function discOverlap(a: number, b: number, d: number): number {
  if (d >= a + b) return 0;
  if (d <= Math.abs(a - b)) return Math.PI * Math.min(a, b) ** 2;
  const ca = Math.acos(Math.max(-1, Math.min(1, (d * d + a * a - b * b) / (2 * d * a))));
  const cb = Math.acos(Math.max(-1, Math.min(1, (d * d + b * b - a * a) / (2 * d * b))));
  return a * a * (ca - Math.sin(2 * ca) / 2) + b * b * (cb - Math.sin(2 * cb) / 2);
}
