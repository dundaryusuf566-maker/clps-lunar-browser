import { scaleLinear } from "d3-scale";
import { useState } from "react";
import { fmtNum } from "../lib/format";
import { useWidth } from "../lib/hooks";
import type { SiteTerrain } from "../types";

interface Props {
  terrain: SiteTerrain;
  latDeg: number;
  name: string;
  height?: number;
  /** replaces the default description (for horizons without distances, e.g. interpolated from a grid) */
  note?: string;
}

const M = { top: 16, right: 10, bottom: 26, left: 34 };
const COMPASS: [number, string][] = [[0, "N"], [45, "NE"], [90, "E"], [135, "SE"], [180, "S"], [225, "SW"], [270, "W"], [315, "NW"]];
const OBLIQUITY_DEG = 1.54;   // the Moon's spin axis vs the ecliptic: the Sun's highest elevation is 90 - |lat| + 1.54

/** 360 deg panorama of the terrain horizon around a site (LOLA). */
export function HorizonChart({ terrain, latDeg, name, height = 170, note }: Props) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const w = Math.max(0, width - M.left - M.right);
  const h = height - M.top - M.bottom;
  const el = terrain.elev_deg;
  const step = terrain.az_step_deg;
  const sunMax = 90 - Math.abs(latDeg) + OBLIQUITY_DEG;
  const lo = Math.min(-2, Math.floor(Math.min(...el))), hi = Math.max(Math.ceil(Math.max(...el)) + 1, Math.ceil(sunMax) + 1);
  const x = scaleLinear().domain([0, 360]).range([0, w]);
  const y = scaleLinear().domain([lo, hi]).nice().range([h, 0]);
  const pts = [...el, el[0]].map((v, i) => [i * step, v] as const);
  const path = pts.map(([a, v], i) => `${i ? "L" : "M"}${x(a).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const fill = `${path}L${x(360)},${h}L0,${h}Z`;
  const imax = el.indexOf(Math.max(...el));
  const hi_ = hover ?? imax;

  return (
    <div ref={ref} className="chart horizon-chart">
      {width > 0 && (
        <svg width={width} height={height} role="img"
          aria-label={`Terrain horizon around ${name}: highest ${fmtNum(el[imax], 1)} degrees towards azimuth ${fmtNum(imax * step, 0)}`}>
          <g transform={`translate(${M.left},${M.top})`}>
            {y.ticks(4).map((v) => (
              <g key={v} className="axis">
                <line className="gridline" x1={0} x2={w} y1={y(v)} y2={y(v)} />
                <text x={-6} y={y(v) + 4} textAnchor="end">{v}°</text>
              </g>
            ))}
            <path className="terrain-fill" d={fill} />
            <path className="terrain-line" d={path} />
            <line x1={0} x2={w} y1={y(0)} y2={y(0)} stroke="var(--ink-3)" strokeDasharray="3 3" />
            <g className="ref-line sun-max">
              <line x1={0} x2={w} y1={y(sunMax)} y2={y(sunMax)} />
              <text x={w} y={y(sunMax) - 5} textAnchor="end">Sun never higher than {fmtNum(sunMax, 1)}°</text>
            </g>
            <g className="axis" transform={`translate(0,${h + 16})`}>
              {COMPASS.map(([a, l]) => <text key={a} x={x(a)} textAnchor="middle">{l}</text>)}
            </g>
            <line x1={x(hi_ * step)} x2={x(hi_ * step)} y1={y(el[hi_])} y2={h} stroke="var(--ink)" strokeWidth={1} />
            <circle cx={x(hi_ * step)} cy={y(el[hi_])} r={3.5} fill="var(--ink)" />
            <rect width={w} height={h} fill="transparent"
              onPointerMove={(e) => {
                const b = e.currentTarget.getBoundingClientRect();
                const i = Math.round(x.invert(e.clientX - b.left) / step) % el.length;
                setHover(Math.max(0, i));
              }}
              onPointerLeave={() => setHover(null)} />
          </g>
        </svg>
      )}
      {note ? (
        <p className="orbit-note num">{hover === null ? "Highest: " : ""}{fmtNum(el[hi_], 2)}° at azimuth {fmtNum(hi_ * step, 1)}°. {note}</p>
      ) : <p className="orbit-note num">
        {hover === null ? "Highest: " : ""}{fmtNum(el[hi_], 2)}° at azimuth {fmtNum(hi_ * step, 1)}°,
        terrain {terrain.dist_km[hi_] < 1 ? `${fmtNum(terrain.dist_km[hi_] * 1000, 0)} m` : `${fmtNum(terrain.dist_km[hi_], 0)} km`} away. Site {fmtNum(terrain.site_height_m, 0)} m above the 1737.4 km
        sphere; LOLA {terrain.source}, observer {fmtNum(terrain.observer_m, 0)} m above the ground, terrain to{" "}
        {fmtNum(terrain.max_dist_km, 0)} km.
      </p>}
    </div>
  );
}
