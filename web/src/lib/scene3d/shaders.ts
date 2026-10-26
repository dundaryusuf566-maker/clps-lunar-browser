/** GLSL for the 3D view. MARCH_GLSL is the GPU twin of march_sun_clear() in
 *  engine/surface/scene3d.py: keep the two in step (the page measures the result
 *  against the engine's horizon masks on load). */

export const HEADER = `#version 300 es
precision highp float;
precision highp int;
precision highp sampler2D;
`;

export const MARCH_GLSL = `
uniform sampler2D uH0, uH1, uH2;     // heights, km above the reference sphere (R32F); < -999 = no data
uniform vec3 uG0, uG1, uG2;          // grid origin x0, y0 and step (km, map plane)
uniform ivec2 uN0, uN1, uN2;         // grid size
uniform float uR, uHTop, uObs;       // Moon radius, highest terrain, observer height (km)
uniform vec4 uMarch;                 // first step, growth, min step, max step (km)
uniform float uMaxKm;

const float INVALID = -999.0;

float bil(sampler2D t, ivec2 n, vec2 c) {
  ivec2 i = clamp(ivec2(floor(c)), ivec2(0), n - 2);
  vec2 f = clamp(c - vec2(i), 0.0, 1.0);
  float a = texelFetch(t, i, 0).r, b = texelFetch(t, i + ivec2(1, 0), 0).r;
  float d = texelFetch(t, i + ivec2(0, 1), 0).r, e = texelFetch(t, i + ivec2(1, 1), 0).r;
  if (min(min(a, b), min(d, e)) < INVALID) return INVALID - 1.0;
  return mix(mix(a, b, f.x), mix(d, e, f.x), f.y);
}
bool inside(vec2 c, ivec2 n) { return c.x >= 0.0 && c.y >= 0.0 && c.x <= float(n.x - 1) && c.y <= float(n.y - 1); }

// finest grid that covers the point
float heightPlane(vec2 P) {
  vec2 c = (P - uG0.xy) / uG0.z;
  if (inside(c, uN0)) { float h = bil(uH0, uN0, c); if (h > INVALID) return h; }
  c = (P - uG1.xy) / uG1.z;
  if (inside(c, uN1)) { float h = bil(uH1, uN1, c); if (h > INVALID) return h; }
  c = (P - uG2.xy) / uG2.z;
  if (inside(c, uN2)) { float h = bil(uH2, uN2, c); if (h > INVALID) return h; }
  return INVALID - 1.0;
}
vec2 planeOf(vec3 q) { float d = length(q) - q.z; return 2.0 * uR * vec2(q.y, -q.x) / d; }
vec3 upOfPlane(vec2 P) { float rr = dot(P, P), k = 4.0 * uR * uR; return vec3(-4.0 * uR * P.y, 4.0 * uR * P.x, rr - k) / (rr + k); }

// Elevation of the direction s (Moon-fixed unit) above the terrain horizon seen from the
// map point P, observer uObs above the ground (deg). stepScale 1 = the engine's schedule.
float clearance(vec2 P, vec3 s, float stepScale) {
  float hs = heightPlane(P);
  if (hs < INVALID) return -90.0;
  vec3 up = upOfPlane(P);
  float rObs = uR + hs + uObs;
  vec3 O = up * rObs;
  float sinS = dot(s, up);
  float cosS = sqrt(max(1.0 - sinS * sinS, 1e-12));
  float best = -1e9;
  float t = uMarch.x;
  for (int i = 0; i < 4000; i++) {
    if (t > uMaxKm) break;
    vec3 Q = O + t * s;
    float dr = (2.0 * t * rObs * sinS + t * t) / (length(Q) + rObs);
    float r = rObs + dr;
    float h = heightPlane(planeOf(Q));
    if (h < INVALID) break;                                  // off the map
    float k = (uR + h) / r;
    float km1 = (h - hs - uObs - dr) / r;
    best = max(best, (rObs * km1 + k * t * sinS) / (k * t * cosS));
    if (r - uR > uHTop && t > -rObs * sinS) break;           // above all terrain and rising
    t += clamp(uMarch.y * t, uMarch.z, uMarch.w) * stepScale;
  }
  return degrees(asin(clamp(sinS, -1.0, 1.0))) - degrees(atan(best));
}

uniform float uSemi;                 // solar semi-diameter, deg
float disc(float c) {
  float x = clamp(c / uSemi, -1.0, 1.0);
  float th = acos(-x);
  return (th - sin(th) * cos(th)) / 3.141592653589793;
}
// clearance packed in two bytes: -30..30 deg
vec2 packClear(float c) {
  float v = floor((clamp(c, -30.0, 30.0) + 30.0) / 60.0 * 65535.0 + 0.5);
  return vec2(floor(v / 256.0), mod(v, 256.0)) / 255.0;
}
`;

