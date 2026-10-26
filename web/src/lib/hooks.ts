import { useEffect, useRef, useState } from "react";
import type { HorizonGridMeta } from "./horizonGrid";
import type { SlopeMapMeta } from "./slopeMap";
import { ephemFromBuffers, type Ephem, type EphemMeta } from "./sky";
import type { Dataset, OrientationFile, DivinerDiagnosticsFile, DivinerPolarFile, ForecastFile, LandingsFile, ThermalFile, Trajectory, TransferRow, ValidationFile } from "../types";
import { fetchTrajectoryLive, getHealth, type Health } from "./api";

export const BASE = import.meta.env.BASE_URL;

export type Loadable<T> = { status: "loading" } | { status: "ready"; data: T } | { status: "error"; message: string };

function useJson<T>(path: string, optional = false): Loadable<T | null> {
  const [state, setState] = useState<Loadable<T | null>>({ status: "loading" });
  useEffect(() => {
    fetch(`${BASE}${path}`)
      .then((r) => {
        if (r.status === 404 && optional) return null;
        if (!r.ok) throw new Error(`${path} returned ${r.status}`);
        return r.json();
      })
      .then((data) => setState({ status: "ready", data }))
      .catch((e: Error) => (optional ? setState({ status: "ready", data: null }) : setState({ status: "error", message: e.message })));
  }, [path, optional]);
  return state;
}

export const useDataset = () => useJson<Dataset>("data/transfers.json");
/** Landing analysis is optional: older exports did not have it. */
export const useLandingsFile = () => useJson<LandingsFile>("data/landings.json", true);
/** Validation page data (scripts/build_validation.py), optional. */
export const useValidationFile = () => useJson<ValidationFile>("data/validation.json", true);
/** Registered forecast for an upcoming mission (scripts/build_forecast.py), optional. */
export const useForecastFile = () => useJson<ForecastFile>("data/forecast.json", true);
/** Regolith temperatures (scripts/build_thermal.py), optional. */
export const useThermalFile = () => useJson<ThermalFile>("data/thermal.json", true);
/** Polar temperatures against Diviner (scripts/diviner_polar_check.py), optional. */
export const useDivinerPolarFile = () => useJson<DivinerPolarFile>("data/diviner_polar.json", true);
/** The Moon's sky table (scripts/build_ephemeris_table.py): for the analysis of any point, in the browser. */
export function useEphem(): Loadable<Ephem | null> {
  const [state, setState] = useState<Loadable<Ephem | null>>({ status: "loading" });
  useEffect(() => {
    Promise.all([fetch(`${BASE}data/ephem_moon.json`), fetch(`${BASE}data/ephem_moon.bin`)])
      .then(async ([m, b]) => {
        if (m.status === 404 || b.status === 404) return null;
        if (!m.ok || !b.ok) throw new Error(`ephemeris table returned ${m.status}/${b.status}`);
        return ephemFromBuffers((await m.json()) as EphemMeta, await b.arrayBuffer());
      })
      .then((data) => setState({ status: "ready", data }))
      .catch((e: Error) => setState({ status: "error", message: e.message }));
  }, []);
  return state;
}
/** Polar horizon grids (scripts/build_horizon_grid.py), optional; tiles are fetched by the page. */
export const useHorizonGridMeta = (pole: "s" | "n") => useJson<HorizonGridMeta>(`data/horizon_grid_${pole}.json`, true);
/** Polar slope maps (scripts/build_slope_map.py), optional; tiles are fetched by the page. */
export const useSlopeMapMeta = (pole: "s" | "n") => useJson<SlopeMapMeta>(`data/slope_map_${pole}.json`, true);
export const useOrientationFile = (pole: "south" | "north") => useJson<OrientationFile>(`data/orientation_${pole}.json`, true);
export const useDivinerDiagnosticsFile = () => useJson<DivinerDiagnosticsFile>("data/diviner_polar_diagnostics.json", true);

/** Page kept in the URL hash so a link can open the validation page directly. */
export function useHashPage<T extends string>(pages: readonly T[], fallback: T): [T, (p: T) => void] {
  const read = () => {
    const h = window.location.hash.replace(/^#/, "").split("?")[0] as T;
    return pages.includes(h) ? h : fallback;
  };
  const [page, setPage] = useState<T>(read);
  useEffect(() => {
    const on = () => setPage(read());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const go = (p: T) => {
    const h = window.location.hash.replace(/^#/, "");
    const q = h.includes("?") ? h.slice(h.indexOf("?")) : "";
    if (p === fallback && !q) history.replaceState(null, "", window.location.pathname + window.location.search);
    else history.replaceState(null, "", `${window.location.pathname}${window.location.search}#${p}${q}`);
    setPage(p);
    window.scrollTo({ top: 0 });
  };
  return [page, go];
}

/** Polls the engine server so live design appears / disappears with it. */
export function useEngineHealth(intervalMs = 15000): Health | null {
  const [health, setHealth] = useState<Health | null>(null);
  useEffect(() => {
    let alive = true;
    const check = () => getHealth().then((h) => alive && setHealth(h));
    check();
    const id = window.setInterval(check, intervalMs);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [intervalMs]);
  return health;
}

const trajectoryCache = new Map<string, Promise<Trajectory>>();

/** Pre-load a trajectory that arrived with a live design result. */
export function primeTrajectory(t: Trajectory) {
  trajectoryCache.set(t.id, Promise.resolve(t));
}

/** Static file when it was exported, otherwise computed by the engine server. */
export function useTrajectory(row: TransferRow | null, engineOnline: boolean): Loadable<Trajectory> | { status: "unavailable" } | null {
  const [state, setState] = useState<Loadable<Trajectory> | { status: "unavailable" } | null>(null);
  const id = row?.id ?? null;
  const canFetch = !!row && (row.has_trajectory || engineOnline);
  useEffect(() => {
    if (!row) {
      setState(null);
      return;
    }
    let p = trajectoryCache.get(row.id);
    if (!p && !canFetch) {
      setState({ status: "unavailable" });
      return;
    }
    let alive = true;
    setState({ status: "loading" });
    if (!p) {
      p = row.has_trajectory
        ? fetch(`${BASE}data/trajectories/${row.id}.json`).then((r) => {
            if (!r.ok) throw new Error(`trajectory ${row.id} returned ${r.status}`);
            return r.json();
          })
        : fetchTrajectoryLive(row);
      trajectoryCache.set(row.id, p);
      p.catch(() => trajectoryCache.delete(row.id));
    }
    p.then((data) => alive && setState({ status: "ready", data })).catch(
      (e: Error) => alive && setState({ status: "error", message: e.message }),
    );
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, canFetch]);
  return state;
}

/** Width of an element, kept up to date with a ResizeObserver. */
export function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T | null>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    ro.observe(el);
    setWidth(Math.floor(el.getBoundingClientRect().width));
    return () => ro.disconnect();
  }, []);
  return [ref, width];
}

/** Re-render when the colour scheme changes (OS setting or the theme toggle). */
export function useThemeVersion(): number {
  const [v, setV] = useState(0);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const bump = () => setV((x) => x + 1);
    mq.addEventListener("change", bump);
    const mo = new MutationObserver(bump);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => {
      mq.removeEventListener("change", bump);
      mo.disconnect();
    };
  }, []);
  return v;
}
