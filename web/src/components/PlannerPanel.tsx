import { extent } from "d3-array";
import { scaleUtc } from "d3-scale";
import { utcFormat } from "d3-time-format";
import { useEffect, useMemo, useState } from "react";
import { sequential } from "../lib/color";
import { familyName, fmtDay, fmtNum, fmtShortDay, fmtTof, parseUtc } from "../lib/format";
import { useWidth } from "../lib/hooks";
import { numParam, readParams, writeParams } from "../lib/urlstate";
import { dayMs, dayOf, plan, slipTolerance, type LaunchDay, type Plan, type Requirements } from "../lib/planner";
import type { Landing, Site, TransferRow } from "../types";
import { Legend } from "./Legend";

interface Props {
  site: Site | null;
  rows: TransferRow[];               // already filtered by approach
  landingOf: (r: TransferRow) => Landing | null;
  maxWaitAnalysed: number;           // the landing analysis looked this far ahead
  daylightHorizon: number;
  selected: TransferRow | null;
  onSelect: (id: string) => void;
  showFamily: boolean;
  dark: boolean;
}

const DAY_MS = 86400e3;
const tickFmt = utcFormat("%-d %b");
const days = (n: number) => `${fmtNum(n, Number.isInteger(n) ? 0 : 1)} ${n === 1 ? "day" : "days"}`;

