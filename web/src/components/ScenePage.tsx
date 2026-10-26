import { utcFormat } from "d3-time-format";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fmtNum, fmtShortDay } from "../lib/format";
import {
  agreement, azEl, dirFromAzEl, dirToScene, discFraction, heightAt, latLonOf, loadScene, planeOf, sunEarth,
  surfacePoint, tEndMs, toFixed, upOf, upOfLatLon, type Agreement, type Scene,
} from "../lib/scene3d/data";
import { add, DEG, lookAt, mul, perspective, project, scale, type V3 } from "../lib/scene3d/math";
import { pickTerrain, SceneRenderer, type Line, type View } from "../lib/scene3d/renderer";
import { readParams, writeParams } from "../lib/urlstate";
import type { ForecastFile, RegionPoint } from "../types";
import { coord, goodFill, LAYERS, rankPoints, type Layer } from "./ForecastPage";
import { JourneyView } from "./JourneyView";
import { Legend } from "./Legend";

const BASE = import.meta.env.BASE_URL;
const HOUR = 3600e3;
const DAY = 86400e3;
const timeFmt = utcFormat("%-d %b %Y, %H:%M UTC");
const isoMinute = (ms: number) => new Date(ms).toISOString().slice(0, 16) + "Z";
const utcMs = (s: string) => Date.parse(s.endsWith("Z") || s.includes("+") ? s : `${s}Z`);

type Mode = "orbit" | "eye";
interface Spot {
  key: string; label: string; short: string; X: number; Y: number; lat: number; lon: number;
  region: RegionPoint | null; check: number | null;
}
interface Cam { yaw: number; pitch: number; dist: number; target: V3; eyeYaw: number; eyePitch: number; fov: number }
interface Readout { sunClear: number; earthClear: number; sunEl: number; sunAz: number; earthEl: number; earthAz: number; heightKm: number }
type CheckState = { status: "running" } | { status: "done"; total: Agreement; per: Agreement[]; ms: number } | { status: "error"; message: string };

type Scene3d = "journey" | "region";

export function ScenePage({ forecast }: { forecast: ForecastFile | null }) {
  const [which, setWhich] = useState<Scene3d>(() => (readParams().get("scene") === "region" ? "region" : "journey"));
  const choose = (w: Scene3d) => { writeParams({ scene: w }); setWhich(w); };
  return (
    <div className="validation scene3d">
      <section className="panel val-intro">
        <div className="panel-body scene-switch">
          <div className="segmented" role="group" aria-label="3D scene">
            <button aria-pressed={which === "journey"} onClick={() => choose("journey")}>Journey: Earth to the Moon</button>
            <button aria-pressed={which === "region"} onClick={() => choose("region")}>Landing region</button>
          </div>
          <p className="sub">
            {which === "journey"
              ? "IM-1 and IM-2 as reconstructed, Griffin-1 as forecast: launch, coast, lunar orbit and descent on one clock."
              : "The forecast region's LOLA terrain with shadows computed by the engine's own horizon geometry."}
          </p>
        </div>
      </section>
      {which === "journey" ? <JourneyView /> : <RegionScene forecast={forecast} />}
    </div>
  );
}

function RegionScene({ forecast }: { forecast: ForecastFile | null }) {
  const [scene, setScene] = useState<Scene | null | "loading" | Error>("loading");
  useEffect(() => {
    let alive = true;
    loadScene(BASE).then((s) => alive && setScene(s)).catch((e: Error) => alive && setScene(e));
    return () => { alive = false; };
  }, []);
  if (scene === "loading") return <p className="empty">Loading the 3D scene…</p>;
  if (scene instanceof Error) return <p className="empty">Could not load the 3D scene ({scene.message}).</p>;
  if (!scene) {
    return (
      <p className="empty">
        No 3D scene yet. Build it with <code>python scripts/build_scene3d.py --spice</code> (after the forecast) and reload.
      </p>
    );
  }
  return <SceneView scene={scene} forecast={forecast} />;
}

function buildSpots(s: Scene, f: ForecastFile | null): Spot[] {
  const checks = s.meta.checks.points;
  const checkOf = (lat: number, lon: number) => {
    const k = checks.findIndex((c) => Math.abs(c.lat - lat) < 1e-6 && Math.abs(c.lon - lon) < 1e-6);
    return k >= 0 ? k : null;
  };
  const mk = (key: string, label: string, short: string, lat: number, lon: number, region: RegionPoint | null): Spot => {
    const [X, Y] = planeOf(scale(upOfLatLon(lat, lon), s.R), s.R);
    return { key, label, short, X, Y, lat, lon, region, check: checkOf(lat, lon) };
  };
  const r = f?.region;
  if (!r) return checks.map((c, k) => mk(k === 0 ? "ref" : String(k), c.label, k === 0 ? "Ref" : String(k), c.lat, c.lon, null));
  const out: Spot[] = [];
  const ref = r.references[0];
  if (ref) out.push(mk("ref", ref.label ?? "Reference point", "IM-2", ref.lat, ref.lon, ref));
  rankPoints(r.points, r.ranking.max_slope_deg, r.ranking.min_earth_after_pct).slice(0, 10)
    .forEach((p, k) => out.push(mk(String(k + 1), `Candidate ${k + 1}`, String(k + 1), p.lat, p.lon, p)));
  return out;
}

