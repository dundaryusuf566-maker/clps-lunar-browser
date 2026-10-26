// The browser's slope-map lookup (src/lib/slopeMap.ts) against the Python decoder that
// scripts/build_slope_map.py checked against build_thermal.py's local_normal: same points, same tiles,
// same normals (within 1e-6 deg), and the build's own check passed.
//   cd web && npm install && node tests/slope.check.mjs
import { build } from "esbuild";
import { existsSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = (p) => fileURLToPath(new URL(p, import.meta.url));
const metas = ["s", "n"].map((p) => here(`../public/data/slope_map_${p}.json`)).filter((p) => existsSync(p));
if (!metas.length) {
  console.log("no slope map yet (python scripts/build_slope_map.py): skipped");
  process.exit(0);
}
const out = join(mkdtempSync(join(tmpdir(), "slope-")), "slope.mjs");
await build({ entryPoints: [here("../src/lib/slopeMap.ts")], bundle: true, outfile: out, format: "esm", platform: "node", logLevel: "warning" });
const S = await import(pathToFileURL(out).href);
let failed = 0;
const check = (ok, what) => { console.log(`${ok ? "PASS" : "FAIL"}  ${what}`); if (!ok) failed++; };
for (const path of metas) {
  const m = JSON.parse(readFileSync(path, "utf8"));
  console.log(`--- ${m.pole} pole: ${m.dem}, ${m.block_m} m blocks, to ${m.min_abs_lat}°`);
  check(m.check.pass, `build check: stored normals vs local_normal afresh at ${m.check.points} points, worst ${m.check.worst_deg}° (limit ${m.check.limit_deg}°)`);
  const tiles = new Map();
  let worst = 0, found = 0;
  for (const s of m.check_samples) {
    const t = S.slopeTileFor(m, s.lat, s.lon);
    if (t && !tiles.has(t.join(","))) {
      const b = readFileSync(here(`../public/data/${m.tiles_dir}/t_${t[0]}_${t[1]}.bin`));
      tiles.set(t.join(","), new Int16Array(b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength)));
    }
    const r = S.normalAt(m, tiles, s.lat, s.lon);
    if (!r) continue;
    found++;
    const a = r.n, b = s.normal;     // angle from the cross product: acos loses precision near 0
    const cr = Math.hypot(a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]);
    worst = Math.max(worst, (Math.atan2(cr, a[0] * b[0] + a[1] * b[1] + a[2] * b[2]) * 180) / Math.PI);
  }
  check(found === m.check_samples.length, `every sample point found on the map (${found}/${m.check_samples.length})`);
  check(worst < 1e-6, `browser and Python decode the same normal (worst ${worst.toExponential(1)}°)`);
  const sg = m.pole === "north" ? 1 : -1;
  check(!S.slopeCovers(m, sg * (m.min_abs_lat - 0.5)) && S.slopeCovers(m, sg * (m.min_abs_lat + 0.5)), `the map covers its own cap only (beyond ${m.min_abs_lat}°)`);
}
console.log(failed ? `${failed} FAILED` : "all slope-map checks passed");
process.exit(failed ? 1 : 0);
