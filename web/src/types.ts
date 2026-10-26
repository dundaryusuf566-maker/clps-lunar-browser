export interface TransferRow {
  id: string;
  tli_utc: string;
  tli_epoch: number;          // TDB s past J2000
  tof_days: number;           // requested transit time
  tof_actual_days: number;
  family: number;             // +1 south pass, -1 north pass
  lunar_inc_deg: number;
  target_alt_km: number;
  periselene_alt_km: number;
  loi_dv_ms: number;
  tli_dv_ms: number;
  total_dv_ms: number;
  c3_km2s2: number;
  v_inf_kms: number;
  raan_moon_sun_deg: number;
  periselene_lat_deg: number;
  periselene_lon_deg: number | null;
  parking_inc_deg: number;
  parking_raan_deg: number;
  controls: number[];
  has_trajectory: boolean;
  custom?: boolean;           // designed live in this session
}

export interface DatasetMeta {
  generated_utc: string;
  ephemeris: string;
  count: number;
  families?: number[];
  first_tli_utc?: string;
  last_tli_utc?: string;
  capture_orbit: { periselene_alt_km: number; apolune_alt_km: number | null; lunar_inc_deg: number };
  parking_orbit: { alt_km: number; min_inc_deg: number };
  trajectories?: string;
  source_csv: string;
}

export interface Dataset {
  meta: DatasetMeta;
  rows: TransferRow[];
}

export type Vec3 = [number, number, number];

export interface Trajectory {
  id: string;
  t: number[];               // s since TLI
  sc_eci: Vec3[];            // spacecraft, Earth-centred J2000, km
  moon_tli: Vec3;            // Moon at TLI and at arrival
  moon_arrival: Vec3;
  approach_mci: Vec3[];      // SOI entry -> periselene, Moon-centred
  capture_mci: Vec3[];       // one revolution of the capture orbit
  moon_ring_eci: Vec3[];     // Moon's path over ±14 days around arrival
  sun_dir: Vec3;             // unit vector at arrival
  moon_pole: Vec3;
  events: { tli: number; soi: number; periselene: number };
  radii: { earth: number; moon: number };
}

// --- landing ---------------------------------------------------------------------
export interface Site {
  id: string;
  name: string;
  lat_deg: number;
  lon_deg: number;
  region: string;
  missions: string;
  source: string;
  requires_relay: boolean;
  sun_min_deg: number;
  sun_max_deg: number;
  sun_rising: boolean;
  note: string;
  horizon?: string | null;
  terrain?: SiteTerrain | null;   // LOLA horizon panorama, null = flat horizon
}

export interface SiteTerrain {
  source: string;
  map_scale_m: number;
  observer_m: number;
  site_height_m: number;
  max_dist_km: number;
  az_step_deg: number;
  elev_deg: number[];      // horizon elevation every az_step_deg from north, clockwise
  dist_km: number[];       // distance of the terrain that forms it
}

export interface LandingConstraintsMeta {
  min_coast_days: number;
  max_wait_days: number;
  max_plane_change_ms: number;
  min_earth_elev_deg: number;
  daylight_horizon_days: number;
  prefer_within_ms: number;
  energy_window_days?: number;
  require_dsn?: boolean;
}

export interface SunSeries {
  t0: number;        // TDB s
  step_s: number;
  sun_el_deg: number[];
  horizon_deg?: number[];   // terrain horizon in the Sun's direction (terrain sites only)
  terrain?: string;
}

/** Compact landing entry: feasible -> [wait_d, plane_ms, sun_deg, earth_deg, daylight_d, capped, sun_horizon_deg?,
 *  dsn_bitmask?, energy_pct?, max_dark_gap_h?];
 *  infeasible -> [code, best_plane_ms | null]. */
export type LandingEntry =
  | [number, number, number, number, number, number, (number | null)?, (number | null)?, (number | null)?, (number | null)?]
  | [string, number | null];

export interface LandingsFile {
  meta: { constraints: LandingConstraintsMeta; descent_ms: number; sites: Site[]; model_notes: string[] };
  series: Record<string, SunSeries>;
  results: Record<string, Record<string, LandingEntry>>;
}

export interface Landing {
  feasible: boolean;
  code: "" | "sun" | "earth" | "daylight" | "plane";
  waitDays: number | null;
  planeChangeMs: number | null;
  sunElDeg: number | null;
  sunHorizonDeg: number | null;   // terrain horizon in the Sun's direction at touchdown
  dsn: number | null;             // DSN stations seeing the site at touchdown (1 Goldstone, 2 Madrid, 4 Canberra)
  energyPct: number | null;       // solar disc above the terrain over the first days, % of full Sun
  darkGapH: number | null;        // longest stretch with the Sun hidden in those days
  earthElDeg: number | null;
  daylightDays: number | null;
  daylightCapped: boolean;
  bestPlaneMs: number | null;
  descentMs: number;
  surfaceMs: number | null;     // LOI + plane change + descent
}

