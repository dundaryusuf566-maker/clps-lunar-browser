// The point analysis (src/lib/siteAnalysis.ts) against facts that do not depend on our code:
// the Moon's synodic month and day length, the near side always facing the Earth, the far side never,
// the solar-disc formula, and (with the DE440 table) a lunar eclipse seen from the near side.
//   cd web && npm install && node tests/site.check.mjs
import { build } from "esbuild";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = (p) => fileURLToPath(new URL(p, import.meta.url));
const dir = mkdtempSync(join(tmpdir(), "site-"));
for (const m of ["sky", "siteAnalysis"]) {
  await build({ entryPoints: [here(`../src/lib/${m}.ts`)], bundle: true, outfile: join(dir, `${m}.mjs`), format: "esm", platform: "node", logLevel: "warning" });
}
const S = await import(pathToFileURL(join(dir, "sky.mjs")).href);
const A = await import(pathToFileURL(join(dir, "siteAnalysis.mjs")).href);
const meta = JSON.parse(readFileSync(here("../public/data/ephem_moon.json"), "utf8"));
const buf = readFileSync(here("../public/data/ephem_moon.bin"));
const eph = S.ephemFromBuffers(meta, buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength));
const de = /DE440/.test(meta.ephemeris);

let failed = 0;
const check = (ok, what) => { console.log(`${ok ? "PASS" : "FAIL"}  ${what}`); if (!ok) failed++; };
const DAY = 86400e3, Y2025 = Date.UTC(2025, 0, 1);

// 1. equator, a year: Sun up half the time, days of ~14.8 days, sunrise every synodic month (29.27-29.83 d)
const eq = A.analyzeSite(eph, 0, 30, Y2025, 365, { stepMin: 30 });
check(Math.abs(eq.stats.sunUpPct - 50) < 2, `equator: Sun up ${eq.stats.sunUpPct.toFixed(1)}% of the year (about half)`);
const full = eq.daylight.filter((d) => d.start > Y2025 && d.end < Y2025 + 364 * DAY);
const lens = full.map((d) => (d.end - d.start) / DAY);
check(lens.length >= 11 && lens.every((l) => l > 14.4 && l < 15.2), `equator: ${lens.length} full lunar days, ${Math.min(...lens).toFixed(2)}-${Math.max(...lens).toFixed(2)} d long (~14.77)`);
const gaps = full.slice(1).map((d, i) => (d.start - full[i].start) / DAY);
check(gaps.every((g) => g > 29.2 && g < 29.9), `equator: sunrise to sunrise ${Math.min(...gaps).toFixed(2)}-${Math.max(...gaps).toFixed(2)} d (synodic month 29.27-29.83)`);

// 2. the Earth: always up at the sub-Earth point, never on the far side, sometimes at the limb (libration)
const sub = A.analyzeSite(eph, 0, 0, Y2025, 60, { stepMin: 60 });
check(sub.stats.earthAlwaysUp, `sub-Earth point: Earth up ${sub.stats.earthUpPct.toFixed(1)}% of the time`);
const far = A.analyzeSite(eph, 10, 180, Y2025, 60, { stepMin: 60 });
check(far.stats.earthNeverUp && far.windows.length === 0, `far side: Earth never up (${far.stats.earthUpPct.toFixed(1)}%), no direct-to-Earth landing windows`);
const limb = A.analyzeSite(eph, 0, 90, Y2025, 60, { stepMin: 60 });
check(limb.stats.earthUpPct > 5 && limb.stats.earthUpPct < 95, `east limb: Earth up ${limb.stats.earthUpPct.toFixed(1)}% (libration brings it over the horizon and back)`);
check(sub.series.dsn.every((m, i) => m === 0 || sub.series.earthEl[i] >= 0), "DSN contact only when the Earth is up");