export const QUAD_VS = `${HEADER}
const vec2 P[3] = vec2[3](vec2(-1.0, -1.0), vec2(3.0, -1.0), vec2(-1.0, 3.0));
out vec2 vNdc;
void main() { vNdc = P[gl_VertexID]; gl_Position = vec4(P[gl_VertexID], 0.0, 1.0); }
`;

/** One texel per map node: R = share of the solar disc, GB = packed clearance. */
export const LIGHT_FS = `${HEADER}${MARCH_GLSL}
uniform vec3 uTarget;     // x0, y0, step of the nodes this texture covers
uniform vec3 uSun;
uniform float uStepScale;
out vec4 o;
void main() {
  vec2 P = uTarget.xy + floor(gl_FragCoord.xy) * uTarget.z;
  float c = clearance(P, uSun, uStepScale);
  o = vec4(disc(c), packClear(c), 1.0);
}
`;

/** The check: texel (i, j) = check time i at check point j. */
export const CHECK_FS = `${HEADER}${MARCH_GLSL}
uniform sampler2D uSeries;           // RGBA32F, 1024 wide: Sun unit vector per hour
uniform ivec3 uTimes;                // first index, stride, count
uniform vec2 uPts[16];
uniform vec3 uDirA, uDirB;           // probe mode: two directions at uPts[0]
uniform int uProbe;
out vec4 o;
void main() {
  ivec2 p = ivec2(gl_FragCoord.xy);
  vec3 s;
  vec2 P;
  if (uProbe == 1) { s = p.x == 0 ? uDirA : uDirB; P = uPts[0]; }
  else {
    int k = uTimes.x + p.x * uTimes.y;
    s = normalize(texelFetch(uSeries, ivec2(k % 1024, k / 1024), 0).xyz);
    P = uPts[p.y];
  }
  float c = clearance(P, s, 1.0);
  o = vec4(disc(c), packClear(c), 1.0);
}
`;

export const LOGDEPTH = `
uniform float uLogC;                 // 2 / log2(far + 1)
`;

export const TERRAIN_VS = `${HEADER}${LOGDEPTH}
in vec3 aPos;
in vec3 aNor;
in vec2 aPlane;                      // map plane, km from the region centre
uniform mat4 uViewProj;
out vec3 vNor;
out vec2 vPlane;
out float vW;
void main() {
  vNor = aNor;
  vPlane = aPlane;
  gl_Position = uViewProj * vec4(aPos, 1.0);
  vW = gl_Position.w;
}
`;

export const TERRAIN_FS = `${HEADER}${LOGDEPTH}
in vec3 vNor;
in vec2 vPlane;
in float vW;
uniform sampler2D uLight;
uniform vec4 uLightMap;              // x0, y0 (relative to the region centre), step, unused
uniform vec2 uLightSize;
uniform sampler2D uOverlay;
uniform vec4 uOverlayMap;            // x0, y0, step, on
uniform vec2 uOverlaySize;
uniform vec3 uSunScene;
uniform float uGain, uFill, uDim;
out vec4 o;
void main() {
  vec2 lc = ((vPlane - uLightMap.xy) / uLightMap.z + 0.5) / uLightSize;
  float f = texture(uLight, lc).r;
  float ndl = max(dot(normalize(vNor), uSunScene), 0.0);
  float L = 1.0 - exp(-uGain * f * ndl);
  vec3 c = vec3(0.93, 0.92, 0.9) * L * uDim + uFill;
  if (uOverlayMap.w > 0.5) {
    vec2 oc = ((vPlane - uOverlayMap.xy) / uOverlayMap.z + 0.5) / uOverlaySize;
    if (oc.x >= 0.0 && oc.y >= 0.0 && oc.x <= 1.0 && oc.y <= 1.0) {
      vec4 ov = texture(uOverlay, oc);
      c = mix(c, ov.rgb * (0.45 + 0.55 * L), ov.a * 0.8);
    }
  }
  o = vec4(c, 1.0);
  gl_FragDepth = log2(max(1e-6, 1.0 + vW)) * uLogC * 0.5;
}
`;

/** The rest of the Moon, a smooth sphere without terrain (context only). */
export const SPHERE_FS = `${HEADER}${LOGDEPTH}
in vec3 vNor;
in vec2 vPlane;
in float vW;
uniform vec3 uSunScene;
uniform float uGain, uFill;
out vec4 o;
void main() {
  float ndl = max(dot(normalize(vNor), uSunScene), 0.0);
  float L = 1.0 - exp(-uGain * ndl);
  o = vec4(vec3(0.55, 0.57, 0.62) * L * 0.55 + uFill * 0.6, 1.0);
  gl_FragDepth = log2(max(1e-6, 1.0 + vW)) * uLogC * 0.5;
}
`;

