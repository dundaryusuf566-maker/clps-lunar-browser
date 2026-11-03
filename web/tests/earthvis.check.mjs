// Communication maps (src/lib/commsMap.ts). Criteria written before the first run (3 November 2026):
//  1. Check A in the browser (the engine's pre-registered check, here on the DE440 table): level ground over
//     the map's twelve months, Earth in view 100% at 0N 0E, 0% at 0N 180E, strictly between at 0N 90E and 90W.
//  2. The whole-Moon grid is the point analysis: at six cells, Earth in view and Sun + Earth equal
//     siteAnalysis (level, same samples) within 0.01 percentage points; DSN contact within 0.5 (the grid
//     takes the DSN geometry from the Moon's centre, the point analysis from the point).
//  3. Polar maps (if built): the browser decodes the engine's sample grid points exactly, and, when the map
//     and the table come from the same ephemeris, the point analysis with the grid horizon at those points
//     reproduces all three layers within 1 percentage point.
//   cd web && npm install && node tests/earthvis.check.mjs
import { build } from "esbuild";
import { existsSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = (p) => fileURLToPath(new URL(p, import.meta.url));
const dir = mkdtempSync(join(tmpdir(), "earthvis-"));
for (const m of ["sky", "siteAnalysis", "commsMap", "horizonGrid"]) {
  await build({ entryPoints: [here(`../src/lib/${m}.ts`)], bundle: true, outfile: join(dir, `${m}.mjs`), format: "esm", platform: "node", logLevel: "warning" });
}
const S = await import(pathToFileURL(join(dir, "sky.mjs")).href);
const A = await import(pathToFileURL(join(dir, "siteAnalysis.mjs")).href);
const C = await import(pathToFileURL(join(dir, "commsMap.mjs")).href);
const G = await import(pathToFileURL(join(dir, "horizonGrid.mjs")).href);
const data = (p) => here(`../public/data/${p}`);
const meta = JSON.parse(readFileSync(data("ephem_moon.json"), "utf8"));
const buf = readFileSync(data("ephem_moon.bin"));
const eph = S.ephemFromBuffers(meta, buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength));
const de = /DE440/.test(meta.ephemeris);

let failed = 0;
const check = (ok, what) => { console.log(`${ok ? "PASS" : "FAIL"}  ${what}`); if (!ok) failed++; };
const START = Date.UTC(2026, 10, 1), DAYS = 365;

// 1. check A on the browser's table
const pts = { near_centre: [0, 0], far_centre: [0, 180], east_limb: [0, 90], west_limb: [0, -90] };
const a = Object.fromEntries(Object.entries(pts).map(([k, [la, lo]]) => [k, A.analyzeSite(eph, la, lo, START, DAYS, { stepMin: 60 }).stats.earthUpPct]));
const txt = Object.entries(a).map(([k, v]) => `${k} ${v.toFixed(2)}%`).join(", ");
if (de) {
  check(a.near_centre === 100 && a.far_centre === 0 && a.east_limb > 0 && a.east_limb < 100 && a.west_limb > 0 && a.west_limb < 100,
    `check A, level ground, 12 months from 1 Nov 2026 (${meta.ephemeris}): ${txt}`);
} else {
  check(a.near_centre === 100 && a.far_centre === 0, `check A near/far only (${meta.ephemeris} has no libration in longitude): ${txt}`);
}

// 2. whole-Moon grid against the point analysis
const g = C.worldGrid(eph, START, DAYS);
console.log(`whole-Moon grid: ${g.rows} x ${g.cols} cells of ${g.stepDeg} deg, ${g.samples} samples every ${g.stepH} h`);
let worst = { earth: 0, sun_earth: 0, dsn: 0 };
for (const [r, c] of [[44, 89], [44, 0], [45, 135], [3, 20], [86, 150], [60, 40]]) {
  const la = 90 - (r + 0.5) * g.stepDeg, lo = -180 + (c + 0.5) * g.stepDeg;
  const p = A.analyzeSite(eph, la, lo, START, DAYS, { stepMin: 60 * g.stepH });
  const s = p.series;
  let se = 0;
  for (let i = 0; i < s.t.length; i++) if (s.earthEl[i] >= s.earthHorizon[i] && s.sunEl[i] >= s.sunHorizon[i]) se++;
  const k = r * g.cols + c;
  worst.earth = Math.max(worst.earth, Math.abs(g.earth[k] - p.stats.earthUpPct));
  worst.sun_earth = Math.max(worst.sun_earth, Math.abs(g.sun_earth[k] - (100 * se) / s.t.length));
  worst.dsn = Math.max(worst.dsn, Math.abs(g.dsn[k] - p.stats.dsnPct));
}
check(worst.earth <= 0.01 && worst.sun_earth <= 0.01 && worst.dsn <= 0.5,
  `whole-Moon grid = point analysis at 6 cells: worst Earth ${worst.earth.toFixed(3)}, Sun + Earth ${worst.sun_earth.toFixed(3)}, DSN ${worst.dsn.toFixed(3)} pp`);
