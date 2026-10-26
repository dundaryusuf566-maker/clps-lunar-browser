# CLPS Lunar Mission Browser

NASA Space Apps Challenge 2026, *CLPS Lunar Mission Browser* challenge: a tool for comparing candidate landing sites and time windows. It consists of a modular Earth-Moon flight dynamics engine, a transfer database generated with it, an API for live design, and a web interface that ties them together.

The central question: **"I want to land at this site. If I launch on which day do I get there with the least Δv, after how long a wait in orbit, and with how much daylight?"**

*Türkçe: [README.tr.md](README.tr.md).*

## At a glance

**Pages of the website**

- **Browse and plan:** 1,830 Earth-to-Moon transfers of 2026 (full force model, JPL DE440), landing analysis for seven CLPS-relevant sites, a reverse-query mission planner ("land here between these dates with at least N days of sunlight").
- **Anywhere:** click any point of the Moon. The browser computes, hour by hour and with no server, the Sun and Earth in its sky, daylight, landing windows, Deep Space Network contact, eclipses, ground temperature and a power budget. Near the poles it uses LOLA terrain horizons and slopes. Everything can be downloaded as CSV.
- **Forecast: Griffin Mission One:** a forecast of when and where Astrobotic's Griffin-1 can land, registered in git before the launch.
- **3D view:** the Griffin-1 region on real LOLA terrain with shadows computed on the GPU, and a "journey" view of IM-1, IM-2 and Griffin-1 from launch to touchdown.
- **Validation:** every check below, passed or failed.

**How we test.** Every check has its pass criterion written into the code before the data it is judged on is seen. A failed check stays failed; analysis done afterwards is labelled as such and never replaces the registered result.

**Validation scorecard**

| Check | Result |
|---|---|
| NASA Ames reference (Genova et al. 2024 window), 195 transfers | **pass**: all converged, LOI band 805-982 m/s vs NASA ~797-980; January minimum 800.7 vs ~797 m/s (0.5%) |
| IM-1 Odysseus and IM-2 Athena retrodiction, 13 checks | **12/13 pass**: IM-1 landing 36 min from the real one, all real launch windows inside the predicted ones; IM-2's landing day comes out 1.02 days late with LOLA terrain (limit 1 day) |
| Blue Ghost Mission 1 retrodiction (6 checks) | **5/6 pass**; the landing chosen from the TLI day is 1.4 days late (limit 1 day) |
| Polar terrain against NASA Goddard's illumination map (2 sites × 25 pixels) | **pass**: median 0.2, max 3.6 percentage points (limits 3 and 8); correlation 0.98 / 0.998 |
| Polar map orientation from 12 named craters | **pass**, exactly one reading per pole |
| Regolith model vs Diviner at the equator | **pass**: 385.2 / 101.9 / 95.6 K vs 385 / 101 / 95 K |
| Regolith model vs Diviner at the south pole (12 points, 414 slots) | **fail**: median 21.4 K (limit 10 K); nights agree (−2.5 K), sunlit hours run ~30 K cold |
| Terrain light and heat vs Ingersoll et al. (1992) | **pass**: 170.76 vs 170.44 K (0.19%) |
| Browser vs engine: ephemeris, eclipses (NASA catalogue), horizons, temperatures | **pass** (Sun 0.00002°, 12/12 eclipses within 4.3 min, temperatures within 0.05 K) |
| Python test suite | 99 tests (3 need SPICE) |

## Quick start (Windows command line)

In the project folder (where `pyproject.toml` is):

```
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev,spice]"
python scripts/download_kernels.py
pytest
```

On macOS / Linux the `activate` line is `source .venv/bin/activate`.

**Build the database** (sweep → landing analysis → web data, one command):

```
python scripts/build_database.py --preset quick --spice
```

| Preset | Coverage | Transfers | Time (8 cores) |
|---|---|---|---|
| `quick` | January 2026, every 3 days, 4/5/6/8 days, both families | ~88 | a few min |
| `genova` | Dec 2025 - Mar 2026, 4-12 days, south family (NASA comparison) | 195 | ~5 min |
| `year2026` | all of 2026, every 2 days, 4/5/6/8/10 days, both families | 1,830 | ~30 min |

The sweep resumes where it stopped: if it is interrupted, run the same command again.

**Open the interface:**

```
python -m api.server
```

**LOLA terrain for the polar sites** (Malapert A, Mons Mouton; once):

```
python scripts/download_terrain.py
python scripts/build_horizons.py --spice
python scripts/build_database.py --preset year2026 --spice --skip-sweep
```

The first command downloads the LOLA elevation map (`LDEM_75S_120M`) and NASA's illumination map (`AVGVISIB_75S_120M`), ~233 MB. The second computes the horizon of every polar site, saves it as small JSON files under `engine/surface/horizons/` and compares it with NASA's map (a few minutes). The third redoes the landing analysis with the terrain horizon; the sweep is not repeated.

**Upcoming mission forecast (Griffin-1)**, once the terrain is in place:

```
python scripts/build_forecast.py --spice
python scripts/verify_forecast.py
python scripts/build_scene3d.py --spice
python scripts/build_journeys.py --spice
python scripts/build_thermal.py --spice
python scripts/build_ephemeris_table.py --spice
python scripts/check_polar_orientation.py --pole south
python scripts/build_horizon_grid.py --spice
python scripts/build_slope_map.py
```

For the north pole (optional, +116 MB download):

```
python scripts/download_terrain.py --north
python scripts/check_polar_orientation.py --pole north
python scripts/build_horizon_grid.py --spice --pole north
python scripts/build_slope_map.py --pole north
```

What each one does:

- **`build_forecast`** designs ~2,400 transfers and scans 1,681 points in the Mons Mouton-Nobile region (~25 min on 8 cores, resumable). It writes `web/public/data/forecast.json` with a timestamp and a SHA-256 digest. Commit and push this file to GitHub **before the launch**: the commit date is the public record that the forecast came first. `verify_forecast` checks that the file has not changed since.
- **`build_scene3d`** makes the **3D view's** data (`scene3d.json` + `scene3d.bin`, ~2 MB, 1-2 min): the region's terrain, hourly Sun and Earth directions, and the engine's reference values for the shadow self-check. Run it after the forecast, because it uses the forecast's top 10 candidates as check points.
- **`build_journeys`** makes the **3D journey's** data (`journeys.json` + `moon_cap.bin`, ~1 min). It designs no new transfers; it reuses the validation and forecast results under `data/cache`.
- **`build_thermal`** computes the surface temperature at the candidates and the sunlight the power calculator uses (`thermal.json`).
- **`build_ephemeris_table`** makes the **Anywhere** page's table (`ephem_moon.bin`, ~2 MB, hourly for 2024-2028; independent of the forecast, ~1 min).
- **`check_polar_orientation`** confirms with named craters which way round the polar map reads (below); `build_horizon_grid` refuses to run until it has passed.
- **`build_horizon_grid`** makes the LOLA horizon grid and the shaded relief map of a polar cap (~10 min, ~24 MB of tiles).
- **`build_slope_map`** makes the 240 m slope map of a polar cap (~8 s, 25.7 MB of tiles).

Putting the project on GitHub, publishing the site and registering the forecast step by step: [`docs/KAYIT.md`](docs/KAYIT.md) (in Turkish).

