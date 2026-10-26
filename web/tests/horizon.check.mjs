// The browser's horizon grid lookup (src/lib/horizonGrid.ts) against the Python one that measured the
// interpolation error (scripts/build_horizon_grid.py, interp_nodes): same points, same tiles, same numbers.
//   cd web && npm install && node tests/horizon.check.mjs
import { build } from "esbuild";
import { existsSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = (p) => fileURLToPath(new URL(p, import.meta.url));
const metas = ["s", "n"].map((p) => here(`../public/data/horizon_grid_${p}.json`)).filter((p) => existsSync(p));
if (!metas.length) {
  console.log("no horizon grid yet (python scripts/build_horizon_grid.py --spice): skipped");
  process.exit(0);
}
const out = join(mkdtempSync(join(tmpdir(), "hz-")), "hz.mjs");
await build({ entryPoints: [here("../src/lib/horizonGrid.ts")], bundle: true, outfile: out, format: "esm", platform: "node", logLevel: "warning" });
const H = await import(pathToFileURL(out).href);
let failed = 0;
const check = (ok, what) => { console.log(`${ok ? "PASS" : "FAIL"}  ${what}`); if (!ok) failed++; };
for (const metaPath of metas) {
const m = JSON.parse(readFileSync(metaPath, "utf8"));
console.log(`--- ${m.pole} pole: ${m.dem}, every ${m.spacing_km} km`);
const tiles = new Map();
const load = (lat, lon) => {
  for (const [r, c] of H.tilesFor(m, lat, lon)) {
    const k = `${r},${c}`;
    if (!tiles.has(k)) {
      const b = readFileSync(here(`../public/data/${H.tilesDir(m)}/t_${r}_${c}.bin`));
      tiles.set(k, new Int16Array(b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength)));
    }
  }
};
let worst = 0;
for (const s of m.check.interp_samples) {
  load(s.lat, s.lon);
  const h = H.horizonAt(m, tiles, s.lat, s.lon);
  check(!!h, `(${s.lat}, ${s.lon}): grid points found`);
  if (!h) continue;
  const d = Math.max(...s.elev_deg.map((v, k) => Math.abs(v - h.elev[k])));
  worst = Math.max(worst, d);
  check(d < 1e-5, `(${s.lat.toFixed(3)}, ${s.lon.toFixed(3)}): browser and Python interpolation agree (worst ${d.toExponential(1)} deg)`);
  // the function form interpolates in azimuth between the 1 deg values
  check(Math.abs(h.fn(10.5) - (h.elev[10] + h.elev[11]) / 2) < 1e-12 && Math.abs(h.fn(359.5) - (h.elev[359] + h.elev[0]) / 2) < 1e-12,
    "azimuth interpolation, across north too");
}
{
  let worstLL = 0;
  for (let k = 0; k < 200; k++) {
    const la = (m.pole === "north" ? 1 : -1) * (m.min_abs_lat + Math.random() * (90 - m.min_abs_lat - 0.01)), lo = Math.random() * 360 - 180;
    const [x, y] = H.planeXY(m, la, lo), [la2, lo2] = H.latLonOfPlane(m, x, y);
    worstLL = Math.max(worstLL, Math.abs(la2 - la), Math.abs(((lo2 - lo + 540) % 360) - 180) * Math.cos(la * Math.PI / 180));
  }
  check(worstLL < 1e-9, `the polar map's click -> latitude/longitude inverts the projection (worst ${worstLL.toExponential(1)} deg)`);
}
const sg = m.pole === "north" ? 1 : -1;
check(!H.covers(m, sg * (m.min_abs_lat - 1)) && H.covers(m, sg * (m.min_abs_lat + 1)) && !H.covers(m, -sg * 89),
  `the ${m.pole} grid covers its own cap only (beyond ${m.min_abs_lat}°)`);
console.log(`${m.check.interp_samples.length} points; interpolation check from the build: sunlight error median ` +
  `${m.check.sunlit_pct_interp_minus_own.median} pp (flat ground ${m.check.sunlit_pct_flat_minus_own.median} pp)`);
}
console.log(failed ? `\n${failed} failed` : "\nall passed");
process.exit(failed ? 1 : 0);
