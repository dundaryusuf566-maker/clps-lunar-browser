import { utcFormat } from "d3-time-format";
import { useCallback, useEffect, useMemo, useState } from "react";
import { DesignPanel } from "./components/DesignPanel";
import { AnywherePage } from "./components/AnywherePage";
import { ForecastPage } from "./components/ForecastPage";
import { ScenePage } from "./components/ScenePage";
import { PlannerPanel } from "./components/PlannerPanel";
import { Porkchop } from "./components/Porkchop";
import { SitePanel, summarise, type SiteSummary } from "./components/SitePanel";
import { SolutionSpace } from "./components/SolutionSpace";
import { TransferDetail } from "./components/TransferDetail";
import { TransferTable } from "./components/TransferTable";
import { ValidationPage } from "./components/ValidationPage";
import { isDark } from "./lib/color";
import { readParams, writeParams } from "./lib/urlstate";
import { familyName, fmtDay, parseUtc } from "./lib/format";
import { primeTrajectory, useDataset, useEngineHealth, useForecastFile, useHashPage, useThermalFile, useDivinerPolarFile, useDivinerDiagnosticsFile, useEphem, useOrientationFile, useLandingsFile, useThemeVersion, useValidationFile } from "./lib/hooks";
import { landingFor, seriesFor, type LandingStore } from "./lib/landing";
import { compareBy, LANDING_METRICS, METRICS, TRANSFER_METRICS } from "./lib/metrics";
import type { Dataset, DesignResult, FamilyFilter, LandingsFile, MetricKey, TransferRow } from "./types";

type View = "map" | "space";
const PAGES = ["browse", "anywhere", "forecast", "3d", "validation"] as const;
const monthFmt = utcFormat("%B %Y");

function ephemerisLabel(name: string): { text: string; demo: boolean } {
  if (name.includes("spice")) return { text: "JPL DE440 ephemeris", demo: false };
  return { text: "Analytic ephemeris, demo data only", demo: true };
}

export default function App() {
  const state = useDataset();
  const landings = useLandingsFile();
  if (state.status === "loading" || landings.status === "loading") {
    return <div className="app"><p className="empty">Loading transfers…</p></div>;
  }
  if (state.status === "error" || !state.data) {
    return (
      <div className="app">
        <p className="empty">
          Could not load the transfer data{state.status === "error" ? ` (${state.message})` : ""}. Build it with{" "}
          <code>python scripts/build_database.py --preset quick --spice</code> and reload.
        </p>
      </div>
    );
  }
  return <Browser data={state.data} landingsFile={landings.status === "ready" ? landings.data : null} />;
}