export const SKY_FS = `${HEADER}
in vec2 vNdc;
uniform vec3 uRight, uUp, uFwd;      // camera axes, right / up scaled by tan(half field of view)
uniform vec3 uSunDir, uEarthDir;     // scene axes
uniform float uSunRad, uEarthRad;    // angular radii, rad
uniform float uGlow;
out vec4 o;
void main() {
  vec3 d = normalize(uFwd + vNdc.x * uRight + vNdc.y * uUp);
  vec3 c = vec3(0.0);
  float ds = acos(clamp(dot(d, uSunDir), -1.0, 1.0));
  c += vec3(1.0, 0.97, 0.9) * (ds < uSunRad ? 1.0 : 0.0);
  c += vec3(1.0, 0.85, 0.6) * uGlow * 0.5 * exp(-(ds - uSunRad) / (uSunRad * 6.0)) * step(uSunRad, ds);
  float de = acos(clamp(dot(d, uEarthDir), -1.0, 1.0));
  if (de < uEarthRad) {
    // point on the Earth's disc -> sphere normal facing us, lit by the Sun
    vec3 off = (d - uEarthDir * dot(d, uEarthDir)) / sin(uEarthRad);
    vec3 n = normalize(off - uEarthDir * sqrt(max(0.0, 1.0 - dot(off, off))));
    float lit = max(dot(n, uSunDir), 0.0);
    c = vec3(0.32, 0.5, 0.86) * (0.08 + 0.92 * lit) + vec3(0.9) * 0.25 * lit * lit;
  }
  o = vec4(c, 1.0);
}
`;

export const LINE_VS = `${HEADER}${LOGDEPTH}
in vec3 aPos;
uniform mat4 uViewProj;
out float vW;
void main() { gl_Position = uViewProj * vec4(aPos, 1.0); vW = gl_Position.w; gl_PointSize = 3.0; }
`;

export const LINE_FS = `${HEADER}${LOGDEPTH}
in float vW;
uniform vec4 uColor;
uniform int uNoDepth;
out vec4 o;
void main() {
  o = uColor;
  gl_FragDepth = uNoDepth == 1 ? 0.0 : log2(max(1e-6, 1.0 + vW)) * uLogC * 0.5;
}
`;

// --- journey view ------------------------------------------------------------------
/** A body-fixed object placed in the scene: world = uCenter + uScale * uRot * aPos. */
export const OBJ_VS = `${HEADER}${LOGDEPTH}
in vec3 aPos;
in vec3 aNor;
uniform mat4 uViewProj;
uniform mat3 uRot;
uniform vec3 uCenter;
uniform float uScale;
uniform float uPointSize;
out vec3 vNor;
out float vW;
void main() {
  vNor = uRot * aNor;
  gl_Position = uViewProj * vec4(uCenter + uScale * (uRot * aPos), 1.0);
  vW = gl_Position.w;
  gl_PointSize = uPointSize;
}
`;

/** Earth (uKind 0) or Moon (uKind 1) surface, lit by the Sun. */
export const BODY_FS = `${HEADER}${LOGDEPTH}
in vec3 vNor;
in float vW;
uniform vec3 uSun;
uniform int uKind;
uniform float uGain;
out vec4 o;
void main() {
  vec3 n = normalize(vNor);
  float d = dot(n, uSun);
  vec3 c;
  if (uKind == 0) {
    float day = smoothstep(-0.08, 0.12, d);
    c = mix(vec3(0.015, 0.025, 0.05), vec3(0.20, 0.40, 0.78) * (0.35 + 0.65 * max(d, 0.0)) + vec3(0.06), day);
  } else {
    float L = 1.0 - exp(-uGain * max(d, 0.0));
    c = vec3(0.86, 0.85, 0.83) * L + vec3(0.025);
  }
  o = vec4(c, 1.0);
  gl_FragDepth = log2(max(1e-6, 1.0 + vW)) * uLogC * 0.5;
}
`;

export const FLAT_FS = `${HEADER}${LOGDEPTH}
in vec3 vNor;
in float vW;
uniform vec4 uColor;
uniform int uRound;
out vec4 o;
void main() {
  if (uRound == 1 && length(gl_PointCoord - 0.5) > 0.5) discard;
  o = uColor;
  gl_FragDepth = log2(max(1e-6, 1.0 + vW)) * uLogC * 0.5;
}
`;

/** Mission path: brighter where the spacecraft has already been. */
export const PATH_VS = `${HEADER}${LOGDEPTH}
in vec3 aPos;
in vec2 aPlane;          // x = phase
in float aTime;
uniform mat4 uViewProj;
uniform vec3 uOffset;
out float vW;
out float vT;
out float vPhase;
void main() {
  gl_Position = uViewProj * vec4(aPos + uOffset, 1.0);
  vW = gl_Position.w; vT = aTime; vPhase = aPlane.x;
}
`;

export const PATH_FS = `${HEADER}${LOGDEPTH}
in float vW;
in float vT;
in float vPhase;
uniform float uNow;
uniform vec3 uColors[4];
out vec4 o;
void main() {
  int k = int(vPhase + 0.5);
  vec3 c = uColors[k];
  o = vec4(c, vT <= uNow ? 0.95 : 0.3);
  gl_FragDepth = log2(max(1e-6, 1.0 + vW)) * uLogC * 0.5;
}
`;
