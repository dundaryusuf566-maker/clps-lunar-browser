import { familyName, fmtDayTime, fmtDuration, fmtNum, parseUtc } from "../lib/format";
import { useTrajectory } from "../lib/hooks";
import { METRICS, type Metric } from "../lib/metrics";
import type { Landing, LandingConstraintsMeta, Site, SunSeries, TransferRow } from "../types";
import { LandingBlock } from "./LandingBlock";
import { TrajectoryView } from "./TrajectoryView";

interface Props {
  row: TransferRow | null;
  best: { row: TransferRow; value: number } | null;
  metric: Metric;
  landing: Landing | null;
  site: Site | null;
  series: SunSeries | null;
  constraints: LandingConstraintsMeta | null;
  showFamily: boolean;
  themeVersion: number;
  engineOnline: boolean;
}

export function TransferDetail({ row, best, metric, landing, site, series, constraints, showFamily, themeVersion, engineOnline }: Props) {
  const traj = useTrajectory(row, engineOnline);
  if (!row) {
    return (
      <section className="panel detail area-detail">
        <div className="empty">Pick a transfer on the map to see its burns, timeline and path.</div>
      </section>
    );
  }
  const value = metric.value(row, landing);
  const hero = value !== null ? metric : METRICS.loi;
  const heroValue = value ?? row.loi_dv_ms;
  const tli = parseUtc(row.tli_utc);
  const arrive = new Date(tli.getTime() + row.tof_actual_days * 86400e3);
  const ready = traj?.status === "ready" ? traj.data : null;
  const soi = ready?.events.soi ?? null;
  const tof = row.tof_actual_days * 86400;
  const wait = landing?.feasible && landing.waitDays !== null ? landing.waitDays * 86400 : null;
  const delta = best && value !== null ? Math.abs(value - best.value) : 0;

  return (
    <section className="panel detail area-detail" aria-live="polite">
      <div className="panel-head">
        <h2>
          {row.custom ? "Your " : ""}{fmtNum(row.tof_days, Number.isInteger(row.tof_days) ? 0 : 2)}-day transfer
          {showFamily || row.custom ? `, ${familyName(row.family).toLowerCase()}` : ""}
        </h2>
      </div>
      <div className="panel-body">
        <p className="when">Leave Earth orbit {fmtDayTime(tli)}<br />Arrive at the Moon {fmtDayTime(arrive)}</p>

        <div className="hero-figure">
          <span className="value">{fmtNum(heroValue, hero.digits)}</span>
          <span className="unit">{hero.unit}</span>
        </div>
        <p className="hero-caption">
          {hero.long}{site && hero.needsSite ? ` at ${site.name}` : ""}.{" "}
          {value === null ? (
            <span className="delta">No landing window at {site?.name} for this transfer.</span>
          ) : row.custom ? null : best && best.row.id !== row.id ? (
            <><span className="delta num">{fmtNum(delta, metric.digits)} {metric.unit}</span> {metric.better === "low" ? "above" : "below"} the best transfer shown.</>
          ) : (
            <span className="delta">The best transfer shown.</span>
          )}
        </p>

        <dl className="figures">
          <div><dt>TLI Δv</dt><dd>{fmtNum(row.tli_dv_ms, 0)}<small>m/s</small></dd></div>
          <div><dt>LOI Δv</dt><dd>{fmtNum(row.loi_dv_ms, 1)}<small>m/s</small></dd></div>
          <div><dt>Total Δv</dt><dd>{fmtNum(row.total_dv_ms, 0)}<small>m/s</small></dd></div>
          <div><dt>C3</dt><dd>{fmtNum(row.c3_km2s2, 3)}<small>km²/s²</small></dd></div>
          <div><dt>v∞ at Moon</dt><dd>{fmtNum(row.v_inf_kms, 3)}<small>km/s</small></dd></div>
          <div><dt>RAAN from Sun</dt><dd>{fmtNum(row.raan_moon_sun_deg, 1)}°</dd></div>
          <div><dt>Periselene latitude</dt><dd>{fmtNum(row.periselene_lat_deg, 1)}°</dd></div>
          <div><dt>Parking inclination</dt><dd>{fmtNum(row.parking_inc_deg, 2)}°</dd></div>
          <div><dt>Capture orbit</dt><dd>{fmtNum(row.periselene_alt_km, 0)}<small>km, {fmtNum(row.lunar_inc_deg, 0)}°</small></dd></div>
        </dl>

        <div className="timeline" aria-label="Mission timeline">
          <div className="timeline-bar" aria-hidden="true">
            <span style={{ flex: soi ?? tof * 0.85, background: "var(--signal)" }} />
            <span style={{ flex: soi ? tof - soi : tof * 0.15, background: "var(--signal)", opacity: 0.45 }} />
            {wait !== null && <span style={{ flex: wait, background: "var(--ink-3)", opacity: 0.35 }} />}
          </div>
          <ol style={{ gridTemplateColumns: `repeat(${wait !== null ? 4 : 3}, 1fr)` }}>
            <li><strong>TLI</strong>Burn {fmtNum(row.tli_dv_ms, 0)} m/s</li>
            <li><strong>Lunar SOI</strong>{soi ? `after ${fmtDuration(soi)}` : "entry point"}</li>
            <li><strong>LOI</strong>after {fmtDuration(tof)}</li>
            {wait !== null && <li><strong>Landing</strong>after {fmtDuration(tof + wait)}</li>}
          </ol>
        </div>

        {site && constraints && (
          <LandingBlock row={row} site={site} landing={landing} series={series} constraints={constraints} />
        )}

        {traj?.status === "unavailable" && (
          <p className="orbit-note">This path was not exported. Start the engine (<code>python -m api.server</code>) to compute it.</p>
        )}
        {traj?.status === "loading" && <p className="orbit-note">{row.has_trajectory ? "Loading path…" : "Computing path with the engine…"}</p>}
        {traj?.status === "error" && <p className="orbit-note">Could not load the path: {traj.message}</p>}
        {ready && <TrajectoryView traj={ready} themeVersion={themeVersion} />}
      </div>
    </section>
  );
}
