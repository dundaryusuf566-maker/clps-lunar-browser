// The Anywhere page's CSV export (src/lib/csvExport.ts): every number in the files is the one the page
// computed, the hours line up with the temperature run, the header says where it all comes from.
//   cd web && npm install && node tests/csv.check.mjs
import { build } from "esbuild";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = (p) => fileURLToPath(new URL(p, import.meta.url));
const dir = mkdtempSync(join(tmpdir(), "csv-"));
const mods = {};
for (const m of ["sky", "siteAnalysis", "siteThermal", "csvExport"]) {
  await build({ entryPoints: [here(`../src/lib/${m}.ts`)], bundle: true, outfile: join(dir, `${m}.mjs`), format: "esm", platform: "node", logLevel: "warning" });
  mods[m] = await import(pathToFileURL(join(dir, `${m}.mjs`)).href);
}
const { sky: S, siteAnalysis: A, siteThermal: T, csvExport: C } = mods;
const meta = JSON.parse(readFileSync(here("../public/data/ephem_moon.json"), "utf8"));
const buf = readFileSync(here("../public/data/ephem_moon.bin"));
const eph = S.ephemFromBuffers(meta, buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength));
let failed = 0;
const check = (ok, what) => { console.log(`${ok ? "PASS" : "FAIL"}  ${what}`); if (!ok) failed++; };
const ctx = { ephemeris: meta.ephemeris, horizon: "level (no terrain)", ground: "level", generatedUtc: "2026-10-21T00:00:00Z" };
const parse = (text) => {
  const lines = text.trimEnd().split("\n"), head = lines.filter((l) => l.startsWith("#")), body = lines.filter((l) => !l.startsWith("#"));
  return { head, cols: body[0].split(","), rows: body.slice(1) };
};
const start = Date.UTC(2026, 10, 1), days = 30;

for (const stepMin of [30, 60]) {
  const r = A.analyzeSite(eph, 0, 30, start, days, { stepMin });
  const t = T.siteTemperatures(eph, 0, 30, S.utcToTdb(start), days * 24 + 1, { spinUpDays: 60, leadDays: 10, cycles: 3 });
  const { head, cols, rows } = parse(C.hourlyCsv(r, t, ctx));
  check(rows.length === days * 24 + 1, `hourly (${stepMin}-min analysis): ${rows.length} rows, one per hour of ${days} days plus the last`);
  check(cols.length === 11 && rows.every((x) => x.split(",").length === cols.length), "every row has the 11 columns");
  check(head.some((h) => h.includes(meta.ephemeris)) && head.some((h) => h.includes("latitude 0.0000")), "header names the ephemeris and the point");
  let worst = 0, hourOk = true;
  rows.forEach((x, h) => {
    const v = x.split(",");
    const i = h * (60 / stepMin);
    hourOk &&= Date.parse(v[0]) === r.series.t[i] && Math.abs(t.t[h] - r.series.t[i]) < 60e3;
    worst = Math.max(worst, Math.abs(+v[1] - r.series.sunEl[i]), Math.abs(+v[10] - t.surfaceK[h]), Math.abs(+v[5] - t.dni[h]) / 10);
  });
  check(hourOk, "each row's time is the analysis sample and the temperature run's hour (within a minute)");
  check(worst < 0.06, `values are the page's own (worst rounding ${worst.toFixed(4)})`);
}
{
  const r = A.analyzeSite(eph, 0, 30, start, 60, { stepMin: 30 });
  const { cols, rows } = parse(C.eventsCsv(r, ctx));
  const kinds = (k) => rows.filter((x) => x.startsWith(k + ",")).length;
  check(cols.join(",") === "type,start_utc,end_utc,hours,peak_utc,detail", "events: header row");
  check(kinds("daylight") === r.daylight.length && kinds("landing_window") === r.windows.length && kinds("eclipse") === r.eclipses.length,
    `events: ${r.daylight.length} daylight, ${r.windows.length} windows, ${r.eclipses.length} eclipses, as on the page`);
  const starts = rows.map((x) => Date.parse(x.split(",")[1]));
  check(starts.every((s, i) => !i || s >= starts[i - 1]), "events in time order");
  const quoted = rows.every((x) => (x.match(/"/g) ?? []).length % 2 === 0);
  check(quoted, "detail fields with commas are quoted");
}
{
  const r = A.analyzeSite(eph, 0, 30, start, 30, { stepMin: 30 });
  const { rows } = parse(C.hourlyCsv(r, null, ctx));
  check(rows.every((x) => x.endsWith(",")) && rows.every((x) => x.split(",")[5] === ""), "without a temperature run the temperature and sunlight columns are left empty");
}
console.log(failed ? `${failed} FAILED` : "all CSV checks passed");
process.exit(failed ? 1 : 0);
