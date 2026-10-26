/** WebGL2 renderer of the 3D scene: GPU terrain shadows (same march as the
 *  engine), terrain meshes on the curved Moon, sky with the Sun and Earth. */
import {
  dirToScene, heightAt, planeOf, toFixed, toScene, upOf, type Grid, type Scene,
} from "./data";
import { norm, scale, sub, type V3 } from "./math";
import {
  CHECK_FS, LIGHT_FS, LINE_FS, LINE_VS, QUAD_VS, SKY_FS, SPHERE_FS, TERRAIN_FS, TERRAIN_VS,
} from "./shaders";

type GL = WebGL2RenderingContext;

interface Target { tex: WebGLTexture; fb: WebGLFramebuffer; w: number; h: number; x0: number; y0: number; step: number }
interface Mesh { vao: WebGLVertexArrayObject; count: number; light: () => Target | null; buffers: WebGLBuffer[] }
export interface Line { pts: V3[]; color: [number, number, number, number]; noDepth?: boolean; points?: boolean }
export interface View {
  viewProj: Float64Array; eye: V3; right: V3; up: V3; fwd: V3; tanX: number; tanY: number; far: number;
}
export type Quality = "fast" | "full";

export function compile(gl: GL, type: number, src: string): WebGLShader {
  const s = gl.createShader(type)!;
  gl.shaderSource(s, src);
  gl.compileShader(s);
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(`shader: ${gl.getShaderInfoLog(s)}`);
  return s;
}

export class Program {
  p: WebGLProgram;
  private loc = new Map<string, WebGLUniformLocation | null>();
  constructor(private gl: GL, vs: string, fs: string) {
    const p = gl.createProgram()!;
    gl.attachShader(p, compile(gl, gl.VERTEX_SHADER, vs));
    gl.attachShader(p, compile(gl, gl.FRAGMENT_SHADER, fs));
    gl.bindAttribLocation(p, 0, "aPos");
    gl.bindAttribLocation(p, 1, "aNor");
    gl.bindAttribLocation(p, 2, "aPlane");
    gl.bindAttribLocation(p, 3, "aTime");
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(`link: ${gl.getProgramInfoLog(p)}`);
    this.p = p;
  }
  u(name: string) {
    if (!this.loc.has(name)) this.loc.set(name, this.gl.getUniformLocation(this.p, name));
    return this.loc.get(name)!;
  }
}

const f32 = (m: Float64Array) => new Float32Array(m);

export class SceneRenderer {
  readonly gl: GL;
  private light: Program; private check: Program; private terrain: Program; private sphere: Program;
  private sky: Program; private line: Program;
  private heights: WebGLTexture[] = [];
  private seriesTex: WebGLTexture;
  private targets: Record<"fine" | "fast" | "mid" | "outer", Target>;
  private meshes: Mesh[] = [];
  private sphereMesh: Mesh;
  private quadVao: WebGLVertexArrayObject;
  private blank: WebGLTexture;
  private overlay: { tex: WebGLTexture; n: number; x0: number; y0: number; step: number } | null = null;
  private lines: { buf: WebGLBuffer; vao: WebGLVertexArrayObject; n: number; l: Line }[] = [];
  private current: Quality = "fast";
  readonly Xc: number; readonly Yc: number;         // map plane of the region centre
  sunMf: V3 = [1, 0, 0]; earthMf: V3 = [0, 1, 0]; earthKm = 384400;
  gain = 6; fill = 0.014;

  constructor(readonly canvas: HTMLCanvasElement, readonly scene: Scene) {
    const gl = canvas.getContext("webgl2", { antialias: true, preserveDrawingBuffer: true });
    if (!gl) throw new Error("WebGL2 is not available in this browser");
    this.gl = gl;
    const s = scene;
    [this.Xc, this.Yc] = planeOf(s.C, s.R);
    this.light = new Program(gl, QUAD_VS, LIGHT_FS);
    this.check = new Program(gl, QUAD_VS, CHECK_FS);
    this.terrain = new Program(gl, TERRAIN_VS, TERRAIN_FS);
    this.sphere = new Program(gl, TERRAIN_VS, SPHERE_FS);
    this.sky = new Program(gl, QUAD_VS, SKY_FS);
    this.line = new Program(gl, LINE_VS, LINE_FS);
    this.quadVao = gl.createVertexArray()!;
    this.blank = gl.createTexture()!;
    gl.bindTexture(gl.TEXTURE_2D, this.blank);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array(4));

