import { fmtNum } from "../lib/format";
import type { Landing, Site, TransferRow } from "../types";
import { HorizonChart } from "./HorizonChart";
import { SiteMap } from "./SiteMap";

export interface SiteSummary {
  windows: number;
  total: number;
  bestSurfaceMs: number | null;
  medianWait: number | null;
  medianDaylight: number | null;
}

function median(v: number[]): number | null {
  if (!v.length) return null;
  const s = [...v].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

export function summarise(rows: TransferRow[], landingOf: (r: TransferRow) => Landing | null): SiteSummary {
  let windows = 0;
  let best: number | null = null;
  const waits: number[] = [], days: number[] = [];
  for (const r of rows) {
    const l = landingOf(r);
    if (!l?.feasible) continue;
    windows++;
    if (l.surfaceMs !== null && (best === null || l.surfaceMs < best)) best = l.surfaceMs;
    if (l.waitDays !== null) waits.push(l.waitDays);
    if (l.daylightDays !== null) days.push(l.daylightDays);
  }
  return { windows, total: rows.length, bestSurfaceMs: best, medianWait: median(waits), medianDaylight: median(days) };
}

interface Props {
  sites: Site[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  summaries: Record<string, SiteSummary>;
}

const coord = (v: number, pos: string, neg: string) => `${fmtNum(Math.abs(v), 2)}°${v >= 0 ? pos : neg}`;

export function SitePanel({ sites, selectedId, onSelect, summaries }: Props) {
  const selected = sites.find((s) => s.id === selectedId) ?? null;
  const windows = Object.fromEntries(sites.map((s) => [s.id, summaries[s.id]?.windows ?? 0]));
  return (
    <section className="panel area-sites" aria-labelledby="sites-title">
      <div className="panel-head">
        <h2 id="sites-title">Where do you want to land?</h2>
        {selected
          ? <button className="theme-toggle" onClick={() => onSelect(null)}>Show transfers only</button>
          : <span className="hint">Pick a site to see when each transfer can land there</span>}
      </div>
      <div className="panel-body site-grid">
        <SiteMap sites={sites} selectedId={selectedId} onSelect={(id) => onSelect(id === selectedId ? null : id)} windows={windows} />
        <div className="table-wrap">
          <table className="site-table" aria-describedby="sites-caption">
            <thead>
              <tr>
                <th>Site</th>
                <th>Landing windows</th>
                <th>Best Δv to surface (m/s)</th>
                <th>Typical wait (d)</th>
                <th>Typical sunlight (d)</th>
              </tr>
            </thead>
            <tbody>
              {sites.map((s) => {
                const m = summaries[s.id];
                return (
                  <tr key={s.id} aria-selected={s.id === selectedId} tabIndex={0}
                    onClick={() => onSelect(s.id === selectedId ? null : s.id)}
                    onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onSelect(s.id === selectedId ? null : s.id))}>
                    <td className="left">{s.name}<span className="sub-cell">{s.region}{s.requires_relay ? ", needs relay" : ""}</span></td>
                    <td>{m ? `${m.windows} of ${m.total}` : "–"}
                      {m && m.total > 0 && <span className="sub-cell">{Math.round((100 * m.windows) / m.total)}% of transfers</span>}</td>
                    <td>{m?.bestSurfaceMs != null ? fmtNum(m.bestSurfaceMs, 0) : "–"}</td>
                    <td>{m?.medianWait != null ? fmtNum(m.medianWait, 1) : "–"}</td>
                    <td>{m?.medianDaylight != null ? fmtNum(m.medianDaylight, 1) : "–"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p id="sites-caption" className="table-note">
            Typical values are medians over the transfers that can land. The best Δv to surface is set mostly by the
            insertion burn: picking the right launch date makes the plane change almost free.
          </p>
        </div>
        {selected && (
          <div className="site-info">
            <p>
              <strong>{selected.name}</strong>, {coord(selected.lat_deg, "N", "S")} {coord(selected.lon_deg, "E", "W")}.{" "}
              {selected.missions}{" "}
              Landing window: Sun {selected.sun_max_deg >= 90
                ? `${selected.sun_min_deg}° above the ${selected.terrain ? "LOLA terrain horizon" : "horizon"}`
                : `${selected.sun_min_deg}° to ${selected.sun_max_deg}°`}
              {selected.sun_rising ? " and rising" : ""}
              {selected.requires_relay ? "; Earth never in view, so a relay satellite is assumed." : ", Earth in view."}
            </p>
            {selected.note && <p className="sub">{selected.note}</p>}
            {selected.terrain && (
              <div className="site-horizon">
                <h3>Horizon around {selected.name}</h3>
                <HorizonChart terrain={selected.terrain} latDeg={selected.lat_deg} name={selected.name} />
              </div>
            )}
            <p className="sub"><a href={selected.source} target="_blank" rel="noreferrer">Coordinates source</a></p>
          </div>
        )}
      </div>
    </section>
  );
}
