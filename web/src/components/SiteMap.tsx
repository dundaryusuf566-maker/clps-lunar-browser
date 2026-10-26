import { useState } from "react";
import { useWidth } from "../lib/hooks";
import type { Site } from "../types";

interface Props {
  sites: Site[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  windows: Record<string, number>; // site id -> landing windows in the current selection
}

const M = { top: 8, right: 8, bottom: 22, left: 30 };

/** Equirectangular map of the Moon with the candidate sites. */
export function SiteMap({ sites, selectedId, onSelect, windows }: Props) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<string | null>(null);
  const w = Math.max(0, width - M.left - M.right);
  const h = w / 2;
  const x = (lon: number) => ((lon + 180) / 360) * w;
  const y = (lat: number) => ((90 - lat) / 180) * h;
  const label = sites.find((s) => s.id === (hover ?? selectedId));

  return (
    <div ref={ref} className="chart site-map">
      {width > 0 && (
        <svg width={width} height={h + M.top + M.bottom} role="group" aria-label="Map of the Moon with candidate landing sites">
          <g transform={`translate(${M.left},${M.top})`}>
            <rect width={w} height={h} fill="var(--surface)" stroke="var(--rule)" />
            <rect x={0} width={x(-90)} height={h} fill="var(--moon-fill)" />
            <rect x={x(90)} width={w - x(90)} height={h} fill="var(--moon-fill)" />
            {[-60, -30, 0, 30, 60].map((lat) => (
              <line key={lat} className="gridline" x1={0} x2={w} y1={y(lat)} y2={y(lat)}
                stroke={lat === 0 ? "var(--rule)" : undefined} />
            ))}
            {[-150, -120, -90, -60, -30, 0, 30, 60, 90, 120, 150].map((lon) => (
              <line key={lon} className="gridline" x1={x(lon)} x2={x(lon)} y1={0} y2={h} />
            ))}
            <text className="map-region" x={x(0)} y={14} textAnchor="middle">Near side</text>
            <text className="map-region" x={x(-135)} y={14} textAnchor="middle">Far side</text>
            <text className="map-region" x={x(135)} y={14} textAnchor="middle">Far side</text>
            <g className="axis">
              {[60, 0, -60].map((lat) => (
                <text key={lat} x={-6} y={y(lat) + 4} textAnchor="end">{lat === 0 ? "0°" : `${Math.abs(lat)}°${lat > 0 ? "N" : "S"}`}</text>
              ))}
              {[-90, 0, 90].map((lon) => (
                <text key={lon} x={x(lon)} y={h + 15} textAnchor="middle">{lon === 0 ? "0°" : `${Math.abs(lon)}°${lon > 0 ? "E" : "W"}`}</text>
              ))}
            </g>

            {sites.map((s) => {
              const sel = s.id === selectedId;
              const none = (windows[s.id] ?? 0) === 0;
              return (
                <g key={s.id} className="site-marker" transform={`translate(${x(s.lon_deg)},${y(s.lat_deg)})`}
                  role="button" tabIndex={0} aria-pressed={sel}
                  aria-label={`${s.name}, ${s.region}, ${windows[s.id] ?? 0} landing windows`}
                  onClick={() => onSelect(s.id)}
                  onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onSelect(s.id))}
                  onPointerEnter={() => setHover(s.id)} onPointerLeave={() => setHover(null)}
                  onFocus={() => setHover(s.id)} onBlur={() => setHover(null)}>
                  <circle r={14} fill="transparent" />
                  {sel && <circle r={9} fill="none" stroke="var(--signal)" strokeWidth={2} />}
                  <circle r={sel ? 5.5 : 4.5} fill={sel ? "var(--signal)" : none ? "var(--surface)" : "var(--ink)"}
                    stroke={sel ? "var(--surface)" : "var(--ink)"} strokeWidth={1.5} />
                </g>
              );
            })}
            {label && (() => {
              const lx = x(label.lon_deg), ly = y(label.lat_deg);
              const right = lx < w * 0.62;
              return (
                <text className="map-label" x={lx + (right ? 12 : -12)} y={ly < 20 ? ly + 16 : ly - 9}
                  textAnchor={right ? "start" : "end"} pointerEvents="none">{label.name}</text>
              );
            })()}
          </g>
        </svg>
      )}
    </div>
  );
}
