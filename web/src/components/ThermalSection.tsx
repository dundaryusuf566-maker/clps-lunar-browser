import { scaleLinear, scaleUtc } from "d3-scale";
import { utcFormat } from "d3-time-format";
import { useMemo, useState, type ReactNode } from "react";
import { fmtNum } from "../lib/format";
import { useWidth } from "../lib/hooks";
import type { ThermalFile, ThermalPoint, ValidationCheck } from "../types";

const tickFmt = utcFormat("%-d %b");
const utcMs = (s: string) => Date.parse(s.endsWith("Z") || s.includes("+") ? s : `${s}Z`);
const DAY = 86400e3;

export function thermalChecks(t: ThermalFile): ValidationCheck[] {
  const e = t.equator_check, b = t.bowl_check;
  const out: ValidationCheck[] = [{
    id: "thermal-diviner", pass: e.pass,
    label: `Regolith temperature model reproduces Diviner's equatorial noon, midnight and pre-dawn temperatures within ${e.tolerance_k} K`,
  }];
  if (b) {
    out.push({ id: "bowl-facets", pass: b.facets.pass,
      label: `Terrain radiation (all bounces): shadow temperature in a bowl crater within ${b.tolerance_pct.facets}% of Ingersoll et al. (1992)` });
    out.push({ id: "bowl-sampling", pass: b.sampling.pass,
      label: `Terrain radiation at a point (the sampling used for the sites): within ${b.tolerance_pct.sampling}% of the one-bounce closed form` });
  }
  return out;
}

