import { extent } from "d3-array";
import { scaleLinear, scaleUtc } from "d3-scale";
import { utcFormat } from "d3-time-format";
import { useMemo, useState } from "react";
import { sequential } from "../lib/color";
import { familyName, fmtDay, fmtDayTime, fmtNum, fmtShortDay, fmtTof, parseUtc } from "../lib/format";
import { useWidth } from "../lib/hooks";
import type { MissionValidation, NasaComparison, ScanDay, TerrainCheck, TestSummary, ThermalFile, DivinerDiagnosticsFile, DivinerPolarFile, OrientationFile, ValidationCheck, ValidationFile } from "../types";
import { Legend } from "./Legend";
import { divinerChecks, DivinerPolarSection } from "./DivinerPolarSection";
import { orientationChecks, OrientationSection } from "./OrientationSection";
import { thermalChecks, ThermalValidationSection } from "./ThermalSection";

const DAY_MS = 86400e3;
const tickFmt = utcFormat("%-d %b");
const dayMs = (d: string) => Date.parse(`${d.slice(0, 10)}T00:00:00Z`);
const utc = (s: string) => parseUtc(s.endsWith("Z") || s.includes("+") ? s : `${s}Z`);
const ephLabel = (e: string) => (e.includes("spice") ? "JPL DE440" : "analytic ephemeris (demo)");

export function ValidationPage({ data, dark, thermal, diviner, divinerDiag, orientation = [] }: {
  data: ValidationFile | null; dark: boolean; thermal?: ThermalFile | null; diviner?: DivinerPolarFile | null;
  divinerDiag?: DivinerDiagnosticsFile | null; orientation?: OrientationFile[];
}) {
  if (!data) {
    return (
      <div className="validation">
        <p className="empty">
          No validation data yet. Build it with <code>python scripts/build_validation.py --spice --tests</code> and reload.
        </p>
      </div>
    );
  }
  const all = [
    ...data.missions.flatMap((m) => m.checks),
    ...(data.nasa ? nasaChecks(data.nasa) : []),
    ...(data.terrain ? terrainChecks(data.terrain) : []),
    ...(data.tests ? [testCheck(data.tests)] : []),
    ...(thermal ? thermalChecks(thermal) : []),
    ...(diviner ? divinerChecks(diviner) : []),
    ...orientationChecks(orientation),
  ];
  const passed = all.filter((c) => c.pass).length;
  return (
    <div className="validation">
      <section className="panel val-intro">
        <div className="panel-body">
          <p className="val-lede">
            <strong>{passed} of {all.length} checks pass.</strong> The browser is tested against the NASA Ames
            Lunar Browser's published solution space, against NASA Goddard's polar illumination map (for the LOLA terrain
            horizons), against two CLPS landers that actually flew (it is told the site, the launch and orbit-insertion
            times and the orbit altitude, never when or how the lander came down), and by its own test suite.
          </p>
          <p className="sub">
            Built {fmtDay(parseUtc(data.meta.generated_utc))} with engine v{data.meta.engine_version}, {ephLabel(data.meta.ephemeris)}.
            {data.meta.ephemeris.includes("spice") ? "" : " Rebuild with --spice for the real Moon orbit; numbers below will move by a few percent."}
          </p>
        </div>
      </section>

      {data.nasa && <NasaSection nasa={data.nasa} dark={dark} />}
      {data.terrain && <TerrainSection t={data.terrain} />}
      {orientation.length > 0 && <OrientationSection files={orientation} checks={(c) => <Checks checks={c} />} />}
      {thermal && <ThermalValidationSection t={thermal} checks={(c) => <Checks checks={c} />} />}
      {diviner && <DivinerPolarSection d={diviner} diag={divinerDiag} checks={(c) => <Checks checks={c} />} />}
      {data.missions.map((m) => <MissionSection key={m.mission.id} v={m} dark={dark} />)}
      {data.tests && <TestsSection t={data.tests} />}
    </div>
  );
}

function nasaChecks(n: NasaComparison): ValidationCheck[] {
  const worst = Math.max(...n.minima.map((m) => Math.abs(m.days_apart)));
  const checks: ValidationCheck[] = [
    { id: "nasa-band", label: "LOI band within 10 m/s of NASA's at both ends",
      pass: Math.abs(n.band_error_ms[0]) <= 10 && Math.abs(n.band_error_ms[1]) <= 10 },
    { id: "nasa-minima", label: "Monthly minima within one grid step of NASA's dates",
      pass: worst <= (n.grid_days ?? 1) },
  ];
  if (n.dense_minimum) {
    checks.push({ id: "nasa-dense", label: "Dense-sweep minimum within 1% of NASA's", pass: Math.abs(n.dense_minimum.error_pct) <= 1 });
  }
  return checks;
}