export function PlannerPanel({ site, rows, landingOf, maxWaitAnalysed, daylightHorizon, selected, onSelect, showFamily, dark }: Props) {
  const allDays = useMemo(() => [...new Set(rows.map((r) => dayOf(r.tli_utc)))].sort(), [rows]);
  const [req, setReq] = useState<Requirements>(() => {
    const p = readParams();
    const iso = (k: string, d: string) => (/^\d{4}-\d{2}-\d{2}$/.test(p.get(k) ?? "") ? p.get(k)! : d);
    return {
      from: iso("from", allDays[0] ?? "2026-01-01"), to: iso("to", allDays[allDays.length - 1] ?? "2026-12-31"),
      minDaylightDays: numParam(p, "minsun") ?? 7, maxWaitDays: numParam(p, "maxwait") ?? Math.min(5, maxWaitAnalysed),
      maxSurfaceMs: numParam(p, "maxdv"), requireDsn: p.get("dsn") === "1", minEnergyPct: numParam(p, "energy"),
    };
  });
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!site) return;
    writeParams({ from: req.from, to: req.to, minsun: req.minDaylightDays, maxwait: req.maxWaitDays,
      maxdv: req.maxSurfaceMs, dsn: req.requireDsn, energy: req.minEnergyPct });
  }, [req, site]);
  const result = useMemo(() => plan(rows, landingOf, req), [rows, landingOf, req]);
  const slip = slipTolerance(result, selected && !selected.custom ? selected : null);

  if (!site) {
    return (
      <section className="panel area-planner planner off" aria-labelledby="planner-title">
        <div className="panel-head"><h2 id="planner-title">Plan a mission</h2></div>
        <div className="panel-body">
          <p>
            Pick a landing site above, then say what the mission needs (sunlight after touchdown, how long the
            lander can wait in orbit, a Δv budget). The planner lists every launch window that delivers it, how
            many days each one stays open, and the best transfers ranked.
          </p>
        </div>
      </section>
    );
  }

  const num = (k: "minDaylightDays" | "maxWaitDays") => (e: React.ChangeEvent<HTMLInputElement>) =>
    setReq({ ...req, [k]: Number(e.target.value) });
  const date = (k: "from" | "to") => (e: React.ChangeEvent<HTMLInputElement>) => e.target.value && setReq({ ...req, [k]: e.target.value });
  const longest = result.windows.reduce<Plan["windows"][number] | null>((a, w) => (!a || w.spanDays > a.spanDays ? w : a), null);

  return (
    <section className="panel area-planner planner" aria-labelledby="planner-title">
      <div className="panel-head">
        <h2 id="planner-title">Plan a mission to {site.name}</h2>
        <span className="hint">Launch windows that meet every requirement below</span>
      </div>
      <div className="panel-body">
        <form className="planner-form" onSubmit={(e) => e.preventDefault()}>
          <label>TLI from<input type="date" value={req.from} min={allDays[0]} max={req.to} onChange={date("from")} /></label>
          <label>TLI to<input type="date" value={req.to} min={req.from} max={allDays[allDays.length - 1]} onChange={date("to")} /></label>
          <label>Sunlight after landing, at least (d)
            <input type="number" min={0} max={daylightHorizon} step={0.5} value={req.minDaylightDays} onChange={num("minDaylightDays")} />
          </label>
          <label>Wait in lunar orbit, at most (d)
            <input type="number" min={1} max={maxWaitAnalysed} step={0.5} value={req.maxWaitDays} onChange={num("maxWaitDays")} />
          </label>
          <label>Δv to surface, at most (m/s)
            <input type="number" min={0} step={10} placeholder="no limit" value={req.maxSurfaceMs ?? ""}
              onChange={(e) => setReq({ ...req, maxSurfaceMs: e.target.value === "" ? null : Number(e.target.value) })} />
          </label>
          <label>Solar energy, first days, at least (%)
            <input type="number" min={0} max={100} step={5} placeholder="no limit" value={req.minEnergyPct ?? ""}
              onChange={(e) => setReq({ ...req, minEnergyPct: e.target.value === "" ? null : Number(e.target.value) })} />
          </label>
          <label className="check">
            <input type="checkbox" checked={req.requireDsn} onChange={(e) => setReq({ ...req, requireDsn: e.target.checked })} />
            Touchdown in view of a NASA DSN station
          </label>
          <div className="share">
            <button type="button" onClick={() => {
              navigator.clipboard?.writeText(window.location.href).then(() => { setCopied(true); window.setTimeout(() => setCopied(false), 2000); },
                () => setCopied(false));
            }}>{copied ? "Link copied" : "Copy link to this plan"}</button>
          </div>
        </form>

        <p className="planner-summary" role="status" aria-live="polite">
          {result.windows.length === 0
            ? <>No launch date between {fmtDay(parseUtc(req.from))} and {fmtDay(parseUtc(req.to))} meets these requirements. Relax the sunlight or wait limit.</>
            : <>
                <strong>{result.windows.length} launch window{result.windows.length > 1 ? "s" : ""}</strong>,{" "}
                {result.matching} of {result.considered} transfers qualify.
                {longest && <> Longest: {fmtShortDay(parseUtc(longest.first))} to {fmtShortDay(parseUtc(longest.last))}, open {days(longest.spanDays)}.</>}
              </>}
        </p>

        {result.days.length > 0 && (
          <WindowStrip plan={result} req={req} selected={selected} onSelect={onSelect} dark={dark} />
        )}

        {slip && selected && (
          <p className="slip">
            <strong>Launch slip, selected transfer ({fmtDay(parseUtc(selected.tli_utc))}):</strong>{" "}
            {slip.slipDays > 0
              ? <>the launch can slip up to {days(slip.slipDays)} (to {fmtDay(parseUtc(slip.window.last))}) and still meet these requirements</>
              : <>this is the last qualifying launch date of its window; any slip moves the mission to the next window</>}
            {slip.earlyDays > 0 ? <>, and the window opened {days(slip.earlyDays)} earlier.</> : "."}
          </p>
        )}
        {!slip && selected && !selected.custom && result.windows.length > 0 && (
          <p className="slip">The selected transfer ({fmtDay(parseUtc(selected.tli_utc))}) is outside every window that meets these requirements.</p>
        )}

        {result.windows.length > 0 && (
          <div className="planner-tables">
            <div className="table-wrap">
              <h3>Launch windows</h3>
              <table>
                <thead>
                  <tr><th className="left">Opens</th><th className="left">Closes</th><th>Open for</th><th>Best Δv to surface</th><th className="left">Best launch</th></tr>
                </thead>
                <tbody>
                  {result.windows.map((w) => (
                    <tr key={w.first} onClick={() => onSelect(w.best.row.id)} aria-selected={w.best.row.id === selected?.id}>
                      <td className="left">{fmtDay(parseUtc(w.first))}</td>
                      <td className="left">{fmtDay(parseUtc(w.last))}</td>
                      <td>{days(w.spanDays)}</td>
                      <td>{fmtNum(w.best.landing.surfaceMs!, 0)} m/s</td>
                      <td className="left">{fmtShortDay(parseUtc(w.best.row.tli_utc))}, {fmtTof(w.best.row.tof_days)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="table-wrap">
              <h3>Best launch dates</h3>
              <table>
                <thead>
                  <tr>
                    <th className="rank">#</th><th className="left">TLI</th><th>Transit</th>
                    {showFamily && <th className="left">Approach</th>}
                    <th className="left">Touchdown</th><th>Wait</th><th>Sunlight</th><th>Δv to surface</th>
                  </tr>
                </thead>
                <tbody>
                  {result.ranked.slice(0, 8).map((o, i) => (
                    <tr key={o.row.id} onClick={() => onSelect(o.row.id)} aria-selected={o.row.id === selected?.id}>
                      <td className="rank">{i + 1}</td>
                      <td className="left">{fmtShortDay(parseUtc(o.row.tli_utc))}</td>
                      <td>{fmtTof(o.row.tof_days)}</td>
                      {showFamily && <td className="left">{familyName(o.row.family)}</td>}
                      <td className="left">{fmtShortDay(new Date(o.landingMs))}</td>
                      <td>{fmtNum(o.landing.waitDays!, 1)} d</td>
                      <td>{o.landing.daylightCapped ? "≥ " : ""}{fmtNum(o.landing.daylightDays!, 1)} d</td>
                      <td>{fmtNum(o.landing.surfaceMs!, 0)} m/s</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
        <p className="table-note">
          Windows are runs of consecutive database launch dates ({result.gridDays}-day grid), so a window's length is
          known to ±{days(result.gridDays)}. A launch date qualifies when any of its transfers meets every requirement.
          Sunlight and solar energy are measured above the LOLA terrain at polar sites and above a flat horizon elsewhere,
          up to {daylightHorizon} days ahead. DSN: Goldstone, Madrid or Canberra sees the site above 10° (our assumption).
        </p>
      </div>
    </section>
  );
}

const M = { top: 22, right: 8, bottom: 22, left: 8 };
const H = 92;

function WindowStrip({ plan: p, req, selected, onSelect, dark }: { plan: Plan; req: Requirements; selected: TransferRow | null;
  onSelect: (id: string) => void; dark: boolean }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<LaunchDay | null>(null);
  const innerW = Math.max(0, width - M.left - M.right);
  const innerH = H - M.top - M.bottom;
  const t0 = dayMs(req.from), t1 = dayMs(req.to) + p.gridDays * DAY_MS;
  const x = scaleUtc().domain([t0, t1]).range([0, innerW]);
  const cw = Math.max(1, x(t0 + p.gridDays * DAY_MS) - x(t0) - (innerW / ((t1 - t0) / DAY_MS) > 6 ? 1 : 0));
  const values = p.days.filter((d) => d.best).map((d) => d.best!.landing.surfaceMs!);
  const domain = (values.length ? extent(values) : [0, 1]) as [number, number];
  const color = sequential(domain[0] === domain[1] ? [domain[0], domain[0] + 1] : domain, dark);
  const selDay = selected ? dayMs(dayOf(selected.tli_utc)) : null;

  return (
    <div ref={ref} className="chart window-strip">
      {width > 0 && (
        <svg width={width} height={H} role="img"
          aria-label={`Qualifying launch dates from ${req.from} to ${req.to}: ${p.windows.length} windows`}>
          <defs>
            <pattern id="strip-hatch" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <line x1="0" y1="0" x2="0" y2="5" stroke="var(--rule)" strokeWidth="2" />
            </pattern>
          </defs>
          <g transform={`translate(${M.left},${M.top})`}>
            {p.windows.map((w) => {
              const a = x(dayMs(w.first)), b = x(dayMs(w.last)) + cw;
              return (
                <g key={w.first} className="bracket">
                  <path d={`M${a},-4 V-9 H${b} V-4`} />
                  {b - a > 34 && <text x={(a + b) / 2} y={-12} textAnchor="middle">{fmtNum(w.spanDays, 0)} d</text>}
                </g>
              );
            })}
            {p.days.map((d) => (
              <rect key={d.day} className="cell" x={x(dayMs(d.day))} y={0} width={cw} height={innerH}
                fill={d.best ? color(d.best.landing.surfaceMs!) : "url(#strip-hatch)"}
                onPointerEnter={() => setHover(d)} onPointerLeave={() => setHover(null)}
                onClick={() => d.best && onSelect(d.best.row.id)}>
                <title>{d.day}</title>
              </rect>
            ))}
            {selDay !== null && selDay >= t0 && selDay < t1 && (
              <rect x={x(selDay) - 1.5} y={-3} width={cw + 3} height={innerH + 6} fill="none" stroke="var(--signal)" strokeWidth={2.5} pointerEvents="none" />
            )}
            <g className="axis" transform={`translate(0,${innerH + 14})`}>
              {x.ticks(Math.max(2, Math.floor(innerW / 80))).map((d) => (
                <text key={+d} x={x(d)} y={0} textAnchor="middle">{tickFmt(d)}</text>
              ))}
            </g>
          </g>
        </svg>
      )}
      {hover && (
        <div className="tooltip" style={{ left: M.left + x(dayMs(hover.day)) + cw / 2, top: M.top }}>
          <strong>{fmtDay(parseUtc(hover.day))}</strong>
          {hover.best
            ? <>{hover.options.length} of {hover.tried} transfers qualify<div className="sub">best {fmtNum(hover.best.landing.surfaceMs!, 0)} m/s, touchdown {fmtShortDay(new Date(hover.best.landingMs))}</div></>
            : <>none of {hover.tried} transfers qualify</>}
        </div>
      )}
      <Legend domain={domain} label="Best Δv to surface (m/s)" digits={0} dark={dark}
        note="Hatched: no transfer that day meets the requirements. Click a day for its best transfer." />
    </div>
  );
}