**Build the validation page** (NASA comparison + retrodiction of flown missions + test suite):

```
python scripts/sweep_transfers.py --start 2025-12-07 --end 2026-03-31 --step 3 --tofs 4 6 8 10 12 --families 1 --spice --out data/cache/genova.csv
python scripts/sweep_transfers.py --start 2026-01-05 --end 2026-01-13 --step 1 --tofs 4 4.5 5 5.5 6 6.5 7 --families 1 --spice --out data/cache/jan_minimum.csv
python scripts/build_validation.py --spice --tests
python scripts/diviner_polar_check.py --spice
python scripts/diviner_polar_diagnose.py --spice
```

The first two commands sweep the window of NASA's chart (195 transfers, ~5 min) and the January minimum (63 transfers, ~2 min); they do not touch the interface data. `build_validation` designs ~2,000 transfers for IM-1 and IM-2 (~20 min on 8 cores, resumable) and writes `web/public/data/validation.json`.

Open `http://localhost:8000` in the browser. The server serves the interface (`web/dist`), the database and the live design API; Node.js is not needed. To develop the interface, in a second window: `cd web`, `npm install`, `npm run dev` (address `http://localhost:5173`, API requests forwarded to 8000). Browser-side tests: `npm test`.

## Architecture

```
engine/
├── core/          time, constants, State, frames (incl. Moon-Sun frame)
├── ephemeris/     EphemerisProvider: Analytic (incl. IAU lunar orientation) | Spice (DE440, MOON_PA) | Cached (table)
├── dynamics/      ForceModel interface + models + DynamicsModel (combiner)
├── propagators/   propagate(), Trajectory, events (periapsis, impact, shadow, SOI, closest approach)
├── orbits/        Kepler elements, B-plane geometry
├── targeting/     Residual interface, Controls, TargetingProblem, Newton (active set) / LM
├── mission/       TLI -> LOI transfer designer, patched-conic initial guess, 3D journey
├── surface/       landing sites, Sun/Earth azimuth and elevation, LOLA horizons, horizon grid, slope map,
│                  landing opportunity analysis, regolith temperatures, terrain light and heat, DSN
├── database/      web export (transfers, landings, trajectories)
├── validation/    conservation residuals, forward-backward error, force budget,
│                  flown missions (IM-1, IM-2, Blue Ghost 1), retrodiction, NASA reference, Diviner reader
└── forecast/      upcoming missions (Griffin-1): timing forecast, region suitability scan
api/               dependency-free HTTP server: live design + interface
web/               React + Vite interface (see web/README.md); src/lib holds the browser-side physics
scripts/           build_database, build_validation, build_forecast, build_thermal, sweep_transfers, ...
data/              SPICE kernels, sweep CSVs, ephemeris tables, LOLA maps (not in git)
```

Units everywhere: km, s, km/s, km³/s². Epoch = TDB seconds past J2000. State = `[x, y, z, vx, vy, vz]`, J2000 inertial frame.

### Two core contracts

**`ForceModel`**: every physical effect is an independent module.

```python
class MyForce(ForceModel):
    name = "my_force"
    def acceleration(self, t, r, v, ctx): ...   # km/s²
    def potential(self, t, r, ctx): ...         # optional; if conservative, the energy test switches on

dyn.add(MyForce()); dyn.set_enabled("sun_third_body", False); dyn.breakdown(t, y)
```

Available models: `PointMassGravity`, `ZonalHarmonics` (J2-J7 for the Moon), `ThirdBodyGravity`, `SolarRadiationPressure`.

**`Residual`**: every targeted quantity is an independent module. `normalized = (measured - target) / tolerance`; |value| ≤ 1 means satisfied. `TargetingProblem(controls, residuals, simulator)` + `solve()`.

## TLI → LOI transfer designer

`design_transfer(eph, TransferSpec(tli_epoch, tof_days, lunar_inc_deg=90, family=+1))`

- Parking orbit + TLI → the Moon's sphere of influence → periselene; two-stage targeting (B-plane, then the true periselene).
- Controls: parking orbit RAAN and inclination (launch azimuth), TLI point, TLI Δv.
- Families: `+1` passes south of the Moon (South pass), `-1` north of it (North pass). They fly the same orbital plane in opposite directions.
- Outputs: TLI/LOI/total Δv, C3, v∞, RAAN (Moon-Sun), periselene latitude/longitude, the capture orbit's plane.

**Major lunar standstill:** in 2024-2026 the Moon's declination reaches ±28.5°; the designer raises the parking inclination to ~30° when needed and solves both families with no Δv penalty.

## Landing analysis

After LOI the orbital plane is almost fixed in space and the Moon turns under it once every 27.3 days. A site passes through the orbital plane twice a month; in between, reaching it needs a plane change. For every (transfer, site) pair a 30-day wait is scanned in 10-minute steps:

- Is the Sun in the site's window and rising (a morning landing keeps the daylight longest)? 3°-20° at the equator and mid-latitudes, > 0.5° at polar sites.
- Is the Earth above the horizon (direct communication during landing)? Far-side sites assume a relay.
- Is the plane change within budget (default 150 m/s)?

The earliest moment within 10 m/s of the cheapest option is chosen. Result: landing time, wait, plane-change Δv, landing Δv (estimate), total Δv to the surface, Sun and Earth elevation at landing, daylight after landing.

**Finding:** for equatorial sites the plane change needed drops from 1,500 → 800 → 85 m/s as the TLI date shifts by two days. The right launch date makes the plane change almost free; the RAAN (Moon-Sun) filter in NASA's tool captures exactly this.

**Sites** (`engine/surface/sites.py`, sources in the file): Tranquility Base, Mare Crisium (Blue Ghost 1), Reiner Gamma (IM-3), Mons Gruithuisen Gamma (Lunar-VISE), Malapert A (IM-1), Mons Mouton (IM-2), Schrödinger basin (APEX 1.0).

**Terrain (LOLA):** at the polar sites the Sun circles a few degrees above and below the horizon, and the surrounding mountains decide when a site is lit. `engine/surface/terrain.py` computes the horizon height for every site at every 0.5° of azimuth from LOLA's `LDEM_75S_120M` map: terrain out to 250 km, the Moon's curvature included, observer 2 m above the ground. The landing rule is unchanged (the Sun 0.5° up and rising); it is now measured against the real terrain horizon instead of a level one. Earth visibility and daylight after landing are also computed against the terrain. Sites without a horizon file keep a level horizon.

**Independent check of the terrain:** NASA Goddard's polar illumination map (Mazarico et al. 2011) gives, on the same grid and from the same LOLA map, the fraction of 18.6 years a pixel stays lit. `build_horizons.py` computes the same fraction with our own horizons and ephemeris at 25 pixels around each site and compares. The pass threshold was written into the code before the first run on real data (`engine/validation/illumination.py`): at every site median difference ≤ 3 and largest difference ≤ 8 percentage points. This check is fully independent of the IM-1/IM-2 test; it tests the horizon computation, the heights, the distance from the pole, the Sun's azimuth and the lunar orientation together. **Result (DE440, 2005-2023): pass** at both sites: Malapert A median 0.2, largest 3.6 points, correlation 0.983; Mons Mouton median 0.2, largest 3.0 points, correlation 0.998.

