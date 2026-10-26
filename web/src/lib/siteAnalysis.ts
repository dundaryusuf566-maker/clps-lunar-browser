/**
 * Everything the browser can say about one point of the Moon over a period, from the
 * ephemeris table alone: daylight, landing windows (the engine's light and
 * communication rules, without a transfer), Earth and DSN contact, eclipses.
 *
 * Horizon: flat unless a horizon function (terrain, elevation by azimuth) is given;
 * the result says which. Pure functions; tested by web/tests/site.check.mjs.
 */
import { DSN, dsnMask, earthAzEl, moonState, siteFrame, sunAzEl, sunCoverage, tdbToUtc, utcToTdb, type Ephem } from "./sky";

export interface SiteRules {
  sunMinDeg: number;          // landing window: Sun elevation above the horizon, rising
  sunMaxDeg: number;
  minEarthElDeg: number;      // direct-to-Earth link at touchdown
  requireDsn: boolean;
}
/** The engine's rules (engine/surface/sites.py, landing.py): 3-20 deg rising, Earth 2 deg; poles 0.5-90. */
export function defaultRules(latDeg: number): SiteRules {
  const polar = Math.abs(latDeg) >= 75;
  return { sunMinDeg: polar ? 0.5 : 3, sunMaxDeg: polar ? 90 : 20, minEarthElDeg: 2, requireDsn: false };
}

export type Horizon = (azDeg: number) => number;
export const flatHorizon: Horizon = () => 0;

export interface Interval { start: number; end: number }        // UTC ms
export interface LandingWindow extends Interval { earthPct: number; dsnAtStart: number; dsnPct: number }
export interface Eclipse { start: number; end: number; peak: number; maxFraction: number; sunUp: boolean }

export interface SiteSeries {
  t: Float64Array; sunEl: Float32Array; sunAz: Float32Array; earthEl: Float32Array; earthAz: Float32Array;
  sunHorizon: Float32Array; earthHorizon: Float32Array; dsn: Uint8Array; disc: Float32Array;   // disc: Sun share above the horizon
}

export interface SiteResult {
  lat: number; lon: number; startMs: number; endMs: number; stepMin: number; terrain: boolean; rules: SiteRules;
  series: SiteSeries;
  daylight: Interval[];                 // Sun's centre above the horizon
  windows: LandingWindow[];
  eclipses: Eclipse[];
  stats: {
    sunUpPct: number; earthUpPct: number; dsnPct: number; dsnWhenEarthUpPct: number;
    longestNightH: number; longestDayH: number; earthNeverUp: boolean; earthAlwaysUp: boolean;
  };
}

const SOLAR_SEMI_DEG = 0.267;

/** Share of the solar disc above a horizon at `h` deg, Sun's centre at `el` (straight-edge approximation). */
export function discAbove(el: number, h: number): number {
  const x = (el - h) / SOLAR_SEMI_DEG;
  if (x >= 1) return 1;
  if (x <= -1) return 0;
  return 0.5 + (x * Math.sqrt(1 - x * x) + Math.asin(x)) / Math.PI;
}

/** Crossings of a sampled function through a level, linearly interpolated: [time, rising] pairs. */
function crossings(t: Float64Array, v: Float32Array, h: Float32Array) {
  const out: [number, boolean][] = [];
  for (let i = 1; i < t.length; i++) {
    const a = v[i - 1] - h[i - 1], b = v[i] - h[i];
    if ((a < 0) !== (b < 0)) out.push([t[i - 1] + (t[i] - t[i - 1]) * (a / (a - b)), b >= 0]);
  }
  return out;
}

function intervalsAbove(t: Float64Array, v: Float32Array, h: Float32Array): Interval[] {
  const out: Interval[] = [];
  let start = v[0] >= h[0] ? t[0] : null;
  for (const [tc, up] of crossings(t, v, h)) {
    if (up) start = tc;
    else if (start !== null) { out.push({ start, end: tc }); start = null; }
  }
  if (start !== null) out.push({ start, end: t[t.length - 1] });
  return out;
}