export type MetricKey = "loi" | "total" | "tli" | "c3" | "vinf" | "surface" | "wait" | "daylight";
export type FamilyFilter = "all" | 1 | -1;

/** Result of designing a transfer live through the API. */
export interface DesignResult {
  converged: boolean;
  message?: string;
  ephemeris: string;
  solve_seconds: number;
  row?: TransferRow;
  trajectory?: Trajectory;
  landings?: Record<string, LandingEntry>;
  series?: Record<string, SunSeries>;
}

// --- validation.json (scripts/build_validation.py) ---------------------------------
export interface ValidationCheck { id: string; label: string; pass: boolean; value?: number | string | null }

export interface MissionInfo {
  id: string; name: string; site_id: string; site_name: string; lat_deg: number; lon_deg: number;
  launch_utc: string; tli_utc: string; tli_note: string; loi_utc: string; loi_note: string;
  landing_utc: string; surface_end_utc: string | null; surface_end_note: string;
  orbit_alt_km: number; orbit_note: string; loi_dv_ms: number | null;
  launch_windows: [string, string, string][];
  sources: [string, string][];
  region?: string; sun_min_deg?: number; sun_max_deg?: number;
  max_wait_days?: number | null; wait_note?: string; scan_note?: string;
  sunset_utc?: string | null; sunset_note?: string; sunset_tol_h?: number;
}

export interface SunEvents {
  sunrise_utc: string | null; sunset_utc: string | null; days_since_sunrise: number | null; daylight_left_days: number | null;
}

export interface Lighting extends SunEvents {
  sun_elev_deg: number; sun_az_deg?: number; earth_elev_deg: number; sun_rising: boolean; max_sun_elev_deg: number;
  dsn_stations?: string[];
  terrain?: (SunEvents & { source: string; observer_m: number; site_height_m: number; horizon_sun_deg: number;
    sun_clear_deg: number; earth_clear_deg: number }) | null;
}

export interface ReconDesign {
  family: number; lunar_inc_deg: number; tof_days: number; loi_dv_ms: number; loi_dv_error_pct: number | null;
  tli_dv_ms: number; c3_km2s2: number; arrival_utc: string;
  windows: { start_utc: string; end_utc: string; hours: number }[];
  first_landing: { feasible: boolean; landing_utc: string | null; wait_days: number | null; plane_change_ms: number | null;
    daylight_days: number | null; reason: string };
  at_real_landing: { plane_change_deg: number; plane_change_ms: number; light_and_comms_ok: boolean; landable: boolean } | null;
  real_landing_landable: boolean;
}

export interface ScanDay {
  tli_day: string; feasible: boolean; feasible_polar: boolean; options: number; tried: number;
  tof_days: number | null; lunar_inc_deg: number | null; landing_utc: string | null; wait_days: number | null;
  daylight_days: number | null; loi_dv_ms: number | null; surface_dv_ms: number | null; total_from_loi_ms: number | null; why_not: string;
}

export interface DayWindow { first: string; last: string; days: number }

export interface MissionValidation {
  mission: MissionInfo;
  ephemeris: string;
  lighting_at_landing: Lighting;
  sunset?: { predicted_utc: string | null; real_utc: string; hours_off: number | null; tolerance_h: number; note: string } | null;
  surface_days_flown: number | null;
  reconstruction: {
    designs: number; failed: number; polar: ReconDesign[]; tuned: ReconDesign | null; landable_incs: number[];
    loi_dv_range_ms: [number, number] | null; loi_dv_reported_ms: number | null;
    curve: { inc: number; family: number; plane_ms: number | null }[];
  };
  scan: {
    constraints: LandingConstraintsMeta; tofs: number[]; incs: number[]; days: ScanDay[];
    windows: DayWindow[]; windows_polar: DayWindow[];
    real_windows: { first: string; last: string; note: string; scanned_days: number; feasible_days: number;
      inside_predicted: boolean; predicted: DayWindow | null }[];
    launch_day: string; on_launch_day: ScanDay | null; landing_miss_days?: number | null;
  };
  checks: ValidationCheck[];
}