const SITE_NAMES: Record<string, string> = { "malapert-a": "Malapert A", "mons-mouton": "Mons Mouton" };
const siteName = (id: string) => SITE_NAMES[id] ?? id;

function terrainChecks(t: TerrainCheck): ValidationCheck[] {
  return t.sites.map((r) => ({
    id: `terrain-${r.site}`, pass: r.pass,
    label: `Average sunlight from our ${siteName(r.site)} horizon matches NASA's map (median ≤ ${Math.round(t.tolerance.median_abs * 100)}, max ≤ ${Math.round(t.tolerance.max_abs * 100)} points)`,
  }));
}

function testCheck(t: TestSummary): ValidationCheck {
  return { id: "tests", label: "Engine test suite", pass: t.failed === 0 && t.passed > 0 };
}

function Checks({ checks }: { checks: ValidationCheck[] }) {
  return (
    <ul className="checks">
      {checks.map((c) => (
        <li key={c.id} className={c.pass ? "ok" : "bad"}>
          <span className="mark" aria-hidden="true">{c.pass ? "✓" : "✗"}</span>
          <span className="sr-only">{c.pass ? "Pass:" : "Fail:"}</span> {c.label}
        </li>
      ))}
    </ul>
  );
}

// --- NASA Ames comparison ----------------------------------------------------------
function NasaSection({ nasa, dark }: { nasa: NasaComparison; dark: boolean }) {
  const r = nasa.reference;
  return (
    <section className="panel" aria-labelledby="nasa-title">
      <div className="panel-head">
        <h2 id="nasa-title">Against NASA Ames: LOI Δv by launch date, Dec 2025 to Mar 2026</h2>
        <span className="hint">{nasa.count} transfers, {ephLabel(nasa.ephemeris)}</span>
      </div>
      <div className="panel-body val-grid">
        <div>
          <NasaChart nasa={nasa} dark={dark} />
        </div>
        <div>
          <Checks checks={nasaChecks(nasa)} />
          <dl className="figures two">
            <div><dt>Our LOI band</dt><dd>{fmtNum(nasa.band_ms[0], 0)}–{fmtNum(nasa.band_ms[1], 0)}<small>m/s</small></dd></div>
            <div><dt>NASA's band</dt><dd>~{fmtNum(r.loi_min_ms, 0)}–{fmtNum(r.loi_max_ms, 0)}<small>m/s</small></dd></div>
            {nasa.dense_minimum && <>
              <div><dt>Dense-sweep minimum</dt><dd>{fmtNum(nasa.dense_minimum.loi_dv_ms, 1)}<small>m/s</small></dd></div>
              <div><dt>Difference from NASA</dt><dd>{fmtNum(nasa.dense_minimum.error_pct, 1)}<small>%</small></dd></div>
            </>}
          </dl>
          <div className="table-wrap">
            <table>
              <thead><tr><th className="left">Month</th><th className="left">NASA minimum</th><th className="left">Ours</th><th>Apart</th></tr></thead>
              <tbody>
                {nasa.minima.map((m) => (
                  <tr key={m.month} className="static">
                    <td className="left">{utcFormat("%b %Y")(utc(`${m.month}-01T00:00:00Z`))}</td>
                    <td className="left">{fmtShortDay(utc(m.nasa_date))}, ~{fmtNum(m.nasa_loi_dv_ms, 0)}</td>
                    <td className="left">{fmtShortDay(utc(m.our_date))}, {fmtNum(m.our_loi_dv_ms, 0)} <span className="sub-cell inline">{fmtTof(m.our_tof_days)}</span></td>
                    <td>{m.days_apart > 0 ? "+" : ""}{m.days_apart} d</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="table-note">
            NASA publishes the figure, not its data: reference values were {r.read_accuracy}. Our sweep has one launch date
            every {nasa.grid_days} days, so our minima can sit up to {nasa.grid_days} days from the true trough and a few m/s above it (the dense sweep
            finds {nasa.dense_minimum ? fmtNum(nasa.dense_minimum.loi_dv_ms, 1) : "a lower value"} where the grid finds {fmtNum(nasa.band_ms[0], 1)}).
            The 10 m/s band tolerance covers that and the reading error. Source: {r.source}.
          </p>
        </div>
      </div>
    </section>
  );
}

function NasaChart({ nasa, dark }: { nasa: NasaComparison; dark: boolean }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const M = { top: 26, right: 12, bottom: 34, left: 48 };
  const H = 320;
  const innerW = Math.max(0, width - M.left - M.right), innerH = H - M.top - M.bottom;
  const r = nasa.reference;
  const pts = nasa.points;
  const tofDomain = extent(pts, (p) => p.tof) as [number, number];
  const color = sequential(tofDomain, dark);
  const x = scaleUtc().domain([dayMs(r.window[0]), dayMs(r.window[1])]).range([0, innerW]);
  const lo = Math.min(r.loi_min_ms, ...pts.map((p) => p.loi)) - 8;
  const hi = Math.max(r.loi_max_ms, ...pts.map((p) => p.loi)) + 8;
  const y = scaleLinear().domain([lo, hi]).nice().range([innerH, 0]);
  const ours = nasa.minima.map((m) => ({ t: dayMs(m.our_date), v: m.our_loi_dv_ms }));
  return (
    <div ref={ref} className="chart">
      {width > 0 && (
        <svg width={width} height={H} role="img" aria-label="Our LOI delta-v against launch date with NASA's band and minima">
          <g transform={`translate(${M.left},${M.top})`}>
            {y.ticks(6).map((v) => (
              <g key={v} className="axis">
                <line className="gridline" x1={0} x2={innerW} y1={y(v)} y2={y(v)} />
                <text x={-8} y={y(v) + 4} textAnchor="end">{fmtNum(v, 0)}</text>
              </g>
            ))}
            <g className="axis" transform={`translate(0,${innerH + 18})`}>
              {x.ticks(Math.max(2, Math.floor(innerW / 80))).map((d) => <text key={+d} x={x(d)} textAnchor="middle">{tickFmt(d)}</text>)}
            </g>
            <text className="axis-title" x={-M.left + 2} y={-12}>LOI Δv (m/s)</text>
            {[r.loi_min_ms, r.loi_max_ms].map((v) => (
              <g key={v} className="ref-line">
                <line x1={0} x2={innerW} y1={y(v)} y2={y(v)} />
                <text x={v === r.loi_min_ms ? 4 : innerW} y={v === r.loi_min_ms ? y(v) + 14 : y(v) - 5} textAnchor={v === r.loi_min_ms ? "start" : "end"}>
                  NASA {v === r.loi_min_ms ? "lowest" : "highest"} ~{fmtNum(v, 0)}</text>
              </g>
            ))}
            {pts.map((p, i) => (
              <circle key={i} cx={x(dayMs(p.tli))} cy={y(p.loi)} r={3.6} fill={color(p.tof)} stroke="var(--surface)" strokeWidth={1.2} />
            ))}
            {ours.map((o) => <circle key={o.t} className="ring-best" cx={x(o.t)} cy={y(o.v)} r={7.5} />)}
            {r.minima.map((m) => {
              const cx = x(dayMs(m.date)), cy = y(m.loi_dv_ms);
              return <path key={m.date} className="nasa-mark" d={`M${cx - 6},${cy} H${cx + 6} M${cx},${cy - 6} V${cy + 6}`} />;
            })}
          </g>
        </svg>
      )}
      <Legend domain={tofDomain} label="Transit time (days)" digits={0} dark={dark} format={(v) => fmtTof(v)}
        note="+ NASA's monthly minimum, read off the published figure. Ring: our lowest transfer that month." />
    </div>
  );
}

// --- flown missions -------------------------------------------------------------------
function MissionSection({ v, dark }: { v: MissionValidation; dark: boolean }) {
  const m = v.mission, li = v.lighting_at_landing, rc = v.reconstruction, sc = v.scan;
  const lt = li.terrain ?? null;
  const days = (d: number | null | undefined) => (d != null ? fmtNum(d, 1) : "–");
  const tuned = rc.tuned;
  const polar = rc.polar.find((d) => d.family === 1) ?? rc.polar[0] ?? rc.tuned ?? null;   // reference design (polar if tried)
  const polarSite = Math.abs(m.lat_deg) >= 75;
  const incs = rc.curve.map((p) => p.inc);
  const incLo = incs.length ? Math.min(...incs) : 80, incHi = incs.length ? Math.max(...incs) : 100;
  const launchWin = sc.real_windows.find((w) => w.first <= sc.launch_day && sc.launch_day <= w.last) ?? sc.real_windows[sc.real_windows.length - 1];
  return (
    <section className="panel mission" aria-labelledby={`m-${m.id}`}>
      <div className="panel-head">
        <h2 id={`m-${m.id}`}>{m.name}: {m.site_name}</h2>
        <span className="hint">{fmtNum(Math.abs(m.lat_deg), 2)}°{m.lat_deg < 0 ? "S" : "N"} {fmtNum(Math.abs(m.lon_deg), 2)}°{m.lon_deg < 0 ? "W" : "E"}, {ephLabel(v.ephemeris)}</span>
      </div>
      <div className="panel-body val-grid">
        <div>
          <p className="val-story">
            Launched {fmtDay(utc(m.launch_utc))}, in lunar orbit {fmtDayTime(utc(m.loi_utc))}, touched down{" "}
            {fmtDayTime(utc(m.landing_utc))}. {!m.launch_windows.length ? <>{m.scan_note}</> : launchWin?.predicted
              ? <>The browser, told only the site, finds a launch window from {fmtShortDay(utc(launchWin.predicted.first))} to{" "}
                  {fmtShortDay(utc(launchWin.predicted.last))} ({launchWin.predicted.days} days); the real window,{" "}
                  {fmtShortDay(utc(launchWin.first))} to {fmtShortDay(utc(launchWin.last))}, sits inside it.</>
              : <>The real launch window is not inside a predicted window.</>}
            {m.wait_note && <> {m.wait_note}</>}
            {sc.on_launch_day?.landing_utc && sc.landing_miss_days != null && <>
              {" "}{m.launch_windows.length ? "Launching on the real day" : "From the real TLI day"}, the browser's cheapest option touches down{" "}
              <strong>{fmtDayTime(utc(sc.on_launch_day.landing_utc))}</strong>, {fmtNum(Math.abs(sc.landing_miss_days) * 24, 0)} hours{" "}
              {sc.landing_miss_days < 0 ? "before" : "after"} the real landing.
              {sc.landing_miss_days < -1 && (lt ? lt.sun_clear_deg : li.sun_elev_deg) > 1.5 && <> The browser goes down as soon as the
                Sun is 0.5° above the {lt ? "terrain" : "horizon"}; the real lander waited for a higher Sun
                ({fmtNum(lt ? lt.sun_clear_deg : li.sun_elev_deg, 1)}° above the {lt ? "terrain" : "horizon"} at touchdown).</>}</>}
            {sc.on_launch_day?.feasible && !sc.on_launch_day.feasible_polar && polarSite && <>
              {" "}A strictly polar orbit could not have landed from that launch day; the orbit has to be tilted a few degrees.</>}
          </p>
          <ScanStrip v={v} dark={dark} />
          <dl className="figures">
            <div><dt>Sun at real touchdown</dt><dd>{fmtNum(li.sun_elev_deg, 1)}°<small>{li.sun_rising ? "rising" : "setting"}</small></dd></div>
            {lt
              ? <div><dt>Above the LOLA terrain</dt><dd>{fmtNum(lt.sun_clear_deg, 1)}°<small>terrain {fmtNum(lt.horizon_sun_deg, 1)}°</small></dd></div>
              : <div><dt>Earth at real touchdown</dt><dd>{fmtNum(li.earth_elev_deg, 1)}°</dd></div>}
            <div><dt>Since local sunrise{lt ? " (terrain)" : ""}</dt><dd>{days(lt ? lt.days_since_sunrise : li.days_since_sunrise)}<small>days</small></dd></div>
            <div><dt>Sunlight left</dt><dd>{days(lt ? lt.daylight_left_days : li.daylight_left_days)}<small>{lt ? `days (flat horizon ${days(li.daylight_left_days)})` : "days, flat horizon"}</small></dd></div>
            {v.sunset && <div><dt>Sunset, ours / real</dt><dd className="dd-text">
              {v.sunset.predicted_utc ? fmtDayTime(utc(v.sunset.predicted_utc)) : "–"}<small> / {fmtDayTime(utc(v.sunset.real_utc))}
              {v.sunset.hours_off != null && ` (${v.sunset.hours_off > 0 ? "+" : ""}${fmtNum(v.sunset.hours_off, 1)} h)`}</small></dd></div>}
            <div><dt>Surface operations flown</dt><dd>{v.surface_days_flown != null ? fmtNum(v.surface_days_flown, 1) : "–"}<small>days</small></dd></div>
            <div><dt>LOI Δv, ours / reported</dt><dd>{polar ? fmtNum(polar.loi_dv_ms, 0) : "–"}<small>/ {m.loi_dv_ms ?? "n/a"} m/s</small></dd></div>
          </dl>
          <p className="table-note">
            {li.dsn_stations && <>DSN at the real touchdown (10° mask): {li.dsn_stations.length ? li.dsn_stations.join(", ") : "none"}. </>}
            {m.surface_end_note}
          </p>
        </div>
        <div>
          <Checks checks={v.checks} />
          <h3 className="val-h3">Which capture orbit lands at the real touchdown time?</h3>
          <IncChart v={v} />
          <p className="table-note">
            Arrival designed with the real TLI ({fmtDayTime(utc(m.tli_utc))}) and transit time ({fmtNum(polar?.tof_days ?? 0, 2)} d),
            for every capture inclination from {fmtNum(incLo, 0)}° to {fmtNum(incHi, 0)}°.{" "}
            {tuned?.at_real_landing && <>Best: {fmtNum(tuned.lunar_inc_deg, 0)}°, {familyName(tuned.family).toLowerCase()}, needing{" "}
              {fmtNum(tuned.at_real_landing.plane_change_ms, 0)} m/s of plane change at the real touchdown; </>}
            {polar?.at_real_landing && <>a strictly polar orbit would need {fmtNum(polar.at_real_landing.plane_change_ms, 0)} m/s. </>}
            LOI Δv stays within {rc.loi_dv_range_ms ? fmtNum(rc.loi_dv_range_ms[1] - rc.loi_dv_range_ms[0], 0) : "–"} m/s across
            the band, so the tilt is free. {polarSite
              ? "Because a polar site lies only a few degrees from the pole, some tilt in the band always brings it under the track; the date is set by sunlight, which is what the window scan tests."
              : "The inclination was not published; any orbit tilted more than the site's latitude passes over it twice a month."}
          </p>
          <details className="sources">
            <summary>Mission data and sources</summary>
            <ul>
              <li>{m.tli_note}</li>
              <li>{m.loi_note}</li>
              <li>{m.orbit_note}</li>
              {m.launch_windows.map(([a, b, note]) => <li key={a}>{fmtShortDay(utc(a))}–{fmtShortDay(utc(b))}: {note}</li>)}
              {m.sunset_note && <li>{m.sunset_note}</li>}
              {m.sources.map(([label, url]) => <li key={url}><a href={url} target="_blank" rel="noreferrer">{label}</a></li>)}
            </ul>
          </details>
        </div>
      </div>
    </section>
  );
}

function ScanStrip({ v, dark }: { v: MissionValidation; dark: boolean }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<ScanDay | null>(null);
  const sc = v.scan;
  const days = sc.days;
  const M = { top: 30, right: 8, bottom: 22, left: 8 };
  const ROW = 22, GAP = 18;
  const H = M.top + 2 * ROW + GAP + M.bottom + 14;
  const innerW = Math.max(0, width - M.left - M.right);
  const t0 = dayMs(days[0].tli_day), t1 = dayMs(days[days.length - 1].tli_day) + DAY_MS;
  const x = scaleUtc().domain([t0, t1]).range([0, innerW]);
  const cw = Math.max(1, x(t0 + DAY_MS) - x(t0) - 1);
  const vals = days.filter((d) => d.total_from_loi_ms !== null).map((d) => d.total_from_loi_ms!);
  const domain = useMemo(() => (vals.length ? (extent(vals) as [number, number]) : ([0, 1] as [number, number])), [vals.join()]);
  const color = sequential(domain[0] === domain[1] ? [domain[0], domain[0] + 1] : domain, dark);
  const launch = dayMs(sc.launch_day);
  const rows: { label: string; y: number; ok: (d: ScanDay) => boolean }[] = [
    { label: `Orbits tried, ${fmtNum(Math.min(...sc.incs), 0)}–${fmtNum(Math.max(...sc.incs), 0)}°`, y: 0, ok: (d) => d.feasible },
    { label: "Strictly polar orbit, 90°", y: ROW + GAP, ok: (d) => d.feasible_polar },
  ];
  return (
    <div ref={ref} className="chart scan-strip">
      {width > 0 && (
        <svg width={width} height={H} role="img" aria-label={`Launch dates from which ${v.mission.site_name} can be reached`}>
          <defs>
            <pattern id={`hatch-${v.mission.id}`} width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <line x1="0" y1="0" x2="0" y2="5" stroke="var(--rule)" strokeWidth="2" />
            </pattern>
          </defs>
          <g transform={`translate(${M.left},${M.top})`}>
            {sc.real_windows.filter((w) => dayMs(w.last) >= t0 && dayMs(w.first) < t1).map((w) => {
              const a = Math.max(0, x(dayMs(w.first))), b = Math.min(innerW, x(dayMs(w.last)) + cw);
              return (
                <g key={w.first} className="bracket real">
                  <path d={`M${a},-6 V-12 H${b} V-6`} />
                  <text x={(a + b) / 2} y={-16} textAnchor="middle">real window</text>
                </g>
              );
            })}
            {rows.map((row) => (
              <g key={row.label} transform={`translate(0,${row.y})`}>
                {days.map((d) => (
                  <rect key={d.tli_day} className="cell" x={x(dayMs(d.tli_day))} width={cw} height={ROW}
                    fill={row.ok(d) ? (row.y === 0 && d.total_from_loi_ms !== null ? color(d.total_from_loi_ms) : "var(--ink-3)") : `url(#hatch-${v.mission.id})`}
                    onPointerEnter={() => setHover(d)} onPointerLeave={() => setHover(null)} />
                ))}
                <text className="row-label" x={2} y={ROW + 12}>{row.label}</text>
              </g>
            ))}
            {launch >= t0 && launch < t1 && <path className="launch-mark" d={`M${x(launch) + cw / 2},-4 V${2 * ROW + GAP + 2}`} />}
            <g className="axis" transform={`translate(0,${2 * ROW + GAP + 30})`}>
              {x.ticks(Math.max(2, Math.floor(innerW / 80))).map((d) => <text key={+d} x={x(d)} textAnchor="middle">{tickFmt(d)}</text>)}
            </g>
          </g>
        </svg>
      )}
      {hover && (
        <div className="tooltip" style={{ left: M.left + x(dayMs(hover.tli_day)) + cw / 2, top: M.top }}>
          <strong>TLI {fmtDay(utc(hover.tli_day))}</strong>
          {hover.feasible && hover.landing_utc
            ? <>touchdown {fmtDayTime(utc(hover.landing_utc))}
                <div className="sub">{fmtTof(hover.tof_days!)} transit, {fmtNum(hover.lunar_inc_deg!, 0)}° orbit, wait {fmtNum(hover.wait_days!, 1)} d, sunlight {fmtNum(hover.daylight_days!, 1)} d</div></>
            : <>no landing within {sc.constraints.max_wait_days} days of arrival<div className="sub">{whyNot(hover.why_not)}</div></>}
        </div>
      )}
      <Legend domain={domain} label="LOI + Δv to surface (m/s)" digits={0} dark={dark}
        note={`Vertical line: real launch. Each day tries ${sc.tofs.length} transit times × ${sc.incs.length} inclinations; landing within ${sc.constraints.max_wait_days} days, Sun up and rising, Earth in view, plane change ≤ ${sc.constraints.max_plane_change_ms} m/s.`} />
    </div>
  );
}

function whyNot(codes: string): string {
  const t: Record<string, string> = { sun: "the Sun is not up and rising", earth: "Earth not in view", plane: "plane change over budget" };
  return codes.split(",").filter(Boolean).map((c) => t[c] ?? c).join("; ");
}

function IncChart({ v }: { v: MissionValidation }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const M = { top: 14, right: 12, bottom: 32, left: 44 };
  const H = 190;
  const innerW = Math.max(0, width - M.left - M.right), innerH = H - M.top - M.bottom;
  const pts = v.reconstruction.curve.filter((p) => p.plane_ms !== null) as { inc: number; family: number; plane_ms: number }[];
  if (!pts.length) return <p className="orbit-note">The real touchdown is outside the reconstructed wait.</p>;
  const budget = v.scan.constraints.max_plane_change_ms;
  const lo = Math.min(...v.reconstruction.curve.map((p) => p.inc)), hi = Math.max(...v.reconstruction.curve.map((p) => p.inc));
  const x = scaleLinear().domain([lo, hi]).range([0, innerW]);
  const y = scaleLinear().domain([0, Math.max(budget * 1.2, ...pts.map((p) => p.plane_ms))]).nice().range([innerH, 0]);
  const fams = [...new Set(pts.map((p) => p.family))].sort((a, b) => b - a);
  return (
    <div ref={ref} className="chart">
      {width > 0 && (
        <svg width={width} height={H} role="img" aria-label="Plane change at the real touchdown against capture inclination">
          <g transform={`translate(${M.left},${M.top})`}>
            {y.ticks(4).map((t) => (
              <g key={t} className="axis">
                <line className="gridline" x1={0} x2={innerW} y1={y(t)} y2={y(t)} />
                <text x={-8} y={y(t) + 4} textAnchor="end">{fmtNum(t, 0)}</text>
              </g>
            ))}
            <g className="axis" transform={`translate(0,${innerH + 16})`}>
              {x.ticks(5).map((t) => <text key={t} x={x(t)} textAnchor="middle">{t}°</text>)}
              <text className="axis-title" x={innerW} y={14} textAnchor="end">Capture inclination</text>
            </g>
            <text className="axis-title" x={-M.left + 2} y={-3}>Plane change (m/s)</text>
            <g className="ref-line">
              <line x1={0} x2={innerW} y1={y(budget)} y2={y(budget)} />
              <text x={innerW} y={y(budget) - 5} textAnchor="end">budget {budget}</text>
            </g>
            {fams.map((f) => {
              const s = pts.filter((p) => p.family === f).sort((a, b) => a.inc - b.inc);
              return (
                <g key={f} className={f > 0 ? "series-a" : "series-b"}>
                  <path d={s.map((p, i) => `${i ? "L" : "M"}${x(p.inc)},${y(p.plane_ms)}`).join("")} />
                  {s.map((p) => <circle key={p.inc} cx={x(p.inc)} cy={y(p.plane_ms)} r={2.6} />)}
                  {s.length > 0 && (
                    <text x={x(s[0].inc) + 6} y={y(s[0].plane_ms) + (s[0].plane_ms > y.domain()[1] * 0.85 ? 14 : -8)} textAnchor="start">{familyName(f)}</text>
                  )}
                </g>
              );
            })}
          </g>
        </svg>
      )}
    </div>
  );
}

// --- terrain vs NASA illumination ----------------------------------------------------------
function TerrainSection({ t }: { t: TerrainCheck }) {
  const pct = (v: number) => `${fmtNum(v * 100, 1)}`;
  return (
    <section className="panel" aria-labelledby="terrain-title">
      <div className="panel-head">
        <h2 id="terrain-title">LOLA terrain horizons against NASA's polar illumination map</h2>
        <span className="hint">{t.dem}{t.ephemeris ? `, ${ephLabel(t.ephemeris)}` : ""}</span>
      </div>
      <div className="panel-body val-grid">
        <div>
          <p className="val-story">
            Near the pole the surrounding relief, not a flat horizon, decides when a site is lit. The browser computes each
            polar site's horizon from LOLA {t.dem} (every {t.az_step_deg}° of azimuth, terrain out to {t.max_dist_km} km,
            with the Moon's curvature) and measures the Sun and Earth above it. To check the horizons independently, the
            fraction of time the Sun is up over an 18.6-year cycle{t.span_utc ? ` (${t.span_utc[0]} to ${t.span_utc[1]}, hourly)` : ""} is
            computed from them and compared with NASA Goddard's map of the same quantity on the same grid
            ({t.avg_map ?? "AVGVISIB_75S_120M"}, Mazarico et al. 2011), at a 5 × 5 grid of pixels around each site. A wrong
            map orientation or horizon would show up as large differences.
          </p>
          {t.sites.length > 0 && <IllumChart t={t} />}
        </div>
        <div>
          <Checks checks={terrainChecks(t)} />
          <div className="table-wrap">
            <table>
              <thead><tr><th className="left">Site</th><th>NASA range (%)</th><th>Median |Δ|</th><th>Max |Δ|</th><th>Bias</th><th>r</th></tr></thead>
              <tbody>
                {t.sites.map((r) => (
                  <tr key={r.site} className="static">
                    <td className="left">{siteName(r.site)}<span className="sub-cell">{r.n} pixels, {fmtNum(r.spacing_m / 1000, 2)} km apart</span></td>
                    <td>{pct(r.nasa_range[0])}–{pct(r.nasa_range[1])}</td>
                    <td>{pct(r.median_abs_diff)}</td><td>{pct(r.max_abs_diff)}</td>
                    <td>{r.mean_diff > 0 ? "+" : ""}{pct(r.mean_diff)}</td>
                    <td>{r.correlation != null ? fmtNum(r.correlation, 2) : "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="table-note">
            Differences in percentage points of time. Pass criteria (median ≤ {pct(t.tolerance.median_abs)}, max ≤ {pct(t.tolerance.max_abs)})
            were fixed in the code before the comparison was first run. Same rule as NASA's map: lit when any part of the Sun's
            disc clears the terrain; observer on the surface for this check, {t.observer_m} m above it for landing.
          </p>
          {t.resolution && (
            <p className="table-note">
              Resolution: the same horizons from the finer map differ by{" "}
              {Object.entries(t.resolution).map(([k, r]) => `${fmtNum(r.rms_deg, 2)}° rms at ${siteName(k)}`).join(", ")}.
            </p>
          )}
          {t.orientation_diagnostic && (
            <p className="table-note">
              Orientation diagnostic (median |Δ| at the central pixels, per site):{" "}
              {t.orientation_diagnostic.map((d) => `x ${d.x_sign > 0 ? "+" : "−"}, y ${d.y_sign > 0 ? "+" : "−"}: ${d.median_abs_diff.map(pct).join(" / ")}`).join("; ")}.
            </p>
          )}
        </div>
      </div>
    </section>
  );
}

function IllumChart({ t }: { t: TerrainCheck }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const size = Math.min(width, 340);
  const M = { top: 12, right: 12, bottom: 34, left: 44 };
  const inner = Math.max(0, size - M.left - M.right);
  const pts = t.sites.flatMap((r, si) => r.points.map((p) => ({ ...p, si })));
  const lo = Math.max(0, Math.floor(Math.min(...pts.flatMap((p) => [p.ours, p.nasa])) * 10) / 10 - 0.05);
  const hi = Math.min(1, Math.ceil(Math.max(...pts.flatMap((p) => [p.ours, p.nasa])) * 10) / 10 + 0.05);
  const x = scaleLinear().domain([lo, hi]).range([0, inner]);
  const y = scaleLinear().domain([lo, hi]).range([inner, 0]);
  const tol = t.tolerance.max_abs;
  return (
    <div ref={ref} className="chart">
      {width > 0 && (
        <svg width={size} height={inner + M.top + M.bottom} role="img" aria-label="Our average illumination against NASA's map">
          <g transform={`translate(${M.left},${M.top})`}>
            {x.ticks(5).map((v) => (
              <g key={v} className="axis">
                <line className="gridline" x1={x(v)} x2={x(v)} y1={0} y2={inner} />
                <line className="gridline" x1={0} x2={inner} y1={y(v)} y2={y(v)} />
                <text x={x(v)} y={inner + 14} textAnchor="middle">{Math.round(v * 100)}</text>
                <text x={-6} y={y(v) + 4} textAnchor="end">{Math.round(v * 100)}</text>
              </g>
            ))}
            <path className="tol-band" d={`M${x(lo)},${y(lo + tol)}L${x(hi - tol)},${y(hi)}L${x(hi)},${y(hi)}L${x(hi)},${y(hi - tol)}L${x(lo + tol)},${y(lo)}L${x(lo)},${y(lo)}Z`} />
            <line x1={x(lo)} y1={y(lo)} x2={x(hi)} y2={y(hi)} stroke="var(--ink-2)" strokeDasharray="4 3" />
            {pts.map((p, i) => (
              <circle key={i} cx={x(p.nasa)} cy={y(p.ours)} r={3.4} className={p.si === 0 ? "pt-a" : "pt-b"} />
            ))}
            <text className="axis-title" x={inner} y={inner + 28} textAnchor="end">NASA map: time sunlit (%)</text>
            <text className="axis-title" x={4} y={10}>Ours (%)</text>
          </g>
        </svg>
      )}
      <div className="key">
        {t.sites.map((r, i) => <span key={r.site} className={i === 0 ? "k-pt-a" : "k-pt-b"}>{siteName(r.site)}</span>)}
        <span className="k-tol">Within ± {Math.round(tol * 100)} points</span>
      </div>
    </div>
  );
}

// --- tests ------------------------------------------------------------------------------
function TestsSection({ t }: { t: TestSummary }) {
  const groups = Object.entries(t.groups).sort();
  return (
    <section className="panel" aria-labelledby="tests-title">
      <div className="panel-head">
        <h2 id="tests-title">Engine test suite</h2>
        <span className="hint">Python {t.python}, {fmtNum(t.seconds, 0)} s, run {fmtDay(parseUtc(t.run_utc))}</span>
      </div>
      <div className="panel-body val-grid">
        <div>
          <p className="val-story">
            <strong>{t.passed} passed, {t.failed} failed{t.skipped ? `, ${t.skipped} skipped` : ""}.</strong> The suite checks the
            physics (energy and Jacobi constant conservation, a forward-backward round trip, force budgets), the targeting
            solvers, the transfer designer, the ephemeris cache against its source, the landing geometry, the live API end to
            end, and the retrodiction above.
            {t.skipped ? " Skipped tests need the DE440 kernels and run with --spice." : ""}
          </p>
        </div>
        <div className="table-wrap">
          <table>
            <thead><tr><th className="left">Module</th><th>Passed</th><th>Failed</th><th>Skipped</th></tr></thead>
            <tbody>
              {groups.map(([name, g]) => (
                <tr key={name} className="static">
                  <td className="left">{name.replace(/^test_/, "")}</td><td>{g.pass}</td><td>{g.fail}</td><td>{g.skip}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
