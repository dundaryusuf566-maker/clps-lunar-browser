# Interface (React + Vite)

*Türkçe: [README.tr.md](README.tr.md).*

The web application that shows the transfer database and landing analysis the engine produces. It reads the JSON files under `public/data/`; when the engine server is running it uses it for live design and missing trajectories. The Anywhere page does all of its physics in the browser (`src/lib`).

## Running

**To use it**, no Node.js is needed. In the project's main folder:

```
python -m api.server
```

`http://localhost:8000` serves the interface (`web/dist`; build it once with `npm run build`, or take it from the GitHub Pages workflow), the database and the API.

**To work on the interface** (Node.js 20+):

```
python -m api.server          (first window, in the project's main folder)
cd web
npm install
npm run dev                   (second window; http://localhost:5173, forwards /api requests to 8000)
npm run build                 (rebuilds web/dist)
npm run typecheck
npm test                      (checks of the browser's computations, below)
```

`npm test` runs: the power budget against hand-worked cases; the Moon's sky against the engine and NASA's eclipse catalogue; the point analysis against independent facts; the polar horizon grid and slope map against their Python twins; the regolith model against the engine and Diviner; the CSV export against the page's own numbers.

## Updating the data

The `public/data/` that comes with a fresh checkout may be **demo data** made with the analytic ephemeris; the interface says so in its top corner. For real DE440 data, in the project's main folder:

```
python scripts/build_database.py --preset year2026 --spice
```

This sweeps, runs the landing analysis and writes `public/data/`: `transfers.json`, `landings.json` and `trajectories/`. The server reads the current files every time it starts.

The Validation page's data (`validation.json`) comes from a separate command:

```
python scripts/sweep_transfers.py --start 2025-12-07 --end 2026-03-31 --step 3 --tofs 4 6 8 10 12 --families 1 --spice --out data/cache/genova.csv
python scripts/build_validation.py --spice --tests
python scripts/diviner_polar_check.py --spice
python scripts/diviner_polar_diagnose.py --spice
```

The last two produce the comparison with Diviner's polar data (`diviner_polar.json`, needs the network, ~5-10 min) and the diagnosis made after that check (`diviner_polar_diagnostics.json`, optional).

The 3D view's data (`scene3d.json`, `scene3d.bin`, `journeys.json`), the temperature / power data (`thermal.json`) and the Anywhere page's tables, after the forecast:

```
python scripts/build_scene3d.py --spice
python scripts/build_journeys.py --spice
python scripts/build_thermal.py --spice
python scripts/build_ephemeris_table.py --spice
python scripts/check_polar_orientation.py --pole south
python scripts/build_horizon_grid.py --spice
python scripts/build_slope_map.py
```

## Screens

