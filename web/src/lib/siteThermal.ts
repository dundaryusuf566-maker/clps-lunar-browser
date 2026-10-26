/**
 * Ground temperature and sunlight at any point, hour by hour, in the browser: the Sun from the
 * ephemeris table, the share of its disc above the horizon (flat, or the terrain horizon where a
 * grid covers the point), and the regolith model of lib/regolith.ts, spun up the way
 * scripts/build_thermal.py does it (a year of the point's own sunlight, then a lead-in).
 *
 * The tilt of the ground: from the 240 m slope map where one covers the point (lib/slopeMap.ts),
 * level elsewhere. Left out, and said so on the page: the light and heat from the surrounding
 * terrain (build_thermal.py has it for the forecast's candidates). Tested by web/tests/regolith.check.mjs against the engine.
 */
import { REGOLITH, Column, absorbedFlux, discFraction } from "./regolith";
import { moonState, siteFrame, sunAzEl, tdbToUtc, utcToTdb, type Ephem, type Vec3 } from "./sky";
import type { Horizon } from "./siteAnalysis";

const DAY = 86400, HOUR = 3600;

export interface ThermalOptions {
  horizon?: Horizon;          // terrain horizon, elevation (deg) by azimuth; flat if absent
  normal?: Vec3;              // outward normal of the ground (Moon-fixed); level if absent
  spinUpDays?: number;        // build_thermal.py: 365
  leadDays?: number;          // build_thermal.py: 60 (the terrain-radiation lead-in); 30 here by default
  cycles?: number;            // build_thermal.py: 6
}

export interface ThermalRun {
  t: Float64Array;            // UTC ms of each hourly sample
  surfaceK: Float32Array;
  dni: Float32Array;          // W m^-2 a Sun-facing panel gets: S / d^2 x disc share above the horizon
  sunEl: Float32Array;        // deg, from the Moon's centre (as the engine)
  spinUpDays: number;         // as run (shorter if the table starts too late)
  spinUpResidualK: number;    // change of the deep mean in the last spin-up pass
  approximate: boolean;       // the table did not reach back a lunation: spun up on the period itself
  terrain: boolean;
  tilted: boolean;            // the ground's tilt from the slope map, not level
  stats: { minK: number; maxK: number; meanK: number; hoursBelow150: number; hoursAbove350: number };
}

/** Sunlight at TDB times: absorbed flux on the ground (level, or with the given normal), panel sunlight,
 * Sun elevation. The disc share is measured above the horizon at the point, as build_thermal.py does. */
function forcing(eph: Ephem, lat: number, lon: number, tdb: ArrayLike<number>, hz: Horizon | null, normal: Vec3 | null) {
  const f = siteFrame(lat, lon);
  const nv = normal ?? f.up;
  const n = tdb.length;
  const F = new Float64Array(n), dni = new Float32Array(n), el = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const st = moonState(eph, tdb[i]);
    const sa = sunAzEl(st, f);
    const cosInc = st.sun[0] * nv[0] + st.sun[1] * nv[1] + st.sun[2] * nv[2];
    const share = discFraction(sa.el - (hz ? hz(sa.az) : 0));
    F[i] = absorbedFlux(cosInc, share, st.sunAu);
    dni[i] = (share * REGOLITH.S) / (st.sunAu * st.sunAu);
    el[i] = sa.el;
  }
  return { F, dni, el };
}

/** The engine's time grid (build_thermal.py): hourly from s0 = start - lead - spin-up; spin-up on the
 * samples before start - lead, the run from the last of them on. Returns the grid split that way. */
export function thermalGrid(tRec0: number, hours: number, spinUpDays: number, leadDays: number) {
  const w0 = tRec0 - leadDays * DAY;
  const s0 = w0 - spinUpDays * DAY;
  const nSpin = Math.round((spinUpDays * DAY) / HOUR);
  const nRun = Math.round((leadDays * DAY) / HOUR) + hours + 1;     // from w0 - 1 h to the last recorded hour
  const spin = new Float64Array(nSpin), run = new Float64Array(nRun);
  for (let k = 0; k < nSpin; k++) spin[k] = s0 + k * HOUR;
  for (let k = 0; k < nRun; k++) run[k] = s0 + (nSpin - 1 + k) * HOUR;
  const rec0 = nRun - hours;                                         // first recorded sample in `run`
  return { spin, run, rec0 };
}

export function siteTemperatures(eph: Ephem, lat: number, lon: number, tRec0: number, hours: number,
  opts: ThermalOptions = {}): ThermalRun {
  const hz = opts.horizon ?? null, nrm = opts.normal ?? null;
  const cycles = opts.cycles ?? 6;
  let lead = opts.leadDays ?? 30, spinDays = opts.spinUpDays ?? 365;
  const tableStart = eph.meta.t0_tdb;
  const reach = tRec0 - lead * DAY - tableStart;                   // how far back the table goes before the lead-in
  let approximate = false;
  if (reach < spinDays * DAY) {
    spinDays = Math.floor(Math.max(0, reach) / DAY);
    if (spinDays < 30) {                                           // less than a lunation: spin up on the period itself
      approximate = true;
      spinDays = 0;
      lead = 0;
    }
  }
  const col = new Column();
  let residual = NaN, run: Float64Array, rec0: number;
  if (!approximate) {
    const g = thermalGrid(tRec0, hours, spinDays, lead);
    const sp = forcing(eph, lat, lon, g.spin, hz, nrm);
    residual = col.spinUp(g.spin, sp.F, cycles).at(-1) ?? NaN;
    run = g.run; rec0 = g.rec0;
  } else {
    const nLun = Math.ceil((29.530589 * DAY) / HOUR) + 1;
    const spin = new Float64Array(nLun);
    for (let k = 0; k < nLun; k++) spin[k] = tRec0 + k * HOUR;
    residual = col.spinUp(spin, forcing(eph, lat, lon, spin, hz, nrm).F, cycles).at(-1) ?? NaN;
    run = new Float64Array(hours);
    for (let k = 0; k < hours; k++) run[k] = tRec0 + k * HOUR;
    rec0 = 0;
  }
  const fr = forcing(eph, lat, lon, run, hz, nrm);
  const T = col.run(run, fr.F).surface;
  const n = run.length - rec0;
  const out: ThermalRun = {
    t: new Float64Array(n), surfaceK: new Float32Array(n), dni: fr.dni.slice(rec0), sunEl: fr.el.slice(rec0),
    spinUpDays: spinDays, spinUpResidualK: residual, approximate, terrain: !!hz, tilted: !!nrm,
    stats: { minK: Infinity, maxK: -Infinity, meanK: 0, hoursBelow150: 0, hoursAbove350: 0 },
  };
  for (let i = 0; i < n; i++) {
    const v = T[rec0 + i];
    out.t[i] = tdbToUtc(run[rec0 + i]);
    out.surfaceK[i] = v;
    out.stats.minK = Math.min(out.stats.minK, v);
    out.stats.maxK = Math.max(out.stats.maxK, v);
    out.stats.meanK += v / n;
    if (v < 150) out.stats.hoursBelow150++;
    if (v > 350) out.stats.hoursAbove350++;
  }
  return out;
}

/** UTC ms -> the TDB second the hourly run starts on. */
export const startTdb = (ms: number) => utcToTdb(ms);
