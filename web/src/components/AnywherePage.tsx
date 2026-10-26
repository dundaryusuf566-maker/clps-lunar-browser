import { scaleLinear, scaleUtc } from "d3-scale";
import { utcFormat } from "d3-time-format";
import { useEffect, useMemo, useState } from "react";
import { fmtNum } from "../lib/format";
import { BASE, useHorizonGridMeta, useSlopeMapMeta, useWidth, type Loadable } from "../lib/hooks";
import { covers, horizonAt, latLonOfPlane, planeXY, tilesDir, tilesFor, type GridHorizon, type HorizonGridMeta } from "../lib/horizonGrid";
import { analyzeSite, dsnNames, type SiteResult } from "../lib/siteAnalysis";
import { normalAt, slopeTileFor, type SlopeMapMeta } from "../lib/slopeMap";
import type { Ephem } from "../lib/sky";
import { numParam, readParams, writeParams } from "../lib/urlstate";
import type { Site } from "../types";
import { GroundSection } from "./GroundSection";
import { HorizonChart } from "./HorizonChart";

const dayFmt = utcFormat("%-d %b %Y");
const dtFmt = utcFormat("%-d %b %Y %H:%M");
const tickFmt = utcFormat("%-d %b");
const SUN = "#eda100";
const LENGTHS = [30, 60, 90, 180, 365];

const wrapLon = (l: number) => ((((l + 180) % 360) + 360) % 360) - 180;
const clampLat = (l: number) => Math.max(-90, Math.min(90, l));
const isoDay = (ms: number) => new Date(ms).toISOString().slice(0, 10);
const fmtLat = (v: number) => `${fmtNum(Math.abs(v), 2)}° ${v < 0 ? "S" : "N"}`;
const fmtLon = (v: number) => `${fmtNum(Math.abs(v), 2)}° ${v < 0 ? "W" : "E"}`;
const hours = (ms: number) => ms / 3600e3;
const dur = (h: number) => (h >= 48 ? `${fmtNum(h / 24, 1)} d` : `${fmtNum(h, 0)} h`);

