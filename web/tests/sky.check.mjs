// The browser's sky (src/lib/sky.ts) against the engine's own answers (tests/ephem_reference.json,
// written by scripts/build_ephemeris_table.py together with the table it reads).
//   cd web && npm install && node tests/sky.check.mjs
import { build } from "esbuild";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = (p) => fileURLToPath(new URL(p, import.meta.url));
const out = join(mkdtempSync(join(tmpdir(), "sky-")), "sky.mjs");
await build({ entryPoints: [here("../src/lib/sky.ts")], bundle: true, outfile: out, format: "esm", platform: "node", logLevel: "warning" });
const S = await import(pathToFileURL(out).href);

const meta = JSON.parse(readFileSync(here("../public/data/ephem_moon.json"), "utf8"));
const buf = readFileSync(here("../public/data/ephem_moon.bin"));
const eph = S.ephemFromBuffers(meta, buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength));
const ref = JSON.parse(readFileSync(here("./ephem_reference.json"), "utf8"));
// the table and the engine's answers must come from the same run of build_ephemeris_table.py
if (ref.meta.generated_utc !== meta.generated_utc || ref.meta.ephemeris !== meta.ephemeris) {
  console.log(`FAIL  the table (${meta.ephemeris}, ${meta.generated_utc}) and the reference answers ` +
    `(${ref.meta.ephemeris}, ${ref.meta.generated_utc}) were made separately.\n` +
    "      Run  python scripts/build_ephemeris_table.py --spice  (it writes both) and test again.");
  process.exit(1);
}

const TOL_DEG = 0.01;                 // linear interpolation of an hourly table, float32
let failed = 0, n = 0, worst = { sun: 0, earth: 0, time: 0 }, dsnBorder = 0;
const check = (ok, what) => { if (!ok) { failed++; if (failed < 15) console.log("FAIL ", what); } };
const dAz = (a, b) => Math.abs(((a - b + 540) % 360) - 180);

ref.tdb.forEach((tdb, k) => {
  const t2 = S.utcToTdb(Date.parse(ref.utc[k]));
  worst.time = Math.max(worst.time, Math.abs(t2 - tdb));
  check(Math.abs(t2 - tdb) < 0.002, `UTC -> TDB at ${ref.utc[k]}: ${t2} vs ${tdb}`);
});

for (const site of ref.sites) {
  const f = S.siteFrame(site.lat, site.lon);
  ref.tdb.forEach((tdb, k) => {
    n++;
    const st = S.moonState(eph, tdb);
    const s = S.sunAzEl(st, f), e = S.earthAzEl(st, f);
    const ds = Math.max(Math.abs(s.el - site.sun_el[k]), Math.abs(site.lat) > 89 ? 0 : dAz(s.az, site.sun_az[k]) * Math.cos(s.el * Math.PI / 180));
    const de = Math.max(Math.abs(e.el - site.earth_el[k]), Math.abs(site.lat) > 89 ? 0 : dAz(e.az, site.earth_az[k]) * Math.cos(e.el * Math.PI / 180));
    worst.sun = Math.max(worst.sun, ds);
    worst.earth = Math.max(worst.earth, de);
    check(ds < TOL_DEG, `${site.id} ${ref.utc[k]} Sun: ${s.az.toFixed(4)}/${s.el.toFixed(4)} vs ${site.sun_az[k]}/${site.sun_el[k]}`);
    check(de < TOL_DEG, `${site.id} ${ref.utc[k]} Earth: ${e.az.toFixed(4)}/${e.el.toFixed(4)} vs ${site.earth_az[k]}/${site.earth_el[k]}`);
    const m = S.dsnMask(st, f, tdb);
    if (m !== site.dsn[k]) {
      const el = S.dsnElevations(st, f, tdb);
      const border = Object.values(el).some((v) => Math.abs(v - S.DSN_MIN_ELEV_DEG) < 0.05);
      if (border) dsnBorder++;
      else check(false, `${site.id} ${ref.utc[k]} DSN mask ${m} vs ${site.dsn[k]} (${JSON.stringify(el)})`);
    }
  });
}