function Browser({ data, landingsFile }: { data: Dataset; landingsFile: LandingsFile | null }) {
  const themeVersion = useThemeVersion();
  const dark = useMemo(() => isDark(), [themeVersion]);
  const health = useEngineHealth();
  const validation = useValidationFile();
  const forecast = useForecastFile();
  const thermal = useThermalFile();
  const diviner = useDivinerPolarFile();
  const divinerDiag = useDivinerDiagnosticsFile();
  const ephem = useEphem();
  const orS = useOrientationFile("south"), orN = useOrientationFile("north");
  const orientation = [orS, orN].flatMap((o) => (o.status === "ready" && o.data ? [o.data] : []));
  const [page, setPage] = useHashPage(PAGES, "browse");
  const initial = useMemo(() => readParams(), []);
  const [metricKey, setMetricKey] = useState<MetricKey>(() => (initial.get("metric") as MetricKey) in METRICS ? (initial.get("metric") as MetricKey) : "loi");
  const [family, setFamily] = useState<FamilyFilter>(() => (initial.get("fam") === "1" ? 1 : initial.get("fam") === "-1" ? -1 : "all"));
  const [month, setMonth] = useState<string>(() => initial.get("month") ?? "all");
  const [view, setView] = useState<View>(() => (initial.get("view") === "space" ? "space" : "map"));
  const [siteId, setSiteId] = useState<string | null>(() =>
    landingsFile?.meta.sites.some((s) => s.id === initial.get("site")) ? initial.get("site") : null);
  const [custom, setCustom] = useState<TransferRow[]>([]);
  const [store, setStore] = useState<LandingStore>({ file: landingsFile, custom: {}, customSeries: {} });
  const metric = METRICS[metricKey];

  const sites = landingsFile?.meta.sites ?? [];
  const site = sites.find((s) => s.id === siteId) ?? null;
  const families = useMemo(() => [...new Set(data.rows.map((r) => r.family))].sort(), [data]);
  const months = useMemo(() => [...new Set(data.rows.map((r) => r.tli_utc.slice(0, 7)))].sort(), [data]);
  const showFamily = families.length > 1;

  const rows = useMemo(
    () => data.rows.filter((r) => (family === "all" || r.family === family) && (month === "all" || r.tli_utc.startsWith(month))),
    [data, family, month],
  );
  // The planner has its own date range, so it ignores the TLI-month filter.
  const familyRows = useMemo(() => data.rows.filter((r) => family === "all" || r.family === family), [data, family]);
  const landingOf = useCallback((r: TransferRow) => landingFor(store, siteId, r), [store, siteId]);

  const best = useMemo(() => {
    let b: { row: TransferRow; value: number } | null = null;
    for (const r of rows) {
      const v = metric.value(r, landingOf(r));
      if (v !== null && (!b || compareBy(metric, v, b.value) < 0)) b = { row: r, value: v };
    }
    return b;
  }, [rows, metric, landingOf]);

  const summaries = useMemo(() => {
    const out: Record<string, SiteSummary> = {};
    for (const s of sites) out[s.id] = summarise(rows, (r) => landingFor(store, s.id, r));
    return out;
  }, [sites, rows, store]);

  const [selectedId, setSelectedId] = useState<string | null>(() =>
    data.rows.some((r) => r.id === initial.get("sel")) ? initial.get("sel") : null);
  useEffect(() => {
    if (page !== "browse") return;
    writeParams({ site: siteId, metric: metricKey === "loi" ? null : metricKey, fam: family === "all" ? null : family,
      month: month === "all" ? null : month, view: view === "map" ? null : view,
      sel: selectedId && !selectedId.startsWith("live-") ? selectedId : null });
  }, [page, siteId, metricKey, family, month, view, selectedId]);
  useEffect(() => {
    const known = rows.some((r) => r.id === selectedId) || custom.some((r) => r.id === selectedId);
    if (!selectedId || !known) setSelectedId(best?.row.id ?? rows[0]?.id ?? null);
  }, [rows, custom, best, selectedId]);
  const selected = rows.find((r) => r.id === selectedId) ?? custom.find((r) => r.id === selectedId) ?? null;

  function chooseSite(id: string | null) {
    setSiteId(id);
    if (!selected?.custom) setSelectedId(null); // jump to the best transfer for the new site
    if (id && !METRICS[metricKey].needsSite) setMetricKey("surface");
    if (!id && METRICS[metricKey].needsSite) setMetricKey("loi");
  }

  function onDesigned(res: DesignResult) {
    if (!res.row) return;
    const row: TransferRow = { ...res.row, custom: true };
    if (res.trajectory) primeTrajectory(res.trajectory);
    setStore((s) => ({
      ...s,
      custom: { ...s.custom, [row.id]: res.landings ?? {} },
      customSeries: { ...s.customSeries, [row.id]: res.series ?? {} },
    }));
    setCustom((list) => [row, ...list.filter((r) => r.id !== row.id)]);
    setSelectedId(row.id);
  }

  const eph = ephemerisLabel(data.meta.ephemeris);
  const cap = data.meta.capture_orbit;
  const dates = data.rows.map((r) => r.tli_utc).sort();
  const toggleTheme = () => {
    document.documentElement.dataset.theme = isDark() ? "light" : "dark";
  };
  const selectedLanding = landingOf(selected as TransferRow);
  const selectedSeries = site && selected ? seriesFor(store, site.id, selected) : null;

  return (
    <div className="app">
      <header className="masthead">
        <div>
          <h1>CLPS Lunar Mission Browser</h1>
          <p>
            Earth-to-Moon transfers from a {data.meta.parking_orbit.alt_km} km parking orbit into a{" "}
            {cap.periselene_alt_km} km, {cap.lunar_inc_deg}° lunar orbit, solved in a full force model.
            Pick where you want to land, find the launch window that gets you there for the least Δv,
            then inspect the burns, the wait in orbit and the path.
          </p>
        </div>
        <div className="masthead-side">
          <div className="dataset">
            <strong>{data.meta.count} transfers</strong>, TLI {fmtDay(parseUtc(dates[0]))} to {fmtDay(parseUtc(dates[dates.length - 1]))}
            <br />
            <span className={eph.demo ? "warn" : undefined}>{eph.text}</span>
          </div>
          <button className="theme-toggle" onClick={toggleTheme}>{dark ? "Light mode" : "Dark mode"}</button>
        </div>
        <nav className="page-tabs" aria-label="Pages">
          <button aria-current={page === "browse" ? "page" : undefined} onClick={() => setPage("browse")}>Browse and plan</button>
          <button aria-current={page === "anywhere" ? "page" : undefined} onClick={() => setPage("anywhere")}>Anywhere</button>
          <button aria-current={page === "forecast" ? "page" : undefined} onClick={() => setPage("forecast")}>
            Forecast{forecast.status === "ready" && forecast.data ? `: ${forecast.data.mission.name.split(" (")[0]}` : ""}
          </button>
          <button aria-current={page === "3d" ? "page" : undefined} onClick={() => setPage("3d")}>3D view</button>
          <button aria-current={page === "validation" ? "page" : undefined} onClick={() => setPage("validation")}>
            Validation
          </button>
        </nav>
      </header>

      {page === "forecast" && <ForecastPage data={forecast.status === "ready" ? forecast.data : null} dark={dark}
        thermal={thermal.status === "ready" ? thermal.data : null} />}
      {page === "anywhere" && <AnywherePage ephem={ephem} sites={sites} />}
      {page === "3d" && <ScenePage forecast={forecast.status === "ready" ? forecast.data : null} />}
      {page === "validation" && <ValidationPage data={validation.status === "ready" ? validation.data : null} dark={dark}
        thermal={thermal.status === "ready" ? thermal.data : null} diviner={diviner.status === "ready" ? diviner.data : null}
        divinerDiag={divinerDiag.status === "ready" ? divinerDiag.data : null} orientation={orientation} />}
      {page === "browse" && <>
      <div className="controls">
        <div className="control">
          <span id="metric-label">Compare by</span>
          <div className="segmented" role="group" aria-labelledby="metric-label">
            {TRANSFER_METRICS.map((k) => (
              <button key={k} aria-pressed={metricKey === k} onClick={() => setMetricKey(k)}>{METRICS[k].label}</button>
            ))}
          </div>
          {site && (
            <div className="segmented" role="group" aria-label={`Landing at ${site.name}`}>
              {LANDING_METRICS.map((k) => (
                <button key={k} aria-pressed={metricKey === k} onClick={() => setMetricKey(k)}>{METRICS[k].label}</button>
              ))}
            </div>
          )}
        </div>
        {showFamily && (
          <div className="control">
            <span id="family-label">Approach</span>
            <div className="segmented" role="group" aria-labelledby="family-label">
              <button aria-pressed={family === "all"} onClick={() => setFamily("all")}>Better of both</button>
              {families.map((f) => (
                <button key={f} aria-pressed={family === f} onClick={() => setFamily(f as 1 | -1)}>{familyName(f)}</button>
              ))}
            </div>
          </div>
        )}
        {months.length > 1 && (
          <label className="control">
            TLI window
            <select value={month} onChange={(e) => setMonth(e.target.value)}>
              <option value="all">All dates</option>
              {months.map((m) => <option key={m} value={m}>{monthFmt(new Date(`${m}-01T00:00:00Z`))}</option>)}
            </select>
          </label>
        )}
      </div>

      <div className="layout">
        {sites.length > 0 && <SitePanel sites={sites} selectedId={siteId} onSelect={chooseSite} summaries={summaries} />}
        {landingsFile && (
          <PlannerPanel site={site} rows={familyRows} landingOf={landingOf}
            maxWaitAnalysed={landingsFile.meta.constraints.max_wait_days}
            daylightHorizon={landingsFile.meta.constraints.daylight_horizon_days}
            selected={selected} onSelect={setSelectedId} showFamily={showFamily} dark={dark} />
        )}
        <div className="area-design">
          <DesignPanel health={health} seed={selected} custom={custom} selectedId={selectedId}
            onDesigned={onDesigned} onSelect={setSelectedId} />
        </div>
        <section className="panel area-chart">
          <div className="panel-head">
            <div className="view-tabs" role="tablist">
              <button role="tab" aria-selected={view === "map"} onClick={() => setView("map")}>Launch window map</button>
              <button role="tab" aria-selected={view === "space"} onClick={() => setView("space")}>{metric.label} by launch date</button>
            </div>
            <span className="hint">{view === "map" ? "Arrow keys move between transfers" : "Hover a dot for its value"}</span>
          </div>
          <div className="panel-body">
            {rows.length === 0 ? (
              <p className="empty">No transfers match these filters.</p>
            ) : view === "map" ? (
              <Porkchop rows={rows} metric={metric} landingOf={landingOf} selectedId={selectedId} onSelect={setSelectedId} dark={dark} />
            ) : (
              <SolutionSpace rows={rows} metric={metric} landingOf={landingOf} selectedId={selectedId} onSelect={setSelectedId} dark={dark} />
            )}
          </div>
        </section>
        <TransferTable rows={rows} metric={metric} landingOf={landingOf} site={site} selectedId={selectedId}
          onSelect={setSelectedId} showFamily={showFamily} />
        <TransferDetail row={selected} best={best} metric={metric} landing={selectedLanding} site={site}
          series={selectedSeries} constraints={landingsFile?.meta.constraints ?? null} showFamily={showFamily}
          themeVersion={themeVersion} engineOnline={!!health} />
      </div>

      <div className="footnote">
        <p>
          Each transfer is targeted in a force model with Earth, Moon and Sun gravity plus Earth and lunar zonal harmonics,
          first in the lunar B-plane and then on the propagated periselene. The parking orbit inclination starts at{" "}
          {data.meta.parking_orbit.min_inc_deg}° (Cape Canaveral) and is raised by the launch azimuth only when the Moon's
          declination requires it. RAAN from Sun is the capture orbit's node measured from the Sun direction in the lunar equator.
        </p>
        {landingsFile && (
          <p>
            Landing: after at least {landingsFile.meta.constraints.min_coast_days} day of checkout and within{" "}
            {landingsFile.meta.constraints.max_wait_days} days, the lander goes down when the site's Sun window and Earth
            visibility allow it, with a plane change of at most {landingsFile.meta.constraints.max_plane_change_ms} m/s. The
            earliest option within {landingsFile.meta.constraints.prefer_within_ms} m/s of the cheapest is chosen. {landingsFile.meta.model_notes.join(" ")}
          </p>
        )}
        <p>Data: {data.meta.source_csv}, generated {fmtDay(parseUtc(data.meta.generated_utc))}.</p>
      </div>
      </>}
    </div>
  );
}