    for (const g of s.grids) this.heights.push(this.floatTex(g.meta.nx, g.meta.ny, g.h, gl.R32F, gl.RED));
    const n = s.meta.time.n, rows = Math.ceil(n / 1024), ser = new Float32Array(1024 * rows * 4);
    for (let i = 0; i < n; i++) ser.set([s.series[i * 7], s.series[i * 7 + 1], s.series[i * 7 + 2], 0], i * 4);
    this.seriesTex = this.floatTex(1024, rows, ser, gl.RGBA32F, gl.RGBA);

    const [g0, g1, g2] = s.grids.map((g) => g.meta);
    const t = (g: Grid["meta"], stride: number) =>
      this.target(Math.ceil(g.nx / stride), Math.ceil(g.ny / stride), g.x0_km, g.y0_km, g.step_km * stride);
    this.targets = { fine: t(g0, 1), fast: t(g0, 2), mid: t(g1, 2), outer: t(g2, 2) };

    const inner = s.grids[0], mid = s.grids[1], outer = s.grids[2];
    const box = (g: Grid["meta"]) => [g.x0_km, g.y0_km, g.x0_km + (g.nx - 1) * g.step_km, g.y0_km + (g.ny - 1) * g.step_km];
    this.meshes.push(this.gridMesh(inner, 2, null, 0, 0.6, () => (this.current === "full" ? this.targets.fine : this.targets.fast)));
    this.meshes.push(this.gridMesh(mid, 2, box(g0), 0, 1.0, () => this.targets.mid));
    this.meshes.push(this.gridMesh(outer, 2, box(g1), 0.05, 0, () => this.targets.outer));
    this.sphereMesh = this.moonSphere(10);
  }

  // --- resources -------------------------------------------------------------------------
  private floatTex(w: number, h: number, data: Float32Array, internal: number, format: number) {
    const gl = this.gl, tex = gl.createTexture()!;
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
    gl.texImage2D(gl.TEXTURE_2D, 0, internal, w, h, 0, format, gl.FLOAT, data);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    return tex;
  }

  private target(w: number, h: number, x0: number, y0: number, step: number): Target {
    const gl = this.gl, tex = gl.createTexture()!;
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    const fb = gl.createFramebuffer()!;
    gl.bindFramebuffer(gl.FRAMEBUFFER, fb);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    return { tex, fb, w, h, x0, y0, step };
  }

  private upload(pos: Float32Array, nor: Float32Array, plane: Float32Array, idx: Uint32Array, light: () => Target | null): Mesh {
    const gl = this.gl, vao = gl.createVertexArray()!;
    gl.bindVertexArray(vao);
    const buffers: WebGLBuffer[] = [];
    [[pos, 3], [nor, 3], [plane, 2]].forEach(([arr, size], k) => {
      const b = gl.createBuffer()!;
      gl.bindBuffer(gl.ARRAY_BUFFER, b);
      gl.bufferData(gl.ARRAY_BUFFER, arr as Float32Array, gl.STATIC_DRAW);
      gl.enableVertexAttribArray(k);
      gl.vertexAttribPointer(k, size as number, gl.FLOAT, false, 0, 0);
      buffers.push(b);
    });
    const ib = gl.createBuffer()!;
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ib);
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, idx, gl.STATIC_DRAW);
    buffers.push(ib);
    gl.bindVertexArray(null);
    return { vao, count: idx.length, light, buffers };
  }

  /** Terrain mesh from every `stride`-th node of a grid, minus the cells inside `hole`,
   *  with a skirt hanging `skirtKm` down from its outer edge to hide the seams between
   *  rings (the 120 m and 360 m meshes meet exactly at the inner square's edge). */
  private gridMesh(g: Grid, stride: number, hole: number[] | null, dropKm: number, skirtKm: number,
                   light: () => Target | null): Mesh {
    const s = this.scene, m = g.meta;
    const nx = Math.floor((m.nx - 1) / stride) + 1, ny = Math.floor((m.ny - 1) / stride) + 1;
    const per: number[] = [];                          // perimeter nodes, in order around
    for (let i = 0; i < nx; i++) per.push(i);
    for (let j = 1; j < ny; j++) per.push(j * nx + nx - 1);
    for (let i = nx - 2; i >= 0; i--) per.push((ny - 1) * nx + i);
    for (let j = ny - 2; j > 0; j--) per.push(j * nx);
    const nv = nx * ny + (skirtKm > 0 ? per.length : 0);
    const pos = new Float32Array(nv * 3), plane = new Float32Array(nv * 2), ok = new Uint8Array(nv);
    const nor = new Float32Array(nv * 3);
    const P: V3[] = new Array(nx * ny), U: V3[] = new Array(nx * ny);
    for (let j = 0; j < ny; j++)
      for (let i = 0; i < nx; i++) {
        const k = j * nx + i, X = m.x0_km + i * stride * m.step_km, Y = m.y0_km + j * stride * m.step_km;
        const h = g.h[j * stride * m.nx + i * stride];
        const valid = h > -999;
        const u = upOf(X, Y, s.R);
        U[k] = u;
        P[k] = toScene(s, scale(u, s.R + (valid ? h : 0) - dropKm));
        ok[k] = valid ? 1 : 0;
        pos.set(P[k], k * 3);
        plane.set([X - this.Xc, Y - this.Yc], k * 2);
      }
    for (let j = 0; j < ny; j++)
      for (let i = 0; i < nx; i++) {
        const at = (a: number, b: number) => P[Math.min(Math.max(b, 0), ny - 1) * nx + Math.min(Math.max(a, 0), nx - 1)];
        const dx = sub(at(i + 1, j), at(i - 1, j)), dy = sub(at(i, j + 1), at(i, j - 1));
        let n: V3 = [dy[1] * dx[2] - dy[2] * dx[1], dy[2] * dx[0] - dy[0] * dx[2], dy[0] * dx[1] - dy[1] * dx[0]];
        const up = dirToScene(s, U[j * nx + i]);
        if (n[0] * up[0] + n[1] * up[1] + n[2] * up[2] < 0) n = scale(n, -1);
        nor.set(scale(n, 1 / (norm(n) || 1)), (j * nx + i) * 3);
      }
    const idx: number[] = [];
    const eps = 1e-6;
    const inHole = (X: number, Y: number) => hole !== null && X >= hole[0] - eps && X <= hole[2] + eps && Y >= hole[1] - eps && Y <= hole[3] + eps;
    for (let j = 0; j < ny - 1; j++)
      for (let i = 0; i < nx - 1; i++) {
        const a = j * nx + i, b = a + 1, c = a + nx, d = c + 1;
        if (!(ok[a] && ok[b] && ok[c] && ok[d])) continue;
        if (hole) {
          const X0 = m.x0_km + i * stride * m.step_km, Y0 = m.y0_km + j * stride * m.step_km, w = stride * m.step_km;
          if (inHole(X0, Y0) && inHole(X0 + w, Y0) && inHole(X0, Y0 + w) && inHole(X0 + w, Y0 + w)) continue;
        }
        idx.push(a, c, b, b, c, d);
      }
    if (skirtKm > 0) {
      per.forEach((k, q) => {
        const v = nx * ny + q;
        pos.set(toScene(s, scale(U[k], norm(toFixed(s, P[k])) - skirtKm)), v * 3);
        plane.set(plane.subarray(k * 2, k * 2 + 2), v * 2);
        nor.set(nor.subarray(k * 3, k * 3 + 3), v * 3);
        ok[v] = ok[k];
      });
      for (let q = 0; q < per.length; q++) {
        const a = per[q], b = per[(q + 1) % per.length], sa = nx * ny + q, sb = nx * ny + ((q + 1) % per.length);
        if (ok[a] && ok[b]) idx.push(a, b, sa, b, sb, sa);
      }
    }
    return this.upload(pos, nor, plane, new Uint32Array(idx), light);
  }

  private moonSphere(belowKm: number): Mesh {
    const s = this.scene, nLat = 96, nLon = 192, r = s.R - belowKm;
    const pos: number[] = [], nor: number[] = [], plane: number[] = [], idx: number[] = [];
    for (let a = 0; a <= nLat; a++) {
      const lat = -Math.PI / 2 + (Math.PI * a) / nLat;
      for (let b = 0; b <= nLon; b++) {
        const lon = (2 * Math.PI * b) / nLon;
        const u: V3 = [Math.cos(lat) * Math.cos(lon), Math.cos(lat) * Math.sin(lon), Math.sin(lat)];
        pos.push(...toScene(s, scale(u, r)));
        nor.push(...dirToScene(s, u));
        plane.push(0, 0);
      }
    }
    for (let a = 0; a < nLat; a++)
      for (let b = 0; b < nLon; b++) {
        const i = a * (nLon + 1) + b;
        idx.push(i, i + 1, i + nLon + 1, i + 1, i + nLon + 2, i + nLon + 1);
      }
    return this.upload(new Float32Array(pos), new Float32Array(nor), new Float32Array(plane), new Uint32Array(idx), () => null);
  }

  // --- the march -------------------------------------------------------------------------
  private marchUniforms(p: Program) {
    const gl = this.gl, s = this.scene;
    s.grids.forEach((g, k) => {
      gl.activeTexture(gl.TEXTURE0 + k);
      gl.bindTexture(gl.TEXTURE_2D, this.heights[k]);
      gl.uniform1i(p.u(`uH${k}`), k);
      gl.uniform3f(p.u(`uG${k}`), g.meta.x0_km, g.meta.y0_km, g.meta.step_km);
      gl.uniform2i(p.u(`uN${k}`), g.meta.nx, g.meta.ny);
    });
    const m = s.meta.march;
    gl.uniform1f(p.u("uR"), s.R);
    gl.uniform1f(p.u("uHTop"), s.hTopKm);
    gl.uniform1f(p.u("uObs"), s.meta.observer_m / 1000);
    gl.uniform4f(p.u("uMarch"), m.t0_km, m.grow, m.min_step_km, m.max_step_km);
    gl.uniform1f(p.u("uMaxKm"), m.max_km);
    gl.uniform1f(p.u("uSemi"), s.meta.solar_semi_diameter_deg);
  }

  /** Recompute the terrain lighting for the current Sun. "fast" halves the inner resolution. */
  updateLight(quality: Quality) {
    const gl = this.gl, p = this.light;
    gl.useProgram(p.p);
    this.marchUniforms(p);
    gl.uniform3f(p.u("uSun"), ...this.sunMf);
    gl.uniform1f(p.u("uStepScale"), 1);
    gl.disable(gl.DEPTH_TEST);
    gl.bindVertexArray(this.quadVao);
    const list: Target[] = [quality === "full" ? this.targets.fine : this.targets.fast, this.targets.mid, this.targets.outer];
    for (const t of list) {
      gl.bindFramebuffer(gl.FRAMEBUFFER, t.fb);
      gl.viewport(0, 0, t.w, t.h);
      gl.uniform3f(p.u("uTarget"), t.x0, t.y0, t.step);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    }
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    this.current = quality;
  }

  private runMarch(w: number, h: number, setup: (p: Program) => void): Float64Array {
    const gl = this.gl, p = this.check;
    const t = this.target(w, h, 0, 0, 1);
    gl.useProgram(p.p);
    this.marchUniforms(p);
    gl.activeTexture(gl.TEXTURE0 + 4);
    gl.bindTexture(gl.TEXTURE_2D, this.seriesTex);
    gl.uniform1i(p.u("uSeries"), 4);
    setup(p);
    gl.disable(gl.DEPTH_TEST);
    gl.bindVertexArray(this.quadVao);
    gl.bindFramebuffer(gl.FRAMEBUFFER, t.fb);
    gl.viewport(0, 0, w, h);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    const px = new Uint8Array(w * h * 4);
    gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, px);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    gl.deleteFramebuffer(t.fb);
    gl.deleteTexture(t.tex);
    const out = new Float64Array(w * h);
    for (let i = 0; i < w * h; i++) out[i] = ((px[i * 4 + 1] * 256 + px[i * 4 + 2]) / 65535) * 60 - 30;
    return out;
  }

  /** GPU clearance (deg) at every check point and check time: [point][time]. */
  runCheck(): Float64Array[] {
    const s = this.scene, [k0, stride, nT] = s.meta.checks.time_index;
    const pts = s.meta.checks.points.slice(0, 16);
    const res = this.runMarch(nT, pts.length, (p) => {
      const gl = this.gl;
      gl.uniform3i(p.u("uTimes"), k0, stride, nT);
      gl.uniform1i(p.u("uProbe"), 0);
      const flat = new Float32Array(32);
      pts.forEach((q, j) => flat.set(planeOf(upOfLatLonDeg(q.lat, q.lon), s.R), j * 2));
      gl.uniform2fv(p.u("uPts"), flat);
    });
    return pts.map((_, j) => res.slice(j * nT, (j + 1) * nT));
  }

  /** Clearance (deg) of two directions above the terrain at one map point. */
  probe(X: number, Y: number, a: V3, b: V3): [number, number] {
    const r = this.runMarch(2, 1, (p) => {
      const gl = this.gl;
      gl.uniform1i(p.u("uProbe"), 1);
      gl.uniform3f(p.u("uDirA"), ...a);
      gl.uniform3f(p.u("uDirB"), ...b);
      const flat = new Float32Array(32);
      flat.set([X, Y]);
      gl.uniform2fv(p.u("uPts"), flat);
    });
    return [r[0], r[1]];
  }

  // --- overlay and lines -----------------------------------------------------------------
  setOverlay(rgba: Uint8Array | null, n = 0, x0 = 0, y0 = 0, step = 1) {
    const gl = this.gl;
    if (!rgba) { this.overlay = null; return; }
    const tex = this.overlay?.tex ?? gl.createTexture()!;
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, n, n, 0, gl.RGBA, gl.UNSIGNED_BYTE, rgba);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    this.overlay = { tex, n, x0, y0, step };
  }

  setLines(lines: Line[]) {
    const gl = this.gl;
    for (const l of this.lines) { gl.deleteBuffer(l.buf); gl.deleteVertexArray(l.vao); }
    this.lines = lines.filter((l) => l.pts.length > 1 || l.points).map((l) => {
      const vao = gl.createVertexArray()!, buf = gl.createBuffer()!;
      gl.bindVertexArray(vao);
      gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(l.pts.flat()), gl.STATIC_DRAW);
      gl.enableVertexAttribArray(0);
      gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 0, 0);
      gl.bindVertexArray(null);
      return { buf, vao, n: l.pts.length, l };
    });
  }

  // --- frame -----------------------------------------------------------------------------
  draw(v: View) {
    const gl = this.gl, s = this.scene, c = this.canvas;
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    gl.viewport(0, 0, c.width, c.height);
    gl.clearColor(0, 0, 0, 1);
    gl.clearDepth(1);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    const sunS = dirToScene(s, this.sunMf), earthS = dirToScene(s, this.earthMf);

    // sky
    gl.disable(gl.DEPTH_TEST);
    gl.useProgram(this.sky.p);
    const sk = this.sky;
    gl.uniform3f(sk.u("uRight"), ...scale(v.right, v.tanX));
    gl.uniform3f(sk.u("uUp"), ...scale(v.up, v.tanY));
    gl.uniform3f(sk.u("uFwd"), ...v.fwd);
    gl.uniform3f(sk.u("uSunDir"), ...sunS);
    gl.uniform3f(sk.u("uEarthDir"), ...earthS);
    gl.uniform1f(sk.u("uSunRad"), (s.meta.solar_semi_diameter_deg * Math.PI) / 180);
    gl.uniform1f(sk.u("uEarthRad"), Math.asin(6371 / this.earthKm));
    gl.uniform1f(sk.u("uGlow"), 1);
    gl.bindVertexArray(this.quadVao);
    gl.drawArrays(gl.TRIANGLES, 0, 3);

    // terrain
    gl.enable(gl.DEPTH_TEST);
    gl.depthFunc(gl.LEQUAL);
    const logC = 2 / Math.log2(v.far + 1);
    const vp = f32(v.viewProj);
    const t = this.terrain;
    gl.useProgram(t.p);
    gl.uniformMatrix4fv(t.u("uViewProj"), false, vp);
    gl.uniform1f(t.u("uLogC"), logC);
    gl.uniform3f(t.u("uSunScene"), ...sunS);
    gl.uniform1f(t.u("uGain"), this.gain);
    gl.uniform1f(t.u("uFill"), this.fill);
    gl.uniform1f(t.u("uDim"), 1);
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, this.overlay?.tex ?? this.blank);
    gl.uniform1i(t.u("uOverlay"), 1);
    if (this.overlay) {
      const o = this.overlay;
      gl.uniform4f(t.u("uOverlayMap"), o.x0, o.y0, o.step, 1);
      gl.uniform2f(t.u("uOverlaySize"), o.n, o.n);
    } else gl.uniform4f(t.u("uOverlayMap"), 0, 0, 1, 0);
    for (const m of this.meshes) {
      const L = m.light()!;
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, L.tex);
      gl.uniform1i(t.u("uLight"), 0);
      gl.uniform4f(t.u("uLightMap"), L.x0 - this.Xc, L.y0 - this.Yc, L.step, 0);
      gl.uniform2f(t.u("uLightSize"), L.w, L.h);
      gl.bindVertexArray(m.vao);
      gl.drawElements(gl.TRIANGLES, m.count, gl.UNSIGNED_INT, 0);
    }
    const sp = this.sphere;
    gl.useProgram(sp.p);
    gl.uniformMatrix4fv(sp.u("uViewProj"), false, vp);
    gl.uniform1f(sp.u("uLogC"), logC);
    gl.uniform3f(sp.u("uSunScene"), ...sunS);
    gl.uniform1f(sp.u("uGain"), this.gain);
    gl.uniform1f(sp.u("uFill"), this.fill);
    gl.bindVertexArray(this.sphereMesh.vao);
    gl.drawElements(gl.TRIANGLES, this.sphereMesh.count, gl.UNSIGNED_INT, 0);

    // lines
    if (this.lines.length) {
      const l = this.line;
      gl.useProgram(l.p);
      gl.uniformMatrix4fv(l.u("uViewProj"), false, vp);
      gl.uniform1f(l.u("uLogC"), logC);
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
      for (const x of this.lines) {
        gl.uniform4f(l.u("uColor"), ...x.l.color);
        gl.uniform1i(l.u("uNoDepth"), x.l.noDepth ? 1 : 0);
        gl.bindVertexArray(x.vao);
        gl.drawArrays(x.l.points ? gl.POINTS : gl.LINE_STRIP, 0, x.n);
      }
      gl.disable(gl.BLEND);
    }
    gl.bindVertexArray(null);
  }

  /** Free the GPU memory (the canvas and its context stay usable for a new renderer). */
  dispose() {
    const gl = this.gl;
    for (const t of this.heights) gl.deleteTexture(t);
    gl.deleteTexture(this.seriesTex);
    gl.deleteTexture(this.blank);
    for (const t of Object.values(this.targets)) { gl.deleteTexture(t.tex); gl.deleteFramebuffer(t.fb); }
    for (const m of [...this.meshes, this.sphereMesh]) { m.buffers.forEach((b) => gl.deleteBuffer(b)); gl.deleteVertexArray(m.vao); }
    for (const l of this.lines) { gl.deleteBuffer(l.buf); gl.deleteVertexArray(l.vao); }
    if (this.overlay) gl.deleteTexture(this.overlay.tex);
    for (const p of [this.light, this.check, this.terrain, this.sphere, this.sky, this.line]) gl.deleteProgram(p.p);
  }
}

