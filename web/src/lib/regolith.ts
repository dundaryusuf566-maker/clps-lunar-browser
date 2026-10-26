/**
 * Regolith temperatures in the browser: the engine's one-dimensional heat
 * conduction model (engine/surface/thermal.py, Hayne et al. 2017) line for line,
 * for one soil column. web/tests/regolith.check.mjs runs both on the same forcing
 * and requires the same temperatures.
 */

export const SIGMA = 5.670374419e-8;
export const LUNATION_S = 29.530589 * 86400;
export const HAYNE2017 = "https://arxiv.org/abs/1711.00977";

export const REGOLITH = {
  rho_s: 1100, rho_d: 1800, H: 0.06, k_s: 7.4e-4, k_d: 3.4e-3, chi: 2.7, emissivity: 0.95,
  A0: 0.12, a: 0.06, b: 0.25, Q_geo: 0.018, S: 1361,
  cp: [-3.6125, 2.7431, 2.3616e-3, -1.234e-5, 8.9093e-9],
} as const;
type R = typeof REGOLITH;

export function heatCapacity(T: number, r: R = REGOLITH): number {
  const t = Math.max(T, 2), c = r.cp;
  return c[0] + t * (c[1] + t * (c[2] + t * (c[3] + t * c[4])));
}

export function albedo(incRad: number, r: R = REGOLITH): number {
  const i = Math.abs(incRad);
  return r.A0 + r.a * (i / (Math.PI / 4)) ** 3 + r.b * (i / (Math.PI / 2)) ** 8;
}

/** Absorbed sunlight, W m^-2: (1 - A(i)) S / d^2 cos(i) f, zero when the Sun is behind the surface. */
export function absorbedFlux(cosInc: number, discFraction: number, sunAu: number, r: R = REGOLITH): number {
  const c = Math.max(-1, Math.min(1, cosInc));
  if (c <= 0) return 0;
  return (1 - albedo(Math.acos(c), r)) * (r.S / (sunAu * sunAu)) * c * discFraction;
}

/** engine/surface/terrain.py: mean solar semi-diameter at 1 AU (deg). */
export const SOLAR_SEMI_DIAMETER_DEG = 0.2666;

/** engine/surface/scene3d.py disc_fraction: share of the solar disc above the terrain, Sun centre `clearDeg` above it. */
export function discFraction(clearDeg: number): number {
  const x = Math.max(-1, Math.min(1, clearDeg / SOLAR_SEMI_DIAMETER_DEG));
  const th = Math.acos(-x);
  return (th - Math.sin(th) * Math.cos(th)) / Math.PI;
}

export interface Grid { z: Float64Array; rho: Float64Array; kc: Float64Array; h: Float64Array }

export function buildGrid(r: R = REGOLITH, firstFrac = 0.1, growth = 1.2, depthM = 0.8, periodS = LUNATION_S): Grid {
  const skin = Math.sqrt((r.k_s / (r.rho_s * heatCapacity(250, r))) * periodS / Math.PI);
  let dz = firstFrac * skin;
  const z = [0];
  while (z[z.length - 1] < depthM) { z.push(z[z.length - 1] + dz); dz *= growth; }
  const n = z.length;
  const g: Grid = { z: Float64Array.from(z), rho: new Float64Array(n), kc: new Float64Array(n), h: new Float64Array(n - 1) };
  for (let i = 0; i < n; i++) {
    g.rho[i] = r.rho_d - (r.rho_d - r.rho_s) * Math.exp(-z[i] / r.H);
    g.kc[i] = r.k_d - (r.k_d - r.k_s) * Math.exp(-z[i] / r.H);
    if (i) g.h[i - 1] = z[i] - z[i - 1];
  }
  return g;
}

export class Column {
  readonly g: Grid;
  readonly T: Float64Array;
  private readonly r: R;
  private readonly k: Float64Array;
  private readonly ki: Float64Array;
  private readonly flux: Float64Array;

  constructor(r: R = REGOLITH, grid?: Grid, T0 = 250) {
    this.r = r;
    this.g = grid ?? buildGrid(r);
    const n = this.g.z.length;
    this.T = new Float64Array(n).fill(T0);
    this.k = new Float64Array(n);
    this.ki = new Float64Array(n - 1);
    this.flux = new Float64Array(n - 1);
  }

  private conductivity(): void {
    const { g, T, r, k } = this;
    for (let i = 0; i < T.length; i++) k[i] = g.kc[i] * (1 + r.chi * (T[i] / 350) ** 3);
  }

  /** Largest explicit step with Fourier number <= 0.45 for the current temperatures. */
  stableDt(): number {
    this.conductivity();
    const { g, T, k, r } = this;
    let m = Infinity;
    for (let i = 1; i < T.length - 1; i++) {
      const hm = Math.min(g.h[i - 1], g.h[i]);
      m = Math.min(m, (g.rho[i] * heatCapacity(T[i], r) * hm * hm) / k[i]);
    }
    return 0.45 * m;
  }

