// The browser's regolith model (src/lib/regolith.ts, siteThermal.ts) against the engine
// (engine/surface/thermal.py) and against Diviner.
//   cd web && npm install && node tests/regolith.check.mjs
//
// Criteria, fixed before the first comparison was run:
//   1. same sunlight, same model: every surface temperature within 0.05 K of the engine's
//      (tests/regolith_reference.json, written by scripts/build_regolith_reference.py), and the
//      spin-up residuals within 0.05 K;
//   2. level ground at the equator: noon, midnight and pre-dawn within 5 K of Diviner
//      (Vasavada et al. 2012 via Hayne et al. 2017), the engine's own check;
//   3. with the DE440 table and a DE440 thermal.json: the browser's whole chain (ephemeris table,
//      Sun, spin-up, model) against build_thermal.py's flat-ground point, every 2 h over the
//      landing period: largest difference <= 1.0 K, mean absolute difference <= 0.2 K.
//   4. (added with the slope map, before its first run on real data) with the slope map, the horizon
//      grid and a sane thermal_attribution.json as well: at each candidate the browser (grid horizon,
//      ground tilted by the slope map) must reproduce that script's version E: its mean |T - T_A|
//      within 0.5 K of E's, its lowest and highest temperature within 0.5 K of E's.
//   Reported, not counted: the same candidates on level ground (the browser before the slope map),
//   and the remaining difference to build_thermal.py, which also has each point's own horizon and the
//   terrain's own light and heat.
import { build } from "esbuild";
import { existsSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = (p) => fileURLToPath(new URL(p, import.meta.url));
const dir = mkdtempSync(join(tmpdir(), "reg-"));
const mods = {};
for (const m of ["regolith", "sky", "siteThermal", "horizonGrid", "slopeMap"]) {
  await build({ entryPoints: [here(`../src/lib/${m}.ts`)], bundle: true, outfile: join(dir, `${m}.mjs`), format: "esm", platform: "node", logLevel: "warning" });
  mods[m] = await import(pathToFileURL(join(dir, `${m}.mjs`)).href);
}
const { regolith: R, sky: S, siteThermal: T, horizonGrid: H, slopeMap: SL } = mods;
let failed = 0;
const check = (ok, what) => { console.log(`${ok ? "PASS" : "FAIL"}  ${what}`); if (!ok) failed++; };

// 1. the engine on made-up sunlight
const ref = JSON.parse(readFileSync(here("regolith_reference.json"), "utf8"));
for (const c of ref.cases) {
  const col = new R.Column();
  check(col.g.z.length === c.layers && Math.abs(col.g.h[0] - c.first_layer_m) < 1e-12 && Math.abs(col.g.z.at(-1) - c.bottom_m) < 1e-12,
    `${c.name}: same soil layers (${c.layers}, first ${(c.first_layer_m * 1000).toFixed(2)} mm, bottom ${c.bottom_m.toFixed(3)} m)`);
  const changes = col.spinUp(c.spin_t, c.spin_F, c.cycles);
  const dc = Math.max(...changes.map((v, i) => Math.abs(v - c.spin_up_changes_k[i])));
  const Ts = col.run(c.t, c.F).surface;
  let worst = 0;
  c.keep.forEach((j, i) => { worst = Math.max(worst, Math.abs(Ts[j] - c.surface_k[i])); });
  check(worst <= 0.05 && dc <= 0.05 && changes.length === c.spin_up_changes_k.length,
    `${c.name} (${c.note}): surface temperature within ${worst.toExponential(1)} K of the engine at ${c.keep.length} samples, spin-up residuals within ${dc.toExponential(1)} K`);
}
{
  // the sunlight formula itself, against the polar case's own forcing
  const c = ref.cases.find((x) => x.name === "polar");
  const P = R.LUNATION_S;
  let worst = 0;
  c.t.forEach((t, i) => {
    const el = 1.0 + 1.2 * Math.sin((2 * Math.PI * t) / P), au = 1.0 + 0.0167 * Math.cos((2 * Math.PI * t) / (365.25 * 86400));
    const F = R.absorbedFlux(Math.sin((el * Math.PI) / 180), R.discFraction(el - 1.5), au);
    worst = Math.max(worst, Math.abs(F - c.F[i]));
  });
  check(worst < 1e-9, `absorbed sunlight with a part of the disc behind the horizon: browser = engine (worst ${worst.toExponential(1)} W/m²)`);
  check(R.discFraction(0) === 0.5 && R.discFraction(0.2666) === 1 && R.discFraction(-0.2666) === 0, "solar disc share: half at the horizon, whole and none one semi-diameter either side");
}

// 2. Diviner at the equator, the browser on its own
{
  const P = R.LUNATION_S, n = 1440;
  const t = Array.from({ length: n + 1 }, (_, i) => (i * P) / n);
  const F = t.map((s) => R.absorbedFlux(Math.cos((2 * Math.PI * s) / P), 1, 1));
  const col = new R.Column();
  col.spinUp(t, F, 8);
  const Ts = col.run(t, F).surface;
  const lt = t.map((s) => (((s / P) * 24 + 12) % 24));
  const at = (h) => Ts[lt.reduce((b, v, i) => (Math.abs(v - h) < Math.abs(lt[b] - h) ? i : b), 0)];
  const div = { noon: [12, 385], midnight: [0, 101], predawn: [5.9, 95] };
  for (const [k, [h, d]] of Object.entries(div)) check(Math.abs(at(h) - d) <= 5, `equator ${k}: browser ${at(h).toFixed(1)} K, Diviner ~${d} K (within 5 K)`);
}

// 3. the whole chain against build_thermal.py (needs DE440 on both sides)
const metaPath = here("../public/data/ephem_moon.json"), thermalPath = here("../public/data/thermal.json");
if (!existsSync(metaPath) || !existsSync(thermalPath)) {
  console.log("no ephemeris table or thermal.json: the end-to-end check is skipped");
} else {
  const meta = JSON.parse(readFileSync(metaPath, "utf8"));
  const th = JSON.parse(readFileSync(thermalPath, "utf8"));
  const de = /DE440/.test(meta.ephemeris) && th.meta.ephemeris === "spice";
  if (!de) {
    console.log(`end-to-end check needs DE440 on both sides (table: ${meta.ephemeris}; thermal.json: ${th.meta.ephemeris}): skipped.\n` +
      "      python scripts/build_ephemeris_table.py --spice  and  python scripts/build_thermal.py --spice");
  } else {
    const buf = readFileSync(here("../public/data/ephem_moon.bin"));
    const eph = S.ephemFromBuffers(meta, buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength));
    const t0 = Date.parse(th.time.t0_utc), step = th.time.step_h, n = th.time.n;
    const tRec0 = S.utcToTdb(t0), hours = (n - 1) * step + 1;
    const opts = { spinUpDays: th.meta.spin_up_days, leadDays: 60, cycles: 6 };
    const flat = th.points.find((p) => p.key === "ref-flat");
    const tic = performance.now();
    const run = T.siteTemperatures(eph, flat.lat, flat.lon, tRec0, hours, opts);
    const ms = performance.now() - tic;
    let worst = 0, sum = 0, worstAt = 0;
    for (let i = 0; i < n; i++) {
      const d = Math.abs(run.surfaceK[i * step] - flat.surface_direct_k[i]);
      sum += d; if (d > worst) { worst = d; worstAt = i; }
    }
    check(worst <= 1.0 && sum / n <= 0.2,
      `${flat.label}: browser vs build_thermal.py over ${n} samples: largest ${worst.toFixed(2)} K (at ${new Date(t0 + worstAt * step * 3600e3).toISOString().slice(0, 16)}), mean ${(sum / n).toFixed(3)} K; ${run.stats.minK.toFixed(1)}..${run.stats.maxK.toFixed(1)} K vs ${flat.min_direct_k}..${flat.max_direct_k} K (${(ms / 1000).toFixed(1)} s)`);
    // 4. the candidates with the terrain horizon from the grid and the tilt from the slope map
    const gm = here("../public/data/horizon_grid_s.json"), sm = here("../public/data/slope_map_s.json");
    const ap = here("../public/data/thermal_attribution.json");
    if (existsSync(gm)) {
      const m = JSON.parse(readFileSync(gm, "utf8"));
      const slope = existsSync(sm) ? JSON.parse(readFileSync(sm, "utf8")) : null;
      const attr = existsSync(ap) ? JSON.parse(readFileSync(ap, "utf8")) : null;
      const attrOk = attr && attr.sane && attr.meta.ephemeris === "spice" && attr.meta.thermal_json === th.meta.generated_utc;
      if (!slope) console.log("no slope map (python scripts/build_slope_map.py): check 4 skipped");
      else if (!attrOk) console.log("no sane DE440 thermal_attribution.json for this thermal.json (python scripts/thermal_attribution.py --spice): check 4 skipped");
      const loadTile = (map, key, file) => {
        if (!map.has(key) && existsSync(file)) { const b = readFileSync(file); map.set(key, new Int16Array(b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength))); }
      };
      const hTiles = new Map(), sTiles = new Map();
      const err = (r, p) => { let s = 0, w = 0; for (let i = 0; i < n; i++) { const d = Math.abs(r.surfaceK[i * step] - p.surface_direct_k[i]); s += d; w = Math.max(w, d); } return [s / n, w]; };
      console.log("candidates: browser vs build_thermal.py direct sunlight (own horizon, tilted ground)" + (slope ? "; level ground reported, not counted" : ""));
      for (const p of th.points.filter((q) => q.terrain)) {
        for (const [r, c] of H.tilesFor(m, p.lat, p.lon)) loadTile(hTiles, `${r},${c}`, here(`../public/data/${H.tilesDir(m)}/t_${r}_${c}.bin`));
        const hz = H.horizonAt(m, hTiles, p.lat, p.lon);
        if (!hz) { console.log(`  ${p.label}: not on the grid`); continue; }
        const lv = T.siteTemperatures(eph, p.lat, p.lon, tRec0, hours, { ...opts, horizon: hz.fn });
        const [lvMean] = err(lv, p);
        let line = `  ${p.label.padEnd(36)} level: mean |ΔT| ${lvMean.toFixed(1)} K, ${lv.stats.minK.toFixed(1)}..${lv.stats.maxK.toFixed(1)} K`;
        if (slope) {
          const t = SL.slopeTileFor(slope, p.lat, p.lon);
          if (t) loadTile(sTiles, t.join(","), here(`../public/data/${slope.tiles_dir}/t_${t[0]}_${t[1]}.bin`));
          const nr = SL.normalAt(slope, sTiles, p.lat, p.lon);
          if (nr) {
            const tl = T.siteTemperatures(eph, p.lat, p.lon, tRec0, hours, { ...opts, horizon: hz.fn, normal: nr.n });
            const [tlMean] = err(tl, p);
            line += ` | slope map (${nr.slopeDeg.toFixed(2)}°): mean |ΔT| ${tlMean.toFixed(1)} K, ${tl.stats.minK.toFixed(1)}..${tl.stats.maxK.toFixed(1)} K` +
              ` (engine ${p.min_direct_k}..${p.max_direct_k} K)`;
            const row = attrOk && attr.points.find((q) => q.key === p.key);
            if (row) {
              console.log(line);
              const dE = Math.abs(tlMean - row.mean_abs_err_k.E), dMin = Math.abs(tl.stats.minK - row.min_k.E), dMax = Math.abs(tl.stats.maxK - row.max_k.E);
              check(dE <= 0.5 && dMin <= 0.5 && dMax <= 0.5, `  ${p.label}: browser with the slope map = thermal_attribution.py E (error ${tlMean.toFixed(2)} vs ${row.mean_abs_err_k.E} K, ` +
                `min ${tl.stats.minK.toFixed(1)} vs ${row.min_k.E}, max ${tl.stats.maxK.toFixed(1)} vs ${row.max_k.E} K)`);
              continue;
            }
          } else line += " | not on the slope map";
        }
        console.log(line);
      }
    }
  }
}
console.log(failed ? `${failed} FAILED` : "all regolith checks passed");
process.exit(failed ? 1 : 0);
