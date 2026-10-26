import { extent } from "d3-array";
import { scaleUtc } from "d3-scale";
import { utcFormat } from "d3-time-format";
import { useMemo, useState } from "react";
import { sequential } from "../lib/color";
import { fmtDay, fmtDayTime, fmtNum, fmtShortDay, fmtTof, parseUtc } from "../lib/format";
import { useWidth } from "../lib/hooks";
import type { ForecastDay, ForecastFile, RegionPoint, ThermalFile } from "../types";
import { PowerBudget } from "./PowerBudget";
import { ThermalForecastSection } from "./ThermalSection";
import { Legend } from "./Legend";

const DAY_MS = 86400e3;
const tickFmt = utcFormat("%-d %b");
const dayMs = (d: string) => Date.parse(`${d.slice(0, 10)}T00:00:00Z`);
const utc = (s: string) => parseUtc(s.endsWith("Z") || s.includes("+") ? s : `${s}Z`);
const ephLabel = (e: string) => (e.includes("spice") ? "JPL DE440" : "analytic ephemeris (demo)");
export const coord = (lat: number, lon: number) => `${fmtNum(Math.abs(lat), 3)}°${lat < 0 ? "S" : "N"} ${fmtNum(Math.abs(lon), 3)}°${lon < 0 ? "W" : "E"}`;
const days = (d: number | null | undefined, digits = 1) => (d == null ? "–" : `${fmtNum(d, digits)} d`);
const span = (dDays: number) => {
  const h = Math.abs(dDays) * 24;
  return h < 2 ? `${fmtNum(h * 60, 0)} minutes` : `${fmtNum(h, 0)} hours`;
};

/** Colour so that the better end of a metric is always the lighter one (both themes),
 *  with the legend's end labels in the matching order. */
export function goodFill(domain: [number, number], better: "high" | "low", dark: boolean) {
  const d: [number, number] = domain[0] === domain[1] ? [domain[0], domain[0] + 1] : domain;
  const ramp = sequential(d, dark);
  // light theme: the ramp darkens towards high values; dark theme: it lightens
  const flipped = (better === "high") !== dark;
  const fill = (v: number) => ramp(flipped ? d[1] - (v - d[0]) : v);
  const legend: [number, number] = flipped ? [domain[1], domain[0]] : domain;
  return { fill, legend };
}

