import type { DesignResult, Trajectory, TransferRow } from "../types";

const BASE = import.meta.env.BASE_URL;
const url = (path: string) => `${BASE}api/${path}`;

export interface Health {
  status: string;
  version: string;
  ephemeris: string;
  workers: number;
  active_jobs: number;
}

export async function getHealth(): Promise<Health | null> {
  try {
    const r = await fetch(url("health"), { cache: "no-store" });
    if (!r.ok) return null;
    const h = await r.json();
    return h?.status === "ok" ? h : null;
  } catch {
    return null;
  }
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(url(path), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error ?? `The engine returned ${r.status}`);
  return data as T;
}

export interface DesignRequest {
  tli_utc: string;
  tof_days: number;
  family: number;
  lunar_inc_deg: number;
  periselene_alt_km: number;
}

/** Submit a design job and poll until it finishes. */
export async function designTransfer(req: DesignRequest, onTick?: (elapsed: number) => void,
                                     signal?: AbortSignal): Promise<DesignResult> {
  const { job_id } = await post<{ job_id: string }>("transfers", req);
  const start = performance.now();
  for (;;) {
    if (signal?.aborted) throw new Error("Cancelled");
    await new Promise((res) => setTimeout(res, 600));
    onTick?.((performance.now() - start) / 1000);
    const r = await fetch(url(`jobs/${job_id}`), { cache: "no-store" });
    const st = await r.json();
    if (!r.ok) throw new Error(st.error ?? `The engine returned ${r.status}`);
    if (st.status === "done") return st.result as DesignResult;
    if (st.status === "error") throw new Error(st.error);
  }
}

export function fetchTrajectoryLive(row: TransferRow): Promise<Trajectory> {
  return post<Trajectory>("trajectory", {
    id: row.id, tli_epoch: row.tli_epoch, tof_days: row.tof_days, family: row.family,
    lunar_inc_deg: row.lunar_inc_deg, target_alt_km: row.target_alt_km, controls: row.controls,
  });
}
