import { scaleLinear, scaleUtc } from "d3-scale";
import { utcFormat } from "d3-time-format";
import { useMemo, useState, type ReactNode } from "react";
import { fmtNum } from "../lib/format";
import { useWidth } from "../lib/hooks";
import { DEFAULTS, MOUNTS, simulate, smallest, type Mount, type Params, type Run, type Sunlight } from "../lib/power";
import type { ThermalFile } from "../types";

const tickFmt = utcFormat("%-d %b");
const dayTime = utcFormat("%-d %b %H:%M UTC");
const utcMs = (s: string) => Date.parse(s.endsWith("Z") || s.includes("+") ? s : `${s}Z`);

export function PowerBudget({ t }: { t: ThermalFile }) {
  const pts = t.points.filter((p) => p.terrain && p.dni_w_m2);
  const [key, setKey] = useState(pts[0]?.key ?? "");
  const p = pts.find((q) => q.key === key) ?? pts[0];
  const t0 = utcMs(t.time.t0_utc), stepH = t.time.step_h;
  const startMs = p?.after_best_slot ? utcMs(p.after_best_slot.start_utc) : t0;
  const startIdx = Math.max(0, Math.round((startMs - t0) / (stepH * 3600e3)));
  if (!p) return null;
  return (
    <section className="panel" aria-labelledby="fc-power">
      <div className="panel-head">
        <h2 id="fc-power">Will it get through the shadows? A power budget</h2>
        <span className="hint">your lander, our sunlight</span>
      </div>
      <div className="panel-body">
        <p className="val-story">
          Astrobotic has not published Griffin's power system, so this is a calculator, not a forecast: you set the panels, the
          battery and the loads, and the engine supplies the sunlight at the point, hour by hour from its best landing slot
          (the Sun's distance, the share of its disc above the LOLA horizon, its elevation). Defaults are generic, not Griffin's.
        </p>
        <PowerCalculator series={p} t0={t0} stepH={stepH} startIdx={startIdx} lead={
          <label className="control">Point
            <select value={p.key} onChange={(e) => setKey(e.target.value)}>
              {pts.map((q) => <option key={q.key} value={q.key}>{q.label}</option>)}
            </select>
          </label>}
          warning={p.after_best_slot?.sun_up_at_start === false && (
            <p className="slip">
              At this point the Sun is behind the terrain at its best landing slot, which the forecast's landing rule does not
              allow. The forecast and this temperature run used different terrain or horizon settings; rebuild both from the
              same LOLA map before trusting this panel.
            </p>
          )} />
      </div>
    </section>
  );
}

/** The calculator itself: controls, figures, battery chart. `series` gives the sunlight and ground
 * temperature in steps of `stepH` hours from `t0` (UTC ms); the run starts at `startIdx`. */
export function PowerCalculator({ series, t0, stepH, startIdx, lead, warning, maxDays, defaults }: {
  series: Sunlight; t0: number; stepH: number; startIdx: number; lead?: ReactNode; warning?: ReactNode; maxDays?: number;
  defaults?: Partial<Params>;
}) {
  const [P, setP] = useState<Params>(() => ({ ...DEFAULTS, ...defaults }));
  const days = maxDays !== undefined ? Math.max(1, Math.min(P.days, Math.floor(maxDays))) : P.days;
  const Q = useMemo(() => ({ ...P, days }), [P, days]);
  const run = useMemo(() => simulate(series, t0, stepH, startIdx, Q), [series, t0, stepH, startIdx, Q]);
  const minBattery = useMemo(() => smallest(series, t0, stepH, startIdx, Q, "battery", 0, 200000), [series, t0, stepH, startIdx, Q]);
  const minArea = useMemo(() => smallest(series, t0, stepH, startIdx, Q, "area", 0, 100), [series, t0, stepH, startIdx, Q]);
  const set = (k: keyof Params) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setP((x) => ({ ...x, [k]: k === "mount" ? (e.target.value as Mount) : Math.max(0, Number(e.target.value)) }));
  const tmin = (() => {
    const n = Math.round((Q.days * 24) / stepH) + 1, s = series.surface_k;
    let m = Infinity;
    for (let i = startIdx; i < Math.min(s.length, startIdx + n); i++) m = Math.min(m, s[i]);
    return Number.isFinite(m) ? m : null;
  })();
  return (
    <>
      <div className="power-grid">
        {lead}
        <label className="control">Days on the surface<input type="number" min={1} max={maxDays !== undefined ? Math.floor(maxDays) : 60} value={days} onChange={set("days")} /></label>
        <label className="control">Panels
          <select value={P.mount} onChange={set("mount")}>
            {(Object.keys(MOUNTS) as Mount[]).map((m) => <option key={m} value={m}>{MOUNTS[m]}</option>)}
          </select>
        </label>
        <label className="control">Panel area (m²)<input type="number" min={0} step={0.1} value={P.area} onChange={set("area")} /></label>
        <label className="control">Efficiency (%)<input type="number" min={1} max={40} value={P.eff} onChange={set("eff")} /></label>
        <label className="control">Battery (Wh)<input type="number" min={0} step={50} value={P.battery} onChange={set("battery")} /></label>
        <label className="control">Usable charge (%)<input type="number" min={10} max={100} value={P.usable} onChange={set("usable")} /></label>
        <label className="control">Load in sunlight (W)<input type="number" min={0} value={P.dayLoad} onChange={set("dayLoad")} /></label>
        <label className="control">Load in shadow: heaters, keep-alive (W)<input type="number" min={0} value={P.nightLoad} onChange={set("nightLoad")} /></label>
      </div>
      <dl className="figures">
        <div><dt>Gets through {days} days</dt><dd className={run.survives ? "ok-text" : "bad-text"}>{run.survives ? "yes" : "no"}
          <small>{run.survives ? `lowest charge ${fmtNum((100 * run.minSoc) / (P.battery || 1), 0)}%` : `battery empty ${dayTime(new Date(run.deadAt!))}`}</small></dd></div>
        <div><dt>Longest shadow</dt><dd>{fmtNum(run.darkH, 0)}<small>h</small></dd></div>
        <div><dt>Ground temperature, lowest</dt><dd>{tmin !== null ? fmtNum(tmin, 0) : "–"}<small>K</small></dd></div>
        <div><dt>Smallest battery that gets through</dt><dd>{minBattery !== null ? fmtNum(minBattery, 0) : "none"}<small>{minBattery === null ? "panels too small" : minBattery === 0 ? "Wh: the panels alone carry the load" : "Wh, with these panels"}</small></dd></div>
        <div><dt>Smallest panel that gets through</dt><dd>{minArea !== null ? fmtNum(minArea, 2) : "none"}<small>{minArea === null ? "battery too small" : minArea === 0 ? "m²: the battery alone lasts" : "m², with this battery"}</small></dd></div>
        <div><dt>Energy in / used</dt><dd>{fmtNum(run.energyIn / 1000, 1)} / {fmtNum(run.energyOut / 1000, 1)}<small>kWh</small></dd></div>
      </dl>
      {warning}
      <SocChart run={run} P={Q} />
      <p className="table-note">
        A sketch of the bookkeeping, not of a real power system: sunlight in steps of {stepH} h, panel output = sunlight ×
        area × efficiency × the panel's angle to the Sun, no battery or wiring losses, the battery starts full and never takes
        more than its capacity. The shadow load is yours: how much heat a lander needs depends on its insulation, and the
        ground temperature above is only a hint. The smallest battery and panel come from bisection on this same simulation.
      </p>
    </>
  );
}

function SocChart({ run, P }: { run: Run; P: Params }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const W = Math.max(0, width), H = 200, M = { top: 18, right: 12, bottom: 28, left: 48 };
  const iw = Math.max(0, W - M.left - M.right), ih = H - M.top - M.bottom;
  const x = scaleUtc().domain([run.t[0], run.t[run.t.length - 1]]).range([0, iw]);
  const y = scaleLinear().domain([0, (P.battery || 1) * 1.08]).range([ih, 0]);
  const d = run.soc.map((v, i) => `${i ? "L" : "M"}${x(run.t[i]).toFixed(1)},${y(Math.max(v, 0)).toFixed(1)}`).join("");
  const floor = P.battery * (1 - P.usable / 100);
  return (
    <div ref={ref} className="chart">
      {W > 0 && (
        <svg width={W} height={H} role="img" aria-label="Battery charge over the first days on the surface">
          <g transform={`translate(${M.left},${M.top})`}>
            {y.ticks(4).map((v) => (
              <g key={v} className="axis"><line className="gridline" x1={0} x2={iw} y1={y(v)} y2={y(v)} />
                <text x={-6} y={y(v) + 4} textAnchor="end">{fmtNum(v, 0)}</text></g>
            ))}
            {x.ticks(Math.max(2, Math.round(iw / 120))).map((v) => (
              <g key={+v} className="axis"><text x={x(v)} y={ih + 14} textAnchor="middle">{tickFmt(v)}</text></g>
            ))}
            <rect x={0} y={y(floor)} width={iw} height={Math.max(0, ih - y(floor))} fill="var(--signal-soft)" />
            <path d={d} fill="none" stroke="var(--earth)" strokeWidth={2} />
            {run.deadAt !== null && <line x1={x(run.deadAt)} x2={x(run.deadAt)} y1={0} y2={ih} stroke="var(--bad)" strokeDasharray="4 3" />}
            <text className="axis-title" x={-6} y={-8} textAnchor="end">Wh</text>
          </g>
        </svg>
      )}
      <div className="key"><span className="k-earth">Battery charge</span><span className="k-window">Below the usable limit</span></div>
    </div>
  );
}

