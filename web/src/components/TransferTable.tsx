import { useState } from "react";
import { familyName, fmtDay, fmtNum, fmtTof, parseUtc } from "../lib/format";
import { compareBy, type Metric } from "../lib/metrics";
import type { Landing, Site, TransferRow } from "../types";

interface Props {
  rows: TransferRow[];
  metric: Metric;
  landingOf: (r: TransferRow) => Landing | null;
  site: Site | null;
  selectedId: string | null;
  onSelect: (id: string) => void;
  showFamily: boolean;
}

/** Best transfers first. Doubles as the accessible table view of the charts. */
export function TransferTable({ rows, metric, landingOf, site, selectedId, onSelect, showFamily }: Props) {
  const [all, setAll] = useState(false);
  const scored = rows.map((r) => ({ r, l: landingOf(r), v: metric.value(r, landingOf(r)) }));
  scored.sort((a, b) => compareBy(metric, a.v, b.v));
  const shown = all ? scored : scored.slice(0, 10);
  const landingTime = (r: TransferRow, l: Landing | null) =>
    l?.feasible && l.waitDays !== null
      ? fmtDay(new Date(parseUtc(r.tli_utc).getTime() + (r.tof_actual_days + l.waitDays) * 86400e3))
      : "–";

  return (
    <section className="panel area-table">
      <div className="panel-head">
        <h2>{all ? `All ${rows.length} transfers` : "Ten best transfers"}, by {metric.label}{site ? ` at ${site.name}` : ""}</h2>
        <button className="theme-toggle" onClick={() => setAll(!all)}>{all ? "Show ten best" : `Show all ${rows.length}`}</button>
      </div>
      <div className="panel-body table-wrap">
        <table>
          <thead>
            <tr>
              <th className="rank">#</th>
              <th className="left">TLI date</th>
              <th>Transit</th>
              {showFamily && <th className="left">Approach</th>}
              <th>LOI Δv (m/s)</th>
              {site ? (
                <>
                  <th className="left">Landing</th>
                  <th>Wait (d)</th>
                  <th>Plane Δv (m/s)</th>
                  <th>Δv to surface (m/s)</th>
                  <th>Sunlight (d)</th>
                </>
              ) : (
                <>
                  <th>Total Δv (m/s)</th>
                  <th>TLI Δv (m/s)</th>
                  <th>C3 (km²/s²)</th>
                  <th>v∞ (km/s)</th>
                  <th>RAAN from Sun (°)</th>
                </>
              )}
            </tr>
          </thead>
          <tbody>
            {shown.map(({ r, l }, i) => (
              <tr key={r.id} aria-selected={r.id === selectedId} onClick={() => onSelect(r.id)} tabIndex={0}
                onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onSelect(r.id))}>
                <td className="rank">{i + 1}</td>
                <td className="left">{fmtDay(parseUtc(r.tli_utc))}</td>
                <td>{fmtTof(r.tof_days)}</td>
                {showFamily && <td className="left">{familyName(r.family)}</td>}
                <td>{fmtNum(r.loi_dv_ms, 1)}</td>
                {site ? (
                  <>
                    <td className="left">{landingTime(r, l)}</td>
                    <td>{l?.feasible ? fmtNum(l.waitDays ?? 0, 1) : "–"}</td>
                    <td>{l?.feasible ? fmtNum(l.planeChangeMs ?? 0, 0) : "–"}</td>
                    <td>{l?.feasible ? fmtNum(l.surfaceMs ?? 0, 0) : "No window"}</td>
                    <td>{l?.feasible ? `${l.daylightCapped ? "≥ " : ""}${fmtNum(l.daylightDays ?? 0, 1)}` : "–"}</td>
                  </>
                ) : (
                  <>
                    <td>{fmtNum(r.total_dv_ms, 0)}</td>
                    <td>{fmtNum(r.tli_dv_ms, 1)}</td>
                    <td>{fmtNum(r.c3_km2s2, 3)}</td>
                    <td>{fmtNum(r.v_inf_kms, 3)}</td>
                    <td>{fmtNum(r.raan_moon_sun_deg, 1)}</td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