**Correction (v0.15):** an earlier version said here that this check also confirmed the map's orientation. That was wrong. Over 18.6 years the Sun goes round the sky evenly, so a mirrored or rotated map gives the same averages; in a synthetic test all four readings passed. The orientation is now tested with named craters: `python scripts/check_polar_orientation.py --pole south` (and `--pole north`). At each pole, the depth of six large craters spread around the pole (IAU coordinates) is measured for each of the four ways the map can be read; read correctly every one is a deep bowl, read wrongly the "floor" lands elsewhere. Criterion written before the real data: every crater at least 500 m deep and exactly one reading passing. On synthetic maps (both poles, all four true readings) it finds exactly the right reading every time (`tests/test_orientation.py`).

**Model limits:** terrain only at the polar sites (75°-90° maps); equatorial sites use a level horizon. The orbital plane drifts only under lunar J2; landing Δv is a simple model (15 km periselene, 6% losses, 60 m/s margin); in-orbit phasing (< 2 h) is ignored.

## Mission planner (in the interface)

The **Plan a mission** panel, opened by selecting a site, answers the reverse question: "Land at site X between dates A and B, with at least N days of daylight, waiting at most W days in orbit." Result:

- **Launch windows:** consecutive TLI dates that meet the conditions and how many days each window stays open (as fine as the database's date spacing, ±2 days for `year2026`).
- **Slip tolerance:** how many days the selected transfer's launch can slip and still meet the conditions.
- **Best launch dates**, sorted by Δv to the surface; click to open the transfer.

Example (analytic demo data, Malapert A, ≥ 7 days of light, ≤ 5 days of waiting): 12 windows in 2026, most open for 12-14 days; the April-June windows shrink to 8 days.

## Upcoming mission forecast: Griffin-1

Astrobotic's Griffin-1 mission (CLPS, last quarter of 2026, Falcon Heavy) is going to Nobile crater and the Mons Mouton region, where IM-2 landed; the goal is at least 5 days of surface operations. The exact landing point and date have not been published. The **Forecast** tab answers two questions:

- **When:** for every TLI day from 1 November 2026 to 28 February 2027, with the rules tested on IM-1/IM-2 (4-7 day transit, 80-100° orbit, landing within 4 days, the Sun 0.5° above the terrain horizon and rising, the Earth in view) and the announced 5-day sunlight requirement: the days a landing is possible and the launch windows. The reference point is Athena's touchdown point, because Griffin's has not been published.
- **Where:** for each of 1,681 points 2 km apart in an 80 × 80 km region: its own terrain horizon, landing moments, sunlight after landing, Earth visibility and slope. The criteria are those NASA used to select VIPER's site: illumination, Earth visibility, slope. The result is a ranked list and map of the places best suited by these criteria.

**Honesty rules:** announced facts are listed with their sources, our assumptions separately. The map does not say "Astrobotic will land here"; metre-scale boulders, the payloads' goals and the company's own rules are invisible on a 120 m map. The calibration from past missions is stated too: the terrain-aware rules found IM-1's real landing within 36 minutes and were 1 day late for IM-2 (same point). Forecast landing dates should therefore be read with up to ±2 days of uncertainty (the page derives this from the calibration data, rounded up).

## Ground stations, energy and shareable link

- **DSN visibility** (`engine/surface/ground.py`): for every landing moment, which of NASA's three Deep Space Network complexes (Goldstone, Madrid, Canberra) see the landing point above 10°. Earth orientation from IAU 1976 precession and mean sidereal time (nutation and polar motion neglected, error ~0.01°). Station coordinates from Wikipedia; the 10° mask is our assumption. The planner has a "landing in view of a DSN station" condition. Note: commercial missions may use their own ground stations besides the DSN (Intuitive Machines has its own network), so for past missions this is shown as information, not as a check.
- **Energy budget:** after landing, the share of the solar disc above the terrain horizon (100% = full Sun all the time) and the longest shadow. Default window in the planner: 5 days; in the Griffin-1 forecast one lunar day (14 days). Using 5 days in the forecast was meaningless: the landing rule already demands 5 days of uninterrupted Sun, so every point came out ~100% with 0 h of shadow. The 14-day window separates points by how early the first lunar night arrives and by terrain shadows; 14 days is our choice (an assumption), not an announced mission length. At the poles the terrain can hide the Sun for hours within a day; that is the number that sizes a battery. Panel orientation is unknown, so the visible share of the disc is used, not panel output.
- **Shareable link:** the selected site, metric, filters, planner conditions and selected transfer are kept in the address bar (`#browse?site=...&minsun=...`). "Copy link to this plan" copies a link that opens the same view.

## Anywhere on the Moon (the Anywhere page)

Click any point on the map (or enter latitude / longitude, or choose a known site). For the chosen period (30-365 days) the browser computes, hour by hour: the Sun's and the Earth's elevation and azimuth in the point's sky, sunrise / sunset and night lengths, landing windows (the light and communication rule the engine uses for every site: the Sun 3-20° above the horizon and rising, 0.5-90° at the poles; the Earth at least 2° up), which DSN stations (Goldstone, Madrid, Canberra, 10° mask) see the point, a "the Earth never rises, a relay is needed" warning on the far side, and eclipses (the Earth passing in front of the Sun; a sudden loss of power for a solar-powered lander). The link can be shared (`#anywhere?lat=..&lon=..&from=..&days=..`).

There is no Python behind the site: `scripts/build_ephemeris_table.py` writes the Sun's and the Earth's directions relative to the Moon and the Moon's orientation from DE440 into an hourly table (`web/public/data/ephem_moon.bin`), and the browser does the rest (`web/src/lib/sky.ts`, `siteAnalysis.ts`). When the table is built, the engine's own answers at 9 points (poles, CLPS sites, far side, limb) and 60 random moments are written alongside it (`web/tests/ephem_reference.json`); `web/tests/sky.check.mjs` compares the browser with them: Sun and Earth directions within 0.01° (worst 0.00011°), DSN masks identical. Eclipses are tested against NASA's catalogue: all 12 lunar eclipses of 2024-2028 must be found, the greatest eclipse within 15 minutes of NASA's (measured: 4.3 min at worst), and for umbral magnitudes above 0.5 the Sun fully covered as seen from the Moon's centre (needs the DE440 table; the analytic Moon is degrees off). `web/tests/site.check.mjs` tests against facts independent of our code: at the equator the Sun is up ~50% of the year, the lunar day is ~14.77 days, sunrises are a synodic month apart (29.27-29.83 days), the Earth is always up at the sub-Earth point, never on the far side, sometimes at the limb; every landing window obeys the rule.

**Real terrain at the poles: the horizon grid** (`engine/surface/horizon_grid.py`, `scripts/build_horizon_grid.py`). At both poles, from the pole to 75°, the LOLA horizon (1° azimuth, 2 m observer) of a point every 5 km on the polar stereographic plane is computed and written as tiles; the browser downloads only the tiles around the clicked point and blends the horizons of the four neighbouring grid points bilinearly. For speed the horizon uses the step schedule and map levels of the 3D view's shadows, tested there (120 m map to 15 km from the point, 360 m block means to 100 km, 1.2 km beyond): against the engine's full `compute_horizon` on a synthetic map, median 0.0000°, p95 0.01°, worst 0.07° (`tests/test_horizon_grid.py`), ~7 times faster per point. The error between grid points is measured, not assumed: at 300 random points of the cap the script compares the blended horizon with the point's own, both in degrees of horizon and as the number that matters to a lander, the share of 2026 with the Sun above the terrain; it gives the same number for a level horizon. The results go into the JSON and onto the page. On real LOLA (south, 300 points): the fast horizon differs from the full computation by a median 0.0°, p99 0.05°; with the blended horizon the Sun time is off by a median 2.5 and p90 11 percentage points, with a level horizon by a median 13.1 and p90 36. The grid is much better than a level horizon, but between grid points nearby terrain (crater rims and floors) gets mixed; the page shows these numbers. **A denser grid was tried:** at 2.5 km spacing (105,000 points, 85 MB) the same 300 points gave a median 1.5 and p90 7.5 points. The decision criterion was written before the trial: switch to 2.5 km if p90 drops below 6 points. It did not (7.5), so the grid stayed at 5 km (4 times smaller, 4 times faster). `web/tests/horizon.check.mjs` tests that the browser's blending is identical to Python's (within 10⁻⁵°) and that a click on the polar map inverts the projection correctly. The page has a horizon panorama, the terrain towards the Sun, and a switch to compare terrain with a level horizon.

**Which way round the map reads** (`scripts/check_polar_orientation.py`, `tests/test_orientation.py`): a polar map can be read four ways (x and y straight or mirrored); read wrongly, the terrain stands in the wrong directions around every point and the Sun disappears at the wrong times. The PDS projection document gives one formula, but its signs do not match our southern reading directly, so the orientation is tested, not assumed (method above). **Result on real data:** the south (+1, −1) and north (+1, +1) readings are the only ones of four that pass; read correctly the craters are 0.8-3.1 km deep, read wrongly at least one is shallow or a mound. The results are on the Validation page. North horizon grid (300 points): Sun-time error median 3.4, p90 15.0 points (level horizon 12.0 / 38.6); slightly worse than the south, the nearby terrain is rougher in the north.

**Ground temperature and power budget at any point** (`web/src/lib/regolith.ts`, `siteThermal.ts`, v0.17). The regolith model (below, Regolith temperatures) was ported to the browser line by line. The point's hourly sunlight comes from the table (the Sun's distance and elevation, the share of its disc above the horizon; the LOLA horizon where a polar grid covers the point, a level one elsewhere); the soil is spun up the way `build_thermal` does it (365 days of the point's own sunlight, 6 passes, then a 30-day lead-in) and the surface temperature over the period is plotted: lowest / highest / mean and the time below 150 K. The same hourly sunlight feeds the power budget calculator from the Forecast page (now one component on both pages); it can start at a landing window or at the start of the period. The default panel depends on latitude: vertical near the poles (low Sun), flat on the deck elsewhere, because at the equator a vertical panel gets almost nothing at noon. New option: a panel always facing the Sun (two-axis tracking). A year of spin-up takes ~0.3-0.6 s in the browser.

Tests (`web/tests/regolith.check.mjs`, criteria written into the file before the code was run):

1. Given the same sunlight, the browser and the engine must give the same temperature within 0.05 K. `scripts/build_regolith_reference.py` runs the engine on three made-up cases that need no ephemeris or map (the equator; a polar point with a low Sun and a horizon cutting the disc; a 5-hour eclipse in 5-minute steps) and writes `web/tests/regolith_reference.json`, kept in the repository; difference 10⁻¹³ K. `tests/test_regolith_reference.py` checks the file still matches the engine as it is (if the engine changes, a stale file is caught).
2. At the equator, Diviner's noon / midnight / pre-dawn values within 5 K (385.2 / 101.8 / 95.6 K).
3. With the DE440 table and a DE440 `thermal.json`, the browser's whole chain (table, Sun, spin-up, model) against `build_thermal`'s flat-ground point every 2 h over the landing period: largest difference ≤ 1.0 K, mean absolute difference ≤ 0.2 K. **Result (DE440): pass**, largest 0.05 K, mean 0.025 K over 1,717 samples.

Reported alongside, not counted: at the candidates, the browser with level ground and the grid horizon against `build_thermal`'s direct-sunlight result (each point's own 0.5° LOLA horizon and tilted ground). The difference was **large**: 11-84 K on average (median 32 K), the hottest value off by −66 to +40 K. `python scripts/thermal_attribution.py --spice` (~2-5 min) separates the causes: the engine is run five ways at the same points (own / grid horizon × tilted / level ground, plus the grid horizon with a 240 m slope map) and each is compared with the engine (own horizon, tilted). **Decision rule, written before the run:** the 240 m slope map is added to the browser only if it brings the median error to at most half of the level-ground error and to 15 K or less.

