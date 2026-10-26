import type { Landing, LandingEntry, LandingsFile, Site, SunSeries, TransferRow } from "../types";

/** Everything the UI knows about landings: the static file plus live results. */
export interface LandingStore {
  file: LandingsFile | null;
  custom: Record<string, Record<string, LandingEntry>>;   // transfer id -> site id -> entry
  customSeries: Record<string, Record<string, SunSeries>>; // transfer id -> site id -> series
}

export function decode(entry: LandingEntry | undefined, row: TransferRow, descentMs: number): Landing | null {
  if (!entry) return null;
  if (typeof entry[0] === "string") {
    return {
      feasible: false, code: entry[0] as Landing["code"], waitDays: null, planeChangeMs: null, sunElDeg: null, sunHorizonDeg: null,
      dsn: null, energyPct: null, darkGapH: null,
      earthElDeg: null, daylightDays: null, daylightCapped: false, bestPlaneMs: (entry[1] as number | null) ?? null,
      descentMs, surfaceMs: null,
    };
  }
  const [wait, pc, sun, earth, day, capped, hz, dsn, energy, gap] = entry as (number | null)[] as number[];
  return {
    feasible: true, code: "", waitDays: wait, planeChangeMs: pc, sunElDeg: sun, sunHorizonDeg: hz ?? null,
    dsn: dsn ?? null, energyPct: energy ?? null, darkGapH: gap ?? null, earthElDeg: earth,
    daylightDays: day, daylightCapped: capped === 1, bestPlaneMs: pc, descentMs,
    surfaceMs: row.loi_dv_ms + pc + descentMs,
  };
}

export function landingFor(store: LandingStore, siteId: string | null, row: TransferRow | null): Landing | null {
  if (!siteId || !row || !store.file) return null;
  const descent = store.file.meta.descent_ms;
  const entry = row.custom ? store.custom[row.id]?.[siteId] : store.file.results[siteId]?.[row.id];
  return decode(entry, row, descent);
}

export function seriesFor(store: LandingStore, siteId: string, row: TransferRow): SunSeries | null {
  if (row.custom) return store.customSeries[row.id]?.[siteId] ?? null;
  return store.file?.series[siteId] ?? null;
}

export function reasonText(l: Landing, site: Site, maxPlaneMs: number, maxWaitDays: number): string {
  if (l.code === "sun") {
    const above = site.terrain ? "the terrain horizon" : "the horizon";
    const win = site.sun_max_deg >= 90 ? `${site.sun_min_deg}° above ${above}` : `between ${site.sun_min_deg}° and ${site.sun_max_deg}° above ${above}`;
    return `The Sun is never ${win}${site.sun_rising ? " and rising" : ""} at the site during the ${maxWaitDays} days in orbit.`;
  }
  if (l.code === "earth") return "Earth is below the horizon whenever the light is right, so the landing needs a relay.";
  if (l.code === "daylight") return "Every landing slot is too close to sunset to leave the required days of sunlight.";
  if (l.code === "plane") {
    return `Lining the orbit up with the site at dawn needs a ${Math.round(l.bestPlaneMs ?? 0)} m/s plane change; the budget is ${maxPlaneMs} m/s.`;
  }
  return "";
}

/** Sun elevation from a series between two TDB epochs, as [t, el, horizon] triples
 *  (horizon = terrain in the Sun's direction, 0 for a flat horizon). */
export function sliceSeries(s: SunSeries, from: number, to: number): [number, number, number][] {
  const i0 = Math.max(0, Math.floor((from - s.t0) / s.step_s));
  const i1 = Math.min(s.sun_el_deg.length - 1, Math.ceil((to - s.t0) / s.step_s));
  const out: [number, number, number][] = [];
  for (let i = i0; i <= i1; i++) out.push([s.t0 + i * s.step_s, s.sun_el_deg[i], s.horizon_deg?.[i] ?? 0]);
  return out;
}

/** Names of the DSN stations in a bitmask. */
export const DSN_STATIONS: [number, string][] = [[1, "Goldstone"], [2, "Madrid"], [4, "Canberra"]];
export const dsnNames = (mask: number | null) => (mask ? DSN_STATIONS.filter(([b]) => mask & b).map(([, n]) => n) : []);

/** TDB epoch of the transfer's arrival at the Moon (LOI). */
export const arrivalEpoch = (row: TransferRow) => row.tli_epoch + row.tof_actual_days * 86400;