export interface NasaComparison {
  reference: { source: string; read_accuracy: string; window: [string, string]; tof_days: [number, number];
    loi_min_ms: number; loi_max_ms: number; minima: { month: string; date: string; loi_dv_ms: number }[] };
  ephemeris: string; count: number; requested: number; grid_days: number | null;
  band_ms: [number, number]; band_error_ms: [number, number];
  minima: { month: string; nasa_date: string; nasa_loi_dv_ms: number; our_date: string; our_loi_dv_ms: number;
    our_tof_days: number; days_apart: number }[];
  points: { tli: string; tof: number; loi: number }[];
  dense_minimum?: { count: number; tli_utc: string; tof_days: number; loi_dv_ms: number; nasa_loi_dv_ms: number; error_pct: number };
}

export interface TestSummary {
  passed: number; failed: number; skipped: number; seconds: number; python: string; run_utc: string;
  groups: Record<string, { pass: number; fail: number; skip: number }>;
}

export interface IlluminationSite {
  site: string; lat_deg: number; lon_deg: number; n: number; spacing_m: number;
  points: { lat: number; lon: number; ours: number; nasa: number; diff: number }[];
  median_abs_diff: number; max_abs_diff: number; mean_diff: number; correlation: number | null;
  nasa_range: [number, number]; pass: boolean;
}

export interface TerrainCheck {
  generated_utc: string; dem: string; avg_map?: string; ephemeris?: string; samples?: number; span_utc?: [string, string];
  observer_m: number; az_step_deg: number; max_dist_km: number;
  tolerance: { median_abs: number; max_abs: number };
  sites: IlluminationSite[];
  resolution: Record<string, { fine: string; rms_deg: number; max_abs_deg: number; mean_deg: number }> | null;
  orientation_diagnostic: { x_sign: number; y_sign: number; median_abs_diff: number[] }[] | null;
  pass: boolean | null;
  masks?: string[];
}

export interface ValidationFile {
  meta: { generated_utc: string; engine_version: string; ephemeris: string };
  missions: MissionValidation[];
  nasa: NasaComparison | null;
  terrain?: TerrainCheck | null;
  tests: TestSummary | null;
}

// --- forecast.json (scripts/build_forecast.py) -------------------------------------
export interface ForecastDay {
  tli_day: string; feasible: boolean; options: number; tried: number;
  tof_days: number | null; lunar_inc_deg: number | null; landing_utc: string | null;
  landing_range_utc: [string, string] | null; wait_days: number | null; daylight_days: number | null;
  daylight_capped: boolean | null; sun_elev_deg: number | null; sun_horizon_deg: number | null;
  loi_dv_ms: number | null; total_from_loi_ms: number | null; why_not: string;
  dsn_stations?: string[] | null; energy_pct?: number | null; max_dark_gap_h?: number | null;
}

export interface ForecastWindow {
  first: string; last: string; days: number; landing_first_utc: string; landing_last_utc: string;
  best_tli_day: string; best_landing_utc: string; best_total_from_loi_ms: number;
  min_daylight_days: number; max_daylight_days: number;
}

export interface RegionPoint {
  i: number; j: number; x_km: number; y_km: number; lat: number; lon: number; label?: string;
  height_m: number; slope_deg: number; horizon_max_deg: number; horizon_mean_deg: number;
  slot_days: number; opportunities: number; sunlit_pct: number; earth_when_lit_pct: number;
  best_daylight_days: number | null; best_daylight_capped: boolean; best_slot: string | null;
  earth_after_best_pct: number | null; first_slot: string | null; runs: [string, string][];
  energy_pct?: number | null; max_dark_gap_h?: number | null;
}

export interface ForecastFile {
  meta: { registered_utc: string; engine_version: string; ephemeris: string; git_commit: string | null; sha256: string; how_to_verify: string };
  mission: {
    id: string; name: string; operator: string; announced: [string, string][]; assumptions: string[];
    reference_name: string; reference_lat: number; reference_lon: number; tli_first: string; tli_last: string;
    min_daylight_days: number; landing_first: string; landing_last: string; sources: [string, string][];
  };
  time: {
    reference: { name: string; lat_deg: number; lon_deg: number; terrain: string | null };
    constraints: LandingConstraintsMeta & { min_daylight_days?: number };
    tofs: number[]; incs: number[]; transfers: number; days: ForecastDay[]; windows: ForecastWindow[];
    calibration: { mission: string; site: string; miss_days: number | null; ephemeris: string }[];
  };
  region: {
    grid: { center_lat: number; center_lon: number; half_km: number; step_km: number; n: number; pole_direction: [number, number]; frame: string };
    landmarks: { label: string; lat: number; lon: number; source: string; x_km: number; y_km: number }[];
    rules: { sun_min_deg: number; earth_min_deg: number; observer_m: number; az_step_deg: number; max_dist_km: number; min_daylight_days: number; energy_window_days?: number; dem: string; slope_baseline_m: number };
    period_utc: [string, string];
    ranking: { max_slope_deg: number; min_earth_after_pct: number; order: string };
    points: RegionPoint[]; references: RegionPoint[]; top: RegionPoint[];
  } | null;
}

