import { fmtDayTime, fmtNum, parseUtc } from "../lib/format";
import { arrivalEpoch, dsnNames, reasonText } from "../lib/landing";
import type { Landing, LandingConstraintsMeta, Site, SunSeries, TransferRow } from "../types";
import { SunChart } from "./SunChart";

interface Props {
  row: TransferRow;
  site: Site;
  landing: Landing | null;
  series: SunSeries | null;
  constraints: LandingConstraintsMeta;
}

export function LandingBlock({ row, site, landing, series, constraints }: Props) {
  const arrivalMs = parseUtc(row.tli_utc).getTime() + row.tof_actual_days * 86400e3;
  return (
    <div className="landing-block">
      <h3>Landing at {site.name}</h3>
      {!landing && <p className="orbit-note">No landing analysis for this transfer.</p>}
      {landing && landing.feasible && landing.waitDays !== null && (
        <>
          <p className="when">
            Touch down {fmtDayTime(new Date(arrivalMs + landing.waitDays * 86400e3))}
            <br />after {fmtNum(landing.waitDays, 1)} days in lunar orbit
          </p>
          <dl className="figures">
            <div><dt>Plane change</dt><dd>{fmtNum(landing.planeChangeMs ?? 0, 0)}<small>m/s</small></dd></div>
            <div><dt>Descent (estimate)</dt><dd>{fmtNum(landing.descentMs, 0)}<small>m/s</small></dd></div>
            <div><dt>Δv to surface</dt><dd>{fmtNum(landing.surfaceMs ?? 0, 0)}<small>m/s</small></dd></div>
            <div><dt>Sun at touchdown</dt><dd>{fmtNum(landing.sunElDeg ?? 0, 1)}°
              {site.terrain && landing.sunHorizonDeg !== null && <small>{fmtNum((landing.sunElDeg ?? 0) - landing.sunHorizonDeg, 1)}° above terrain</small>}</dd></div>
            <div><dt>Earth at touchdown</dt><dd>{site.requires_relay ? "Relay" : `${fmtNum(landing.earthElDeg ?? 0, 1)}°`}</dd></div>
            <div><dt>Sunlight after landing</dt><dd>{landing.daylightCapped ? "≥ " : ""}{fmtNum(landing.daylightDays ?? 0, 1)}<small>days</small></dd></div>
            {landing.energyPct !== null && (
              <div><dt>Energy, first {constraints.energy_window_days ?? 5} days</dt><dd>{fmtNum(landing.energyPct, 0)}<small>% of full Sun</small></dd></div>
            )}
            {landing.darkGapH !== null && (
              <div><dt>Longest shadow then</dt><dd>{landing.darkGapH > 0
                ? <>{fmtNum(landing.darkGapH, landing.darkGapH < 10 ? 1 : 0)}<small>h</small></>
                : <span className="dd-text">none</span>}</dd></div>
            )}
            {landing.dsn !== null && (
              <div><dt>DSN at touchdown</dt><dd className="dd-text">{dsnNames(landing.dsn).join(", ") || "none"}</dd></div>
            )}
          </dl>
        </>
      )}
      {landing && !landing.feasible && (
        <p className="no-landing">
          No landing window within {constraints.max_wait_days} days of arrival.{" "}
          {reasonText(landing, site, constraints.max_plane_change_ms, constraints.max_wait_days)}
        </p>
      )}
      {series && (
        <SunChart series={series} site={site} arrival={arrivalEpoch(row)} days={constraints.max_wait_days}
          coastDays={constraints.min_coast_days} landingDays={landing?.feasible ? landing.waitDays : null} />
      )}
    </div>
  );
}
