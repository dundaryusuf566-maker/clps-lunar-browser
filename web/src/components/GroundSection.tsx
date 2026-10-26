import { scaleLinear, scaleUtc } from "d3-scale";
import { utcFormat } from "d3-time-format";
import { useEffect, useMemo, useState } from "react";
import { fmtNum } from "../lib/format";
import { useWidth } from "../lib/hooks";
import { download, eventsCsv, fileStem, hourlyCsv, type ExportContext } from "../lib/csvExport";
import type { Sunlight } from "../lib/power";
import { HAYNE2017 } from "../lib/regolith";
import type { Horizon, SiteResult } from "../lib/siteAnalysis";
import { siteTemperatures, startTdb, type ThermalRun } from "../lib/siteThermal";
import type { Ephem, Vec3 } from "../lib/sky";
import { PowerCalculator } from "./PowerBudget";

const tickFmt = utcFormat("%-d %b");
const dtFmt = utcFormat("%-d %b %Y %H:%M");

/** Ground temperature and a power budget at the chosen point, computed in the browser. */
export function GroundSection({ e, r, horizon, demName, tilt, slopeMissing }: {
  e: Ephem; r: SiteResult; horizon?: Horizon; demName?: string;
  tilt?: { normal: Vec3; slopeDeg: number; blockM: number }; slopeMissing?: boolean;
}) {
  const days = Math.round((r.endMs - r.startMs) / 86400e3);
  const [run, setRun] = useState<{ sig: string; run: ThermalRun | null; ms: number; error?: string } | null>(null);
  const sig = `${r.lat}|${r.lon}|${r.startMs}|${days}|${horizon ? "t" : "f"}|${tilt ? tilt.normal.join(",") : "level"}`;
  useEffect(() => {
    let live = true;
    const id = window.setTimeout(() => {          // after the page has painted: the year of spin-up takes ~0.5-1 s
      const tic = performance.now();
      try {
        const out = siteTemperatures(e, r.lat, r.lon, startTdb(r.startMs), days * 24 + 1, { horizon, normal: tilt?.normal, spinUpDays: 365, leadDays: 30, cycles: 6 });
        if (live) setRun({ sig, run: out, ms: performance.now() - tic });
      } catch (err) {
        if (live) setRun({ sig, run: null, ms: 0, error: (err as Error).message });
      }
    }, 30);
    return () => { live = false; window.clearTimeout(id); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [e, sig]);
  const current = run && run.sig === sig ? run : null;

  // where the power budget starts: a landing window, or the start of the period
  const [startKey, setStartKey] = useState("first");
  const starts = useMemo(() => [
    ...r.windows.slice(0, 12).map((w, i) => ({ key: `w${i}`, label: `Landing window ${i + 1}: ${dtFmt(new Date(w.start))} UTC`, ms: w.start })),
    { key: "period", label: "Start of the period", ms: r.startMs },
  ], [r]);
  const start = (startKey === "first" ? starts[0] : starts.find((s) => s.key === startKey)) ?? starts[starts.length - 1];
  const series = useMemo<Sunlight | null>(() => current?.run
    ? { surface_k: current.run.surfaceK, dni_w_m2: current.run.dni, sun_el_deg: current.run.sunEl } : null, [current]);

  const ctx = (): ExportContext => ({
    ephemeris: e.meta.ephemeris, tableGenerated: e.meta.generated_utc,
    horizon: r.terrain ? `LOLA terrain (${demName ?? "horizon grid"}), blended from the 5 km horizon grid` : "level (no terrain)",
    ground: tilt ? `tilted ${tilt.slopeDeg.toFixed(2)} deg, from the ${tilt.blockM.toFixed(0)} m LOLA slope map` : "level",
    pageUrl: window.location.href,
  });
  const stem = fileStem(r);

  return (
    <section className="ground" aria-labelledby="any-ground">
      <div className="downloads" role="group" aria-label="Download the data">
        <span>Download (CSV):</span>
        <button className="btn" disabled={!current?.run} title={current?.run ? "" : "after the temperature run"}
          onClick={() => download(`${stem}_hourly.csv`, hourlyCsv(r, current?.run ?? null, ctx()))}>Hourly series</button>
        <button className="btn" onClick={() => download(`${stem}_events.csv`, eventsCsv(r, ctx()))}>Windows, daylight, eclipses</button>
      </div>
      <h3 id="any-ground">Ground temperature and power</h3>
      {!current ? <p className="table-note">Working out the ground temperature (a year of spin-up, in your browser)…</p>
        : !current.run ? <p className="slip">The temperature run failed: {current.error}</p>
        : (() => {
          const t = current.run, st = t.stats;
          const t0 = t.t[0];
          const startIdx = Math.max(0, Math.min(t.t.length - 1, Math.round((start.ms - t0) / 3600e3)));
          const maxDays = (t.t.length - 1 - startIdx) / 24;
          return (
            <>
              <dl className="figures">
                <div><dt>Surface, coldest</dt><dd>{fmtNum(st.minK, 0)}<small>K ({fmtNum(st.minK - 273.15, 0)} °C)</small></dd></div>
                <div><dt>Surface, hottest</dt><dd>{fmtNum(st.maxK, 0)}<small>K ({fmtNum(st.maxK - 273.15, 0)} °C)</small></dd></div>
                <div><dt>Mean</dt><dd>{fmtNum(st.meanK, 0)}<small>K</small></dd></div>
                <div><dt>Below 150 K</dt><dd>{fmtNum((100 * st.hoursBelow150) / t.t.length, 0)}<small>% of the period</small></dd></div>
                <div><dt>Ground tilt</dt><dd>{t.tilted && tilt ? fmtNum(tilt.slopeDeg, 1) : "level"}<small>{t.tilted && tilt ? `° (LOLA, ${fmtNum(tilt.blockM, 0)} m block)` : "assumed"}</small></dd></div>
              </dl>
              {Math.abs(r.lat) >= 75 && (t.tilted ? (
                <p className="slip">
                  Near the poles treat this curve as approximate. The ground's tilt comes from LOLA here, but the horizon is
                  blended from the 5 km grid. At the 11 Griffin candidate points, against the engine with each point's own
                  horizon, that leaves a mean difference of 5–81 K (median 14.8 K; DE440, scripts/thermal_attribution.py, the
                  same calculation as this page). The large ones are ridge points where the grid hides the Sun for too long
                  (Candidate 1: 81 K, Candidate 4: 46 K). Use the Forecast's temperatures for those points; here, on level
                  ground the browser equals the engine to 0.05 K.
                </p>
              ) : (
                <p className="slip">
                  Near the poles treat this curve as rough: the ground is taken as level
                  {slopeMissing ? " (no LOLA slope map for this point: python scripts/build_slope_map.py)" : ""}. At the 11 Griffin
                  candidate points, where the engine uses each point's own LOLA horizon and the tilt of its ground, level ground
                  and the 5 km horizon grid differ by 11–84 K on average (median 32 K; DE440). With the Sun a few degrees up, a
                  slope of a few degrees doubles or halves the sunlight. Use the Forecast's temperatures for those points.
                </p>
              ))}
              <TempChart t={t} r={r} />
              <p className="table-note">
                Surface temperature from the Hayne et al. (2017) regolith model (<a href={HAYNE2017}>arXiv:1711.00977</a>,
                standard parameters, not fitted), the same code as the engine's (engine/surface/thermal.py; the browser copy
                agrees with it to 10⁻¹² K on test sunlight, web/tests/regolith.check.mjs). Sunlight hourly from the
                {" "}{e.meta.ephemeris} table: the Sun's distance and elevation and the share of its disc above the
                {t.terrain ? ` LOLA horizon (${demName ?? "horizon grid"})` : " level horizon"}.{" "}
                {t.approximate
                  ? "The table does not reach a lunation back before this period, so the soil was spun up on the period's own first lunation: the first days are approximate. "
                  : `Spun up on the point's own sunlight over the ${fmtNum(t.spinUpDays, 0)} days before a 30-day lead-in (deep-soil change in the last pass ${fmtNum(t.spinUpResidualK, 2)} K). `}
                Ground: {t.tilted ? "tilted as the 240 m LOLA slope map says (scripts/build_slope_map.py)" : "level"}.
                Left out: the sunlight and heat the surrounding terrain sends back, which keep shadowed polar ground warmer than
                this; the Forecast's temperature section has it for its candidate sites. Computed in {current.ms < 100 ? "under 0.1" : fmtNum(current.ms / 1000, 1)} s.
              </p>
              <h3>Power budget</h3>
              <p className="val-story">
                A calculator, not a lander: you set the panels, the battery and the loads, and the browser supplies this
                point's sunlight hour by hour. Defaults are generic; the panel starts vertical near the poles, where the Sun stays
                low, and flat on the deck elsewhere, where it climbs high (a vertical panel gets almost nothing at noon there).
              </p>
              {series && <PowerCalculator series={series} t0={t0} stepH={1} startIdx={startIdx} maxDays={maxDays}
                key={Math.abs(r.lat) >= 75 ? "polar" : "low"} defaults={{ mount: Math.abs(r.lat) >= 75 ? "tracking" : "horizontal" }} lead={
                <label className="control">Start
                  <select value={startKey === "first" ? starts[0].key : startKey} onChange={(ev) => setStartKey(ev.target.value)}>
                    {starts.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
                  </select>
                </label>} />}
            </>
          );
        })()}
    </section>
  );
}

function TempChart({ t, r }: { t: ThermalRun; r: SiteResult }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const W = Math.max(0, width), H = 210, M = { top: 24, right: 12, bottom: 28, left: 44 };
  const iw = Math.max(0, W - M.left - M.right), ih = H - M.top - M.bottom;
  const n = t.t.length;
  const x = scaleUtc().domain([t.t[0], t.t[n - 1]]).range([0, iw]);
  const y = scaleLinear().domain([Math.min(t.stats.minK, 150) - 10, Math.max(t.stats.maxK, 150) + 10]).nice().range([ih, 0]);
  const stride = Math.max(1, Math.floor(n / Math.max(200, iw * 2)));
  let d = "";
  for (let i = 0; i < n; i += stride) d += `${i ? "L" : "M"}${x(t.t[i]).toFixed(1)},${y(t.surfaceK[i]).toFixed(1)}`;
  return (
    <div ref={ref} className="chart">
      {W > 0 && (
        <svg width={W} height={H} role="img" aria-label="Surface temperature over the period">
          <g transform={`translate(${M.left},${M.top})`}>
            {r.daylight.map((dl, i) => <rect key={i} x={x(Math.max(dl.start, t.t[0]))} width={Math.max(0, x(Math.min(dl.end, t.t[n - 1])) - x(Math.max(dl.start, t.t[0])))} y={0} height={ih} fill="#eda10022" />)}
            {y.ticks(5).map((v) => (
              <g key={v} className="axis"><line className="gridline" x1={0} x2={iw} y1={y(v)} y2={y(v)} />
                <text x={-6} y={y(v) + 4} textAnchor="end">{v}</text></g>
            ))}
            <line x1={0} x2={iw} y1={y(150)} y2={y(150)} stroke="var(--ink-3)" strokeDasharray="4 3" />
            {x.ticks(Math.max(2, Math.round(iw / 110))).map((v) => (
              <g key={+v} className="axis"><text x={x(v)} y={ih + 16} textAnchor="middle">{tickFmt(v)}</text></g>
            ))}
            <path d={d} fill="none" stroke="var(--bad)" strokeWidth={1.8} />
            <text className="axis-title" x={-6} y={-10} textAnchor="end">K</text>
          </g>
        </svg>
      )}
      <div className="key"><span className="k-temp">Surface temperature</span><span className="k-sunup">Sun up</span><span className="k-ref">150 K</span></div>
    </div>
  );
}