// 3. landing windows follow the rules: Sun rising, inside the elevation band, Earth up
const w0 = eq.windows[0];
check(eq.windows.length >= 11, `equator: ${eq.windows.length} morning landing windows in a year (one per lunar day)`);
const okWindows = eq.windows.every((w) => {
  const i = eq.series.t.findIndex((t) => t >= w.start), j = eq.series.t.findIndex((t) => t >= w.end);
  for (let k = i; k <= j; k++) {
    const el = eq.series.sunEl[k];
    if (el < eq.rules.sunMinDeg - 1e-3 || el > eq.rules.sunMaxDeg + 1e-3 || eq.series.earthEl[k] < eq.rules.minEarthElDeg - 1e-3) return false;
  }
  return true;
});
check(okWindows, `every window keeps the Sun at ${eq.rules.sunMinDeg}-${eq.rules.sunMaxDeg} deg and the Earth above ${eq.rules.minEarthElDeg} deg (first: ${new Date(w0.start).toISOString().slice(0, 16)}, ${((w0.end - w0.start) / 3600e3).toFixed(0)} h)`);

// 4. the solar disc above a horizon
check(A.discAbove(0, 0) === 0.5 && A.discAbove(1, 0) === 1 && A.discAbove(-1, 0) === 0, "solar disc: half at the horizon, all above, none below");
check(Math.abs(A.discAbove(0.1, 0) + A.discAbove(-0.1, 0) - 1) < 1e-12, "solar disc: symmetric about the horizon");

// 5. a terrain horizon delays sunrise and shortens the day
const ridge = A.analyzeSite(eph, 0, 30, Y2025, 60, { stepMin: 30, horizon: (az) => (az > 45 && az < 135 ? 5 : 0) });
const flat = A.analyzeSite(eph, 0, 30, Y2025, 60, { stepMin: 30 });
check(ridge.stats.sunUpPct < flat.stats.sunUpPct && ridge.terrain && !flat.terrain, `a 5 deg ridge to the east: Sun up ${ridge.stats.sunUpPct.toFixed(1)}% vs ${flat.stats.sunUpPct.toFixed(1)}% flat`);

// 6. the total lunar eclipse of 14 March 2025 (greatest 06:59:56 TD, NASA) from the sub-Earth point
const ecl = A.analyzeSite(eph, 0, 0, Date.UTC(2025, 2, 13), 3, { stepMin: 60 }).eclipses;
const e0 = ecl.find((e) => Math.abs(e.peak - Date.UTC(2025, 2, 14, 6, 59)) < 3 * 3600e3);
if (de) {
  check(!!e0 && e0.maxFraction > 0.999 && e0.sunUp, `14 March 2025 from the sub-Earth point: Sun fully hidden (${e0 ? e0.maxFraction.toFixed(3) : "none"}), in daylight`);
  check(!!e0 && Math.abs(e0.peak - Date.UTC(2025, 2, 14, 6, 59)) < 20 * 60e3, `... deepest within 20 min of NASA's greatest eclipse (${e0 ? new Date(e0.peak).toISOString().slice(11, 16) : "-"} UTC)`);
  // the whole Moon is in the penumbra for 6.0 h (NASA: P1 03:57 - P4 10:00 UTC); one point crosses it on a chord,
  // (Earth + Sun discs, ~2.4 deg) / (~0.55 deg/h) ~ 4.5 h
  const h = e0 ? (e0.end - e0.start) / 3600e3 : 0;
  check(h > 4 && h < 6.5, `... the Sun is covered for ${h.toFixed(1)} h from that point (the whole event, not cut short)`);
} else {
  console.log(`(eclipse timing needs the DE440 table; analytic table: ${ecl.length} eclipse(s) in 13-16 March 2025)`);
}
// whatever the table: each event ends with the Sun clear, and none is cut by a fixed window
const yr = A.analyzeSite(eph, 0, 0, Date.UTC(2025, 0, 1), 365, { stepMin: 60 }).eclipses;
check(yr.length >= 2 && yr.every((c) => c.end - c.start > 3 * 3600e3 && c.peak >= c.start && c.peak <= c.end),
  `2025 from the sub-Earth point: ${yr.length} eclipses, each followed to its end (${yr.map((c) => ((c.end - c.start) / 3600e3).toFixed(1) + " h").join(", ")})`);

console.log(failed ? `\n${failed} failed` : "\nall passed");
process.exit(failed ? 1 : 0);
