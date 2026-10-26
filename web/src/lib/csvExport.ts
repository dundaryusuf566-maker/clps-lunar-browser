/**
 * The Anywhere page's numbers as CSV files: what was computed, hour by hour, and the events, with a
 * header saying where every column comes from and what it leaves out. Pure functions; tested by
 * web/tests/csv.check.mjs.
 *
 * Header lines start with "#" (pandas: read_csv(..., comment="#"); Excel shows them as rows).
 */
import { dsnNames, type SiteResult } from "./siteAnalysis";
import type { ThermalRun } from "./siteThermal";

export interface ExportContext {
  ephemeris: string;              // the table's source (e.g. "JPL DE440")
  tableGenerated?: string;        // when the table was built
  horizon: string;                // "level", or the LOLA grid it came from
  ground: string;                 // "level", or the slope and where it came from
  pageUrl?: string;               // a link back to the same view
  generatedUtc?: string;          // export time (ISO); defaults to now
}

const iso = (ms: number) => new Date(ms).toISOString().replace(".000Z", "Z");
const num = (v: number, d: number) => (Number.isFinite(v) ? v.toFixed(d) : "");
const field = (s: string) => (/[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s);

function header(r: SiteResult, c: ExportContext, what: string): string[] {
  return [
    `# CLPS Lunar Mission Browser, Anywhere page: ${what}`,
    `# point: latitude ${r.lat.toFixed(4)} deg, longitude ${r.lon.toFixed(4)} deg east (IAU Moon-fixed)`,
    `# period: ${iso(r.startMs)} to ${iso(r.endMs)} (UTC)`,
    `# ephemeris: ${c.ephemeris}${c.tableGenerated ? ` (hourly table built ${c.tableGenerated})` : ""}, interpolated in the browser`,
    `# horizon: ${c.horizon}`,
    `# ground: ${c.ground}`,
    `# landing rule: Sun ${r.rules.sunMinDeg}-${r.rules.sunMaxDeg} deg above the horizon and rising, Earth at least ${r.rules.minEarthElDeg} deg up; no transfer or orbit plane`,
    "# DSN: Goldstone, Madrid, Canberra with the Moon above 10 deg (our assumption)",
    ...(c.pageUrl ? [`# view: ${c.pageUrl}`] : []),
    `# exported: ${c.generatedUtc ?? new Date().toISOString()}`,
  ];
}

/** One row per hour: the sky (from the point analysis) and the ground (from the temperature run). */
export function hourlyCsv(r: SiteResult, t: ThermalRun | null, c: ExportContext): string {
  const s = r.series, per = Math.round(60 / r.stepMin);
  const n = Math.floor((s.t.length - 1) / per) + 1;
  const lines = header(r, c, "hourly series");
  lines.push(
    "# sun_disc_above_horizon: share of the solar disc above the horizon (0-1); sun_w_m2: sunlight on a surface facing the Sun",
    "#   (S / d^2 x that share, S = 1361 W/m^2); surface_k: regolith surface temperature, Hayne et al. 2017 model, direct sunlight",
    "#   only (no light or heat from surrounding terrain); empty where not computed",
  );
  if (t?.approximate) lines.push("# note: the table did not reach a lunation before the period; the soil was spun up on the period itself, the first days are approximate");
  lines.push("utc,sun_el_deg,sun_az_deg,sun_horizon_deg,sun_disc_above_horizon,sun_w_m2,earth_el_deg,earth_az_deg,earth_horizon_deg,dsn_stations,surface_k");
  for (let h = 0; h < n; h++) {
    const i = h * per;
    const k = t ? Math.round((s.t[i] - t.t[0]) / 3600e3) : -1;
    const ok = t && k >= 0 && k < t.t.length && Math.abs(t.t[k] - s.t[i]) < 60e3;
    lines.push([
      iso(s.t[i]), num(s.sunEl[i], 3), num(s.sunAz[i], 2), num(s.sunHorizon[i], 3), num(s.disc[i], 4),
      ok ? num(t!.dni[k], 1) : "", num(s.earthEl[i], 3), num(s.earthAz[i], 2), num(s.earthHorizon[i], 3),
      dsnNames(s.dsn[i]).join("|"), ok ? num(t!.surfaceK[k], 2) : "",
    ].join(","));
  }
  return lines.join("\n") + "\n";
}

/** Landing windows, daylight and eclipses, one row each. */
export function eventsCsv(r: SiteResult, c: ExportContext): string {
  const lines = header(r, c, "events");
  lines.push(
    "# daylight: Sun's centre above the horizon (start or end at the period's edge means it began before / lasted beyond);",
    "#   landing_window: the rule above holds; eclipse: the Earth covers part of the Sun (geometric; the atmosphere widens it ~2%)",
    "type,start_utc,end_utc,hours,peak_utc,detail",
  );
  const rows: [number, string][] = [];
  const h = (a: number, b: number) => ((b - a) / 3600e3).toFixed(2);
  for (const d of r.daylight) rows.push([d.start, ["daylight", iso(d.start), iso(d.end), h(d.start, d.end), "",
    field(`${d.start <= r.startMs ? "began before the period" : ""}${d.start <= r.startMs && d.end >= r.endMs ? "; " : ""}${d.end >= r.endMs ? "lasts beyond the period" : ""}`)].join(",")]);
  for (const w of r.windows) rows.push([w.start, ["landing_window", iso(w.start), iso(w.end), h(w.start, w.end), "",
    field(`DSN at opening: ${dsnNames(w.dsnAtStart).join("|") || "none"}; DSN in window ${w.dsnPct.toFixed(0)}%; Earth up ${w.earthPct.toFixed(0)}%`)].join(",")]);
  for (const e of r.eclipses) rows.push([e.start, ["eclipse", iso(e.start), iso(e.end), h(e.start, e.end), iso(e.peak),
    field(`Sun hidden at most ${(100 * e.maxFraction).toFixed(0)}%; ${e.sunUp ? "in daylight here" : "at night here"}`)].join(",")]);
  rows.sort((a, b) => a[0] - b[0]);
  return lines.concat(rows.map((x) => x[1])).join("\n") + "\n";
}

/** Hand a text file to the browser's download. */
export function download(name: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export const fileStem = (r: SiteResult) =>
  `moon_${Math.abs(r.lat).toFixed(3)}${r.lat < 0 ? "S" : "N"}_${Math.abs(r.lon).toFixed(3)}${r.lon < 0 ? "W" : "E"}_${iso(r.startMs).slice(0, 10)}`;
