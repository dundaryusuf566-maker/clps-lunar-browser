import { scaleLinear } from "d3-scale";
import { fmtNum } from "../lib/format";
import { useWidth } from "../lib/hooks";
import { sliceSeries } from "../lib/landing";
import type { Site, SunSeries } from "../types";

interface Props {
  series: SunSeries;
  site: Site;
  arrival: number;        // TDB epoch of LOI
  days: number;           // span after LOI to draw
  coastDays: number;
  landingDays: number | null;
}

const M = { top: 14, right: 10, bottom: 26, left: 34 };
const H = 150;

/** Sun elevation at the site through the wait in lunar orbit, with the landing marked.
 *  At terrain sites the LOLA horizon in the Sun's direction is drawn as a silhouette and
 *  the landing window starts above it. */
export function SunChart({ series, site, arrival, days, coastDays, landingDays }: Props) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const pts = sliceSeries(series, arrival, arrival + days * 86400).map(([t, el, hz]) => [(t - arrival) / 86400, el, hz] as const);
  if (pts.length < 2) return <p className="orbit-note">No Sun elevation data for this period.</p>;
  const terrain = !!series.horizon_deg;

  const w = Math.max(0, width - M.left - M.right);
  const h = H - M.top - M.bottom;
  const els = pts.flatMap((p) => [p[1], p[2]]);
  const lo = Math.min(-5, Math.min(...els)), hi = Math.max(site.sun_min_deg + 5, Math.max(...els) + 1);
  const x = scaleLinear().domain([0, days]).range([0, w]);
  const y = scaleLinear().domain([lo, hi]).nice().range([h, 0]);
  const [y0, y1] = y.domain();
  const line = (f: (p: (typeof pts)[number]) => number) =>
    pts.map((p, i) => `${i ? "L" : "M"}${x(p[0]).toFixed(1)},${y(f(p)).toFixed(1)}`).join("");
  const sunPath = line((p) => p[1]);
  const top = Math.min(site.sun_max_deg, y1);
  // Landing band: from (horizon + minimum) up to the site's maximum Sun elevation.
  const band = pts.map((p, i) => `${i ? "L" : "M"}${x(p[0]).toFixed(1)},${y(Math.min(top, Math.max(y0, p[2] + site.sun_min_deg))).toFixed(1)}`).join("")
    + `L${x(pts[pts.length - 1][0]).toFixed(1)},${y(top).toFixed(1)}L${x(pts[0][0]).toFixed(1)},${y(top).toFixed(1)}Z`;
  const ground = terrain
    ? `${line((p) => Math.max(y0, p[2]))}L${x(pts[pts.length - 1][0]).toFixed(1)},${h}L${x(pts[0][0]).toFixed(1)},${h}Z`
    : null;
  const near = landingDays !== null ? pts.reduce((b, p) => (Math.abs(p[0] - landingDays) < Math.abs(b[0] - landingDays) ? p : b)) : null;

  return (
    <div ref={ref} className="chart sun-chart">
      {width > 0 && (
        <svg width={width} height={H} role="img"
          aria-label={`Sun elevation at ${site.name} over the ${days} days after lunar orbit insertion${terrain ? ", with the terrain horizon" : ""}`}>
          <g transform={`translate(${M.left},${M.top})`}>
            <rect x={0} width={x(coastDays)} y={0} height={h} fill="var(--grid)" opacity={0.6} />
            <path d={band} fill="var(--signal-soft)" />
            {y.ticks(4).map((v) => (
              <g key={v} className="axis">
                <line className="gridline" x1={0} x2={w} y1={y(v)} y2={y(v)} />
                <text x={-6} y={y(v) + 4} textAnchor="end">{v}°</text>
              </g>
            ))}
            <line x1={0} x2={w} y1={y(0)} y2={y(0)} stroke="var(--ink-3)" strokeWidth={1} strokeDasharray={terrain ? "3 3" : undefined} />
            {ground && <path className="terrain-fill" d={ground} />}
            <path d={sunPath} fill="none" stroke="#eda100" strokeWidth={2} />
            <g className="axis" transform={`translate(0,${h + 6})`}>
              {x.ticks(6).map((d) => <text key={d} x={x(d)} y={12} textAnchor="middle">{d}</text>)}
              <text className="axis-title" x={w} y={24} textAnchor="end">Days after LOI</text>
            </g>
            {landingDays !== null && near && (
              <g>
                <line x1={x(landingDays)} x2={x(landingDays)} y1={0} y2={h} stroke="var(--signal)" strokeWidth={1.5} />
                <circle cx={x(landingDays)} cy={y(near[1])} r={4.5} fill="var(--signal)" stroke="var(--surface)" strokeWidth={2} />
                <text className="annotation" x={x(landingDays) + (x(landingDays) > w - 70 ? -6 : 6)} y={10}
                  textAnchor={x(landingDays) > w - 70 ? "end" : "start"}>Touchdown</text>
              </g>
            )}
          </g>
        </svg>
      )}
      <div className="key">
        <span className="k-sun">Sun elevation</span>
        {terrain && <span className="k-terrain">Terrain horizon towards the Sun (LOLA)</span>}
        <span className="k-window">
          Landing window, {site.sun_max_deg >= 90 ? `${site.sun_min_deg}° above the ${terrain ? "terrain" : "horizon"}` : `${site.sun_min_deg}° to ${site.sun_max_deg}°`}
          {site.sun_rising ? ", rising" : ""}
        </span>
        <span className="k-coast">First {fmtNum(coastDays, 0)} d: checkout in orbit</span>
      </div>
    </div>
  );
}
