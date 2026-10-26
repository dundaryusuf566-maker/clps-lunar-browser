import { extent } from "d3-array";
import { scaleLinear, scaleUtc } from "d3-scale";
import { utcFormat } from "d3-time-format";
import { useMemo, useState } from "react";
import { sequential } from "../lib/color";
import { fmtDay, fmtNum, fmtTof, parseUtc } from "../lib/format";
import { useWidth } from "../lib/hooks";
import type { Metric } from "../lib/metrics";
import type { Landing, TransferRow } from "../types";
import { Legend } from "./Legend";

interface Props {
  rows: TransferRow[];
  metric: Metric;
  landingOf: (r: TransferRow) => Landing | null;
  selectedId: string | null;
  onSelect: (id: string) => void;
  dark: boolean;
}

const M = { top: 30, right: 12, bottom: 34, left: 52 };
const HEIGHT = 340;
const tickFmt = utcFormat("%-d %b");

/** The Lunar Browser's own view: a metric against launch date, coloured by transit time. */
export function SolutionSpace({ rows, metric, landingOf, selectedId, onSelect, dark }: Props) {
  const [wrapRef, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<{ r: TransferRow; v: number } | null>(null);

  const pts = useMemo(
    () => rows
      .map((r) => ({ r, t: parseUtc(r.tli_utc), v: metric.value(r, landingOf(r)) }))
      .filter((p): p is { r: TransferRow; t: Date; v: number } => p.v !== null)
      .sort((a, b) => a.r.tof_days - b.r.tof_days),
    [rows, metric, landingOf],
  );
  const missing = rows.length - pts.length;
  const innerW = Math.max(0, width - M.left - M.right);
  const innerH = HEIGHT - M.top - M.bottom;
  const tofDomain = (extent(rows, (r) => r.tof_days) as [number, number]) ?? [4, 12];
  const color = sequential(tofDomain, dark);

  if (pts.length === 0) {
    return <div ref={wrapRef} className="chart"><p className="empty">No transfer in this selection can land at the chosen site.</p></div>;
  }
  const [t0, t1] = extent(pts, (p) => p.t) as [Date, Date];
  const [v0, v1] = extent(pts, (p) => p.v) as [number, number];
  const pad = (v1 - v0) * 0.06 || 1;
  const x = scaleUtc().domain([t0, t1]).range([0, innerW]);
  const y = scaleLinear().domain([v0 - pad, v1 + pad]).nice().range([innerH, 0]);

  function nearest(px: number, py: number) {
    let best: (typeof pts)[number] | null = null;
    let bestD = 18 * 18; // hit radius well beyond the 9 px mark
    for (const p of pts) {
      const dx = x(p.t) - px, dy = y(p.v) - py;
      const d = dx * dx + dy * dy;
      if (d < bestD) {
        bestD = d;
        best = p;
      }
    }
    return best;
  }
  const local = (e: React.MouseEvent<SVGRectElement>) => {
    const b = e.currentTarget.getBoundingClientRect();
    return nearest(e.clientX - b.left, e.clientY - b.top);
  };
  const sel = pts.find((p) => p.r.id === selectedId);
  const tickDigits = metric.unit === "days" ? 0 : metric.digits > 1 ? 2 : 0;

  return (
    <div ref={wrapRef} className="chart">
      {width > 0 && (
        <svg width={width} height={HEIGHT} role="img" aria-label={`${metric.label} against TLI date, coloured by transit time`}>
          <g transform={`translate(${M.left},${M.top})`}>
            {y.ticks(6).map((v) => (
              <g key={v} className="axis">
                <line className="gridline" x1={0} x2={innerW} y1={y(v)} y2={y(v)} />
                <text x={-8} y={y(v) + 4} textAnchor="end">{fmtNum(v, tickDigits)}</text>
              </g>
            ))}
            <g className="axis" transform={`translate(0,${innerH + 6})`}>
              {x.ticks(Math.max(2, Math.floor(innerW / 90))).map((d) => (
                <text key={+d} x={x(d)} y={12} textAnchor="middle">{tickFmt(d)}</text>
              ))}
              <text className="axis-title" x={innerW} y={28} textAnchor="end">TLI date (UTC)</text>
            </g>
            <text className="axis-title" x={-M.left + 2} y={-16}>{metric.label} ({metric.unit})</text>

            {pts.map((p) => (
              <circle key={p.r.id} cx={x(p.t)} cy={y(p.v)} r={pts.length > 600 ? 3.5 : 4.5} fill={color(p.r.tof_days)}
                stroke="var(--surface)" strokeWidth={pts.length > 600 ? 1 : 2} />
            ))}
            {sel && <circle cx={x(sel.t)} cy={y(sel.v)} r={8.5} fill="none" stroke="var(--signal)" strokeWidth={2.5} pointerEvents="none" />}
            {hover && <circle cx={x(parseUtc(hover.r.tli_utc))} cy={y(hover.v)} r={7} fill="none" stroke="var(--ink)" strokeWidth={1.5} pointerEvents="none" />}

            <rect width={innerW} height={innerH} fill="transparent" style={{ cursor: hover ? "pointer" : "default" }}
              onPointerMove={(e) => {
                const p = local(e);
                setHover(p ? { r: p.r, v: p.v } : null);
              }}
              onPointerLeave={() => setHover(null)}
              onClick={(e) => {
                const p = local(e);
                if (p) onSelect(p.r.id);
              }} />
          </g>
        </svg>
      )}
      {hover && (
        <div className="tooltip" style={{ left: M.left + x(parseUtc(hover.r.tli_utc)), top: M.top + y(hover.v) }}>
          <strong className="num">{fmtNum(hover.v, metric.digits)} {metric.unit}</strong>
          {metric.label}, TLI {fmtDay(parseUtc(hover.r.tli_utc))}
          <div className="sub">{fmtTof(hover.r.tof_days)} transfer</div>
        </div>
      )}
      <Legend domain={tofDomain} label="Transit time (days)" digits={0} dark={dark} format={(v) => fmtTof(v)}
        note={`Darker dots take longer to reach the Moon.${missing ? ` ${missing} transfers without a landing window are left out.` : ""}`} />
    </div>
  );
}