  /** Solve eps sigma T0^4 = F + k (T1 - T0) / h0 for T0 (Newton). */
  surface(F: number): void {
    const { r, g, T } = this;
    const T1 = T[1], h0 = g.h[0];
    let T0 = T[0];
    for (let it = 0; it < 30; it++) {
      const k = 0.5 * (g.kc[0] * (1 + r.chi * (T0 / 350) ** 3) + g.kc[1] * (1 + r.chi * (T1 / 350) ** 3));
      const dk = (0.5 * g.kc[0] * r.chi * 3 * T0 ** 2) / 350 ** 3;
      const f = r.emissivity * SIGMA * T0 ** 4 - F - (k * (T1 - T0)) / h0;
      const fp = 4 * r.emissivity * SIGMA * T0 ** 3 + k / h0 - (dk * (T1 - T0)) / h0;
      const step = f / fp;
      T0 = Math.max(T0 - step, 2);
      if (Math.abs(step) < 1e-6) break;
    }
    T[0] = T0;
  }

  /** Advance by dt seconds with absorbed surface flux F (W m^-2). */
  step(F: number, dt: number): void {
    const { g, T, r, k, ki, flux } = this;
    const n = T.length;
    this.conductivity();
    for (let i = 0; i < n - 1; i++) {
      ki[i] = 0.5 * (k[i] + k[i + 1]);
      flux[i] = (ki[i] * (T[i + 1] - T[i])) / g.h[i];
    }
    for (let i = 1; i < n - 1; i++) {
      const rc = g.rho[i] * heatCapacity(T[i], r);
      T[i] += (dt * 2 * (flux[i] - flux[i - 1])) / (rc * (g.h[i - 1] + g.h[i]));
    }
    T[n - 1] = T[n - 2] + (r.Q_geo * g.h[n - 2]) / ki[n - 2];
    this.surface(F);
  }

  /** Integrate over sample times tS (s, increasing) with absorbed flux F[j], linear in between.
   * Returns the surface temperature at the samples (and, if asked, at the node nearest `depthM`). */
  run(tS: ArrayLike<number>, F: ArrayLike<number>, depthM?: number): { surface: Float64Array; depth?: Float64Array } {
    const n = tS.length;
    const out = new Float64Array(n);
    let di = -1;
    if (depthM !== undefined) {
      let best = Infinity;
      for (let i = 0; i < this.g.z.length; i++) { const d = Math.abs(this.g.z[i] - depthM); if (d < best) { best = d; di = i; } }
    }
    const deep = di >= 0 ? new Float64Array(n) : undefined;
    this.surface(F[0]);
    out[0] = this.T[0];
    if (deep) deep[0] = this.T[di];
    for (let j = 1; j < n; j++) {
      const span = tS[j] - tS[j - 1];
      const m = Math.max(1, Math.ceil(span / this.stableDt()));
      const dt = span / m;
      for (let s = 1; s <= m; s++) {
        const w = s / m;
        this.step(F[j - 1] * (1 - w) + F[j] * w, dt);
      }
      out[j] = this.T[0];
      if (deep) deep[j] = this.T[di];
    }
    return { surface: out, depth: deep };
  }

  /** The engine's accelerated spin-up (thermal.py Column.spin_up): run the window repeatedly, reset
   * the layers below `settleDepthM` to their pass mean plus the geothermal gradient, with Aitken's
   * extrapolation every third pass. Returns the change of that mean after each pass but the first. */
  spinUp(tS: ArrayLike<number>, F: ArrayLike<number>, cycles = 4, settleDepthM = 0.1): number[] {
    const { g, r } = this;
    let i0 = 0;
    while (i0 < g.z.length && g.z[i0] < settleDepthM) i0++;
    const changes: number[] = [];
    let prev: number | null = null, hist: number[] = [];
    for (let c = 0; c < cycles; c++) {
      const res = this.run(tS, F, g.z[i0]);
      let mean = 0;
      for (const v of res.depth!) mean += v;
      mean /= res.depth!.length;
      hist.push(mean);
      if (hist.length === 3) {
        const d1 = hist[1] - hist[0], d2 = hist[2] - hist[1];
        const ratio = Math.abs(d1) > 1e-9 ? d2 / d1 : 0;
        const ok = ratio > 0 && ratio < 0.95;
        const jump = ok ? (d2 * ratio) / (1 - ratio) : 0;
        mean = hist[2] + Math.max(-60, Math.min(60, jump));
        hist = [mean];
      }
      for (let i = i0; i < g.z.length; i++) {
        const kDeep = g.kc[i] * (1 + r.chi * (mean / 350) ** 3);
        this.T[i] = mean + (r.Q_geo * (g.z[i] - g.z[i0])) / kDeep;
      }
      if (prev !== null) changes.push(Math.abs(mean - prev));
      prev = mean;
    }
    return changes;
  }
}