Tabs at the top: **Browse and plan** (below), **Anywhere** (`#anywhere`: daylight, landing windows, Earth and DSN, eclipses, ground temperature and power budget for any point of the Moon, with CSV export; computed in the browser), **Forecast** (`#forecast`: the registered timing and location forecast for Griffin-1, region suitability map, candidate temperatures, power budget), **3D view** (`#3d`: two scenes. Journey: IM-1, IM-2 and Griffin-1 from launch to touchdown, DSN links. Landing region: the region's LOLA terrain, shadows computed on the GPU, time slider, astronaut camera, shadow check against the engine. Needs WebGL2) and **Validation** (`#validation`).

- **Where do you want to land?** A map of the Moon and a site comparison table: number of landing windows, best Δv to the surface, typical wait and daylight. Selecting a site recomputes every view for it.
- For a polar site, a **horizon panorama**: the 360° silhouette of the LOLA terrain and the highest the Sun can climb at that latitude. The Sun chart in the landing block also shows the terrain towards the Sun; the landing window opens 0.5° above the terrain horizon.
- **Plan a mission to …** (with a site selected): the reverse query. Give a TLI date range, the minimum daylight after landing, the maximum wait in orbit and optionally a limit on Δv to the surface; the tool lists every launch window meeting them (consecutive suitable TLI dates), how many days each stays open, the best launch dates in order, and the **slip tolerance** of the selected transfer: "the launch can slip 4 days and the conditions hold until 22 February".
- Extra planner conditions: at least X% solar energy in the first days, a DSN station in view at landing; "Copy link to this plan" for a link to the same view. The landing block shows energy, the longest shadow and the DSN stations that see the landing.
- **Design a transfer:** with the engine running, designs a transfer for any date, transit time, approach family and capture orbit (~5 s), with the landing analysis for all sites.
- **Launch window map:** TLI date × transit time heat map. Metrics: LOI, total and TLI Δv, C3, v∞; with a site selected, Δv to the surface, wait, daylight after landing. Hatched cell: no landing window within 30 days with that transfer. Navigable with the arrow keys.
- **… by launch date:** NASA Lunar Browser's own view; metric × date, colour = transit time.
- **Transfer detail:** burns, timeline (TLI → SOI → LOI → landing), the landing block and Sun elevation chart for the selected site, a rotatable 3D trajectory (Earth and Moon views).
- **Table:** the ten best transfers or all of them; the accessible table equivalent of the charts.
- Filters: approach family, TLI month; light / dark theme.
- **Validation:** comparison with NASA Ames' Lunar Browser chart (LOI band, monthly minima), retrodiction of three flown CLPS missions (IM-1 Odysseus, IM-2 Athena, Blue Ghost 1: illumination at the real landing moment, reconstructed arrival, predicted versus real launch windows, sunset), the polar map orientation check, the regolith temperature model's checks against Diviner (equator and south pole), and a summary of the test suite.
- **Power budget** (Forecast and Anywhere): enter panels, battery and loads; the point's sunlight comes from the engine (Forecast, 2-hour steps from the best landing moment) or the browser (Anywhere, hourly); battery charge, whether it runs out in shadow, the smallest battery and panel that get through (by bisection).

## Structure

```
src/
├── App.tsx                  layout, filters, selection, live results
├── types.ts                 transfers.json, landings.json, trajectory and API schemas
├── lib/
│   ├── metrics.ts           comparable metrics (unit, better direction, needs a site)
│   ├── landing.ts           decoding compressed landing results, reason texts
│   ├── api.ts               engine server: health, design job, trajectory
│   ├── color.ts             single-hue sequential colour scale (light / dark)
│   ├── format.ts            date and number formats
│   ├── planner.ts           reverse query, launch windows, slip tolerance
│   ├── urlstate.ts          shareable link: state in the address bar
│   ├── power.ts             power budget: battery simulation, smallest battery / panel (tests/power.check.mjs)
│   ├── sky.ts               the Moon's sky: ephemeris table, Sun / Earth directions, DSN, eclipses (tests/sky.check.mjs)
│   ├── siteAnalysis.ts      any point: daylight, landing windows, communication, eclipses (tests/site.check.mjs)
│   ├── horizonGrid.ts       polar (south / north) LOLA horizon grid: tile choice, blending four points (tests/horizon.check.mjs)
│   ├── slopeMap.ts          polar 240 m slope map: tile choice, decoding the normal (tests/slope.check.mjs)
│   ├── regolith.ts          the engine's regolith heat model, line for line (tests/regolith.check.mjs)
│   ├── siteThermal.ts       ground temperature and sunlight at a point, spun up like the engine
│   ├── csvExport.ts         the Anywhere page's numbers as CSV (tests/csv.check.mjs)
│   ├── scene3d/             3D view (dependency-free WebGL2)
│   │   ├── data.ts          scene3d file, map plane ↔ Moon-fixed ↔ scene transforms, Sun / Earth
│   │   ├── shaders.ts       GLSL; MARCH_GLSL is the GPU twin of the engine's march_sun_clear()
│   │   ├── renderer.ts      light pass, terrain rings, sky, lines, check and point query
│   │   ├── journey.ts       journey file, interpolation in time (position, attitude quaternions)
│   │   ├── journeyRenderer.ts  Earth, Moon (LOLA polar terrain), path, spacecraft, DSN links
│   │   └── math.ts          4x4 matrices
│   └── hooks.ts             data loading, server status, trajectory, width, theme, page (#hash)
└── components/
    ├── SitePanel.tsx, SiteMap.tsx      site selection and comparison
    ├── DesignPanel.tsx                 live design form
    ├── Porkchop.tsx, SolutionSpace.tsx charts
    ├── TransferDetail.tsx, LandingBlock.tsx, SunChart.tsx
    ├── TrajectoryView.tsx              dependency-free 3D canvas projection
    ├── TransferTable.tsx, Legend.tsx
    ├── PlannerPanel.tsx                mission planner (window strip, tables)
    ├── HorizonChart.tsx                LOLA horizon panorama
    ├── ForecastPage.tsx                upcoming mission forecast, region map
    ├── ScenePage.tsx                   3D view: scene choice; region scene (cameras, time, layers, shadow check)
    ├── JourneyView.tsx                 3D journey: mission, camera, timeline, comparison with reality
    ├── ThermalSection.tsx              regolith temperatures: Diviner check (Validation), candidates (Forecast)
    ├── PowerBudget.tsx                 power budget calculator (Forecast and Anywhere)
    ├── AnywherePage.tsx                anywhere on the Moon: map, point analysis, tables
    ├── GroundSection.tsx               Anywhere: ground temperature, power budget, CSV downloads
    ├── OrientationSection.tsx          polar map orientation check (Validation)
    ├── DivinerPolarSection.tsx         model and Diviner measurements at the south pole (Validation)
    └── ValidationPage.tsx              validation page
```

## Design notes

- The visual language comes from the trajectory charts of NASA technical reports: a cool-toned millimetre-grid background, navy ink, data on a single-hue blue scale ("dark = worse" for every metric), **magenta only for the selected transfer**.
- Typeface TeX Gyre Heros (a free twin of Helvetica), in `public/fonts/`, GUST Font License.
- Light and dark themes; in the dark theme the colour scale is chosen separately for the dark background.
