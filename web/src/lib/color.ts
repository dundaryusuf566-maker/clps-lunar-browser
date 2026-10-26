import { interpolateRgbBasis } from "d3-interpolate";
import { scaleSequential } from "d3-scale";

// Single-hue blue ramp (dataviz reference palette, steps 250 -> 700). Starting at
// 250 keeps the cheapest cells and the lightest dots >= 2:1 against the surface.
const LIGHT = ["#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b"];
// Dark mode: same hue, low values recede into the dark surface.
const DARK = ["#184f95", "#1c5cab", "#256abf", "#2a78d6", "#3987e5", "#5598e7", "#6da7ec", "#86b6ef", "#9ec5f4", "#b7d3f6", "#cde2fb"];

export function isDark(): boolean {
  const forced = document.documentElement.dataset.theme;
  if (forced) return forced === "dark";
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
}

export function ramp(dark: boolean) {
  return interpolateRgbBasis(dark ? DARK : LIGHT);
}

export function sequential(domain: [number, number], dark: boolean) {
  return scaleSequential(ramp(dark)).domain(domain).clamp(true);
}

export function rampGradient(dark: boolean): string {
  const r = ramp(dark);
  const stops = Array.from({ length: 11 }, (_, i) => `${r(i / 10)} ${i * 10}%`);
  return `linear-gradient(90deg, ${stops.join(", ")})`;
}