// --- regolith temperatures (scripts/build_thermal.py) ---------------------------------
export interface ThermalPoint {
  key: string; label: string; lat: number; lon: number; slope_deg: number; terrain: boolean;
  min_k: number; max_k: number; mean_k: number; depth_10cm_mean_k: number;
  min_direct_k?: number; max_direct_k?: number; terrain_view_factor?: number; terrain_directions?: number;
  missing_bounces_pct?: number; terrain_flux_max_w_m2?: number; terrain_flux_mean_w_m2?: number;
  surface_direct_k?: number[];
  dni_w_m2?: number[]; sun_el_deg?: number[];
  after_best_slot: { start_utc: string; min_k: number; max_k: number; mean_k: number; hours_below_150k: number;
    sun_up_at_start?: boolean; shadow_hours?: number } | null;
  surface_k: number[];
}
export interface ThermalFile {
  meta: {
    generated_utc: string; engine_version: string; ephemeris: string; dem: string; forecast_sha256: string | null;
    regolith: { H: number; chi: number; A0: number; a: number; b: number; emissivity: number; k_s: number; k_d: number;
      rho_s: number; rho_d: number; Q_geo: number; S: number; source: string };
    grid: { layers: number; first_layer_mm: number; bottom_m: number };
    spin_up_days: number; spin_up_residual_k: number; notes: string[];
  };
  equator_check: {
    model: Record<string, number>; diviner: Record<string, number>; tolerance_k: number; source: string; pass: boolean;
    spin_up_residual_k: number; curve: [number, number][];
  };
  bowl_check?: {
    depth_to_diameter: number; sun_el_deg: number; albedo: number; emissivity: number; f: number; source: string;
    tolerance_pct: { facets: number; sampling: number };
    facets: { n: number; shadow_t_k: number; ingersoll_t_k: number; diff_pct: number; pass: boolean };
    sampling: { directions: number; view_factor: number; flux_w_m2: number; one_bounce_w_m2: number; diff_pct: number; pass: boolean };
  };
  time: { t0_utc: string; step_h: number; n: number; landing_period_utc: [string, string] };
  points: ThermalPoint[];
}

// --- Diviner polar check (scripts/diviner_polar_check.py) ------------------------------
export type DivinerClass = "both_dark" | "both_lit" | "model_dark" | "diviner_dark" | "between";
export interface DivinerDiagnosticsFile {
  meta: { generated_utc: string; engine_version: string; ephemeris: string; dem: string; registered_generated_utc: string;
    sub_points_m: number[]; classes_k: { dark_below: number; lit_above: number } };
  point_breakdown: Record<DivinerClass, { n: number; median_k: number | null }>;
  bin_breakdown: Record<DivinerClass, { n: number; median_k: number | null }>;
  same_bins_point_breakdown?: Record<DivinerClass, { n: number; median_k: number | null }>;
  bin_median_abs_k: number | null; bin_n: number; same_bins_point_median_abs_k?: number | null;
  points: { key: string; label: string; slope_min_deg?: number; slope_max_deg?: number; bin_dist: number | null;
    median_abs_k: number | null; bias_k: number | null; own_bin_files?: number;
    seasons: Record<"sum" | "win", [number, number | null, number | null, number | null][]> }[];
}

export interface DivinerPolarFile {
  meta: { generated_utc: string; engine_version: string; ephemeris: string; dem: string; span_utc: [string, string];
    bins: number[]; night_below_k: number; layout: string | null; range_requests: number; diviner_source: string;
    diviner_archive: string; model_source: string; notes: string[] };
  summary: { n: number; median_abs_k: number | null; p90_abs_k: number | null; bias_day_k: number | null; n_day: number;
    bias_night_k: number | null; n_night: number; criterion_k: number; pass: boolean };
  points: { key: string; label: string; lat: number; lon: number; n: number; median_abs_k: number | null; bias_k: number | null;
    seasons: Record<"sum" | "win", [number, number | null, number | null][]> }[];
}

// --- Polar map orientation (scripts/check_polar_orientation.py) -------------------------
export interface OrientationFile {
  dem: string; criterion_min_depth_m: number; engine_reading: [number, number];
  craters: { name: string; lat: number; lon: number; diameter_km: number }[]; craters_source: string;
  readings: { x_sign: number; y_sign: number; pass: boolean; depths_m: Record<string, number | null> }[];
  verdict: string; code: number; generated_utc: string;
}