export function ForecastPage({ data, dark, thermal }: { data: ForecastFile | null; dark: boolean; thermal?: ThermalFile | null }) {
  if (!data) {
    return (
      <div className="validation">
        <p className="empty">
          No forecast yet. Build it with <code>python scripts/build_forecast.py --spice</code> and reload.
        </p>
      </div>
    );
  }
  const m = data.mission, meta = data.meta;
  const best = data.time.calibration.filter((c) => c.miss_days != null && Math.abs(c.miss_days) < 1)
    .sort((a, b) => Math.abs(a.miss_days!) - Math.abs(b.miss_days!))[0] ?? null;
  return (
    <div className="validation forecast">
      <section className="panel val-intro">
        <div className="panel-body">
          <p className="val-lede">
            <strong>{m.name}: where and when it can land.</strong> A forecast made before launch with the same rules
            {best ? <> that, told only the launch day, put {best.mission.split(" (")[0]}'s touchdown {span(best.miss_days!)} from the real one</> : " tested on flown CLPS missions"},
            registered so it can be checked once the mission flies.
          </p>
          <p className="sub num">
            Registered {fmtDayTime(utc(meta.registered_utc))} · engine v{meta.engine_version} · {ephLabel(meta.ephemeris)}
            {meta.git_commit ? ` · commit ${meta.git_commit}` : ""} · SHA-256 <code title={meta.sha256}>{meta.sha256.slice(0, 16)}…</code>{" "}
            (check with <code>python scripts/verify_forecast.py</code>)
          </p>
        </div>
      </section>

      <section className="panel" aria-labelledby="fc-basis">
        <div className="panel-head"><h2 id="fc-basis">What is announced, and what we assume</h2></div>
        <div className="panel-body val-grid">
          <div>
            <h3 className="val-h3 first">Announced</h3>
            <ul className="plain-list">
              {m.announced.map(([text, url]) => (
                <li key={text}>{text} <a href={url} target="_blank" rel="noreferrer">Source</a></li>
              ))}
            </ul>
          </div>
          <div>
            <h3 className="val-h3 first">Assumed by us</h3>
            <ul className="plain-list">{m.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
          </div>
        </div>
      </section>

      <TimeSection data={data} dark={dark} />
      {data.region && <RegionSection data={data} dark={dark} />}
      {thermal && <ThermalForecastSection t={thermal} />}
      {thermal?.points.some((p) => p.dni_w_m2) && <PowerBudget t={thermal} />}

      <section className="panel" aria-labelledby="fc-limits">
        <div className="panel-head"><h2 id="fc-limits">What this forecast cannot know</h2></div>
        <div className="panel-body">
          <ul className="plain-list">
            <li>Metre-scale hazards (rocks, small craters, boulders) that decide the exact touchdown point: the LOLA map has 120 m pixels.</li>
            <li>The payloads' science goals and where the FLIP rover is meant to drive.</li>
            <li>Astrobotic's trajectory, orbit and operating rules, including how high they want the Sun before descent and how they trade Δv against an earlier landing.</li>
            <li>Ground-station coverage on Earth at the moment of landing.</li>
          </ul>
          <p className="table-note">
            So the map ranks places by the criteria NASA itself named for VIPER's site on Mons Mouton (illumination, Earth
            visibility, slopes). It is not a claim about the point Astrobotic will choose.
          </p>
        </div>
      </section>
    </div>
  );
}

// --- when ------------------------------------------------------------------------------
function TimeSection({ data, dark }: { data: ForecastFile; dark: boolean }) {
  const t = data.time, m = data.mission;
  const cal = t.calibration.filter((c) => c.miss_days != null);
  return (
    <section className="panel" aria-labelledby="fc-time">
      <div className="panel-head">
        <h2 id="fc-time">When: launch windows for {t.reference.name}</h2>
        <span className="hint">{t.transfers} transfers, {t.tofs.length} transit times × {t.incs.length} inclinations per day</span>
      </div>
      <div className="panel-body">
        <p className="val-story">
          Every TLI date from {fmtDay(utc(m.tli_first))} to {fmtDay(utc(m.tli_last))} is tried with {t.tofs.map(fmtTof).join(", ")} transits.
          A date qualifies when a landing within {t.constraints.max_wait_days} days of arrival has the Sun {data.region?.rules.sun_min_deg ?? 0.5}°
          above the LOLA terrain and rising, Earth in view, and at least {m.min_daylight_days} days of sunlight left, the
          announced surface mission.
        </p>
        <DayStrip days={t.days} dark={dark} />
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th className="left">TLI window</th><th>Open for</th><th className="left">Touchdown</th><th>Sunlight after</th><th className="left">Cheapest option</th></tr>
            </thead>
            <tbody>
              {t.windows.map((w) => (
                <tr key={w.first} className="static">
                  <td className="left">{fmtShortDay(utc(w.first))} – {fmtShortDay(utc(w.last))}</td>
                  <td>{w.days} d</td>
                  <td className="left">{fmtShortDay(utc(w.landing_first_utc))} – {fmtShortDay(utc(w.landing_last_utc))}</td>
                  <td>{fmtNum(w.min_daylight_days, 1)}–{fmtNum(w.max_daylight_days, 1)} d</td>
                  <td className="left">TLI {fmtShortDay(utc(w.best_tli_day))}, touchdown {fmtDayTime(utc(w.best_landing_utc))}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {cal.length > 0 && (
          <p className="table-note">
            Calibration from flown missions: the browser's own pick touched down{" "}
            {cal.map((c) => `${span(c.miss_days!)} ${c.miss_days! < 0 ? "before" : "after"} ${c.mission.split(" (")[0]} at ${c.site}`).join(" and ")}.
            {" "}So read our touchdown dates as uncertain by about ±{fmtNum(Math.ceil(Math.max(...cal.map((c) => Math.abs(c.miss_days!)))), 0)} day
            {Math.ceil(Math.max(...cal.map((c) => Math.abs(c.miss_days!)))) > 1 ? "s" : ""}: the operator's own rules decide the hour.
          </p>
        )}
      </div>
    </section>
  );
}

function DayStrip({ days: ds, dark }: { days: ForecastDay[]; dark: boolean }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<ForecastDay | null>(null);
  const M = { top: 24, right: 8, bottom: 22, left: 8 };
  const H = 84;
  const innerW = Math.max(0, width - M.left - M.right), innerH = H - M.top - M.bottom;
  const t0 = dayMs(ds[0].tli_day), t1 = dayMs(ds[ds.length - 1].tli_day) + DAY_MS;
  const x = scaleUtc().domain([t0, t1]).range([0, innerW]);
  const cw = Math.max(1, x(t0 + DAY_MS) - x(t0) - 1);
  const vals = ds.filter((d) => d.daylight_days !== null).map((d) => d.daylight_days!);
  const domain = (vals.length ? extent(vals) : [0, 1]) as [number, number];
  const { fill, legend } = goodFill(domain, "high", dark);
  return (
    <div ref={ref} className="chart scan-strip">
      {width > 0 && (
        <svg width={width} height={H} role="img" aria-label="TLI dates from which the reference point can be reached">
          <defs>
            <pattern id="fc-hatch" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <line x1="0" y1="0" x2="0" y2="5" stroke="var(--rule)" strokeWidth="2" />
            </pattern>
          </defs>
          <g transform={`translate(${M.left},${M.top})`}>
            {ds.map((d) => (
              <rect key={d.tli_day} className="cell" x={x(dayMs(d.tli_day))} width={cw} height={innerH}
                fill={d.feasible && d.daylight_days !== null ? fill(d.daylight_days) : "url(#fc-hatch)"}
                onPointerEnter={() => setHover(d)} onPointerLeave={() => setHover(null)} />
            ))}
            <g className="axis" transform={`translate(0,${innerH + 14})`}>
              {x.ticks(Math.max(2, Math.floor(innerW / 80))).filter((d, k, all) => k === 0 || tickFmt(d) !== tickFmt(all[k - 1]))
                .map((d) => <text key={+d} x={x(d)} textAnchor="middle">{tickFmt(d)}</text>)}
            </g>
          </g>
        </svg>
      )}
      {hover && (
        <div className="tooltip" style={{ left: M.left + x(dayMs(hover.tli_day)) + cw / 2, top: M.top }}>
          <strong>TLI {fmtDay(utc(hover.tli_day))}</strong>
          {hover.feasible && hover.landing_utc
            ? <>touchdown {fmtDayTime(utc(hover.landing_utc))}
                <div className="sub">{fmtTof(hover.tof_days!)} transit, {fmtNum(hover.lunar_inc_deg!, 0)}° orbit, wait {days(hover.wait_days)}, sunlight {days(hover.daylight_days)}</div>
                {hover.energy_pct != null && <div className="sub">energy over 14 d {fmtNum(hover.energy_pct, 0)}% of full Sun, DSN {hover.dsn_stations?.join(", ") || "none"}</div>}</>
            : <>no qualifying landing<div className="sub">{hover.why_not || "–"}</div></>}
        </div>
      )}
      <Legend domain={legend} label="Sunlight after touchdown (days)" digits={0} dark={dark}
        format={(v) => fmtNum(v, 0)} note="Lighter is more sunlight. Hatched: no qualifying landing from that launch date." />
    </div>
  );
}

// --- where -----------------------------------------------------------------------------
export type Layer = "daylight" | "slots" | "earth" | "energy" | "slope" | "height";
export const LAYERS: Record<Layer, { label: string; unit: string; get: (p: RegionPoint) => number | null; better: "high" | "low"; digits: number }> = {
  daylight: { label: "Sunlight after the best landing slot", unit: "days", get: (p) => p.best_daylight_days, better: "high", digits: 1 },
  slots: { label: "Landing-slot time in the period", unit: "days", get: (p) => (p.best_daylight_days !== null ? p.slot_days : null), better: "high", digits: 1 },
  earth: { label: "Earth in view, first days on the surface", unit: "%", get: (p) => p.earth_after_best_pct, better: "high", digits: 0 },
  energy: { label: "Solar energy, first lunar day (14 d)", unit: "% of full Sun", get: (p) => p.energy_pct ?? null, better: "high", digits: 0 },
  slope: { label: "Slope (240 m baseline)", unit: "°", get: (p) => p.slope_deg, better: "low", digits: 1 },
  height: { label: "Height above the 1737.4 km sphere", unit: "m", get: (p) => p.height_m, better: "high", digits: 0 },
};

export function rankPoints(points: RegionPoint[], maxSlope: number, minEarth: number): RegionPoint[] {
  return points
    .filter((p) => p.best_daylight_days !== null && p.slope_deg <= maxSlope && (p.earth_after_best_pct ?? 0) >= minEarth)
    .sort((a, b) => (b.best_daylight_days! - a.best_daylight_days!) || (b.slot_days - a.slot_days) || (a.slope_deg - b.slope_deg));
}

function RegionSection({ data, dark }: { data: ForecastFile; dark: boolean }) {
  const r = data.region!;
  const [layer, setLayer] = useState<Layer>("daylight");
  const [maxSlope, setMaxSlope] = useState(r.ranking.max_slope_deg);
  const [minEarth, setMinEarth] = useState(r.ranking.min_earth_after_pct);
  const ranked = useMemo(() => rankPoints(r.points, maxSlope, minEarth), [r.points, maxSlope, minEarth]);
  const top = ranked.slice(0, 10);
  const [sel, setSel] = useState<RegionPoint | null>(null);
  const withSlot = r.points.filter((p) => p.best_daylight_days !== null).length;
  const ref = r.references[0];
  const picked = sel ?? top[0] ?? null;

  return (
    <section className="panel" aria-labelledby="fc-region">
      <div className="panel-head">
        <h2 id="fc-region">Where: the Mons Mouton – Nobile region, {fmtNum(2 * r.grid.half_km, 0)} × {fmtNum(2 * r.grid.half_km, 0)} km</h2>
        <span className="hint">{r.points.length} points, {r.grid.step_km} km apart, LOLA {r.rules.dem}</span>
      </div>
      <div className="panel-body">
        <p className="val-story">
          Every point gets its own terrain horizon and is scored on the three things NASA weighed for VIPER's site here:
          sunlight, Earth in view and slope. A landing slot is an instant between {fmtDay(utc(r.period_utc[0]))} and{" "}
          {fmtDay(utc(r.period_utc[1]))} with the Sun {r.rules.sun_min_deg}° above the terrain and rising, Earth {r.rules.earth_min_deg}° above it and{" "}
          {r.rules.min_daylight_days} days of sunlight to follow. {withSlot} of {r.points.length} points have one.
        </p>
        <div className="controls region-controls">
          <label className="control">Map shows
            <select value={layer} onChange={(e) => setLayer(e.target.value as Layer)}>
              {(Object.keys(LAYERS) as Layer[]).map((k) => <option key={k} value={k}>{LAYERS[k].label}</option>)}
            </select>
          </label>
          <label className="control">Slope at most (°)
            <input type="number" min={0} max={30} step={1} value={maxSlope} onChange={(e) => setMaxSlope(Number(e.target.value))} />
          </label>
          <label className="control">Earth in view at least (%)
            <input type="number" min={0} max={100} step={5} value={minEarth} onChange={(e) => setMinEarth(Number(e.target.value))} />
          </label>
        </div>
        <div className="val-grid">
          <RegionMap data={data} layer={layer} top={top} passing={new Set(ranked.map((p) => `${p.i},${p.j}`))}
            selected={picked} onSelect={setSel} dark={dark} />
          <div>
            {picked && <PointCard p={picked} rank={top.indexOf(picked) + 1} minDaylight={r.rules.min_daylight_days}
              energyDays={r.rules.energy_window_days ?? r.rules.min_daylight_days} />}
            {ref && (
              <p className="table-note">
                For comparison, {ref.label}: {ref.best_daylight_days !== null
                  ? `best slot ${fmtDayTime(utc(ref.best_slot!))}, ${days(ref.best_daylight_days)} of sunlight, slope ${fmtNum(ref.slope_deg, 1)}°, Earth ${fmtNum(ref.earth_after_best_pct ?? 0, 0)}%`
                  : "no qualifying landing slot in the period"}.
              </p>
            )}
          </div>
        </div>
        <div className="table-wrap">
          <h3 className="val-h3">Best places by these criteria</h3>
          <table>
            <thead>
              <tr><th className="rank">#</th><th className="left">Point</th><th>Sunlight after</th><th className="left">Best slot</th><th>Slot time</th><th>Earth</th><th>Slope</th><th>Height</th></tr>
            </thead>
            <tbody>
              {top.map((p, k) => (
                <tr key={`${p.i},${p.j}`} onClick={() => setSel(p)} aria-selected={picked === p}>
                  <td className="rank">{k + 1}</td>
                  <td className="left num">{coord(p.lat, p.lon)}</td>
                  <td>{p.best_daylight_capped ? "≥ " : ""}{days(p.best_daylight_days)}</td>
                  <td className="left">{p.best_slot ? fmtShortDay(utc(p.best_slot)) : "–"}</td>
                  <td>{days(p.slot_days)}</td>
                  <td>{fmtNum(p.earth_after_best_pct ?? 0, 0)}%</td>
                  <td>{fmtNum(p.slope_deg, 1)}°</td>
                  <td>{fmtNum(p.height_m, 0)} m</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="table-note">
            Ranked by the sunlight their best landing slot leaves, then by total slot time. Slope and Earth limits are ours
            (defaults {r.ranking.max_slope_deg}° and {r.ranking.min_earth_after_pct}%), not Astrobotic's; change them above. Slope is
            measured over {r.rules.slope_baseline_m} m, so it cannot show rocks or small craters.
          </p>
        </div>
      </div>
    </section>
  );
}

function PointCard({ p, rank, minDaylight, energyDays }: { p: RegionPoint; rank: number; minDaylight: number; energyDays: number }) {
  return (
    <div className="point-card">
      <h3 className="val-h3 first">{rank > 0 ? `#${rank}: ` : ""}{coord(p.lat, p.lon)}</h3>
      <dl className="figures two">
        <div><dt>Best landing slot</dt><dd>{p.best_slot ? fmtShortDay(utc(p.best_slot)) : "–"}<small>{p.best_slot ? utcFormat("%H:%M UTC")(utc(p.best_slot)) : ""}</small></dd></div>
        <div><dt>Sunlight after it</dt><dd>{p.best_daylight_capped ? "≥ " : ""}{fmtNum(p.best_daylight_days ?? 0, 1)}<small>days</small></dd></div>
        <div><dt>Earth in view, first {minDaylight} d</dt><dd>{fmtNum(p.earth_after_best_pct ?? 0, 0)}<small>%</small></dd></div>
        <div><dt>Sunlit in the period</dt><dd>{fmtNum(p.sunlit_pct, 0)}<small>%</small></dd></div>
        <div><dt>Slope</dt><dd>{fmtNum(p.slope_deg, 1)}<small>°</small></dd></div>
        <div><dt>Highest horizon</dt><dd>{fmtNum(p.horizon_max_deg, 1)}<small>°</small></dd></div>
        {p.energy_pct != null && <div><dt>Solar energy, first {energyDays} d</dt><dd>{fmtNum(p.energy_pct, 0)}<small>% of full Sun</small></dd></div>}
        {p.max_dark_gap_h != null && <div><dt>Longest shadow then</dt><dd>{p.max_dark_gap_h > 0 ? <>{fmtNum(p.max_dark_gap_h, 0)}<small>h</small></> : "none"}</dd></div>}
      </dl>
      <p className="table-note">
        <a href={`#3d?scene=region&pt=${p.lat},${p.lon}${p.best_slot ? `&t=${p.best_slot}` : ""}`}>See this point in 3D{p.best_slot ? " at its best landing slot" : ""}</a>
      </p>
      {p.runs.length > 0 && (
        <p className="table-note">
          Landing slots: {p.runs.slice(0, 6).map(([a, b]) => `${fmtShortDay(utc(a))}${a.slice(0, 10) !== b.slice(0, 10) ? `–${fmtShortDay(utc(b))}` : ""}`).join(", ")}
          {p.runs.length > 6 ? ", …" : ""}.
        </p>
      )}
    </div>
  );
}

function RegionMap({ data, layer, top, passing, selected, onSelect, dark }: {
  data: ForecastFile; layer: Layer; top: RegionPoint[]; passing: Set<string>; selected: RegionPoint | null;
  onSelect: (p: RegionPoint) => void; dark: boolean;
}) {
  const r = data.region!;
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<RegionPoint | null>(null);
  const L = LAYERS[layer];
  const size = Math.min(width, 520);
  const pad = 6;
  const inner = Math.max(0, size - 2 * pad);
  const half = r.grid.half_km + r.grid.step_km / 2;
  const sx = (km: number) => pad + ((km + half) / (2 * half)) * inner;
  const cell = (r.grid.step_km / (2 * half)) * inner;
  const vals = r.points.map(L.get).filter((v): v is number => v !== null);
  const domain = (vals.length ? extent(vals) : [0, 1]) as [number, number];
  const { fill, legend } = goodFill(domain, L.better, dark);
  const [pdx, pdy] = r.grid.pole_direction;
  const show = hover ?? null;
  return (
    <div ref={ref} className="chart region-map">
      {width > 0 && (
        <svg width={size} height={size} role="img" aria-label={`${L.label} over the region`}>
          <defs>
            <pattern id="rg-hatch" width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <line x1="0" y1="0" x2="0" y2="4" stroke="var(--rule)" strokeWidth="1.6" />
            </pattern>
            <pattern id="rg-fail" width="4" height="4" patternUnits="userSpaceOnUse">
              <circle cx="2" cy="2" r="0.9" fill="var(--surface)" opacity="0.9" />
            </pattern>
          </defs>
          {r.points.map((p) => {
            const v = L.get(p);
            const x0 = sx(p.x_km) - cell / 2, y0 = sx(p.y_km) - cell / 2;
            const fails = v !== null && p.best_daylight_days !== null && !passing.has(`${p.i},${p.j}`);
            return (
              <g key={`${p.i},${p.j}`} className="cell" onPointerEnter={() => setHover(p)} onPointerLeave={() => setHover(null)}
                onClick={() => onSelect(p)}>
                <rect x={x0} y={y0} width={cell + 0.5} height={cell + 0.5} fill={v === null ? "url(#rg-hatch)" : fill(v)} />
                {fails && <rect x={x0} y={y0} width={cell + 0.5} height={cell + 0.5} fill="url(#rg-fail)" />}
              </g>
            );
          })}
          {r.landmarks.map((l) => Math.abs(l.x_km) <= half && Math.abs(l.y_km) <= half && (
            <g key={l.label} className="landmark" transform={`translate(${sx(l.x_km)},${sx(l.y_km)})`}>
              <path d="M-5,0 H5 M0,-5 V5" />
              <text x={sx(l.x_km) > size * 0.6 ? -7 : 7} y={-6} textAnchor={sx(l.x_km) > size * 0.6 ? "end" : "start"}>{l.label}</text>
            </g>
          ))}
          {r.references.map((p) => (
            <g key={p.label} className="ref-mark" transform={`translate(${sx(p.x_km)},${sx(p.y_km)})`}>
              <circle r={6} />
              <text x={sx(p.x_km) > size * 0.6 ? -9 : 9} y={15} textAnchor={sx(p.x_km) > size * 0.6 ? "end" : "start"}>
                {p.label?.includes("IM-2") ? "IM-2 Athena touchdown" : p.label}</text>
            </g>
          ))}
          {top.map((p, k) => (
            <g key={`t${p.i},${p.j}`} className={`top-mark${selected === p ? " sel" : ""}`} transform={`translate(${sx(p.x_km)},${sx(p.y_km)})`}
              onClick={() => onSelect(p)}>
              <circle r={8} />
              <text y={3.5} textAnchor="middle">{k + 1}</text>
            </g>
          ))}
          {selected && !top.includes(selected) && (
            <circle cx={sx(selected.x_km)} cy={sx(selected.y_km)} r={7} fill="none" stroke="var(--signal)" strokeWidth={2.5} />
          )}
          <g className="scale-bar" transform={`translate(${pad + 8},${size - 14})`}>
            <line x1={0} x2={(10 / (2 * half)) * inner} y1={0} y2={0} />
            <text x={(5 / (2 * half)) * inner} y={-5} textAnchor="middle">10 km</text>
          </g>
        </svg>
      )}
      {show && (
        <div className="tooltip" style={{ left: sx(show.x_km), top: sx(show.y_km) - 4 }}>
          <strong>{L.get(show) === null ? "–" : `${fmtNum(L.get(show)!, L.digits)} ${L.unit}`}</strong>
          {coord(show.lat, show.lon)}
          <div className="sub">
            {show.best_daylight_days !== null ? `slot ${fmtShortDay(utc(show.best_slot!))}, ${days(show.best_daylight_days)} sunlight` : "no landing slot"}, slope {fmtNum(show.slope_deg, 1)}°
          </div>
        </div>
      )}
      <Legend domain={legend} label={`${L.label} (${L.unit})`} digits={L.digits} dark={dark}
        note={`${L.better === "high" ? "Lighter is better." : "Lighter is flatter."} Hatched: no landing slot. Dotted: outside the slope / Earth limits. Numbers: best places.`} />
      <p className="orbit-note map-orient">
        <svg width="18" height="18" viewBox="-9 -9 18 18" aria-hidden="true">
          <line x1={-pdx * 7} y1={-pdy * 7} x2={pdx * 7} y2={pdy * 7} />
          <path d={`M${pdx * 7},${pdy * 7} l${-pdx * 4 - pdy * 3},${-pdy * 4 + pdx * 3} M${pdx * 7},${pdy * 7} l${-pdx * 4 + pdy * 3},${-pdy * 4 - pdx * 3}`} />
        </svg>
        towards the south pole. LOLA polar stereographic map, north is away from the pole.
      </p>
    </div>
  );
}