// --- eclipses against NASA's catalogue (https://eclipse.gsfc.nasa.gov/LEdecade/LEdecade2021.html) ---
// every lunar eclipse 2024-2028: date and time of greatest eclipse (TD), type, umbral magnitude
const CATALOGUE = [
  ["2024-03-25T07:13:59", "penumbral", -0.132], ["2024-09-18T02:45:25", "partial", 0.085],
  ["2025-03-14T06:59:56", "total", 1.178], ["2025-09-07T18:12:58", "total", 1.362],
  ["2026-03-03T11:34:52", "total", 1.151], ["2026-08-28T04:14:04", "partial", 0.930],
  ["2027-02-20T23:14:06", "penumbral", -0.057], ["2027-07-18T16:04:09", "penumbral", -1.068],
  ["2027-08-17T07:14:59", "penumbral", -0.525], ["2028-01-12T04:14:13", "partial", 0.066],
  ["2028-07-06T18:20:57", "partial", 0.389], ["2028-12-31T16:53:15", "total", 1.246],
];
const J2000_TT_MS = Date.UTC(2000, 0, 1, 12);
const tdOf = (iso) => (Date.parse(iso + "Z") - J2000_TT_MS) / 1000;        // TD ~ TDB (< 2 ms)
const MOON_FROM_EARTH_DEG = 0.259;   // the Moon's radius seen from the Earth: any point of the Moon in the penumbra
const step = 600, t0 = meta.t0_tdb + 3600, t1 = meta.t0_tdb + (meta.n - 2) * meta.step_s;
const events = [];
let cur = null;
for (let t = t0; t < t1; t += step) {
  const c = S.sunCoverage(S.moonState(eph, t), null);
  const near = c.sepDeg < c.sunRDeg + c.earthRDeg + MOON_FROM_EARTH_DEG;
  if (near) {
    if (!cur) cur = { min: Infinity, at: t, maxCentre: 0 };
    if (c.sepDeg < cur.min) { cur.min = c.sepDeg; cur.at = t; }
    cur.maxCentre = Math.max(cur.maxCentre, c.fraction);
  } else if (cur) { events.push(cur); cur = null; }
}
// the geometry itself, on states built by hand: Earth straight in front of the Sun, grazing, half way
{
  const sunAu = 1, rs = Math.asin(695700 / 149597870.7), dE = 384400, re = Math.asin(6378.137 / dE);
  const at = (sepRad) => S.sunCoverage({ sun: [1, 0, 0], sunAu, earth: [dE * Math.cos(sepRad), dE * Math.sin(sepRad), 0], q: [0, 0, 0, 1] }, null);
  check(Math.abs(at(0).fraction - 1) < 1e-12, "Earth centred on the Sun hides all of it");
  check(at(re + rs + 1e-6).fraction === 0, "discs just apart: nothing hidden");
  const tang = at(re - rs);                                     // Sun's disc just inside the Earth's
  check(Math.abs(tang.fraction - 1) < 1e-9, `Sun's disc internally tangent: all hidden (${tang.fraction})`);
  // two discs of radii a, b with centres sqrt(b^2 - a^2)... use the symmetric case: the Earth's edge through the Sun's centre
  const half = at(re).fraction;                                 // a little under half (the Earth's edge curves away)
  check(half > 0.45 && half < 0.5, `Earth's edge through the Sun's centre hides just under half (${half.toFixed(4)})`);
}

const deEphem = /DE440/.test(meta.ephemeris);
if (!deEphem) console.log("eclipse timing against NASA's catalogue needs the DE440 table (the analytic Moon is degrees off): reported, not counted");
const tCheck = (ok, what) => (deEphem ? check(ok, what) : (!ok && console.log("  (analytic)", what)));
tCheck(events.length === CATALOGUE.length, `${events.length} eclipses found in 2024-2028, NASA lists ${CATALOGUE.length}`);
let worstMin = 0;
for (const [iso, type, mag] of CATALOGUE) {
  const td = tdOf(iso);
  const ev = events.find((e) => Math.abs(e.at - td) < 6 * 3600);
  tCheck(!!ev, `no eclipse found near ${iso} (${type})`);
  if (!ev) continue;
  const dmin = Math.abs(ev.at - td) / 60;
  worstMin = Math.max(worstMin, dmin);
  tCheck(dmin < 15, `${iso}: greatest eclipse ${dmin.toFixed(1)} min from NASA's`);
  // the Moon's centre is in the umbra (Sun fully hidden there) exactly when the umbral magnitude > 0.5
  if (mag > 0.6) tCheck(ev.maxCentre > 0.999, `${iso} (${type}, ${mag}): Sun not fully hidden at the Moon's centre (${ev.maxCentre.toFixed(3)})`);
  if (mag < 0.4) tCheck(ev.maxCentre < 0.999, `${iso} (${type}, ${mag}): Sun fully hidden at the centre, NASA says it is not in the umbra`);
}
console.log(`eclipses: ${events.length} found, NASA lists ${CATALOGUE.length}; greatest eclipse within ${worstMin.toFixed(1)} min of NASA's (10 min scan)`);

console.log(`${n} point-epochs (${ref.sites.length} points, ${ref.tdb.length} epochs), ephemeris ${meta.ephemeris}`);
console.log(`worst difference: Sun ${worst.sun.toFixed(5)} deg, Earth ${worst.earth.toFixed(5)} deg, time ${(worst.time * 1000).toFixed(3)} ms; ` +
  `DSN masks differing only within 0.05 deg of the 10 deg limit: ${dsnBorder}`);
console.log(failed ? `\n${failed} failed` : "\nall passed");
process.exit(failed ? 1 : 0);
