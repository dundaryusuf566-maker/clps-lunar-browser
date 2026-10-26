import { scaleBand } from "d3-scale";
import { useMemo, useState } from "react";
import { sequential } from "../lib/color";
import { fmtDay, fmtNum, fmtShortDay, fmtTof, parseUtc } from "../lib/format";
import { useWidth } from "../lib/hooks";
import { compareBy, type Metric } from "../lib/metrics";
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

const M = { top: 30, right: 8, bottom: 34, left: 46 };

/** Launch window map: TLI date across, transit time down, colour = metric.
 *  When both approaches are shown, each cell keeps the better one.
 *  Hatched cells have no value (no landing window at the chosen site). */
export function Porkchop({ rows, metric, landingOf, selectedId, onSelect, dark }: Props) {
  const [wrapRef, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<{ row: TransferRow; value: number | null; x: number; y: number } | null>(null);

  const grid = useMemo(() => {
    const dates = [...new Set(rows.map((r) => r.tli_utc))].sort();
    const tofs = [...new Set(rows.map((r) => r.tof_days))].sort((a, b) => a - b);
    const cells = new Map<string, { row: TransferRow; value: number | null }>();
    for (const r of rows) {
      const value = metric.value(r, landingOf(r));
      const key = `${r.tli_utc}|${r.tof_days}`;
      const prev = cells.get(key);
      if (!prev || compareBy(metric, value, prev.value) < 0) cells.set(key, { row: r, value });
    }
    const values = [...cells.values()].map((c) => c.value).filter((v): v is number => v !== null);
    let best: { row: TransferRow; value: number | null } | null = null;
    for (const c of cells.values()) if (c.value !== null && (!best || compareBy(metric, c.value, best.value) < 0)) best = c;
    const lo = values.length ? Math.min(...values) : 0, hi = values.length ? Math.max(...values) : 1;
    // Colour domain runs best -> worst, so darker always means worse.
    const domain: [number, number] = metric.better === "low" ? [lo, hi] : [hi, lo];
    return { dates, tofs, cells, domain, best, empty: values.length === 0 };
  }, [rows, metric, landingOf]);

  const innerW = Math.max(0, width - M.left - M.right);
  const rowH = grid.tofs.length > 8 ? 26 : 38;
  const innerH = grid.tofs.length * rowH;
  const x = scaleBand<string>().domain(grid.dates).range([0, innerW]);
  const y = scaleBand<number>().domain(grid.tofs).range([0, innerH]);
  const color = sequential(grid.domain, dark);
  const gap = x.bandwidth() > 10 ? 2 : x.bandwidth() > 4 ? 1 : 0.5;
  const radius = x.bandwidth() > 8 ? 1.5 : 0;

  const step = Math.max(1, Math.ceil(64 / Math.max(1, x.bandwidth())));
  const dateTicks = grid.dates.filter((_, i) => i % step === 0);
  const cellsArr = [...grid.cells.values()];
  const selected = selectedId ? cellsArr.find((c) => c.row.id === selectedId) : undefined;

  function onKey(e: React.KeyboardEvent) {
    const cur = selected ?? grid.best ?? cellsArr[0];
    if (!cur) return;
    let di = grid.dates.indexOf(cur.row.tli_utc);
    let ti = grid.tofs.indexOf(cur.row.tof_days);
    if (e.key === "ArrowRight") di++;
    else if (e.key === "ArrowLeft") di--;
    else if (e.key === "ArrowDown") ti++;
    else if (e.key === "ArrowUp") ti--;
    else return;
    e.preventDefault();
    const next = grid.cells.get(`${grid.dates[di]}|${grid.tofs[ti]}`);
    if (next) onSelect(next.row.id);
  }

  const rect = (r: TransferRow) => ({
    x: (x(r.tli_utc) ?? 0) + gap / 2,
    y: (y(r.tof_days) ?? 0) + gap / 2,
    w: Math.max(0.5, x.bandwidth() - gap),
    h: Math.max(1, y.bandwidth() - gap),
  });
  const fmt = (v: number) => `${fmtNum(v, metric.digits)} ${metric.unit}`;

  return (
    <div ref={wrapRef} className="chart">
      {width > 0 && (
        <svg width={width} height={innerH + M.top + M.bottom} role="grid" tabIndex={0} onKeyDown={onKey}
          aria-label={`Launch window map of ${metric.label} by TLI date and transit time. Arrow keys move between transfers.`}
          onPointerLeave={() => setHover(null)}>
          <defs>
            <pattern id="pc-hatch" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <rect width="5" height="5" fill="var(--surface)" />
              <line x1="0" y1="0" x2="0" y2="5" stroke="var(--rule)" strokeWidth="2" />
            </pattern>
          </defs>
          <g transform={`translate(${M.left},${M.top})`}>
            {cellsArr.map(({ row, value }) => {
              const c = rect(row);
              return (
                <rect key={row.id} className="cell" x={c.x} y={c.y} width={c.w} height={c.h} rx={radius}
                  fill={value === null ? "url(#pc-hatch)" : color(value)}
                  onClick={() => onSelect(row.id)}
                  onPointerMove={() => setHover({ row, value, x: M.left + c.x + c.w / 2, y: M.top + c.y })} />
              );
            })}

            {grid.best && (() => {
              const c = rect(grid.best.row);
              const cx = c.x + c.w / 2;
              const anchor = cx > innerW - 160 ? "end" : cx < 160 ? "start" : "middle";
              return (
                <g aria-hidden="true">
                  <rect className="ring-best" x={c.x - 2} y={c.y - 2} width={c.w + 4} height={c.h + 4} rx={2.5} />
                  <line className="annotation-line" x1={cx} x2={cx} y1={-8} y2={c.y - 2} />
                  <text className="annotation" x={cx} y={-13} textAnchor={anchor}>
                    {metric.best}: {fmt(grid.best.value as number)}
                  </text>
                </g>
              );
            })()}
            {grid.empty && (
              <text className="annotation" x={innerW / 2} y={-13} textAnchor="middle">No landing window in this selection</text>
            )}
            {selected && (() => {
              const c = rect(selected.row);
              return <rect className="ring-selected" x={c.x - 3} y={c.y - 3} width={c.w + 6} height={c.h + 6} rx={3} pointerEvents="none" />;
            })()}

            <g className="axis" transform={`translate(0,${innerH + 6})`}>
              {dateTicks.map((d) => (
                <text key={d} x={(x(d) ?? 0) + x.bandwidth() / 2} y={12} textAnchor="middle">{fmtShortDay(parseUtc(d))}</text>
              ))}
              <text className="axis-title" x={innerW} y={28} textAnchor="end">TLI date (UTC)</text>
            </g>
            <g className="axis">
              {grid.tofs.map((t) => (
                <text key={t} x={-8} y={(y(t) ?? 0) + y.bandwidth() / 2 + 4} textAnchor="end">{fmtTof(t)}</text>
              ))}
            </g>
          </g>
        </svg>
      )}
      {hover && (
        <div className="tooltip" style={{ left: hover.x, top: hover.y }}>
          <strong className="num">{hover.value === null ? "No landing window" : fmt(hover.value)}</strong>
          {hover.value === null ? "" : `${metric.label}, `}TLI {fmtDay(parseUtc(hover.row.tli_utc))}
          <div className="sub">{fmtTof(hover.row.tof_days)} transfer, LOI {fmtNum(hover.row.loi_dv_ms, 0)} m/s</div>
        </div>
      )}
      {!grid.empty && (
        <Legend domain={grid.domain} label={`${metric.label} (${metric.unit})`} digits={metric.digits} dark={dark}
          note={`Darker is worse.${metric.needsSite ? " Hatched: no landing window." : ""} The outlined cell is the best; click any cell to inspect it.`} />
      )}
    </div>
  );
}