**Result (DE440, 11 points, median of the mean |ΔT|):** own horizon + level ground 26.7 K (the tilt alone), grid horizon + true tilt 10.5 K (the horizon alone), grid horizon + level ground 32.2 K (the old browser), grid horizon + 240 m slope map **14.8 K**. Sanity check held: the script's engine version reproduces `thermal.json` within 0.025 K at every point. The rule was met (32.2 → 14.8 K, below 16.1 and below 15 K, close to the 15 K limit), so the slope map was added. The tilt is the larger effect overall, but on ridge points the horizon still dominates: at Candidate 1 the grid horizon shows the Sun for 63 hours instead of 8,325 and the error stays at 81 K; Candidate 4, 46 K. The 240 m block's normal sometimes differs a lot from the point's own (Candidate 9: 16.5° instead of 8.4°), which is why the slope map is worse than the true tilt; blending neighbouring blocks might help, but it would be chosen after seeing the result, so it was not tried.

**Polar slope map** (`engine/surface/slope_map.py`, `scripts/build_slope_map.py`): for each 2 × 2 pixel block of the 120 m map, `build_thermal`'s `local_normal` at the block's centre, stored as its local east / north components in int16 (0.002° resolution) tiles (`web/public/data/slope_map_s/`, to 80°, 25.7 MB per pole, ~8 s; `--min-lat 75` doubles it). The script compares the stored normals with freshly computed ones at 300 random points and at the candidates (limit 0.01°, exit code 2 if exceeded): worst 0.0012° at both poles. `web/tests/slope.check.mjs` tests that the browser decodes the same normal as Python (within 10⁻⁶°); `tests/test_slope_map.py` that the normals are exactly `local_normal` and that a uniformly tilted map gives back its tilt. **New registered check** (`regolith.check.mjs` 4, written before it ran on data): with the slope map and the grid horizon, the browser must reproduce the script's slope-map version at every candidate: mean error, lowest and highest temperature within 0.5 K. **Result (DE440, LOLA): 11 of 11 pass**, all within 0.02 K (e.g. Mons Mouton: error 5.25 / 5.26 K, lowest 62.8 / 62.8, highest 194.9 / 194.9 K). The slope map does not improve every point: Candidates 8 (10.9 → 13.8 K) and 10 (11.7 → 12.4 K) get slightly worse, and at Candidate 9 the block's slope (16.4°) exceeds the point's (8.4°), so the highest temperature comes out 276 K against the engine's 243 K. The median improvement was judged by the registered rule; these individual deviations are stated with numbers.