function upOfLatLonDeg(lat: number, lon: number): V3 {
  const p = (lat * Math.PI) / 180, l = (lon * Math.PI) / 180;
  return [Math.cos(p) * Math.cos(l), Math.cos(p) * Math.sin(l), Math.sin(p)];
}

/** First terrain point along a ray (scene km), or null if it misses the terrain grids. */
export function pickTerrain(s: Scene, eye: V3, dir: V3, maxKm = 1500): V3 | null {
  const below = (p: V3) => {
    const f = toFixed(s, p), [X, Y] = planeOf(f, s.R), h = heightAt(s, X, Y);
    return h === null ? null : norm(f) < s.R + h;
  };
  let t = 0, prev = 0;
  while (t < maxKm) {
    const p: V3 = [eye[0] + dir[0] * t, eye[1] + dir[1] * t, eye[2] + dir[2] * t];
    const b = below(p);
    if (b) {
      let lo = prev, hi = t;
      for (let i = 0; i < 30; i++) {
        const m = (lo + hi) / 2;
        if (below([eye[0] + dir[0] * m, eye[1] + dir[1] * m, eye[2] + dir[2] * m])) hi = m; else lo = m;
      }
      return [eye[0] + dir[0] * hi, eye[1] + dir[1] * hi, eye[2] + dir[2] * hi];
    }
    prev = t;
    t += Math.max(0.01, t * 0.003);
  }
  return null;
}