function nearestRegionPoint(f: ForecastFile | null, s: Scene, X: number, Y: number): RegionPoint | null {
  const r = f?.region;
  if (!r) return null;
  const [Xr, Yr] = planeOf(scale(upOfLatLon(r.grid.center_lat, r.grid.center_lon), s.R), s.R);
  const i = Math.round((X - Xr + r.grid.half_km) / r.grid.step_km), j = Math.round((Y - Yr + r.grid.half_km) / r.grid.step_km);
  if (i < 0 || j < 0 || i >= r.grid.n || j >= r.grid.n) return null;
  return r.points.find((p) => p.i === i && p.j === j) ?? null;
}

function SceneView({ scene: s, forecast: f }: { scene: Scene; forecast: ForecastFile | null }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const labelRefs = useRef(new Map<string, HTMLDivElement | null>());
  const rendRef = useRef<SceneRenderer | null>(null);
  const [glError, setGlError] = useState<string | null>(null);
  const spots = useMemo(() => buildSpots(s, f), [s, f]);
  const params = useMemo(() => readParams(), []);
  const t0 = s.t0Ms, t1 = tEndMs(s);

  const defaultT = useMemo(() => {
    const w = f?.time.windows[0];
    const v = w ? utcMs(w.best_landing_utc) : utcMs(s.meta.region.landing_period_utc[0]) + 10 * DAY;
    return Math.min(Math.max(v, t0), t1);
  }, [f, s, t0, t1]);
  const [t, setT] = useState(() => {
    const p = params.get("t");
    const v = p ? utcMs(p) : NaN;
    return Number.isFinite(v) ? Math.min(Math.max(v, t0), t1) : defaultT;
  });
  const [mode, setMode] = useState<Mode>(() => (params.get("v") === "eye" ? "eye" : "orbit"));
  const [spotKey, setSpotKey] = useState<string>(() => {
    const k = params.get("pt");
    return k && (spots.some((x) => x.key === k) || /^-?\d+(\.\d+)?,-?\d+(\.\d+)?$/.test(k)) ? k : spots[0]?.key ?? "ref";
  });
  const [layer, setLayer] = useState<Layer | "none">(() => {
    const l = params.get("layer");
    return l && l in LAYERS ? (l as Layer) : "none";
  });
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(24);          // hours per second
  const [exposure, setExposure] = useState(1);
  const [check, setCheck] = useState<CheckState>({ status: "running" });
  const [readout, setReadout] = useState<Readout | null>(null);
  const cam = useRef<Cam>((() => {
    const c = (params.get("cam") ?? "").split(",").map(Number);
    const ok = c.length === 3 && c.every(Number.isFinite);
    return { yaw: (ok ? c[0] : 205) * DEG, pitch: clamp(ok ? c[1] : 30, 2, 89) * DEG, dist: clamp(ok ? c[2] : 95, 1.5, 900),
      target: [0, 0, 0], eyeYaw: (ok ? c[0] : 0) * DEG, eyePitch: (ok ? clamp(c[1], -30, 85) : 1) * DEG, fov: (ok ? clamp(c[2], 1, 100) : 40) * DEG };
  })());
  const [camVersion, setCamVersion] = useState(0);
  const quality = useRef<"fast" | "full">("fast");
  const fullTimer = useRef<number | null>(null);
  const frame = useRef<number | null>(null);

  // the selected spot: a named one, or "lat,lon" picked on the terrain
  const spot: Spot | null = useMemo(() => {
    const named = spots.find((x) => x.key === spotKey);
    if (named) return named;
    const m = /^(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)$/.exec(spotKey);
    if (!m) return spots[0] ?? null;
    const lat = Number(m[1]), lon = Number(m[2]);
    const same = spots.find((x) => Math.abs(x.lat - lat) < 2e-5 && Math.abs(x.lon - lon) < 2e-5);
    if (same) return same;
    const [X, Y] = planeOf(scale(upOfLatLon(lat, lon), s.R), s.R);
    if (heightAt(s, X, Y) === null) return spots[0] ?? null;
    return { key: spotKey, label: "Picked point", short: "•", X, Y, lat, lon, region: nearestRegionPoint(f, s, X, Y), check: null };
  }, [spotKey, spots, s, f]);
  const se = useMemo(() => sunEarth(s, t), [s, t]);

  // --- renderer --------------------------------------------------------------------
  useEffect(() => {
    const c = canvasRef.current!;
    let r: SceneRenderer;
    try {
      r = new SceneRenderer(c, s);
    } catch (e) {
      setGlError((e as Error).message);
      return;
    }
    rendRef.current = r;
    const centre = surfacePoint(s, r.Xc, r.Yc) ?? [0, 0, 0];
    cam.current.target = (params.get("pt") && spot ? surfacePoint(s, spot.X, spot.Y) : null) ?? centre;
    if (mode === "eye" && spot && !params.get("cam")) cam.current.eyeYaw = azEl(se.sun, upOf(spot.X, spot.Y, s.R)).az * DEG;
    const id = window.setTimeout(() => {           // the GPU vs engine check, once
      try {
        const tic = performance.now();
        const gpu = r.runCheck();
        const nT = s.meta.checks.time_index[2];
        const eng = gpu.map((_, j) => Array.from(s.engineClear.slice(j * nT, (j + 1) * nT), (v) => v / 100));
        const semi = s.meta.solar_semi_diameter_deg;
        const per = gpu.map((g, j) => agreement(g, eng[j], semi));
        const total = agreement(gpu.flatMap((g) => Array.from(g)), eng.flat(), semi);
        setCheck({ status: "done", total, per, ms: performance.now() - tic });
      } catch (e) {
        setCheck({ status: "error", message: (e as Error).message });
      }
    }, 60);
    return () => {
      window.clearTimeout(id);
      rendRef.current = null;
      r.dispose();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s]);

  const draw = useCallback(() => {
    const r = rendRef.current, c = canvasRef.current;
    if (!r || !c || !spot) return;
    const w = c.width, h = c.height, aspect = w / h, k = cam.current;
    let eye: V3, viewUp: V3, target: V3, fov: number;
    const spotUp = upOf(spot.X, spot.Y, s.R);
    if (mode === "orbit") {
      eye = add(k.target, scale([Math.cos(k.pitch) * Math.sin(k.yaw), Math.cos(k.pitch) * Math.cos(k.yaw), Math.sin(k.pitch)], k.dist));
      target = k.target;
      viewUp = [0, 0, 1];
      fov = 45 * DEG;
    } else {
      eye = surfacePoint(s, spot.X, spot.Y, s.meta.observer_m / 1000) ?? k.target;
      const look = dirToScene(s, dirFromAzEl(spotUp, k.eyeYaw / DEG, k.eyePitch / DEG));
      target = add(eye, look);
      viewUp = dirToScene(s, spotUp);
      fov = k.fov;
    }
    const far = 6000, near = mode === "eye" ? 0.0005 : Math.max(0.002, k.dist * 0.002);
    const view = lookAt(eye, target, viewUp), proj = perspective(fov, aspect, near, far);
    const viewProj = mul(proj, view);
    const tanY = Math.tan(fov / 2);
    const v: View = {
      viewProj, eye, far, tanX: tanY * aspect, tanY,
      right: [view[0], view[4], view[8]], up: [view[1], view[5], view[9]], fwd: [-view[2], -view[6], -view[10]],
    };
    r.draw(v);
    // labels
    const place = (key: string, p: V3 | null, hide = false) => {
      const el = labelRefs.current.get(key);
      if (!el) return;
      const q = p && !hide ? project(viewProj, p) : null;
      if (!q || Math.abs(q.x) > 1.05 || Math.abs(q.y) > 1.05) { el.style.display = "none"; return; }
      el.style.display = "";
      el.style.transform = `translate(${((q.x + 1) / 2) * (w / devicePixelRatioCap())}px, ${((1 - q.y) / 2) * (h / devicePixelRatioCap())}px)`;
    };
    for (const x of spots) place(`spot-${x.key}`, surfacePoint(s, x.X, x.Y, 0.02), mode === "eye" && x.key === spot.key);
    place("spot-pick", spots.some((x) => x.key === spot.key) ? null : surfacePoint(s, spot.X, spot.Y, 0.02), mode === "eye");
    const sky = (d: V3) => add(eye, scale(dirToScene(s, d), 1000));
    place("sky-sun", mode === "eye" ? sky(r.sunMf) : null);
    place("sky-earth", mode === "eye" ? sky(r.earthMf) : null);
    for (const [name, az] of [["N", 0], ["E", 90], ["S", 180], ["W", 270]] as const)
      place(`compass-${name}`, mode === "eye" ? sky(dirFromAzEl(spotUp, az, 0)) : null);
    // elevation scale along the left edge (lander's view)
    const fine = k.fov < 25 * DEG;
    for (const el of TICKS) {
      const lab = labelRefs.current.get(`tick-${el}`);
      if (!lab) continue;
      const q = mode === "eye" && (fine || el % 2 === 0) ? project(viewProj, sky(dirFromAzEl(spotUp, k.eyeYaw / DEG, el))) : null;
      if (!q || q.y > 0.86 || q.y < -0.9) { lab.style.display = "none"; continue; }
      lab.style.display = "";
      lab.style.transform = `translate(0px, ${((1 - q.y) / 2) * (h / devicePixelRatioCap())}px)`;
    }
  }, [mode, spot, spots, s]);

  const requestDraw = useCallback(() => {
    if (frame.current !== null) return;
    frame.current = requestAnimationFrame(() => {
      frame.current = null;
      draw();
    });
  }, [draw]);

  // canvas size
  useEffect(() => {
    const c = canvasRef.current!, wrap = wrapRef.current!;
    const ro = new ResizeObserver(() => {
      const d = devicePixelRatioCap(), w = wrap.clientWidth, h = wrap.clientHeight;
      c.width = Math.max(1, Math.round(w * d));
      c.height = Math.max(1, Math.round(h * d));
      requestDraw();
    });
    ro.observe(wrap);
    return () => ro.disconnect();
  }, [requestDraw]);

  // Sun, Earth and the terrain lighting for the current time
  useEffect(() => {
    const r = rendRef.current;
    if (!r) return;
    r.sunMf = se.sun; r.earthMf = se.earth; r.earthKm = se.earthKm;
    r.updateLight("fast");
    quality.current = "fast";
    if (fullTimer.current) window.clearTimeout(fullTimer.current);
    if (!playing) {
      fullTimer.current = window.setTimeout(() => {
        rendRef.current?.updateLight("full");
        quality.current = "full";
        requestDraw();
      }, 220);
    }
    requestDraw();
  }, [se, playing, requestDraw, glError]);

  // readout at the selected spot (exact march, two directions)
  useEffect(() => {
    const r = rendRef.current;
    if (!r || !spot) return;
    const [sunClear, earthClear] = r.probe(spot.X, spot.Y, se.sun, se.earth);
    const up = upOf(spot.X, spot.Y, s.R);
    const a = azEl(se.sun, up), b = azEl(se.earth, up);
    setReadout({ sunClear, earthClear, sunEl: a.el, sunAz: a.az, earthEl: b.el, earthAz: b.az, heightKm: heightAt(s, spot.X, spot.Y) ?? 0 });
  }, [se, spot, s, glError]);

  // overlay layer from the forecast's region scan
  useEffect(() => {
    const r = rendRef.current, reg = f?.region;
    if (!r) return;
    if (!reg || layer === "none") { r.setOverlay(null); requestDraw(); return; }
    const L = LAYERS[layer], n = reg.grid.n;
    const vals = reg.points.map((p) => L.get(p)).filter((v): v is number => v !== null);
    const domain: [number, number] = [Math.min(...vals), Math.max(...vals)];
    const { fill } = goodFill(domain, L.better, true);
    const passing = new Set(rankPoints(reg.points, reg.ranking.max_slope_deg, reg.ranking.min_earth_after_pct).map((p) => `${p.i},${p.j}`));
    const rgba = new Uint8Array(n * n * 4);
    for (const p of reg.points) {
      const v = L.get(p);
      if (v === null) continue;
      const m = /rgb\((\d+),\s*(\d+),\s*(\d+)\)/.exec(fill(v));
      if (!m) continue;
      rgba.set([Number(m[1]), Number(m[2]), Number(m[3]), passing.has(`${p.i},${p.j}`) ? 255 : 110], (p.j * n + p.i) * 4);
    }
    const [Xr, Yr] = planeOf(scale(upOfLatLon(reg.grid.center_lat, reg.grid.center_lon), s.R), s.R);
    r.setOverlay(rgba, n, Xr - r.Xc - reg.grid.half_km, Yr - r.Yc - reg.grid.half_km, reg.grid.step_km);
    requestDraw();
  }, [layer, f, s, requestDraw, glError]);

  // paths on the sky and the engine's horizon, in the lander's view
  useEffect(() => {
    const r = rendRef.current;
    if (!r || !spot) return;
    const lines: Line[] = [];
    if (mode === "eye") {
      const eye = surfacePoint(s, spot.X, spot.Y, s.meta.observer_m / 1000)!;
      const sky = (d: V3) => add(eye, scale(dirToScene(s, d), 1000));
      const sunPath: V3[] = [], earthPath: V3[] = [];
      for (let x = t - 15 * DAY; x <= t + 15 * DAY; x += 2 * HOUR) {
        const q = sunEarth(s, Math.min(Math.max(x, t0), t1));
        sunPath.push(sky(q.sun));
        earthPath.push(sky(q.earth));
      }
      lines.push({ pts: sunPath, color: [1, 0.82, 0.4, 0.55] }, { pts: earthPath, color: [0.45, 0.65, 1, 0.55] });
      const up0 = upOf(spot.X, spot.Y, s.R), flat: V3[] = [];
      for (let az = 0; az <= 360; az += 1) flat.push(sky(dirFromAzEl(up0, az, 0)));
      lines.push({ pts: flat, color: [1, 1, 1, 0.22] });            // geometric horizon (0 deg)
      if (spot.check !== null) {
        const nAz = s.masks.length / s.meta.checks.points.length, up = upOf(spot.X, spot.Y, s.R), pts: V3[] = [];
        for (let i = 0; i <= nAz; i++) {
          const el = s.masks[spot.check * nAz + (i % nAz)] / 100;
          pts.push(sky(dirFromAzEl(up, i * s.meta.checks.mask_az_step_deg, el)));
        }
        lines.push({ pts, color: [0.94, 0.42, 0.71, 0.95], noDepth: true });
      }
    }
    r.setLines(lines);
    requestDraw();
  }, [mode, spot, s, t, t0, t1, requestDraw, glError]);

  useEffect(() => {
    if (rendRef.current) rendRef.current.gain = 6 * exposure;
    requestDraw();
  }, [exposure, requestDraw, glError]);

  useEffect(() => { requestDraw(); }, [draw, requestDraw]);

  // play
  useEffect(() => {
    if (!playing) return;
    let last = performance.now(), acc = 0, id = 0;
    const tick = (now: number) => {
      acc += ((now - last) / 1000) * speed * HOUR;
      last = now;
      if (acc >= HOUR) {
        const step = Math.floor(acc / HOUR) * HOUR;
        acc -= step;
        setT((x) => {
          const y = x + step;
          if (y >= t1) { setPlaying(false); return t1; }
          return y;
        });
      }
      id = requestAnimationFrame(tick);
    };
    id = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(id);
  }, [playing, speed, t1]);

  // shareable state
  useEffect(() => {
    if (playing) return;
    const id = window.setTimeout(() => writeParams({
      t: isoMinute(t), v: mode === "eye" ? "eye" : null, pt: spotKey === spots[0]?.key ? null : spotKey,
      layer: layer === "none" ? null : layer,
      cam: camParam(cam.current, mode),
    }), 300);
    return () => window.clearTimeout(id);
  }, [t, mode, spotKey, layer, playing, spots, camVersion]);

  // pointer: orbit / look / pick
  useEffect(() => {
    const c = canvasRef.current!;
    const pts = new Map<number, { x: number; y: number }>();
    let moved = 0, startDist = 0, startVal = 0, button = 0, shift = false;
    const down = (e: PointerEvent) => {
      c.setPointerCapture(e.pointerId);
      pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
      moved = 0; button = e.button; shift = e.shiftKey;
      if (pts.size === 2) {
        const [a, b] = [...pts.values()];
        startDist = Math.hypot(a.x - b.x, a.y - b.y);
        startVal = mode === "orbit" ? cam.current.dist : cam.current.fov;
      }
    };
    const move = (e: PointerEvent) => {
      const p = pts.get(e.pointerId);
      if (!p) return;
      const dx = e.clientX - p.x, dy = e.clientY - p.y;
      p.x = e.clientX; p.y = e.clientY;
      moved += Math.abs(dx) + Math.abs(dy);
      const k = cam.current;
      if (pts.size === 2) {
        const [a, b] = [...pts.values()];
        const ratio = startDist / Math.max(1, Math.hypot(a.x - b.x, a.y - b.y));
        if (mode === "orbit") k.dist = clamp(startVal * ratio, 1.5, 900);
        else k.fov = clamp(startVal * ratio, 1 * DEG, 100 * DEG);
      } else if (mode === "orbit") {
        if (button === 2 || shift) {
          // move the target over the ground: right / forward of the camera, kept on the terrain
          const sx = k.dist * 0.0016, cy = Math.cos(k.yaw), sy = Math.sin(k.yaw);
          const nt: V3 = [k.target[0] + (cy * dx - sy * dy) * sx, k.target[1] + (-sy * dx - cy * dy) * sx, k.target[2]];
          const [X, Y] = planeOf(toFixed(s, nt), s.R);
          const g = surfacePoint(s, X, Y);
          if (g) k.target = g;
        } else {
          k.yaw -= dx * 0.005;
          k.pitch = clamp(k.pitch + dy * 0.005, 2 * DEG, 89 * DEG);
        }
      } else {
        const f = k.fov / (c.clientHeight || 1);
        k.eyeYaw -= dx * f;
        k.eyePitch = clamp(k.eyePitch + dy * f, -30 * DEG, 85 * DEG);
      }
      requestDraw();
    };
    const up = (e: PointerEvent) => {
      const wasSingle = pts.size === 1;
      pts.delete(e.pointerId);
      if (moved >= 5) setCamVersion((v) => v + 1);
      if (wasSingle && moved < 5 && mode === "orbit" && button === 0) pick(e);
    };
    const pick = (e: PointerEvent) => {
      const r = rendRef.current;
      if (!r) return;
      const rect = c.getBoundingClientRect();
      const nx = ((e.clientX - rect.left) / rect.width) * 2 - 1, ny = 1 - ((e.clientY - rect.top) / rect.height) * 2;
      const k = cam.current, aspect = rect.width / rect.height, tanY = Math.tan(22.5 * DEG);
      const eye = add(k.target, scale([Math.cos(k.pitch) * Math.sin(k.yaw), Math.cos(k.pitch) * Math.cos(k.yaw), Math.sin(k.pitch)], k.dist));
      const view = lookAt(eye, k.target, [0, 0, 1]);
      const right: V3 = [view[0], view[4], view[8]], upv: V3 = [view[1], view[5], view[9]], fwd: V3 = [-view[2], -view[6], -view[10]];
      const d = add(fwd, add(scale(right, nx * tanY * aspect), scale(upv, ny * tanY)));
      const hit = pickTerrain(s, eye, scale(d, 1 / Math.hypot(...d)));
      if (!hit) return;
      const [lat, lon] = latLonOf(toFixed(s, hit));
      setSpotKey(`${lat.toFixed(5)},${lon.toFixed(5)}`);
    };
    const wheel = (e: WheelEvent) => {
      e.preventDefault();
      const k = cam.current, z = Math.exp(e.deltaY * 0.0012);
      if (mode === "orbit") k.dist = clamp(k.dist * z, 1.5, 900);
      else k.fov = clamp(k.fov * z, 1 * DEG, 100 * DEG);
      requestDraw();
      setCamVersion((v) => v + 1);
    };
    const menu = (e: Event) => e.preventDefault();
    c.addEventListener("pointerdown", down);
    c.addEventListener("pointermove", move);
    c.addEventListener("pointerup", up);
    c.addEventListener("pointercancel", up);
    c.addEventListener("wheel", wheel, { passive: false });
    c.addEventListener("contextmenu", menu);
    return () => {
      c.removeEventListener("pointerdown", down);
      c.removeEventListener("pointermove", move);
      c.removeEventListener("pointerup", up);
      c.removeEventListener("pointercancel", up);
      c.removeEventListener("wheel", wheel);
      c.removeEventListener("contextmenu", menu);
    };
  }, [mode, s, requestDraw]);

  function chooseSpot(key: string) {
    setSpotKey(key);
    const x = spots.find((q) => q.key === key);
    if (x && mode === "orbit") {
      const g = surfacePoint(s, x.X, x.Y);
      if (g) { cam.current.target = g; cam.current.dist = Math.min(cam.current.dist, 45); }
    }
  }
  function chooseMode(m: Mode) {
    if (m === "eye" && spot) {
      const up = upOf(spot.X, spot.Y, s.R);
      cam.current.eyeYaw = azEl(se.sun, up).az * DEG;
      cam.current.eyePitch = 1 * DEG;
      cam.current.fov = 40 * DEG;
    }
    if (m === "orbit" && spot) {
      const g = surfacePoint(s, spot.X, spot.Y);
      if (g) cam.current.target = g;
    }
    setMode(m);
  }
  const step = (h: number) => { setPlaying(false); setT((x) => Math.min(Math.max(x + h * HOUR, t0), t1)); };

  const reg = f?.region ?? null;
  const L = layer !== "none" ? LAYERS[layer] : null;
  const legend = useMemo(() => {
    if (!L || !reg) return null;
    const vals = reg.points.map((p) => L.get(p)).filter((v): v is number => v !== null);
    return goodFill([Math.min(...vals), Math.max(...vals)], L.better, true).legend;
  }, [L, reg]);
  const jumps = (f?.time.windows ?? []).map((w, k) => ({ label: `Window ${k + 1}: ${fmtShortDay(new Date(utcMs(w.best_landing_utc)))}`, t: utcMs(w.best_landing_utc) }));
  const bestSlot = spot?.region?.best_slot ? utcMs(spot.region.best_slot) : null;
  const synthetic = !s.meta.dem.startsWith("LDEM_75S");
  const demo = synthetic || !s.meta.ephemeris.includes("spice");
  const semi = s.meta.solar_semi_diameter_deg;

  return (
    <>
      <section className="panel val-intro">
        <div className="panel-body">
          <p className="val-lede">
            <strong>The forecast region in 3D.</strong> LOLA terrain on the curved Moon, lit by the Sun at any hour of{" "}
            {s.meta.mission.split(" (")[0]}'s landing period. The shadows are computed, not painted: from every map cell the GPU
            walks towards the Sun and finds the terrain horizon with the engine's own geometry, then takes the share of the
            solar disc above it.
          </p>
          <p className="sub num">
            {s.meta.dem} · {s.meta.ephemeris.includes("spice") ? "JPL DE440" : "analytic ephemeris"} · engine v{s.meta.engine_version} · no vertical exaggeration
            {demo && <span className="warn"> · {synthetic ? "synthetic terrain, " : ""}demo data: build with the LOLA map and --spice for real results</span>}
          </p>
        </div>
      </section>

      <section className="panel" aria-label="3D view">
        <div className="scene-stage" ref={wrapRef}>
          <canvas ref={canvasRef} className="scene-canvas" tabIndex={0} aria-label={`3D view of the region, ${mode === "orbit" ? "overview" : "lander's view"} at ${timeFmt(new Date(t))}`}
            onKeyDown={(e) => {
              if (e.key === " ") { e.preventDefault(); setPlaying((p) => !p); }
              if (e.key === "ArrowRight") { e.preventDefault(); step(e.shiftKey ? 24 : 1); }
              if (e.key === "ArrowLeft") { e.preventDefault(); step(e.shiftKey ? -24 : -1); }
            }} />
          {spots.map((x) => (
            <div key={x.key} ref={(el) => { labelRefs.current.set(`spot-${x.key}`, el); }}
              className={`scene-pin${x.key === spot?.key ? " on" : ""}${x.key === "ref" ? " ref" : ""}`}>
              <span>{x.short}</span>
            </div>
          ))}
          <div ref={(el) => { labelRefs.current.set("spot-pick", el); }} className="scene-pin on pick"><span>•</span></div>
          <div ref={(el) => { labelRefs.current.set("sky-sun", el); }} className="scene-sky">Sun</div>
          <div ref={(el) => { labelRefs.current.set("sky-earth", el); }} className="scene-sky earth">Earth</div>
          {TICKS.map((el) => (
            <div key={el} ref={(e) => { labelRefs.current.set(`tick-${el}`, e); }} className="scene-tick num">{el > 0 ? "+" : ""}{el}°</div>
          ))}
          {["N", "E", "S", "W"].map((n) => (
            <div key={n} ref={(el) => { labelRefs.current.set(`compass-${n}`, el); }} className="scene-compass">{n}</div>
          ))}
          <div className="scene-hud">
            <strong className="num">{timeFmt(new Date(t))}</strong>
            {readout && spot && (
              <span className="num">
                {spot.label}: Sun {fmtNum(readout.sunEl, 1)}° up, {readout.sunClear >= 0 ? `${fmtNum(readout.sunClear, 2)}° above` : `${fmtNum(-readout.sunClear, 2)}° below`} the terrain
                ({fmtNum(100 * discFraction(readout.sunClear, semi), 0)}% of the disc)
              </span>
            )}
          </div>
          {glError && <p className="scene-error">The 3D view needs WebGL2: {glError}</p>}
          <p className="scene-help">
            {mode === "orbit" ? "Drag to turn, scroll or pinch to zoom, right-drag or Shift-drag to pan, click the terrain to pick a point."
              : `Drag to look around, scroll or pinch to zoom. Yellow / blue: the Sun's and Earth's paths over ±15 days; faint white: the flat 0° horizon${spot?.check !== null ? "; pink: the engine's horizon mask for this point" : ""}.`}
          </p>
        </div>

        <div className="panel-body scene-controls">
          <div className="scene-time">
            <button className="play" onClick={() => setPlaying((p) => !p)} aria-pressed={playing}>{playing ? "Pause" : "Play"}</button>
            <button onClick={() => step(-24)} aria-label="One day back">−1 d</button>
            <button onClick={() => step(-1)} aria-label="One hour back">−1 h</button>
            <input type="range" min={t0} max={t1} step={HOUR} value={t} aria-label="Time"
              onChange={(e) => { setPlaying(false); setT(Number(e.target.value)); }} />
            <button onClick={() => step(1)} aria-label="One hour on">+1 h</button>
            <button onClick={() => step(24)} aria-label="One day on">+1 d</button>
            <label className="control">Speed
              <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
                <option value={6}>6 h / s</option>
                <option value={24}>1 day / s</option>
                <option value={72}>3 days / s</option>
              </select>
            </label>
          </div>
          <div className="controls">
            <div className="control">
              <span id="scene-view">View</span>
              <div className="segmented" role="group" aria-labelledby="scene-view">
                <button aria-pressed={mode === "orbit"} onClick={() => chooseMode("orbit")}>Overview</button>
                <button aria-pressed={mode === "eye"} onClick={() => chooseMode("eye")}>Lander's eye (2 m)</button>
              </div>
            </div>
            <label className="control">Point
              <select value={spots.some((x) => x.key === spotKey) ? spotKey : "pick"} onChange={(e) => chooseSpot(e.target.value)}>
                {spots.map((x) => <option key={x.key} value={x.key}>{x.key === "ref" ? x.label : `${x.label}${x.region ? ` (${coord(x.lat, x.lon)})` : ""}`}</option>)}
                {!spots.some((x) => x.key === spotKey) && <option value="pick">Picked: {spot ? coord(spot.lat, spot.lon) : ""}</option>}
              </select>
            </label>
            <label className="control">Exposure
              <select value={exposure} onChange={(e) => setExposure(Number(e.target.value))}>
                <option value={0.5}>Darker</option>
                <option value={1}>Normal</option>
                <option value={2.5}>Brighter</option>
                <option value={6}>Much brighter</option>
              </select>
            </label>
            {reg && (
              <label className="control">Colour by
                <select value={layer} onChange={(e) => setLayer(e.target.value as Layer | "none")}>
                  <option value="none">Nothing (terrain only)</option>
                  {(Object.keys(LAYERS) as Layer[]).filter((k) => k !== "height").map((k) => <option key={k} value={k}>{LAYERS[k].label}</option>)}
                </select>
              </label>
            )}
          </div>
          {(jumps.length > 0 || bestSlot) && (
            <div className="scene-jumps">
              <span>Go to</span>
              {jumps.map((j) => <button key={j.label} onClick={() => { setPlaying(false); setT(Math.min(Math.max(j.t, t0), t1)); }}>{j.label}</button>)}
              {bestSlot && <button onClick={() => { setPlaying(false); setT(Math.min(Math.max(bestSlot, t0), t1)); }}>Best landing slot here: {fmtShortDay(new Date(bestSlot))}</button>}
            </div>
          )}
          {L && legend && <Legend domain={legend} label={`${L.label} (${L.unit})`} digits={L.digits} dark={true}
            note="faded: outside the ranking limits; no colour: no landing slot" />}
        </div>
      </section>

      <div className="val-grid">
        <section className="panel" aria-labelledby="scene-point">
          <div className="panel-head"><h2 id="scene-point">{spot?.label ?? "Point"}</h2>{spot && <span className="hint num">{coord(spot.lat, spot.lon)}</span>}</div>
          <div className="panel-body">
            {readout && (
              <dl className="figures two">
                <div><dt>Sun above the terrain</dt><dd>{fmtNum(readout.sunClear, 2)}<small>° · {fmtNum(100 * discFraction(readout.sunClear, semi), 0)}% of the disc</small></dd></div>
                <div><dt>Sun</dt><dd>{fmtNum(readout.sunEl, 2)}<small>° up, azimuth {fmtNum(readout.sunAz, 0)}°</small></dd></div>
                <div><dt>Earth above the terrain</dt><dd>{fmtNum(readout.earthClear, 2)}<small>°</small></dd></div>
                <div><dt>Earth</dt><dd>{fmtNum(readout.earthEl, 2)}<small>° up, azimuth {fmtNum(readout.earthAz, 0)}°</small></dd></div>
                <div><dt>Height</dt><dd>{fmtNum(readout.heightKm * 1000, 0)}<small>m above 1737.4 km</small></dd></div>
                {spot?.region && <div><dt>Slope (240 m)</dt><dd>{fmtNum(spot.region.slope_deg, 1)}<small>°</small></dd></div>}
                {spot?.region && <div><dt>Best landing slot</dt><dd className="dd-text">{spot.region.best_slot ? timeFmt(new Date(utcMs(spot.region.best_slot))) : "none in the period"}</dd></div>}
                {spot?.region && <div><dt>Sunlight after it</dt><dd>{spot.region.best_daylight_days !== null ? fmtNum(spot.region.best_daylight_days, 1) : "–"}<small>days</small></dd></div>}
              </dl>
            )}
            <p className="table-note">
              Sun and Earth heights here come from the same GPU march as the shadows, at this exact point.
              {spot?.region && spot.key.includes(",") ? " Forecast figures are those of the nearest scan point (2 km grid)." : ""}
            </p>
          </div>
        </section>

        <section className="panel" aria-labelledby="scene-check">
          <div className="panel-head"><h2 id="scene-check">Do the 3D shadows match the engine?</h2></div>
          <div className="panel-body">
            <CheckBlock state={check} scene={s} />
          </div>
        </section>
      </div>

      <section className="panel">
        <div className="panel-body">
          <h3 className="val-h3 first">What is real here and what is drawn</h3>
          <ul className="plain-list">
            <li><strong>Real:</strong> terrain heights (LOLA {s.meta.grids.map((g) => `${fmtNum(g.step_km * 1000, 0)} m`).join(", ")}{" "}
              out to {fmtNum(s.meta.grids[0].nx * s.meta.grids[0].step_km / 2, 0)}, 100 and 250 km), the Moon's curvature, the Sun and Earth directions
              ({s.meta.ephemeris.includes("spice") ? "DE440" : "analytic ephemeris"}), the shadows and the share of the solar disc, the size of the Sun and
              Earth discs and the Earth's phase.</li>
            <li><strong>Drawn for clarity:</strong> surface brightness (a simple matte model, not the regolith's real reflectance), a faint lift in the
              shadows so the relief stays visible (real shadows here are almost black), and the glow around the Sun.</li>
            <li><strong>Not shown:</strong> anything smaller than the {fmtNum(s.meta.grids[0].step_km * 1000, 0)} m map pixels (rocks, small craters);
              beyond 250 km the Moon is a smooth sphere.</li>
          </ul>
        </div>
      </section>
    </>
  );
}

function CheckBlock({ state, scene: s }: { state: CheckState; scene: Scene }) {
  const py = s.meta.checks.python_vs_engine;
  const nT = s.meta.checks.time_index[2], strideH = s.meta.checks.time_index[1];
  if (state.status === "running") return <p className="table-note">Running the check on this GPU…</p>;
  if (state.status === "error") return <p className="table-note warn">The GPU check failed: {state.message}</p>;
  const a = state.total;
  return (
    <>
      <p className="val-story">
        At {s.meta.checks.points.length} points (the reference point and the top candidates), every {strideH} hours of the landing period
        ({fmtNum(a.n, 0)} point-hours), this browser's GPU shadows are compared with the engine's sun clearance from full-resolution horizon masks.
      </p>
      <dl className="figures two">
        <div><dt>Sunlit vs shadowed, same answer</dt><dd>{a.lit_agree_pct ?? "–"}<small>% of {fmtNum(a.lit_compared, 0)}</small></dd></div>
        <div><dt>Share of the solar disc, mean difference</dt><dd>{a.mean_abs_disc_pct ?? "–"}<small>points of %</small></dd></div>
        <div><dt>Sun height difference, median</dt><dd>{a.median_abs_deg ?? "–"}<small>°</small></dd></div>
        <div><dt>95th percentile</dt><dd>{a.p95_abs_deg ?? "–"}<small>°</small></dd></div>
      </dl>
      <p className="table-note">
        Differences are measured where the Sun is within {a.clamp_deg}° of the terrain ({fmtNum(a.near_horizon, 0)} cases), where it matters;
        sunlit / shadowed is compared where the engine puts the Sun more than {a.edge_deg}° from the terrain. The same algorithm in numpy gave{" "}
        {py.lit_agree_pct}% and a median of {py.median_abs_deg}° when the scene was built; the GPU took {fmtNum(state.ms, 0)} ms here.
        The remaining difference comes from the coarser grids beyond the region (360 m, 1.2 km), which flatten distant peaks a little.
      </p>
      <details className="sources">
        <summary>Per point</summary>
        <table>
          <thead><tr><th className="left">Point</th><th>Agree</th><th>Median</th><th>p95</th></tr></thead>
          <tbody>
            {s.meta.checks.points.map((p, j) => (
              <tr key={p.label}><td className="left">{p.label}</td><td>{state.per[j]?.lit_agree_pct ?? "–"}%</td>
                <td>{state.per[j]?.median_abs_deg ?? "–"}°</td><td>{state.per[j]?.p95_abs_deg ?? "–"}°</td></tr>
            ))}
          </tbody>
        </table>
        <p className="table-note">{nT} check times per point.</p>
      </details>
    </>
  );
}

const TICKS = Array.from({ length: 19 }, (_, i) => i - 4);      // -4 .. +14 deg
const clamp = (v: number, a: number, b: number) => Math.min(Math.max(v, a), b);
/** Camera in the link: orbit yaw, pitch (deg), distance (km); lander's view yaw, pitch, field of view (deg). */
function camParam(k: Cam, mode: Mode): string {
  const r = (v: number, d = 1) => Number(v.toFixed(d));
  return mode === "orbit" ? `${r(k.yaw / DEG)},${r(k.pitch / DEG)},${r(k.dist)}` : `${r(k.eyeYaw / DEG)},${r(k.eyePitch / DEG, 2)},${r(k.fov / DEG)}`;
}
function devicePixelRatioCap() { return Math.min(window.devicePixelRatio || 1, 1.75); }