export function AnywherePage({ ephem, sites }: { ephem: Loadable<Ephem | null>; sites: Site[] }) {
  const p = readParams();
  const [lat, setLat] = useState(() => clampLat(numParam(p, "lat") ?? -84.7906));
  const [lon, setLon] = useState(() => wrapLon(numParam(p, "lon") ?? 29.1957));
  const [from, setFrom] = useState(() => p.get("from") ?? "2026-11-01");
  const [days, setDays] = useState(() => (LENGTHS.includes(numParam(p, "days") ?? 0) ? (numParam(p, "days") as number) : 60));
  const gs = useHorizonGridMeta("s"), gn = useHorizonGridMeta("n");
  const grids = { south: gs.status === "ready" ? gs.data : null, north: gn.status === "ready" ? gn.data : null };
  const grid = lat < 0 ? grids.south : grids.north;
  const ss = useSlopeMapMeta("s"), sn = useSlopeMapMeta("n");
  const slope = lat < 0 ? (ss.status === "ready" ? ss.data : null) : (sn.status === "ready" ? sn.data : null);
  useEffect(() => writeParams({ lat: lat.toFixed(4), lon: lon.toFixed(4), from, days }), [lat, lon, from, days]);

  if (ephem.status === "loading") return <div className="validation"><p className="empty">Loading the Moon's ephemeris table…</p></div>;
  if (ephem.status === "error" || !ephem.data) {
    return (
      <div className="validation">
        <p className="empty">
          No ephemeris table yet. Build it with <code>python scripts/build_ephemeris_table.py --spice</code> and reload.
          {ephem.status === "error" ? ` (${ephem.message})` : ""}
        </p>
      </div>
    );
  }
  const e = ephem.data;
  const span = e.meta.span_utc.map((s) => Date.parse(s.endsWith("Z") || s.includes("+") ? s : `${s}Z`));
  const preset = sites.find((s) => Math.abs(s.lat_deg - lat) < 1e-3 && Math.abs(s.lon_deg - lon) < 1e-3);
  return (
    <div className="validation">
      <section className="panel" aria-labelledby="any-title">
        <div className="panel-head">
          <h2 id="any-title">Anywhere on the Moon</h2>
          <span className="hint">computed in your browser · {e.meta.ephemeris}</span>
        </div>
        <div className="panel-body val-grid">
          <div>
            <p className="val-story">
              Pick any point. The browser works out, hour by hour, where the Sun and the Earth stand in its sky, when a
              lander could touch down there by the same light and communication rules the engine uses for every site,
              which of NASA's Deep Space Network stations can hear it, and when the Earth eclipses the Sun. Everything
              runs here from a table of JPL's ephemeris; nothing is sent anywhere.
            </p>
            <MoonPicker lat={lat} lon={lon} sites={sites} grids={grids} onPick={(la, lo) => { setLat(la); setLon(lo); }} />
          </div>
          <div>
            <div className="power-grid">
              <label className="control">Known site
                <select value={preset?.id ?? ""} onChange={(ev) => {
                  const s = sites.find((q) => q.id === ev.target.value);
                  if (s) { setLat(s.lat_deg); setLon(s.lon_deg); }
                }}>
                  <option value="">Custom point</option>
                  {sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                </select>
              </label>
              <label className="control">Latitude (° N, negative S)
                <input type="number" step={0.01} min={-90} max={90} value={Number(lat.toFixed(4))}
                  onChange={(ev) => Number.isFinite(+ev.target.value) && setLat(clampLat(+ev.target.value))} />
              </label>
              <label className="control">Longitude (° E, negative W)
                <input type="number" step={0.01} min={-180} max={180} value={Number(lon.toFixed(4))}
                  onChange={(ev) => Number.isFinite(+ev.target.value) && setLon(wrapLon(+ev.target.value))} />
              </label>
              <label className="control">From
                <input type="date" value={from} min={isoDay(span[0])} max={isoDay(span[1] - 30 * 86400e3)}
                  onChange={(ev) => ev.target.value && setFrom(ev.target.value)} />
              </label>
              <label className="control">Period
                <select value={days} onChange={(ev) => setDays(+ev.target.value)}>
                  {LENGTHS.map((d) => <option key={d} value={d}>{d} days</option>)}
                </select>
              </label>
            </div>
            <Analysis e={e} lat={lat} lon={lon} from={from} days={days} span={span} grid={grid} slope={slope} />
          </div>
        </div>
      </section>
    </div>
  );
}

// tiles of the horizon grid, fetched once per page load
const TILE_CACHE = new Map<string, Map<string, Int16Array>>();      // tiles dir -> "row,col" -> data
const TILE_PENDING = new Map<string, Promise<void>>();
const tilesOf = (dir: string) => { if (!TILE_CACHE.has(dir)) TILE_CACHE.set(dir, new Map()); return TILE_CACHE.get(dir)!; };
function loadTiles(dir: string, keys: [number, number][]): Promise<void> {
  const cache = tilesOf(dir);
  return Promise.all(keys.map(([r, c]) => {
    const k = `${r},${c}`, pk = `${dir}/${k}`;
    if (cache.has(k)) return Promise.resolve();
    if (!TILE_PENDING.has(pk)) {
      TILE_PENDING.set(pk, fetch(`${BASE}data/${dir}/t_${r}_${c}.bin`)
        .then((res) => { if (!res.ok) throw new Error(`horizon tile ${k}: ${res.status}`); return res.arrayBuffer(); })
        .then((b) => { cache.set(k, new Int16Array(b)); })
        .finally(() => TILE_PENDING.delete(pk)));
    }
    return TILE_PENDING.get(pk)!;
  })).then(() => undefined);
}

function useGridHorizon(m: HorizonGridMeta | null, lat: number, lon: number): { h: GridHorizon | null; loading: boolean; error: string | null } {
  const [, bump] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const keys = m && covers(m, lat) ? tilesFor(m, lat, lon) : [];
  const dir = m ? tilesDir(m) : "";
  const missing = keys.filter(([r, c]) => !tilesOf(dir).has(`${r},${c}`));
  const sig = missing.map((k) => k.join(",")).join(";");
  useEffect(() => {
    if (!m || !sig) return;
    let live = true;
    loadTiles(dir, missing).then(() => live && bump((x) => x + 1)).catch((err: Error) => live && setError(err.message));
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [m, sig]);
  const ready = !!m && keys.length > 0 && missing.length === 0;
  // one horizon object per point, so that what is computed from it is not redone on every render
  const h = useMemo(() => (ready && m ? horizonAt(m, tilesOf(dir), lat, lon) : null), [ready, m, dir, lat, lon]);
  if (!m || !keys.length) return { h: null, loading: false, error: null };
  if (missing.length) return { h: null, loading: !error, error };
  return { h, loading: false, error: null };
}

/** The ground's normal at a point from the polar slope map, once its tile is in. */
function useSlopeNormal(m: SlopeMapMeta | null, lat: number, lon: number) {
  const [, bump] = useState(0);
  const tile = m ? slopeTileFor(m, lat, lon) : null;
  const dir = m?.tiles_dir ?? "";
  const have = !!tile && tilesOf(dir).has(tile.join(","));
  const sig = tile && !have ? tile.join(",") : "";
  useEffect(() => {
    if (!m || !sig || !tile) return;
    let live = true;
    loadTiles(dir, [tile]).then(() => live && bump((x) => x + 1)).catch(() => undefined);
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [m, sig]);
  return useMemo(() => (m && have ? normalAt(m, tilesOf(dir), lat, lon) : null), [m, have, dir, lat, lon]);
}

function Analysis({ e, lat, lon, from, days, span, grid, slope }: {
  e: Ephem; lat: number; lon: number; from: string; days: number; span: number[]; grid: HorizonGridMeta | null; slope: SlopeMapMeta | null;
}) {
  const gh = useGridHorizon(grid, lat, lon);
  const sn = useSlopeNormal(slope, lat, lon);
  const [useTerrain, setUseTerrain] = useState(true);
  const start = Date.parse(`${from}T00:00:00Z`);
  const ok = Number.isFinite(start) && start >= span[0] && start + days * 86400e3 <= span[1];
  const horizon = useTerrain && gh.h ? gh.h.fn : undefined;
  const r = useMemo(() => (ok ? analyzeSite(e, lat, lon, start, days, { stepMin: days > 120 ? 60 : 30, horizon }) : null),
    [e, lat, lon, start, days, ok, horizon]);
  if (!r) return <p className="slip">The table covers {dayFmt(new Date(span[0]))} to {dayFmt(new Date(span[1]))}; choose a period inside it.</p>;
  const polar = Math.abs(lat) >= 75;
  const inGrid = !!grid && covers(grid, lat);
  const farSide = r.series.earthEl.every((v) => v < 0);       // below even a level horizon all the time
  return (
    <>
      <dl className="figures">
        <div><dt>Point</dt><dd className="dd-text">{fmtLat(lat)}, {fmtLon(lon)}</dd></div>
        <div><dt>Sun up</dt><dd>{fmtNum(r.stats.sunUpPct, 0)}<small>% of the time</small></dd></div>
        <div><dt>Longest night</dt><dd>{dur(r.stats.longestNightH)}<small>in the period</small></dd></div>
        <div><dt>Earth in view</dt><dd>{fmtNum(r.stats.earthUpPct, 0)}<small>% of the time</small></dd></div>
        <div><dt>DSN contact</dt><dd>{r.stats.earthNeverUp ? "none" : fmtNum(r.stats.dsnWhenEarthUpPct, 0)}<small>{r.stats.earthNeverUp ? "relay needed" : "% of Earth-in-view time"}</small></dd></div>
        <div><dt>Landing windows</dt><dd>{r.windows.length}<small>Sun {r.rules.sunMinDeg}–{r.rules.sunMaxDeg}°, rising</small></dd></div>
      </dl>
      {r.stats.earthNeverUp && (farSide ? (
        <p className="slip">The Earth never rises here: this is the far side. A lander needs a relay satellite to talk to the
          Earth (Blue Ghost Mission 2 plans one, Lunar Pathfinder), so no direct-to-Earth landing window exists.</p>
      ) : (
        <p className="slip">The Earth does come above the level horizon here, but never above the terrain around this point
          in this period: no direct-to-Earth link from the ground. A relay satellite, or a site a little higher, would be needed.</p>
      ))}
      {polar && !inGrid && (
        <p className="slip">Near the pole the Sun skims the horizon and the surrounding relief decides the light. This analysis
          uses a flat horizon{grid ? "" : ` (no LOLA horizon grid for this pole yet: python scripts/build_horizon_grid.py --spice${lat > 0 ? " --pole north" : ""})`};
          for the polar sites with a LOLA horizon use Browse and plan and the Forecast, which measure the Sun above the real terrain.</p>
      )}
      {inGrid && grid && (
        <div className="any-terrain">
          <label className="control check">
            <input type="checkbox" checked={useTerrain} onChange={(ev) => setUseTerrain(ev.target.checked)} />
            Use the LOLA terrain horizon {gh.loading ? "(loading…)" : gh.error ? `(${gh.error})` : !gh.h ? "(no grid points here)" : ""}
          </label>
          {gh.h && useTerrain && (
            <HorizonChart latDeg={lat} name="this point" height={150}
              terrain={{ source: grid.dem, map_scale_m: grid.map_scale_m, observer_m: grid.observer_m, site_height_m: 0,
                max_dist_km: grid.max_dist_km, az_step_deg: grid.az_step_deg, elev_deg: Array.from(gh.h.elev), dist_km: [] }}
              note={`Interpolated from the ${fmtNum(grid.spacing_km, 0)} km LOLA horizon grid (${gh.h.nodes} grid points, nearest ${fmtNum(gh.h.nearestKm, 1)} km away). ` +
                `Checked at ${grid.check.points} random points of the cap: the share of ${grid.check.year} with the Sun above the terrain is off by ` +
                `${fmtNum(grid.check.sunlit_pct_interp_minus_own.median, 1)} points (median; 90% within ${fmtNum(grid.check.sunlit_pct_interp_minus_own.p90, 1)}) ` +
                `against each point's own horizon; a flat horizon is off by ${fmtNum(grid.check.sunlit_pct_flat_minus_own.median, 1)} ` +
                `(90% within ${fmtNum(grid.check.sunlit_pct_flat_minus_own.p90, 1)}).`} />
          )}
        </div>
      )}
      <ElevationChart r={r} />
      <Tables r={r} />
      <p className="table-note">
        Sun and Earth from the {e.meta.ephemeris} table (hourly, Moon-fixed IAU frame), interpolated; checked against the engine
        at fixed points and times (web/tests/sky.check.mjs). Horizon: {r.terrain ? `LOLA terrain (${grid?.dem}, interpolated from the horizon grid)` : "flat (no terrain)"}. Landing window:
        Sun {r.rules.sunMinDeg}–{r.rules.sunMaxDeg}° above the horizon and rising, Earth at least {r.rules.minEarthElDeg}° up
        (the engine's rule for {polar ? "polar" : "non-polar"} sites; a transfer and the orbit plane are not part of this
        page). DSN: Goldstone, Madrid, Canberra above 10° (our assumption). Eclipses: the Earth's disc over the Sun's,
        geometric (the atmosphere widens the real shadow by ~2%). Step {r.stepMin} min.
      </p>
      <GroundSection e={e} r={r} horizon={horizon} demName={grid?.dem}
        tilt={useTerrain && sn ? { normal: sn.n, slopeDeg: sn.slopeDeg, blockM: slope!.block_m } : undefined}
        slopeMissing={Math.abs(lat) >= 75 && useTerrain && !sn} />
    </>
  );
}

type Pole = "south" | "north";
function MoonPicker({ lat, lon, sites, grids, onPick }: {
  lat: number; lon: number; sites: Site[]; grids: Record<Pole, HorizonGridMeta | null>; onPick: (lat: number, lon: number) => void;
}) {
  const ok = (p: Pole) => !!grids[p]?.relief_png && !!grids[p]?.relief_extent_km;
  const poles = (["south", "north"] as Pole[]).filter(ok);
  const [view, setView] = useState<"moon" | Pole>(() => poles.find((p) => covers(grids[p]!, lat)) ?? "moon");
  const tabs = poles.length > 0 && (
    <div className="segmented any-tabs" role="group" aria-label="Map">
      <button aria-pressed={view === "moon"} onClick={() => setView("moon")}>Whole Moon</button>
      {poles.map((p) => <button key={p} aria-pressed={view === p} onClick={() => setView(p)}>{p === "south" ? "South" : "North"} pole (LOLA)</button>)}
    </div>
  );
  if (view !== "moon" && ok(view)) return <>{tabs}<PolarPicker key={view} lat={lat} lon={lon} sites={sites} grid={grids[view]!} onPick={onPick} /></>;
  return <>{tabs}<WorldPicker lat={lat} lon={lon} sites={sites} onPick={onPick} /></>;
}

function PolarPicker({ lat, lon, sites, grid, onPick }: {
  lat: number; lon: number; sites: Site[]; grid: HorizonGridMeta; onPick: (lat: number, lon: number) => void;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [x0, x1, y0, y1] = grid.relief_extent_km!;
  const PAD = 26, W = Math.max(0, Math.min(width, 640) - 2 * PAD);
  const px = (X: number) => ((X - x0) / (x1 - x0)) * W;
  const py = (Y: number) => ((Y - y0) / (y1 - y0)) * W;
  const rho = 2 * grid.radius_km * Math.tan(((90 - grid.min_abs_lat) * Math.PI) / 360);
  const here = covers(grid, lat) ? planeXY(grid, lat, lon) : null;
  const ring = (absLat: number) => 2 * grid.radius_km * Math.tan(((90 - absLat) * Math.PI) / 360);
  const pick = (ev: React.MouseEvent<SVGElement>) => {
    const b = ev.currentTarget.getBoundingClientRect();     // the transparent rect over the image
    const X = x0 + ((ev.clientX - b.left) / b.width) * (x1 - x0), Y = y0 + ((ev.clientY - b.top) / b.height) * (y1 - y0);
    if (Math.hypot(X, Y) > rho) return;
    const [la, lo] = latLonOfPlane(grid, X, Y);
    onPick(Math.round(la * 1e4) / 1e4, Math.round(lo * 1e4) / 1e4);
  };
  const cx = px(0), cy = py(0);
  return (
    <div ref={ref} className="chart site-map">
      {W > 0 && (
        <svg width={W + 2 * PAD} height={W + 2 * PAD} role="img" aria-label={`${grid.pole === "north" ? "North" : "South"} polar map (LOLA shaded relief): click to choose a point`}>
          <g transform={`translate(${PAD},${PAD})`}>
          <defs><clipPath id={`cap-${grid.pole}`}><circle cx={cx} cy={cy} r={px(rho) - cx} /></clipPath></defs>
          <image href={`${BASE}data/${grid.relief_png}`} x={0} y={0} width={W} height={W} preserveAspectRatio="none" clipPath={`url(#cap-${grid.pole})`} />
          {[85, 80].filter((a) => a > grid.min_abs_lat).map((a) => (
            <g key={a}><circle cx={cx} cy={cy} r={px(ring(a)) - cx} fill="none" stroke="#ffffff88" strokeDasharray="3 4" />
              <text className="map-region" x={cx + 4} y={cy - (px(ring(a)) - cx) + 12} fill="#fff">{a}° {grid.pole === "north" ? "N" : "S"}</text></g>
          ))}
          <circle cx={cx} cy={cy} r={px(rho) - cx} fill="none" stroke="var(--rule)" />
          {[0, 90, 180, 270].map((l) => {
            const [X, Y] = planeXY(grid, (grid.pole === "north" ? 1 : -1) * grid.min_abs_lat, l);
            return <text key={l} className="map-region" x={px(X * 1.07)} y={py(Y * 1.07) + 4} textAnchor="middle">{l === 0 ? "0°" : l === 180 ? "180°" : l === 90 ? "90° E" : "90° W"}</text>;
          })}
          {sites.filter((s) => covers(grid, s.lat_deg)).map((s) => {
            const [X, Y] = planeXY(grid, s.lat_deg, s.lon_deg);
            return <circle key={s.id} cx={px(X)} cy={py(Y)} r={4} fill="#fff" stroke="var(--ink)"><title>{s.name}</title></circle>;
          })}
          <rect width={W} height={W} fill="transparent" style={{ cursor: "crosshair" }} onClick={pick} />
          {here && <g pointerEvents="none">
            <circle cx={px(here[0])} cy={py(here[1])} r={8} fill="none" stroke="var(--signal)" strokeWidth={2.5} />
            <circle cx={px(here[0])} cy={py(here[1])} r={2} fill="var(--signal)" />
          </g>}
          </g>
        </svg>
      )}
      <div className="key"><span className="k-moon">Known sites</span><span className="k-terrain">LOLA {grid.dem}, shaded relief; horizons every {fmtNum(grid.spacing_km, 0)} km</span></div>
    </div>
  );
}

function WorldPicker({ lat, lon, sites, onPick }: { lat: number; lon: number; sites: Site[]; onPick: (lat: number, lon: number) => void }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const M = { top: 8, right: 8, bottom: 22, left: 30 };
  const w = Math.max(0, width - M.left - M.right), h = w / 2;
  const x = (lo: number) => ((lo + 180) / 360) * w;
  const y = (la: number) => ((90 - la) / 180) * h;
  const pick = (ev: React.MouseEvent<SVGRectElement>) => {
    const b = ev.currentTarget.getBoundingClientRect();
    const lo = ((ev.clientX - b.left) / b.width) * 360 - 180, la = 90 - ((ev.clientY - b.top) / b.height) * 180;
    onPick(Math.round(la * 100) / 100, Math.round(lo * 100) / 100);
  };
  return (
    <div ref={ref} className="chart site-map">
      {width > 0 && (
        <svg width={width} height={h + M.top + M.bottom} role="img" aria-label="Map of the Moon: click to choose a point">
          <g transform={`translate(${M.left},${M.top})`}>
            <rect width={w} height={h} fill="var(--surface)" stroke="var(--rule)" />
            <rect x={0} width={x(-90)} height={h} fill="var(--moon-fill)" />
            <rect x={x(90)} width={w - x(90)} height={h} fill="var(--moon-fill)" />
            <rect y={y(-75)} width={w} height={h - y(-75)} fill="var(--terrain)" opacity={0.5} />
            <rect width={w} height={y(75)} fill="var(--terrain)" opacity={0.5} />
            {[-60, -30, 0, 30, 60].map((la) => <line key={la} className="gridline" x1={0} x2={w} y1={y(la)} y2={y(la)} />)}
            {[-150, -120, -90, -60, -30, 0, 30, 60, 90, 120, 150].map((lo) => <line key={lo} className="gridline" x1={x(lo)} x2={x(lo)} y1={0} y2={h} />)}
            <text className="map-region" x={x(0)} y={14} textAnchor="middle">Near side</text>
            <text className="map-region" x={x(-135)} y={14} textAnchor="middle">Far side</text>
            <text className="map-region" x={x(135)} y={14} textAnchor="middle">Far side</text>
            {[-60, 0, 60].map((la) => <text key={la} className="map-region" x={-6} y={y(la) + 4} textAnchor="end">{la}°</text>)}
            {[-90, 0, 90].map((lo) => <text key={lo} className="map-region" x={x(lo)} y={h + 14} textAnchor="middle">{lo}°</text>)}
            {sites.map((s) => <circle key={s.id} cx={x(s.lon_deg)} cy={y(s.lat_deg)} r={3.5} fill="var(--ink-3)"><title>{s.name}</title></circle>)}
            <rect width={w} height={h} fill="transparent" style={{ cursor: "crosshair" }} onClick={pick} />
            <g pointerEvents="none">
              <circle cx={x(lon)} cy={y(lat)} r={7} fill="none" stroke="var(--signal)" strokeWidth={2.5} />
              <circle cx={x(lon)} cy={y(lat)} r={2} fill="var(--signal)" />
            </g>
          </g>
        </svg>
      )}
      <div className="key"><span className="k-terrain">Beyond 75°: LOLA terrain matters (see polar sites)</span><span className="k-moon">Known sites</span></div>
    </div>
  );
}

function ElevationChart({ r }: { r: SiteResult }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const W = Math.max(0, width), H = 240, M = { top: 14, right: 12, bottom: 44, left: 40 };
  const iw = Math.max(0, W - M.left - M.right), ih = H - M.top - M.bottom;
  const s = r.series, n = s.t.length;
  let lo = 0, hi = 0;
  for (let i = 0; i < n; i++) {
    lo = Math.min(lo, s.sunEl[i], s.earthEl[i]);
    hi = Math.max(hi, s.sunEl[i], s.earthEl[i], r.terrain ? s.sunHorizon[i] : -90);
  }
  const x = scaleUtc().domain([s.t[0], s.t[n - 1]]).range([0, iw]);
  const y = scaleLinear().domain([Math.max(-90, lo - 1), Math.min(90, hi + 1)]).nice().range([ih, 0]);
  const path = (v: Float32Array) => {
    const stride = Math.max(1, Math.floor(n / Math.max(200, iw * 2)));
    let d = "";
    for (let i = 0; i < n; i += stride) d += `${i ? "L" : "M"}${x(s.t[i]).toFixed(1)},${y(v[i]).toFixed(1)}`;
    return d;
  };
  const dsnRuns: [number, number][] = [];
  let a: number | null = null;
  for (let i = 0; i < n; i++) {
    if (s.dsn[i] && a === null) a = s.t[i];
    if (!s.dsn[i] && a !== null) { dsnRuns.push([a, s.t[i]]); a = null; }
  }
  if (a !== null) dsnRuns.push([a, s.t[n - 1]]);
  return (
    <div ref={ref} className="chart">
      {W > 0 && (
        <svg width={W} height={H} role="img" aria-label="Sun and Earth elevation over the period">
          <g transform={`translate(${M.left},${M.top})`}>
            {r.daylight.map((d, i) => <rect key={i} x={x(d.start)} width={Math.max(0, x(d.end) - x(d.start))} y={0} height={ih} fill="#eda10022" />)}
            {r.windows.map((w, i) => <rect key={`w${i}`} x={x(w.start)} width={Math.max(1.5, x(w.end) - x(w.start))} y={0} height={ih} fill="var(--signal-soft)" />)}
            {y.ticks(5).map((v) => (
              <g key={v} className="axis"><line className="gridline" x1={0} x2={iw} y1={y(v)} y2={y(v)} />
                <text x={-6} y={y(v) + 4} textAnchor="end">{v}°</text></g>
            ))}
            <line x1={0} x2={iw} y1={y(0)} y2={y(0)} stroke="var(--ink-3)" />
            {x.ticks(Math.max(2, Math.round(iw / 110))).map((v) => (
              <g key={+v} className="axis"><text x={x(v)} y={ih + 30} textAnchor="middle">{tickFmt(v)}</text></g>
            ))}
            {r.terrain && <path d={`${path(s.sunHorizon)}L${x(s.t[n - 1]).toFixed(1)},${ih}L0,${ih}Z`} fill="var(--terrain)" />}
            <path d={path(s.earthEl)} fill="none" stroke="var(--earth)" strokeWidth={1.5} />
            <path d={path(s.sunEl)} fill="none" stroke={SUN} strokeWidth={2} />
            {r.eclipses.filter((c) => c.sunUp).map((c, i) => (
              <g key={`e${i}`}><line x1={x(c.peak)} x2={x(c.peak)} y1={0} y2={ih} stroke="var(--ink)" strokeDasharray="2 3" />
                <text className="annotation" x={x(c.peak) + 4} y={10}>eclipse</text></g>
            ))}
            <text className="axis-title" x={0} y={ih + 12}>DSN</text>
            {dsnRuns.map(([t0, t1], i) => <rect key={`d${i}`} x={x(t0)} width={Math.max(0.8, x(t1) - x(t0))} y={ih + 4} height={8} fill="var(--ok)" opacity={0.75} />)}
          </g>
        </svg>
      )}
      <div className="key">
        <span className="k-sun">Sun elevation</span><span className="k-earth">Earth elevation</span>
        {r.terrain && <span className="k-terrain">Terrain horizon towards the Sun</span>}
        <span className="k-window">Landing window</span><span className="k-dsn">DSN station in view</span>
      </div>
    </div>
  );
}

function Tables({ r }: { r: SiteResult }) {
  const [tab, setTab] = useState<"windows" | "daylight" | "eclipses">("windows");
  return (
    <div>
      <div className="segmented any-tabs" role="group" aria-label="Tables">
        {([["windows", `Landing windows (${r.windows.length})`], ["daylight", `Daylight (${r.daylight.length})`],
          ["eclipses", `Eclipses (${r.eclipses.length})`]] as const).map(([k, label]) => (
          <button key={k} aria-pressed={tab === k} onClick={() => setTab(k)}>{label}</button>
        ))}
      </div>
      <div className="table-wrap">
        {tab === "windows" && (r.windows.length ? (
          <table>
            <thead><tr><th className="left">Opens (UTC)</th><th>Closes</th><th>Length</th><th>DSN at opening</th><th>DSN in window</th></tr></thead>
            <tbody>{r.windows.map((w, i) => (
              <tr key={i} className="static"><td className="left">{dtFmt(new Date(w.start))}</td><td>{dtFmt(new Date(w.end))}</td>
                <td>{dur(hours(w.end - w.start))}</td><td>{dsnNames(w.dsnAtStart).join(", ") || "none"}</td><td>{fmtNum(w.dsnPct, 0)}%</td></tr>
            ))}</tbody>
          </table>) : <p className="table-note">No landing window in this period{r.stats.earthNeverUp ? ": the Earth never comes above the horizon" : ""}.</p>)}
        {tab === "daylight" && (
          <table>
            <thead><tr><th className="left">Sunrise (UTC)</th><th>Sunset</th><th>Daylight</th></tr></thead>
            <tbody>{r.daylight.map((d, i) => (
              <tr key={i} className="static">
                <td className="left">{d.start <= r.startMs ? "before the period" : dtFmt(new Date(d.start))}</td>
                <td>{d.end >= r.endMs ? "after the period" : dtFmt(new Date(d.end))}</td><td>{dur(hours(d.end - d.start))}</td></tr>
            ))}</tbody>
          </table>)}
        {tab === "eclipses" && (r.eclipses.length ? (
          <table>
            <thead><tr><th className="left">Deepest (UTC)</th><th>Sun hidden, at most</th><th>Duration</th><th>Sun up here</th></tr></thead>
            <tbody>{r.eclipses.map((c, i) => (
              <tr key={i} className="static"><td className="left">{dtFmt(new Date(c.peak))}</td><td>{fmtNum(100 * c.maxFraction, 0)}%</td>
                <td>{dur(hours(c.end - c.start) + 5 / 60)}</td><td>{c.sunUp ? "yes: solar power drops" : "no (night)"}</td></tr>
            ))}</tbody>
          </table>) : <p className="table-note">The Earth does not pass in front of the Sun in this period.</p>)}
      </div>
    </div>
  );
}

