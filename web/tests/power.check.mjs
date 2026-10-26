// Checks of the power-budget bookkeeping (src/lib/power.ts) against hand-worked cases.
//   cd web && npm install && node tests/power.check.mjs
import { build } from "esbuild";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const out = join(mkdtempSync(join(tmpdir(), "power-")), "power.mjs");
await build({ entryPoints: [fileURLToPath(new URL("../src/lib/power.ts", import.meta.url))], bundle: true, outfile: out,
  format: "esm", platform: "node", logLevel: "warning" });
const P0 = await import(pathToFileURL(out).href);

let failed = 0;
const check = (ok, what) => { console.log(`${ok ? "PASS" : "FAIL"}  ${what}`); if (!ok) failed++; };
const near = (a, b, tol) => Math.abs(a - b) <= tol;

// 2 h steps: 12 h of Sun on the horizon (1361 W/m^2), 24 h behind the terrain, then Sun again
const n = 30, dni = [], el = [];
for (let i = 0; i < n; i++) { dni.push(i >= 6 && i < 18 ? 0 : 1361); el.push(0); }
const site = { surface_k: new Array(n).fill(200), dni_w_m2: dni, sun_el_deg: el };
const P = { area: 1, eff: 25, mount: "tracking", battery: 1000, usable: 80, dayLoad: 100, nightLoad: 50, days: 2 };

const r = P0.simulate(site, 0, 2, 0, P);
check(r.darkH === 24, `longest shadow is 24 h (got ${r.darkH})`);
check(r.soc[5] === 1000, "battery stays full while the panel (340 W) out-produces the load (100 W)");
check(!r.survives && r.minSoc === 0, "1000 Wh with 80% usable cannot cover 50 W x 24 h = 1200 Wh; it empties and stays at 0");
check(near(r.energyOut, 12 * 2 * 50 + 12 * 2 * 100, 1e-9), `2 days = 24 steps: 12 in shadow at 50 W, 12 in Sun at 100 W, 3600 Wh (got ${r.energyOut})`);
const mb = P0.smallest(site, 0, 2, 0, P, "battery", 0, 1e5);
check(near(mb, 1200 / 0.8, 0.01), `smallest battery = 1200 Wh / 0.8 = 1500 Wh (got ${mb.toFixed(3)})`);
check(P0.simulate(site, 0, 2, 0, { ...P, battery: 1500 }).survives && !P0.simulate(site, 0, 2, 0, { ...P, battery: 1490 }).survives,
  "1500 Wh survives, 1490 Wh does not");
check(!P0.simulate(site, 0, 2, 0, { ...P, battery: 0 }).survives, "no battery does not survive a shadow");
// daylight deficit: 0.2 m^2 gives 68 W < 100 W load; a big battery still makes it, so the smallest panel is 0
check(P0.smallest(site, 0, 2, 0, { ...P, battery: 1e5 }, "area", 0, 100) === 0, "with a huge battery no panel is needed for 2 days");
check(P0.smallest(site, 0, 2, 0, { ...P, battery: 100 }, "area", 0, 100) === null, "a battery smaller than the shadow load fails at any panel size");
check(near(P0.panelFactor("horizontal", 90), 1, 1e-12) && near(P0.panelFactor("tracking", 0), 1, 1e-12) &&
  near(P0.panelFactor("vertical", 0), 1 / Math.PI, 1e-12) && P0.panelFactor("horizontal", -3) === 0, "panel angle factors");

// panel orientation: a panel always facing the Sun takes the full sunlight; a vertical one cos(el); a flat one sin(el)
check(P0.panelFactor("facing", 70) === 1 && near(P0.panelFactor("tracking", 60), 0.5, 1e-12) && near(P0.panelFactor("horizontal", 30), 0.5, 1e-12)
  && P0.panelFactor("horizontal", -5) === 0, "panel factors: facing 1, vertical cos(el), flat sin(el), nothing below the horizon");
console.log(failed ? `\n${failed} failed` : "\nall passed");
process.exit(failed ? 1 : 0);