In short: the browser's temperature equals the engine's on level ground; near the poles, with the slope map, the median error is ~15 K but **ridge points are still rough**. The page says so with numbers and points to the Forecast's calculation for the candidates. Near the poles the Sun hours and landing windows are the firmer numbers (the grid error is measured above). At low latitudes the Sun is high and a few degrees of slope matter little; there the Diviner equator check applies.

Left out of the browser's temperature (stated on the page): the point's own horizon (near the poles it is blended from the 5 km grid), the tilt of the ground below 80° latitude (taken as level), and the light and heat from the surrounding terrain. The Forecast page has all three for the candidates. The ~30 K cold bias in sunlit polar hours found against Diviner (below) applies here too.

**CSV export** (`web/src/lib/csvExport.ts`, v0.18): the page's numbers can be downloaded as two files. Hourly series: time (UTC), the Sun's elevation / azimuth / the horizon in that direction, the share of its disc above the horizon, sunlight on a Sun-facing surface (W/m²), the Earth's elevation / azimuth / horizon, DSN stations in view, surface temperature. Events: daylight periods, landing windows and eclipses in time order. The `#` lines at the top of each file state the point, the period, the ephemeris, the kind of horizon and ground, the landing rule, the assumptions and a link to the same view, so a file that leaves the page still says where it came from (pandas: `read_csv(..., comment="#")`). `web/tests/csv.check.mjs` tests that every number in the files is the page's own, that the hours line up with the temperature run, and that the event counts match the page.

Limits (stated on the page): below 75° the horizon is level for now; the landing window does not include a transfer or the orbit plane (those are in Browse and plan); eclipses are geometric (the atmosphere widens the real shadow by ~2%).

## 3D view

The second scene of the **3D view** tab (**Landing region**) shows the Griffin-1 region on real LOLA terrain, with the Moon's curvature and the Sun of any hour of the forecast period (raw WebGL2, no extra library). Two cameras: **Overview** (above the region; rotate / zoom / pan, click the terrain to pick a point) and **Lander's eye** (a 360° view from 2 m above the chosen point: the horizon, the Sun's and the Earth's paths over ±15 days, the Earth's phase). With the time slider and "Play" the shadows can be watched crossing the mountains over a lunar day; the forecast's windows and every candidate's best landing moment are one click away. The forecast map's layers (sunlight after landing, energy, slope...) can be draped over the terrain. The link (camera, time, point, layer) is kept in the address bar.

**Shadows are computed, not painted.** For every map cell the GPU marches a ray towards the Sun and finds the highest terrain angle along the way; the method is the same spherical geometry as `compute_horizon`, the same starting distance (180 m), the same observer height (2 m). The share of the solar disc above the terrain then follows from the energy budget's formula, so penumbrae are physical too. The terrain is made of three rings: the region at 120 m (full LOLA resolution), to 100 km at 360 m, to 250 km at 1.2 km (block means). The middle ring was added deliberately: with 1.2 km straight from 41 km out, distant hills flattened and the error doubled.

**The page checks itself.** On opening, at 11 points (Athena's touchdown point and the top 10 candidates), every 3 hours over the landing period, the shadow computed on the browser's GPU is compared with the engine's full-resolution horizon masks (0.5° azimuth, 250 km, 120 m steps) and the result is written on the page. The numpy version of the same algorithm (`engine/surface/scene3d.py::march_sun_clear`) is tested against `compute_horizon` in the test suite; when the scene is built the same comparison is printed to the terminal, so the browser's result can be compared with it. During development, on synthetic terrain (real LOLA data was not available in that environment): lit / shadowed decision 100% identical, Sun elevation difference median 0.003°, p95 0.015°; GPU and numpy agree. The numbers on real terrain appear in the terminal and on the page once the scene is built from the LOLA map. The remaining difference comes from the coarse outer rings.

**What is real and what is drawn:** terrain, curvature, Sun / Earth directions, shadows, disc share, the angular sizes of the Sun's and the Earth's discs and the Earth's phase are real; there is no vertical exaggeration. Surface brightness is a simple matte model (not the regolith's real reflectance), shadows are lit very slightly so the terrain stays visible (in reality they are almost black), and the glow around the Sun is for visibility. Things smaller than 120 m (boulders, small craters) are invisible; beyond 250 km the Moon is drawn as a smooth sphere. In Lander's eye the engine's horizon mask is drawn as a pink line over the terrain; the silhouette of the drawn terrain should match it.

### 3D journey

The first scene of the **3D view** tab shows a mission from start to end on a single clock: parking orbit, TLI, the trip to the Moon, lunar orbit insertion (LOI), waiting in lunar orbit, the plane change, descent and touchdown. Three missions: **IM-1** and **IM-2** as reconstructed (real TLI date and transit time, the polar orbit needing the smallest plane change for the real landing moment, landing at the real moment; the reconstruction on the Validation page) and **Griffin-1** with the best launch of the registered forecast's first window. Three cameras: Earth and Moon (the whole journey, the Moon's own path), around the Moon (approach hyperbola, the orbit and the Moon turning under it), following the spacecraft. In "Auto" playback the speed slows near events. Green lines are DSN stations seeing the spacecraft above 10° at that moment; the Earth's rotation comes from the engine's ground station model. Earth and Moon are to scale.

**Where each part comes from** (`engine/mission/journey.py`):