const nearCell = g.earth[44 * g.cols + 90], farCell = g.earth[44 * g.cols + 0];
check(nearCell === 100 && farCell === 0, `whole-Moon grid: Earth in view ${nearCell}% beside the sub-Earth point, ${farCell}% at the far side's centre`);

// 3. the engine's polar maps
for (const tag of ["s", "n"]) {
  if (!existsSync(data(`earth_vis_${tag}.json`))) { console.log(`(no earth_vis_${tag}.json: python scripts/build_earth_visibility.py --spice${tag === "n" ? " --pole north" : ""})`); continue; }
  const m = JSON.parse(readFileSync(data(`earth_vis_${tag}.json`), "utf8"));
  const b = readFileSync(data(m.bin));
  const v = { meta: m, data: new Uint8Array(b.buffer, b.byteOffset, b.byteLength) };
  console.log(`--- ${m.pole} pole: ${m.dem}, ${m.ephemeris}, ${m.period_utc[0].slice(0, 10)} to ${m.period_utc[1].slice(0, 10)}; ` +
    `check A ${m.check_a.pass ? "pass" : "FAIL"}, check B ${m.check_b ? (m.check_b.pass ? "pass" : "FAIL") : "not run"}`);
  check(b.byteLength === m.layers.length * m.n * m.n, `${m.pole}: file size ${b.byteLength} = ${m.layers.length} layers x ${m.n} x ${m.n}`);
  let decodeOk = true, posWorst = 0;
  for (const s of m.samples) {
    const [la, lo] = C.nodeLatLon(m, s.row, s.col);
    posWorst = Math.max(posWorst, Math.abs(la - s.lat), Math.abs(((lo - s.lon + 540) % 360) - 180));
    for (const L of ["earth", "sun_earth", "dsn"]) if (C.nodeValue(v, L, s.row, s.col) !== s[L]) decodeOk = false;
  }
  check(decodeOk && posWorst < 1e-6, `${m.pole}: ${m.samples.length} sample grid points decoded exactly (position worst ${posWorst.toExponential(1)} deg)`);
  if (m.ephemeris !== meta.ephemeris) { console.log(`(${m.pole}: map from ${m.ephemeris}, table ${meta.ephemeris}: comparison with the point analysis skipped)`); continue; }
  const gm = JSON.parse(readFileSync(data(`horizon_grid_${tag}.json`), "utf8"));
  const tiles = new Map();
  for (const [r, c] of gm.tiles) {
    const tb = readFileSync(data(`${G.tilesDir(gm)}/t_${r}_${c}.bin`));
    tiles.set(`${r},${c}`, new Int16Array(tb.buffer.slice(tb.byteOffset, tb.byteOffset + tb.byteLength)));
  }
  const p0 = Date.parse(`${m.period_utc[0]}Z`), days = (Date.parse(`${m.period_utc[1]}Z`) - p0) / 86400e3;
  let w = { earth: 0, sun_earth: 0, dsn: 0 };
  for (const s of m.samples) {
    const h = G.horizonAt(gm, tiles, s.lat, s.lon);
    const p = A.analyzeSite(eph, s.lat, s.lon, p0, days, { stepMin: 60, horizon: h.fn });
    const sr = p.series;
    let se = 0;
    for (let i = 0; i < sr.t.length; i++) if (sr.earthEl[i] >= sr.earthHorizon[i] && sr.sunEl[i] >= sr.sunHorizon[i]) se++;
    w.earth = Math.max(w.earth, Math.abs(p.stats.earthUpPct - s.earth));
    w.sun_earth = Math.max(w.sun_earth, Math.abs((100 * se) / sr.t.length - s.sun_earth));
    w.dsn = Math.max(w.dsn, Math.abs(p.stats.dsnPct - s.dsn));
  }
  check(w.earth <= 1 && w.sun_earth <= 1 && w.dsn <= 1,
    `${m.pole}: point analysis with the grid horizon = engine map at ${m.samples.length} grid points: worst Earth ${w.earth.toFixed(2)}, Sun + Earth ${w.sun_earth.toFixed(2)}, DSN ${w.dsn.toFixed(2)} pp`);
}

console.log(failed ? `\n${failed} FAILED` : "\nall communication-map checks passed");
process.exit(failed ? 1 : 0);
