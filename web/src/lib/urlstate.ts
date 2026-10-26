/** Shareable state in the URL hash: "#page?key=value&...". */

export function readParams(): URLSearchParams {
  const h = window.location.hash.replace(/^#/, "");
  const i = h.indexOf("?");
  return new URLSearchParams(i >= 0 ? h.slice(i + 1) : "");
}

export function hashPage(): string {
  return window.location.hash.replace(/^#/, "").split("?")[0];
}

/** Merge values into the hash query (null or "" removes a key) without adding history entries. */
export function writeParams(values: Record<string, string | number | boolean | null | undefined>): void {
  const p = readParams();
  for (const [k, v] of Object.entries(values)) {
    if (v === null || v === undefined || v === "" || v === false) p.delete(k);
    else p.set(k, String(v === true ? 1 : v));
  }
  const page = hashPage() || "browse";
  const q = p.toString();
  const hash = q ? `#${page}?${q}` : page === "browse" ? "" : `#${page}`;
  history.replaceState(null, "", window.location.pathname + window.location.search + hash);
}

export const numParam = (p: URLSearchParams, k: string): number | null => {
  const v = p.get(k);
  if (v === null || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};