- Parking orbit and the trip to the Moon: the transfer the engine solved, re-propagated from the stored controls with the full force model (the same path as the transfer view).
- Lunar orbit: the model the landing analysis uses, a circular orbit with J2 nodal drift. The analysis does not model the spacecraft's position along the orbit (its phase), so the drawing spreads the phase correction that brings the craft over the site at landing across the wait, and states its size on the page (~3% of the orbital motion for IM-1, ~1% for the others).
- Plane change: the analysis counts one instantaneous burn; the drawing turns the plane over the last revolution. Angle and Δv are the analysis's (within 0.02° in the test).
- Descent: **schematic.** A half-ellipse from the orbit down to 15 km (the analysis's descent model) and a braking arc to the site; its Δv is the analysis's, its path and timing are illustrative.
- The Moon's south pole from the LOLA map (~1.9 km blocks), lit without shadows in this view; the real shadows are in the Landing region scene.

The real missions made trajectory correction and phasing burns; these paths are the engine's model, not the flown trajectory. The page says so.

## Regolith temperatures

`engine/surface/thermal.py` is an independent implementation of the Hayne et al. (2017) regolith model (JGR Planets 122, [arXiv:1711.00977](https://arxiv.org/abs/1711.00977), Appendix A and Table A1). One-dimensional heat conduction into the ground:

- density and contact conductivity rise exponentially with depth (ρ 1100 → 1800 kg/m³, k 7.4·10⁻⁴ → 3.4·10⁻³ W/m/K, H = 0.06 m),
- radiation between grains: k(T) = k_c [1 + χ (T/350 K)³], χ = 2.7,
- heat capacity a 4th-degree polynomial in temperature (Hemingway et al. 1981),
- albedo rising with incidence angle: A(i) = 0.12 + 0.06 (i/45°)³ + 0.25 (i/90°)⁸ (important at the poles, where the Sun always comes in low),
- surface: εσT⁴ = (1 − A) S cos i · f + k ∂T/∂z (ε = 0.95, S = 1361 W/m²); at the bottom the Moon's interior heat flow, 0.018 W/m².

All constants are the paper's standard values, not tuned here. What we add is the solar input: the ephemeris's Sun distance and direction, the ground's tilt from LOLA (240 m), and f, the share of the solar disc above the LOLA horizon (the same number as in the energy budget). Numerics: a geometrically growing grid as in Hayne (first layer a tenth of the diurnal skin depth), a stability-limited explicit time step, the surface temperature from the energy balance by Newton's method; the deep layers are spun up over a year with accelerated equilibration (Aitken extrapolation after each pass).

**Validation:** for level ground at the equator, LRO Diviner's typical values (Vasavada et al. 2012, in Hayne et al. 2017): noon ~385 K, midnight 101 K, just before sunrise 95 K. Model: 385.2 / 101.9 / 95.6 K (5 K tolerance). The tests also check exact results: in soil of constant properties the daily wave decays with the skin depth (0.3%), radiative balance at noon (1.5 K), absorbed + interior heat = emitted over a lunar day (1%), halving the grid and time step changes the result by less than 1 K.

**Light and heat from the terrain (multiple reflection)** (`engine/surface/radiosity.py`): besides the direct Sun, a point receives the sunlight reflected and the infrared emitted by the terrain it sees; in shadow that is the only heat source. Two tools:

- **Radiosity between surface facets:** view factors (F_ij = cos θ_i cos θ_j A_j / π r²) and equilibrium with all reflections: B = α(E + FB) for visible light, W = (1 − α)(E + FB) + εFW for infrared (W = εσT⁴). Tested against the closed formula for the temperature in the shadow of a spherical bowl-shaped crater (Ingersoll, Svitek & Murray 1992): 170.76 K against 170.44 K (0.19%; with ε = 1, 0.007%; the remaining difference is how the formula treats infrared absorption).
- **Direction sampling for a single point** (used for the candidates): every direction in which the point sees terrain (below the LOLA horizon, above the plane of its own tilted surface) is followed to where it hits the terrain; that point's sunlight (with its own horizon) and temperature (with the same regolith model) are computed, and the light and heat it sends back are summed with weights (cos θ dΩ / π). One bounce: light the terrain receives from other terrain is not counted; the share this leaves out is given for a bowl with view factor f by `single_bounce_ratio` (at most ~2.4% at the candidates on synthetic terrain). On the same bowl, on a 120 m map, the flux reaching the shadowed floor deviates by 1.5% from the single-bounce closed formula.

Result (on synthetic terrain; the real values come with LOLA): candidates on ridges and plateaus see terrain in only 0.01-2.4% of their sky, and since their surroundings are dark at night too, their lowest temperatures change by < 1 K. At a point in a hollow (2.3% of the sky is terrain, itself in shadow while its surroundings are lit) the lowest temperature rose from 31 K to 41 K. This term matters in shadowed places, not on sunny ridges.

**Forecast page:** for the reference point and the top 10 candidates, the surface temperature over the landing period, the lowest / highest value in the 14 days after the best landing moment and the hours spent below 150 K; for comparison, the reference point as "level ground, no terrain" (the difference is the effect of slope and terrain). The table also shows the terrain's view factor and the lowest temperature with "Sun only". This analysis was made after the forecast was registered; it is not part of the registration.

**Against Diviner at the pole** (`scripts/diviner_polar_check.py`, `engine/validation/diviner_pcp.py`): the equator check uses three typical numbers; the pole is what matters. Diviner's south polar cumulative products (Williams et al. 2019, PDS Geosciences) give, poleward of 80° S, every 240 m cell's mean bolometric temperature between July 2009 and February 2019 by local time (96 slots) and season (summer / winter). The files are ~200 MB of fixed-length rows, so they are not downloaded whole: a cell is read by binary search with HTTP range requests (~16 small requests per point over one kept-alive connection, a single block read once the search is down to the last 256 rows, points in the same file share what has been read, 4 files at a time). Failed requests are retried 6 times with increasing pauses. The file's sort order and x/y projection are not assumed but derived from sample rows and checked; if they do not hold, the script refuses to run. For the reference point, the top 10 candidates and IM-1's Malapert A point, every 4th local-time slot and both seasons are read (48 files, cached in `data/cache`). The model is run at the same points over the same years (hourly, DE440, LOLA horizon and slope, one year of spin-up) and averaged into the same local-time / season slots radiatively (T = ⟨T⁴⟩^¼). **Pass criterion, written into the script before any Diviner value was read:** median |model − Diviner| ≤ 10 K over all points, seasons and slots. Not in the model: roughness below 240 m (lit and shadowed patches within a cell, which raise the measured bolometric temperature at low Sun) and terrain light / heat (< 2 K at these points).

**Result (DE440, LDEM_75S_120M, 12 points, 414 slots): FAIL.** Median |model − Diviner| 21.4 K (criterion 10 K). IM-2's Mons Mouton point is within the criterion at 5.0 K; IM-1's Malapert A point 14.4 K (bias −4 K); the candidates 13-48 K. The criterion was not changed; the result stands on the Validation page as a failed check.

**After the check: where the difference comes from** (analysis after the data were seen, not part of the registration). Splitting the same comparison by whether the model and Diviner see the point as lit (> 150 K) or dark (< 100 K):

| Model and Diviner | Slots | Model − Diviner (median) |
|---|---|---|
| Both in shadow / at night | 175 | −2.5 K |
| Both in sunlight | 115 | −28.7 K |
| Model in shadow, Diviner's cell warm (> 120 K) | 39 | −85.6 K |
| Model in sunlight, Diviner's cell cold | 0 | – |
| In between (sunrise / sunset, partial shadow) | 85 | −50.2 K |

At night and in shadow the model follows Diviner closely: the heat stored in the regolith and the night-time cooling are right (the part that sets the heater load in a power budget). The difference comes with the Sun: when both are sunlit the model is colder (less so at Malapert A at 80° S, where the Sun is higher), and in 39 slots Diviner's cell has warmed up while the model's point is still behind the terrain; never the reverse. Possible explanations: a partly lit cell (its warm part dominates the radiative average), roughness below the 120 m map, the albedo law fitted at the equator. None was tuned.

`python scripts/diviner_polar_diagnose.py --spice` (after the check, ~15-25 min) tests the first explanation: Diviner's number is the radiative average of a 240 m cell, while the registered check ran the model at a single point. The diagnosis reads each point's own cell (the one nearest to the point across all files; where a file had no data in that cell the check had used a neighbour, and those slots are left out here) and its centre from the archive, checks that the temperature read matches the cached one, runs the model at 3 × 3 points spread over the cell (80 m apart, each with its own LOLA horizon and slope) and averages them the same way. No free parameters. For fairness the point model is also given over the same slots. The result goes to `diviner_polar_diagnostics.json` and is shown on the Validation page under the registered result, separately; it does not change the check.

**Result of the diagnosis (DE440, LDEM_75S_120M): this explanation did not hold.** Over the 410 slots that use each point's own cell, the median |model − Diviner| is 21.7 K with the point model and 23.5 K with the model spread over the cell. In sunlight −29.0 → −32.5 K, "model in shadow, Diviner warm" −85.6 K (39 slots) → −73.5 K (34 slots), night / shadow −2.5 → −2.0 K. The within-cell differences a 120 m map can show do not close the gap. What remains is what the map cannot resolve: roughness below 120 m, the albedo law fitted at the equator, and a horizon wrong by a fraction of a degree at sunrise / sunset. These were not tested.

**Consequences for the project:** night and shadow temperatures (the part that sets the heater load in a power budget) agree with Diviner. At 85° S, sunlit temperatures are most likely underestimated by ~30 K. The Griffin-1 forecast ranks by sunlight and terrain, not temperature; it is not affected.

**Power budget** (Forecast and Anywhere pages, `web/src/lib/power.ts`): Astrobotic has not published Griffin's power system, so this is a calculator, not a forecast. The user enters the panel area, efficiency, mounting (vertical turning to the Sun, fixed vertical, flat, always facing the Sun), battery capacity and usable share, and the power drawn in sunlight and in shadow; the engine supplies the sunlight reaching the point: S/r² from the Sun's distance, the share of the solar disc above the LOLA horizon and the Sun's elevation, from the best landing moment on, in 2-hour steps on the Forecast page (`build_thermal` writes them as `dni_w_m2` and `sun_el_deg`) and hourly on the Anywhere page. The battery charge is tracked step by step; if it falls below the usable limit the result is "does not get through" and when. The smallest battery that gets through (with these panels) and the smallest panel (with this battery) are found by bisection on the same simulation. No battery / wiring losses; the heater load in shadow is the user's input (it depends on insulation; the ground temperature is only a hint). The defaults are generic, not Griffin's. `build_thermal` also checks for every point that the Sun is above the terrain at its best landing moment: the forecast's landing rule requires it, so if it fails the forecast and the temperature run used different terrain / horizon settings, and both the output and the interface warn.

## Ephemeris

- `AnalyticEphemeris`: no files; lunar orientation from the full IAU 2009 model (~0.03° from DE440), circular lunar orbit (for demos).
- `SpiceEphemeris`: JPL DE440 + MOON_PA. Use this for results.
- `CachedEphemeris`: hourly Hermite table (format v2: lunar rotation included). Moon position ~1 cm, meridian 0.000001°; roughly halves the time per transfer. Shareable as `.npz`:

```
python scripts/build_ephemeris_cache.py --spice --start 2025-11-01 --end 2026-12-31
python -m api.server --ephem-cache data/cache/ephem_spice_2025-11-01_2026-12-31.npz
```

## API

`python -m api.server [--port 8000] [--workers 2] [--spice | --analytic] [--ephem-cache ...]`

| Endpoint | |
|---|---|
| `GET /api/health` | status, ephemeris |
| `GET /api/sites` | site catalogue, default constraints |
| `POST /api/transfers` | `{tli_utc, tof_days, family, lunar_inc_deg, periselene_alt_km}` → `{job_id}` |
| `GET /api/jobs/<id>` | `queued / running / done / error`; the result holds the transfer, the trajectory and the landing analysis for all sites |
| `POST /api/trajectory` | recomputes the path of a database transfer from its controls |

A transfer design takes ~4-7 s; jobs run in parallel in separate processes. The published GitHub Pages site is static and does not use the API; live design needs the local server.

## Validation

The interface's **Validation** tab (`http://localhost:8000/#validation`) shows all of the validations below together with the temperature model's checks.

**1. NASA Ames comparison (DE440, the window of Genova et al. 2024):** 195/195 transfers converged; LOI band 805-982 m/s (NASA ~797-980). Monthly minima 0-2 days from NASA's chart (our sweep is every 3 days). In a dense sweep of 5-13 January 2026 the minimum is **800.7 m/s** (TLI 10 January, 5.0 days), NASA's ~797 m/s: 0.5% apart. NASA published a chart, not data, so the reference values were read off the chart (date ±1.5 days, Δv ±3 m/s), `engine/validation/nasa_reference.py`.

**2. Retrodiction of flown missions** (`engine/validation/retrodiction.py`, `scripts/build_validation.py`). The tool is given only the site, the launch and LOI times and the orbit altitude; when and how the landing happened is not given. Sourced mission data in `engine/validation/missions.py`.

IM-1 Odysseus (February 2024, Malapert A), with JPL DE440:

| Question | Tool | Reality |
|---|---|---|
| January 2024 launch window | 7-20 January (14 days) | 12-14 January (first plan) |
| February 2024 launch window | 6-19 February (14 days) | 14-16 February, launched on the 15th |
| Landing after the 15 February launch | **22 February 22:48 UTC** | 22 February 23:24 UTC (36 minutes apart) |
| Sun at landing | 10.5°, rising, 6.5 days after sunrise | |
| Daylight after landing | 9.3 days (level horizon) | operated 6 days (had tipped over) |
| LOI Δv (real TLI + 6.35-day transit, 92 km) | 824 m/s | 800 m/s (3.0% apart) |

IM-2 Athena (March 2025, Mons Mouton), with JPL DE440:

| Question | Tool | Reality |
|---|---|---|
| Launch window | 22 February - 6 March (13 days) | 26 February - 1 March, launched on the 27th |
| Landing after the 27 February launch, level horizon | 4 March 20:04 UTC | 6 March 17:29 UTC (1.9 days early) |
| Landing after the 27 February launch, LOLA terrain | 7 March ~17:54 UTC | 6 March 17:29 UTC (1.02 days late) |
| Sun at landing | 2.5°, rising, 2.4 days after sunrise | |
| Real arrival, real landing moment | landable: 52 m/s plane change in a polar orbit, 4 m/s at 92° | |
| LOI Δv | 832 m/s | not published |

Findings:

- **Illumination sets the windows.** A polar site is suitable for landing ~2 weeks a month and unsuitable ~2 weeks; all three real windows fall inside the predicted ones.
- **The orbit inclination is a free design variable.** With an exactly polar (90°) orbit, landing after the 15 February launch is impossible, because Malapert A stays 8.6° from the orbit (245 m/s). Tilting the orbit by a few degrees (80-86° or 94-100°) brings the site under the ground track at the real landing moment and changes the LOI Δv by no more than 2 m/s. That is why the retrodiction scans 80-100°.
- **12 of 13 mission checks pass.** The one that fails is IM-2's landing day. With a level horizon the tool landed 1.9 days early; with LOLA terrain the error changed sign and is now 1.02 days late, exceeding the one-day limit by ~25 minutes. The terrain delays the Sun at the site a little, and the tool, taking the cheapest option, slips to the next day. We did not move the threshold to fit the result; the check stays failed. The real landing moment is a landable moment with the terrain too. The IM-1 LOI check passes the 3% limit by a hair (2.97%).
- With the analytic ephemeris the same test gives 11/13 (LOI off by 5%). The difference comes from the Moon's real, elliptical orbit.

**Blue Ghost Mission 1 (Firefly, March 2025, Mare Crisium):** the first non-polar retrodiction (`engine/validation/missions.py`, `BG1`). The tool again gets only what was published: launch (15 January), TLI day (8 February; its time was not published, noon UTC ±12 h assumed), lunar orbit insertion (14 February 01:53 UTC), a ~100 km orbit and the 16-day orbit check-out Firefly announced at LOI (the tool may wait up to 20 days; its rule still picks the earliest suitable moment). The orbit inclination was not published, so 22-158° is scanned. Near-side rule: the Sun 3-20° above the horizon and rising, the Earth at least 2°. The launch window question is meaningless for this mission (25 days in Earth orbit between launch and TLI); the page says so and that check is not added. A new check: **sunset.** Firefly's reported 346 hours of surface daylight and the last data arriving "5 hours after night began" put the real sunset at 16 March ~18:30 UTC (±20 min); the sunset predicted with a level horizon must be within 3 hours (criterion written before the first run: an unaccounted 1° horizon shifts sunset by ~2 hours at this latitude). `python scripts/build_validation.py --spice --missions blue-ghost-1` (~15-25 min). **Result (DE440): 5 of 6 checks pass.** At the real landing the Sun is 3.4° and rising, 7 hours after local sunrise (the near-side rule's lower limit is 3°); the Earth 25.7°; the real landing moment is landable from the reconstructed arrival with a 23 m/s plane change (best inclination 62°, chosen afterwards); our sunset 20:13 UTC, the real one ~18:30 (+1.7 h, limit 3 h; a late prediction with a level horizon is consistent with terrain to the west, but not tested). **The failing check: the landing the tool chooses itself from the TLI day** is 3 March 18:19 UTC, 1.4 days after the real one; the criterion was 1 day, it stays FAIL. Diagnosis afterwards (does not change the check): the TLI-day scan tries 4-7 day transfers and 5 inclinations 30° apart and takes the option with the least Δv; for a near-side site the time the orbital plane passes over it depends strongly on the inclination, and on this coarse grid the cheapest option falls on the next pass (3 March). With the real transfer time and inclinations scanned every 4°, the first landing opportunity at the best inclination is 2 March 07:43 UTC, 51 minutes before the real landing; but that inclination was chosen knowing the answer, so it does not count as a check.

**3. Diviner polar comparison:** above, in the Regolith temperatures section. `python scripts/diviner_polar_check.py --spice` (needs the network, ~5-10 min, ~15 MB of traffic). It does not crash if the connection drops: what has been read is saved to `data/cache/diviner_pcp_points.json` and the same command continues from the remaining files (if problems persist, `--workers 2`).

**4. Test suite:** `pytest` (or `python tests/run_all.py`): 99 tests, all pass with DE440 installed (without it 3 are skipped). Browser-side: `cd web && npm test` (power budget, sky, site analysis, horizon grid, regolith, slope map, CSV export).

| Test | What it proves |
|---|---|
| Two-body period closure, energy < 1e-11 | integrator accuracy |
| Zonal acceleration = −∇U, energy conservation in the lunar zonal field | harmonic formulas (J2-J7) |
| J2 nodal regression within 2% of the analytic formula | dynamics physically right |
| Third-body tidal limit, SRP, force budget sum | force models and the combiner |
| Event timing, forward-backward error | event detection, numerical stability |
| Shooting (Newton + LM), underdetermined problem, active set | targeting layer |
| B-plane geometry, conic guess, full TLI → LOI | mission chain end to end |
| Cache: exact at nodes, < 1 m, save/load, transfer result unchanged | ephemeris cache |
| IAU rotation orthonormal, sidereal day, the same face of the Moon towards the Earth | lunar orientation |
| Subsolar point at 90°, Earth always below the horizon on the far side, sunrise every 29.53 days | surface geometry |
| Finds a planned dawn opportunity, failure reasons right | landing analysis |
| Sun low and rising at the IM-1/IM-2 landings; IM-2's arrival can land at the real moment; window grouping | retrodiction |
| Synthetic LOLA grids: label parsing, projection orientation, horizon = slope angle on a level sphere, a known mountain in the right direction and height, terrain delays sunrise, the two azimuth computations agree | terrain |
| Map orientation from named craters, both poles, every reading | orientation |
| Fast horizon against `compute_horizon`, grid interpolation | horizon grid |
| Slope map normals = `local_normal`, storage within 0.005°, a tilted plane's tilt | slope map |
| Earth rotation (the Sun at equinox noon), how often the DSN sees the Moon, (with SPICE) comparison with IAU_EARTH, energy and shadow time | ground stations, energy |
| Mission record (announced / assumed kept apart), 5-day Sun requirement, landing moment rules, slope, ranking, the record digest catching a change | forecast |
| 3D scene: map cuts and block means, projection, the numpy version of the GPU ray march against `compute_horizon` (full resolution median < 0.01°, with the coarse outer rings < 0.03°), early exit not changing the result | 3D shadows |
| 3D journey: continuity and order, lunar orbit in the analysis's model (radius, plane-change angle and Δv the same as the analysis, small phase correction), touchdown at the site at the landing moment (< 1 m), attitude quaternions | journey |
| Regolith heat model: Diviner equator temperatures (±5 K), decay of the daily wave with skin depth, radiative balance at noon, energy conservation over a lunar day, grid / time-step convergence; the browser's reference file matches the engine | temperature |
| Terrain light and heat: a bowl crater mesh catches all the sunlight, sphere view factor f, radiosity against Ingersoll's formula (ε = 1: 0.5%, ε = 0.95: 1%), single-point sampling in a bowl on the map against the single-bounce formula (6%), diffuse albedo | multiple reflection |
| Diviner polar file reader: on a synthetic table, row format, sort order and projection found from sample rows, binary search finding the right cell, "none" where there is no data; over real HTTP, reading through a server that drops connections and returns 503 still gives the same result, a single connection reused, a server ignoring range requests refused; the cell's own x/y read and the inverse projection giving back latitude/longitude | Diviner reading |
| Design job over real HTTP, validation errors, access outside the folder blocked | API |
| (with SPICE) cache and IAU model against DE440 | with real data |

## Roadmap

1. ~~Engine core, ephemeris, targeting, validation~~
2. ~~TLI → LOI designer, SPICE, ephemeris cache~~
3. ~~Landing sites, illumination, Earth visibility, landing opportunity analysis~~
4. ~~Database pipeline, live API, interface~~
5. ~~Validation page, IM-1/IM-2 retrodiction, mission planner (slip tolerance, reverse query)~~
   - 5b. ~~Registered forecast for Griffin-1: timing and region suitability map~~
   - 5c. ~~DSN ground station visibility, polar energy budget, shareable planner link~~
   - 5d. ~~3D view: real terrain, GPU shadows computed like the engine's, astronaut camera, self-check against the engine~~
   - 5e. ~~3D journey: IM-1, IM-2 and Griffin-1 on one clock from launch to touchdown, DSN links~~
   - 5f. ~~Regolith temperature model (Hayne et al. 2017), validation against Diviner, surface temperature at the candidates~~
   - 5g. ~~Reflected light and infrared from terrain: radiosity (tested against Ingersoll 1992) and single-bounce direction sampling for the candidates~~
   - 5h. ~~Power budget calculator; the regolith model against Diviner measurements at the south pole (criterion fixed in advance)~~
   - 5i. ~~Anywhere: ground temperature and power budget at any point of the Moon, in the browser (the engine's model to 10⁻¹³ K); polar slope map; CSV export~~
6. ~~Terrain: LOLA horizon masks (real illumination at the polar sites)~~; next: landing ellipse
7. Elliptical / frozen capture orbits, GRAIL full gravity field
8. Propagating the capture orbit for 30 days with the full model (plane drift)

## License

Code: MIT ([LICENSE](LICENSE)). The fonts in `web/public/fonts` keep the GUST Font License. The data products the engine reads or derives from (JPL DE440, LRO LOLA and Diviner) come from NASA and JPL public archives; sources are named in the sections above.