// --- Validation page ------------------------------------------------------------------
export function ThermalValidationSection({ t, checks }: { t: ThermalFile; checks: (c: ValidationCheck[]) => ReactNode }) {
  const e = t.equator_check, r = t.meta.regolith;
  const rows: [string, string][] = [["noon", "Noon"], ["midnight", "Midnight"], ["predawn", "Just before sunrise"]];
  return (
    <section className="panel" aria-labelledby="thermal-title">
      <div className="panel-head">
        <h2 id="thermal-title">Regolith temperatures against LRO Diviner</h2>
        <span className="hint">Hayne et al. (2017) model</span>
      </div>
      <div className="panel-body val-grid">
        <div>
          <p className="val-story">
            The browser computes soil temperatures with the one-dimensional heat-conduction model of Hayne et al. (2017):
            density and conductivity rising with depth (H = {r.H} m), radiation between grains (χ = {r.chi}), a
            temperature-dependent heat capacity, an albedo that grows at grazing sunlight (A₀ = {r.A0}) and the Moon's
            interior heat flow. Every constant is the paper's standard value; none was tuned here. The check: flat ground at
            the equator, where LRO's Diviner radiometer measured typical temperatures of ~{e.diviner.noon} K at noon,{" "}
            {e.diviner.midnight} K at midnight and {e.diviner.predawn} K just before sunrise (Vasavada et al. 2012).
          </p>
          <DiurnalChart t={t} />
        </div>
        <div>
          {checks(thermalChecks(t))}
          <table>
            <thead><tr><th className="left">Local time</th><th>Model</th><th>Diviner</th><th>Difference</th></tr></thead>
            <tbody>
              {rows.map(([k, label]) => (
                <tr key={k} className="static">
                  <td className="left">{label}</td><td>{fmtNum(e.model[k], 1)} K</td><td>~{e.diviner[k]} K</td>
                  <td>{e.model[k] - e.diviner[k] > 0 ? "+" : ""}{fmtNum(e.model[k] - e.diviner[k], 1)} K</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="table-note">
            Tolerance {e.tolerance_k} K: Diviner's "typical" values are rounded and vary with albedo along the equator. The model is also tested against exact results: the
            diurnal wave decays with the skin depth, noon is in radiative equilibrium, absorbed + interior heat equals
            emitted heat over a lunation, and halving the grid and time step changes nothing by more than 1 K.
            Grid: {t.meta.grid.layers} layers, first {fmtNum(t.meta.grid.first_layer_mm, 1)} mm, down to {fmtNum(t.meta.grid.bottom_m, 2)} m.
          </p>
          {t.bowl_check && <BowlBlock b={t.bowl_check} />}
        </div>
      </div>
    </section>
  );
}

function BowlBlock({ b }: { b: NonNullable<ThermalFile["bowl_check"]> }) {
  return (
    <>
      <h3 className="val-h3">Light and heat from the terrain: a bowl crater</h3>
      <p className="table-note">
        In a spherical bowl the temperature of the shadowed floor is known exactly (Ingersoll, Svitek & Murray 1992): every
        point sees the same share f of the bowl, and sunlight and heat bounce between the walls. Bowl with depth/diameter{" "}
        {b.depth_to_diameter} (f = {fmtNum(b.f, 3)}), Sun {b.sun_el_deg}° above the rim, albedo {b.albedo}, emissivity {b.emissivity}.
      </p>
      <div className="table-wrap"><table>
        <thead><tr><th className="left">Method</th><th>Ours</th><th>Exact</th><th>Difference</th></tr></thead>
        <tbody>
          <tr className="static"><td className="left">All bounces, {b.facets.n} facets (shadow temperature)</td>
            <td>{fmtNum(b.facets.shadow_t_k, 2)} K</td><td>{fmtNum(b.facets.ingersoll_t_k, 2)} K</td><td>{fmtNum(b.facets.diff_pct, 2)}%</td></tr>
          <tr className="static"><td className="left">One point, {b.sampling.directions} directions on a 120 m map (irradiance, one bounce)</td>
            <td>{fmtNum(b.sampling.flux_w_m2, 1)} W/m²</td><td>{fmtNum(b.sampling.one_bounce_w_m2, 1)} W/m²</td><td>{fmtNum(b.sampling.diff_pct, 2)}%</td></tr>
        </tbody>
      </table></div>
      <p className="table-note">
        The first row tests the physics (view factors, every bounce of sunlight and infrared); the remaining 0.2% is how
        the closed form treats infrared absorption (it is 0.01% with emissivity 1). The second row tests the method used for
        the landing sites, which follows each direction to the terrain it hits but counts one bounce.
      </p>
    </>
  );
}

function DiurnalChart({ t }: { t: ThermalFile }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const e = t.equator_check;
  const W = Math.max(0, width), H = 220, M = { top: 10, right: 12, bottom: 34, left: 44 };
  const iw = Math.max(0, W - M.left - M.right), ih = H - M.top - M.bottom;
  const x = scaleLinear().domain([0, 24]).range([0, iw]);
  const y = scaleLinear().domain([50, 420]).range([ih, 0]);
  const d = e.curve.map(([h, T], i) => `${i ? "L" : "M"}${x(h)},${y(T)}`).join("");
  const refs: [number, number][] = [[12, e.diviner.noon], [0, e.diviner.midnight], [5.9, e.diviner.predawn], [24, e.diviner.midnight]];
  return (
    <div ref={ref} className="chart">
      {W > 0 && (
        <svg width={W} height={H} role="img" aria-label="Model surface temperature over a lunar day at the equator, with Diviner reference values">
          <g transform={`translate(${M.left},${M.top})`}>
            {y.ticks(5).map((v) => (
              <g key={v} className="axis"><line className="gridline" x1={0} x2={iw} y1={y(v)} y2={y(v)} />
                <text x={-6} y={y(v) + 4} textAnchor="end">{v}</text></g>
            ))}
            {[0, 6, 12, 18, 24].map((h) => (
              <g key={h} className="axis"><text x={x(h)} y={ih + 14} textAnchor="middle">{String(h).padStart(2, "0")}:00</text></g>
            ))}
            <path d={d} fill="none" stroke="var(--earth)" strokeWidth={2} />
            {refs.map(([h, T], i) => (
              <g key={i}>
                <line x1={x(h)} x2={x(h)} y1={y(T - e.tolerance_k)} y2={y(T + e.tolerance_k)} stroke="var(--ink)" strokeWidth={1.5} />
                <circle cx={x(h)} cy={y(T)} r={4} fill="var(--surface)" stroke="var(--ink)" strokeWidth={1.5} />
              </g>
            ))}
            <text className="axis-title" x={iw} y={ih + 28} textAnchor="end">Local time (lunar hours)</text>
            <text className="axis-title" x={4} y={8}>K</text>
          </g>
        </svg>
      )}
      <div className="key"><span className="k-earth">Model, flat equator</span><span>○ Diviner, ± {e.tolerance_k} K</span></div>
    </div>
  );
}

// --- Forecast page -------------------------------------------------------------------
export function ThermalForecastSection({ t }: { t: ThermalFile }) {
  const pts = t.points.filter((p) => p.terrain);
  const flat = t.points.find((p) => !p.terrain) ?? null;
  const [key, setKey] = useState(pts[0]?.key ?? "ref");
  const p = pts.find((q) => q.key === key) ?? pts[0];
  if (!p) return null;
  return (
    <section className="panel" aria-labelledby="fc-thermal">
      <div className="panel-head">
        <h2 id="fc-thermal">Surface temperature at the candidates</h2>
        <span className="hint">Hayne et al. (2017) regolith model; analysis made after registration</span>
      </div>
      <div className="panel-body">
        <p className="val-story">
          Soil temperature from the Sun the engine computes for each point: its distance and direction, the tilt of the ground
          (LOLA, 240 m) and the share of the solar disc above the terrain horizon, fed to the regolith model checked against
          Diviner on the Validation page, plus the sunlight reflected and the infrared emitted by the terrain each point
          can see (one bounce, checked against Ingersoll et al. 1992). Shaded: the 14 days after the point's best landing slot.
        </p>
        <div className="controls">
          <label className="control">Point
            <select value={p.key} onChange={(e) => setKey(e.target.value)}>
              {pts.map((q) => <option key={q.key} value={q.key}>{q.label}</option>)}
            </select>
          </label>
        </div>
        <TempChart t={t} p={p} flat={p.key === "ref" ? flat : null} />
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th className="left">Point</th><th>Slope</th><th>Terrain in view</th><th>Min</th><th>Max</th><th>Min, Sun only</th>
                <th>10 cm deep, mean</th><th>14 d after best slot</th><th>Hours below 150 K</th></tr>
            </thead>
            <tbody>
              {[...pts, ...(flat ? [flat] : [])].map((q) => (
                <tr key={q.key} onClick={() => q.terrain && setKey(q.key)} aria-selected={q.key === p.key}>
                  <td className="left">{q.label}</td>
                  <td>{fmtNum(q.slope_deg, 1)}°</td>
                  <td>{q.terrain_view_factor != null ? `${fmtNum(100 * q.terrain_view_factor, 2)}%` : "–"}</td>
                  <td>{fmtNum(q.min_k, 0)} K</td><td>{fmtNum(q.max_k, 0)} K</td>
                  <td>{q.min_direct_k != null ? `${fmtNum(q.min_direct_k, 0)} K` : "–"}</td>
                  <td>{fmtNum(q.depth_10cm_mean_k, 0)} K</td>
                  <td>{q.after_best_slot ? `${fmtNum(q.after_best_slot.min_k, 0)}–${fmtNum(q.after_best_slot.max_k, 0)} K` : "–"}</td>
                  <td>{q.after_best_slot ? q.after_best_slot.hours_below_150k : "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="table-note">
            Min / max over {t.time.landing_period_utc[0]} to 16 days after {t.time.landing_period_utc[1]}. "Terrain in view":
            the share of the point's sky (cosine-weighted) filled by terrain, which sets how much its light and heat can matter;
            "Min, Sun only" leaves that out. One bounce: the light terrain gets from other terrain is not counted, which for a
            view share f leaves out about {fmtNum(Math.max(...pts.map((q) => q.missing_bounces_pct ?? 0)), 1)}% of the terrain
            term at most here. The last row is the reference point as if the ground were flat with no terrain around it: the
            difference is what the terrain and the slope do. Constants: Hayne et al. (2017) standard values, not fitted to
            these sites.
            {t.meta.dem.startsWith("LDEM_75S") ? "" : " Demo data: built without the LOLA map."}
          </p>
        </div>
      </div>
    </section>
  );
}

function TempChart({ t, p, flat }: { t: ThermalFile; p: ThermalPoint; flat: ThermalPoint | null }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const t0 = utcMs(t.time.t0_utc), step = t.time.step_h * 3600e3;
  const W = Math.max(0, width), H = 240, M = { top: 10, right: 12, bottom: 30, left: 44 };
  const iw = Math.max(0, W - M.left - M.right), ih = H - M.top - M.bottom;
  const n = p.surface_k.length;
  const x = scaleUtc().domain([t0, t0 + (n - 1) * step]).range([0, iw]);
  const hi = Math.max(...p.surface_k, ...(flat?.surface_k ?? [])), lo = Math.min(...p.surface_k, ...(flat?.surface_k ?? []));
  const y = scaleLinear().domain([Math.floor(lo / 50) * 50, Math.ceil(hi / 50) * 50]).range([ih, 0]);
  const path = (s: number[]) => s.map((T, i) => `${i ? "L" : "M"}${x(t0 + i * step).toFixed(1)},${y(T).toFixed(1)}`).join("");
  const win = p.after_best_slot ? [utcMs(p.after_best_slot.start_utc), utcMs(p.after_best_slot.start_utc) + 14 * DAY] : null;
  const ticks = useMemo(() => x.ticks(6), [x]);
  return (
    <div ref={ref} className="chart">
      {W > 0 && (
        <svg width={W} height={H} role="img" aria-label={`Surface temperature at ${p.label} over the landing period`}>
          <g transform={`translate(${M.left},${M.top})`}>
            {win && <rect x={x(win[0])} width={Math.max(1, x(win[1]) - x(win[0]))} y={0} height={ih} fill="var(--signal-soft)" />}
            {y.ticks(5).map((v) => (
              <g key={v} className="axis"><line className="gridline" x1={0} x2={iw} y1={y(v)} y2={y(v)} />
                <text x={-6} y={y(v) + 4} textAnchor="end">{v}</text></g>
            ))}
            {ticks.map((d) => <g key={+d} className="axis"><text x={x(d)} y={ih + 14} textAnchor="middle">{tickFmt(d)}</text></g>)}
            {flat && <path d={path(flat.surface_k)} fill="none" stroke="var(--ink-3)" strokeWidth={1} strokeDasharray="3 3" />}
            {p.surface_direct_k && <path d={path(p.surface_direct_k)} fill="none" stroke="var(--signal)" strokeWidth={1} strokeDasharray="2 2" />}
            <path d={path(p.surface_k)} fill="none" stroke="var(--earth)" strokeWidth={1.5} />
            <text className="axis-title" x={4} y={8}>K</text>
          </g>
        </svg>
      )}
      <div className="key">
        <span className="k-earth">{p.label}</span>
        {p.surface_direct_k && <span className="k-path">Sun only, without the terrain's light and heat</span>}
        {flat && <span className="k-moon">Same point, flat ground, no terrain</span>}
        {win && <span className="k-window">14 days after its best landing slot</span>}
      </div>
    </div>
  );
}