export function analyzeSite(eph: Ephem, lat: number, lon: number, startMs: number, days: number,
  opts: { stepMin?: number; rules?: SiteRules; horizon?: Horizon } = {}): SiteResult {
  const stepMin = opts.stepMin ?? 30, rules = opts.rules ?? defaultRules(lat);
  const hz = opts.horizon ?? flatHorizon, terrain = !!opts.horizon;
  const n = Math.floor((days * 1440) / stepMin) + 1;
  const f = siteFrame(lat, lon);
  const s: SiteSeries = {
    t: new Float64Array(n), sunEl: new Float32Array(n), sunAz: new Float32Array(n), earthEl: new Float32Array(n),
    earthAz: new Float32Array(n), sunHorizon: new Float32Array(n), earthHorizon: new Float32Array(n),
    dsn: new Uint8Array(n), disc: new Float32Array(n),
  };
  let sunUp = 0, earthUp = 0, dsnAny = 0, dsnEarth = 0;
  for (let i = 0; i < n; i++) {
    const ms = startMs + i * stepMin * 60e3, tdb = utcToTdb(ms);
    const st = moonState(eph, tdb);
    const sa = sunAzEl(st, f), ea = earthAzEl(st, f);
    s.t[i] = ms; s.sunEl[i] = sa.el; s.sunAz[i] = sa.az; s.earthEl[i] = ea.el; s.earthAz[i] = ea.az;
    s.sunHorizon[i] = hz(sa.az); s.earthHorizon[i] = hz(ea.az);
    s.disc[i] = discAbove(sa.el, s.sunHorizon[i]);
    const eUp = ea.el >= s.earthHorizon[i];
    s.dsn[i] = eUp ? dsnMask(st, f, tdb) : 0;
    if (sa.el >= s.sunHorizon[i]) sunUp++;
    if (eUp) { earthUp++; if (s.dsn[i]) dsnEarth++; }
    if (s.dsn[i]) dsnAny++;
  }
  const daylight = intervalsAbove(s.t, s.sunEl, s.sunHorizon);

  // landing windows: Sun rising through [min, max] above the horizon, Earth up (unless relay), DSN if asked
  const windows: LandingWindow[] = [];
  let w: { start: number; n: number; earth: number; dsn: number; dsn0: number } | null = null;
  const close = (end: number) => {
    if (w) windows.push({ start: w.start, end, earthPct: (100 * w.earth) / w.n, dsnAtStart: w.dsn0, dsnPct: (100 * w.dsn) / w.n });
    w = null;
  };
  for (let i = 1; i < n; i++) {
    const rel = s.sunEl[i] - s.sunHorizon[i];
    const rising = s.sunEl[i] > s.sunEl[i - 1];
    const earthOk = s.earthEl[i] - s.earthHorizon[i] >= rules.minEarthElDeg;
    const ok = rel >= rules.sunMinDeg && rel <= rules.sunMaxDeg && rising && earthOk && (!rules.requireDsn || s.dsn[i] > 0);
    if (ok) {
      if (!w) w = { start: s.t[i], n: 0, earth: 0, dsn: 0, dsn0: s.dsn[i] };
      w.n++; if (earthOk) w.earth++; if (s.dsn[i]) w.dsn++;
    } else if (w) close(s.t[i - 1]);
  }
  close(s.t[n - 1]);

  // eclipses: scan the hourly table for the Earth near the Sun, then follow the event in 5-minute
  // steps from before the first contact until the Sun is clear again (no fixed window: seen from the
  // surface a total eclipse lasts ~5-6 h). Deepest = smallest Sun-Earth separation.
  const eclipses: Eclipse[] = [];
  const t0 = utcToTdb(startMs), t1 = utcToTdb(startMs + days * 86400e3);
  for (let tdb = t0; tdb < t1; tdb += 3600) {
    const c = sunCoverage(moonState(eph, tdb), f);
    if (c.sepDeg > c.sunRDeg + c.earthRDeg + 1) continue;
    let cur: Eclipse | null = null, minSep = Infinity, u = Math.max(t0, tdb - 3600);
    const stop = Math.min(t1, tdb + 16 * 3600);
    for (; u <= stop; u += 300) {
      const st = moonState(eph, u), cc = sunCoverage(st, f);
      if (cc.fraction > 0) {
        const ms = tdbToUtc(u);
        if (!cur) cur = { start: ms, end: ms, peak: ms, maxFraction: 0, sunUp: false };
        cur.end = ms;
        cur.maxFraction = Math.max(cur.maxFraction, cc.fraction);
        if (cc.sepDeg < minSep) { minSep = cc.sepDeg; cur.peak = ms; }
        const sa = sunAzEl(st, f);
        if (sa.el >= hz(sa.az)) cur.sunUp = true;
      } else if (cur) break;                                     // the Sun is clear again
    }
    if (cur) eclipses.push(cur);
    tdb = Math.max(tdb, u);                                      // continue after the event
  }

  let night = 0, longestNight = 0;
  for (let i = 1; i < n; i++) {
    if (s.sunEl[i] < s.sunHorizon[i]) { night += stepMin; longestNight = Math.max(longestNight, night); } else night = 0;
  }
  const longestDay = daylight.reduce((m, d) => Math.max(m, d.end - d.start), 0) / 3600e3;
  return {
    lat, lon, startMs, endMs: s.t[n - 1], stepMin, terrain, rules, series: s, daylight, windows, eclipses,
    stats: {
      sunUpPct: (100 * sunUp) / n, earthUpPct: (100 * earthUp) / n, dsnPct: (100 * dsnAny) / n,
      dsnWhenEarthUpPct: earthUp ? (100 * dsnEarth) / earthUp : 0,
      longestNightH: longestNight / 60, longestDayH: longestDay,
      earthNeverUp: earthUp === 0, earthAlwaysUp: earthUp === n,
    },
  };
}

export const dsnNames = (mask: number) => DSN.filter((d) => mask & d.bit).map((d) => d.name);
