export type RiskLevel = 'LOW' | 'MODERATE' | 'ELEVATED' | 'HIGH' | 'CRITICAL';
export type Role = 'ADMIN' | 'OPERATOR' | 'ANALYST' | 'VIEWER';
export type ConnectionStatus = 'CONNECTED' | 'DEGRADED' | 'OFFLINE';
export type SimStatus = 'RUNNING' | 'PAUSED' | 'STOPPED';

/** GET /api/realtime/status (Phase 4 §36). */
export interface RealtimeStatus {
  status: SimStatus;
  speed: number;
  simulation_time: number;
  clock: number;
  clock_hour: number;
  last_tick: string | null;
  tick_count: number;
  sensor_interval: number;
  enabled: boolean;
  connected_clients: number;
  data_source: string;
  seed: number;
  scenario: string | null;
  scenario_status: string | null;
}

/** `system.status` WS event payload (Phase 4 §11). */
export interface SystemStatusInfo {
  backend: boolean;
  database: boolean;
  websocket: boolean;
  simulator: SimStatus;
  ai: boolean;
  connected_clients: number;
  clock_hour: number;
  speed: number;
  risk_level: RiskLevel;
  incidents: number;
  metrics?: Metrics;
}

/** Bounded live event timeline entry (Phase 4 §47). */
export interface LiveLogEntry {
  id: number;
  ts: number;
  level: 'info' | 'warn' | 'error' | 'success';
  kind: 'control' | 'sim_status' | 'system' | 'risk';
  title: string;
  detail?: string;
}

/** One bounded live metric trend sample (Phase 4 §45). */
export interface MetricSample {
  t: number;
  occupancy_pct: number;
  energy: number;
  temperature: number;
  risk: number;
  water: number;
}

/** One bounded live sensor chart point. */
export interface LivePoint {
  t: number;
  value: number;
}

export interface User {
  id: string;
  username: string;
  email?: string;
  role: Role;
}

export interface Building {
  id: string;
  code: string;
  name: string;
  type: string;
  description: string;
  capacity: number;
  occupancy: number;
  occupancy_pct: number;
  floors: number;
  status: string;
  position: { x: number; y?: number; z: number };
  latitude?: number | null;
  longitude?: number | null;
  size: { x: number; z: number };
  height: number;
  color: string;
  has_backup_power: boolean;
  temperature: number;
  humidity: number;
  energy: number;
  smoke: number;
  air_quality: number;
  water: number;
  risk: number;
  risk_level: RiskLevel;
  sensor_health: number;
  power: boolean;
  backup_power: boolean;
  evacuation_order: boolean;
}

export interface Floor {
  id: string;
  building_id: string;
  floor_number: number;
  name: string;
  zone_count: number;
  area_sqm: number;
  is_evacuation_level: boolean;
}

export interface FloorDetail extends Floor {
  building: Building | null;
  zones: Zone[];
}

export interface Zone {
  id: string;
  building_id: string;
  name: string;
  floor: number;
  floor_id?: string | null;
  capacity: number;
  occupancy: number;
  kind: string;
  zone_type: string;
  risk_level: RiskLevel;
  width: number;
  depth: number;
  height: number;
  adjacent: string[];
  fire: number;
  smoke: number;
  temperature: number;
  status: 'NORMAL' | 'AFFECTED' | 'SMOKE' | 'FIRE';
  local_x: number;
  local_z: number;
}

export interface Sensor {
  id: string;
  sensor_code: string;
  name: string;
  type: string;
  building_id: string | null;
  zone_id: string | null;
  unit: string;
  status: 'ONLINE' | 'OFFLINE';
  x: number;
  y?: number;
  z: number;
  min_value: number | null;
  max_value: number | null;
  normal_min: number | null;
  normal_max: number | null;
  value: number;
  last_reading: number;
  baseline: number;
  healthy: boolean;
  node_id?: string | null;
  updated_at: number;
}

export interface Road {
  id: string;
  name: string;
  from_node: string;
  to_node: string;
  length: number;
  congestion: number;
  blocked: boolean;
  risk: number;
  kind: string;
}

export interface RoadNode {
  id: string;
  name: string;
  x: number;
  z: number;
  kind: string;
  is_exit?: boolean;
  exit_capacity?: number;
}

export interface Incident {
  id: string;
  incident_code?: string;
  title: string;
  kind: string;
  building_id: string | null;
  location_type?: string;
  location_id?: string | null;
  severity: string;
  status: string;
  description: string;
  risk_score: number;
  started_at: string;
  resolved_at: string | null;
}

export interface RiskFactor {
  label: string;
  contribution: number;
  /** Phase 5 — factor grouping (occupancy/environmental/anomaly/incident/infrastructure). */
  category?: string;
  weight?: number;
}

export interface RiskResult {
  score: number;
  level: RiskLevel;
  factors: RiskFactor[];
  explanation: string;
  worst_building?: string;
}

export interface Route {
  id: string;
  building_id: string;
  building_name: string;
  origin_id: string;
  exit_id: string | null;
  exit_name: string;
  node_path: string[];
  road_path: string[];
  distance: number;
  eta_s: number;
  evac_time_s: number;
  risk: number;
  status: 'SAFE' | 'WARNING' | 'BLOCKED';
  reason: string;
  occupancy: number;
}

export interface Prediction {
  entity_id: string;
  entity_type?: string;
  metric: string;
  current_value: number;
  predicted_value: number;
  horizon_min: number;
  confidence: number;
  model_name: string;
  summary: string;
  prediction_time?: string;
  // Phase 5 — model versioning & honesty metrics
  model_version?: string;
  status?: 'OK' | 'BASELINE' | 'LOW_CONFIDENCE' | 'INSUFFICIENT_DATA';
  confidence_label?: 'HIGH' | 'MEDIUM' | 'LOW' | 'N/A';
  samples?: number;
  mae?: number | null;
  rmse?: number | null;
  r2?: number | null;
  mape?: number | null;
  upper_bound?: number | null;
  trained_at?: string | null;
}

export interface Anomaly {
  id?: string;
  sensor_id: string;
  metric: string;
  location: string;
  building_id: string | null;
  zone_id?: string | null;
  value: number;
  expected: number;
  deviation_pct: number;
  z_score: number;
  score: number;
  /** Phase 5 — score band (0-100); `severity` stays the legacy LOW..CRITICAL. */
  band?: 'NORMAL' | 'LOW' | 'MODERATE' | 'HIGH' | 'CRITICAL';
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  explanation: string;
  method: string;
  // Phase 5 — layered detector detail
  anomaly_type?: string;
  detector?: string;
  reason?: string;
  confidence?: number | null;
  baseline?: string;
  data_quality?: string;
  available_samples?: number;
  minimum_required?: number;
  status?: string;
  score_raw?: number;
  rate_of_change_pct?: number;
  first_seen?: string;
  last_seen?: string;
  observations?: number;
}

/** Per-sensor AI status served by GET /api/ai/anomalies (Phase 5). */
export interface SensorAiStatus {
  status: string; // NORMAL | INSUFFICIENT_DATA | anomaly band
  score: number | null;
  type: string | null;
  detector: string | null;
  anomaly_id: string | null;
  available_samples: number;
  minimum_required: number;
}

export interface AnomaliesResponse {
  anomalies: Anomaly[];
  engine: string;
  sensor_status: Record<string, SensorAiStatus>;
  bands: Record<string, [number, number]>;
  data_quality: 'OK' | 'LIMITED' | 'INSUFFICIENT';
  score_threshold: number;
  min_samples: number;
  count?: number;
  total?: number;
}

export interface PredictionsResponse {
  predictions: Prediction[];
  count: number;
  horizons?: number[];
  engine?: string;
}

/** One bounded AI event (GET /api/ai/events timeline, Phase 5 §53). */
export interface AIEvent {
  id?: string;
  kind: 'ANOMALY' | 'PREDICTION' | 'RISK' | 'DATA' | 'SYSTEM' | string;
  title: string;
  detail?: string;
  level?: 'info' | 'warn' | 'critical' | string;
  entity_id?: string | null;
  at?: string;
  source?: string;
}

export interface AIEventsResponse {
  events: AIEvent[];
  count: number;
  ai_health: Record<string, unknown>;
}

/** Stabilised (EMA + hysteresis) published risk entry (Phase 5). */
export interface PublishedRisk extends RiskResult {
  entity_id?: string;
  raw_score?: number;
  delta?: number;
  /** numeric EMA delta from the backend (`round(delta, 2)`); direction strings tolerated */
  trend?: number | string;
  changed?: boolean;
}

export interface RiskHistoryPoint {
  score: number;
  level: RiskLevel;
}

export interface RiskFloorNode {
  floor: number;
  score: number;
  level: RiskLevel;
  zones: string[];
  worst_zone?: string | null;
}

export interface RiskZoneNode {
  id: string;
  name: string;
  floor: number;
  score: number;
  level: RiskLevel;
  factors?: RiskFactor[];
  explanation?: string;
}

export interface RiskBuildingNode {
  score: number;
  level: RiskLevel;
  factors?: RiskFactor[];
  explanation?: string;
  floors: Record<string, RiskFloorNode>;
  zones: Record<string, RiskZoneNode>;
  worst_zone?: string | null;
}

export interface RiskSensorNode {
  id: string;
  name: string;
  type: string;
  building_id: string | null;
  status: string;
  score: number;
  level: RiskLevel;
  explanation: string;
}

/** campus → building → floor → zone → sensor risk detail (Phase 5). */
export interface RiskHierarchy {
  buildings: Record<string, RiskBuildingNode>;
  sensors: Record<string, RiskSensorNode>;
  weights: { building: Record<string, number>; campus: Record<string, number> };
}

export interface RiskResponse {
  campus: RiskResult;
  buildings: Record<string, RiskResult>;
  metrics: Metrics;
  published: {
    campus: PublishedRisk | null;
    buildings: Record<string, PublishedRisk | null>;
  };
  hierarchy: RiskHierarchy | null;
  risk_history: Record<string, RiskHistoryPoint[]>;
  data_source?: string;
}

export interface Recommendation {
  id: string;
  recommendation_id?: string;
  title: string;
  priority: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  entity_id: string | null;
  action: string;
  rationale: string;
  reason?: string;
  status: 'PENDING' | 'APPLIED' | 'DISMISSED';
  payload: Record<string, unknown>;
  created_at: string;
  applied_at: string | null;
  applied_detail?: string;
}

export interface SimEvent {
  t: number;
  kind: string;
  message: string;
  data?: Record<string, unknown>;
}

export interface ActiveSim {
  id: string;
  simulation_code?: string;
  scenario: string;
  scenario_type?: string;
  target_id: string | null;
  target_type?: string;
  params: Record<string, unknown>;
  parameters?: Record<string, unknown>;
  status: 'CREATED' | 'RUNNING' | 'PAUSED' | 'AWAITING_RECOVERY' | 'RECOVERING' | 'COMPLETED' | 'RESET';
  t: number;
  duration: number;
  progress: number;
  current_step?: number;
  total_steps?: number;
  peak_risk: number;
  people_at_risk: number;
  phase: string;
  events: SimEvent[];
  recover_t: number;
  recover_duration: number;
  // Phase 6 — live metrics from the emergency engine (§46/§48)
  weighted_people?: number;
  affected_zones?: number;
  max_people_at_risk?: number;
  peak_temperature?: number;
  peak_smoke?: number;
  results?: SimulationResults | null;
  // Phase 6 simulation.tick extras (flat merge from WS)
  risk?: number;
  risk_level?: string;
  speed?: number;
  building_smoke?: number | null;
  building_temperature?: number | null;
  building_status?: string | null;
}

/** Phase 6 §48 — honest results block computed from the actual run. */
export interface SimulationResults {
  scenario: string;
  scenario_label?: string;
  target_id: string | null;
  target_name?: string | null;
  status?: string;
  peak_risk: number;
  peak_risk_level?: string;
  peak_people_at_risk?: number;
  weighted_people_at_risk?: number;
  affected_zone_count?: number;
  peak_temperature?: number;
  peak_smoke?: number;
  smoke_band?: string;
  burning_zones?: number;
  duration_s?: number;
  recovery_time_s?: number;
  events?: number;
  intensity?: number | string | null;
  intensity_label?: string | null;
  wind?: string | null;
}

export interface Metrics {
  occupancy: number;
  occupancy_pct: number;
  energy: number;
  temperature: number;
  water: number;
  risk: number;
  risk_level: RiskLevel;
  incidents: number;
  people_at_risk: number;
  anomalies: number;
  clock_hour: number;
  status: string;
  recovery_progress: number;
}

export interface Alert {
  id: string;
  level: string;
  severity?: string;
  type?: string;
  title: string;
  message: string;
  entity_id: string | null;
  created_at: string;
  acknowledged: boolean;
  is_active?: boolean;
}

export interface AnalystReport {
  source: 'llm' | 'local_fallback';
  model: string;
  what_happened: string;
  why_it_matters: string;
  likely_next: string;
  recommended_action: string;
  note?: string;
  generated_at?: number;
  // Phase 8 §26 — structured, evidence-grounded analyst result (optional so
  // legacy Phase 5 payloads still type-check)
  analysis_id?: string;
  timestamp?: string;
  mode?: string;
  situation?: AnalystSituation;
  what_is_happening?: string[];
  why?: AnalystWhyFactor[];
  affected_areas?: string[];
  predicted_effects?: AnalystPredictedEffect[];
  recommendations?: AnalystRecommendationCard[];
  route_assessment?: AnalystRouteAssessment | null;
  confidence?: AnalystConfidence;
  human_decision_required?: boolean;
  evidence?: AnalystEvidenceItem[];
  what_changed?: AnalystChangeItem[];
  provider?: string;
  status?: string;
  latency_ms?: number;
  cached?: boolean;
  simulation_id?: string;
  question?: string;
  query_answer?: string;
  context_summary?: Record<string, unknown> | null;
}

export type AnalystMode =
  | 'INCIDENT' | 'CAMPUS' | 'BUILDING' | 'ROUTE' | 'SIMULATION' | 'RECOVERY';
export type AnalystSeverity = 'LOW' | 'MODERATE' | 'ELEVATED' | 'HIGH' | 'CRITICAL';
export type AnalystPriority = 'LOW' | 'MEDIUM' | 'HIGH' | 'IMMEDIATE';
export type AnalystConfidenceLevel = 'LOW' | 'MEDIUM' | 'HIGH';
export type AnalystHealth = 'ONLINE' | 'FALLBACK' | 'DEGRADED' | 'OFFLINE';
export type AnalystDecision = 'ACCEPTED' | 'DISMISSED';

export interface AnalystSituation {
  title: string;
  summary: string;
  severity: AnalystSeverity;
  priority: AnalystPriority;
  mode: string;
}

export interface AnalystWhyFactor {
  factor: string;
  impact: string;
  evidence?: string;
  evidence_ids?: string[];
}

export interface AnalystPredictedEffect {
  effect: string;
  likelihood: string;
  time_horizon?: string;
  kind?: string;
  source?: string;
  metric?: string;
  evidence_ids?: string[];
}

export interface AnalystRouteAssessment {
  recommended_route?: string;
  route_id?: string;
  origin?: string;
  destination?: string;
  mode?: string;
  reason?: string;
  risk?: number;
  estimated_time?: number;
  status?: string;
  alternatives?: string[];
}

export interface AnalystConfidenceComponent {
  name: string;
  value: number;
  weight: number;
  contribution: number;
}

export interface AnalystConfidence {
  overall: number;
  level: AnalystConfidenceLevel;
  components: AnalystConfidenceComponent[];
  notes: string[];
}

export interface AnalystChangeItem {
  kind: string;
  message: string;
  previous: string;
  current: string;
}

export interface AnalystEvidenceItem {
  id: string;
  label: string;
  source_type: string;
  source_id?: string;
  metric?: string;
  value?: string | number | boolean | null;
  unit?: string;
  severity?: string;
  timestamp?: string | null;
  age_seconds?: number | null;
  confidence?: number | null;
  detail?: string;
}

export interface AnalystRecommendationCard {
  id: string;
  priority: number;
  category: string;
  action: string;
  reason: string;
  evidence?: string[];
  evidence_ids?: string[];
  confidence: number;
  requires_human_approval?: boolean;
}

/** Persisted recommendation row from GET /api/ai/recommendations (§21/§24). */
export interface AnalystRecommendationRow {
  recommendation_id: string;
  analysis_id: string;
  priority: number;
  category: string;
  action: string;
  reason: string;
  evidence: string[];
  evidence_ids: string[];
  confidence: number;
  requires_human_approval: boolean;
  status: 'PENDING' | 'ACCEPTED' | 'DISMISSED' | 'APPLIED' | string;
  decided_by: string;
  decided_at: string | null;
  created_at: string;
}

/** Analyst health block from GET /api/ai/status (§60). */
export interface AnalystStatus {
  status: AnalystHealth;
  llm_configured: boolean;
  model: string;
  cooldown_seconds: number;
  cooldown_remaining_s: number;
  in_flight: boolean;
  cache_size: number;
  cache_hits: number;
  runs: number;
  fallbacks: number;
  llm_errors: number;
  llm_fail_streak: number;
  fail_streak: number;
  last_run: string | null;
  last_latency_ms: number;
  last_source: string | null;
  last_error: string | null;
  current_analysis: string;
  severity: string;
  persisted_limit: number;
}

export interface Snapshot {
  clock: number;
  clock_hour: number;
  speed: number;
  sim_status?: SimStatus;
  status: string;
  recovery_progress: number;
  buildings: Building[];
  zones: Zone[];
  sensors: Sensor[];
  roads: Road[];
  nodes: RoadNode[];
  incidents: Incident[];
  risk: RiskResult;
  building_risk: Record<string, RiskResult>;
  predictions: Prediction[];
  anomalies: Anomaly[];
  recommendations: Recommendation[];
  routes: Route[];
  alerts: Alert[];
  active_sim: ActiveSim | null;
  metrics: Metrics;
  system_health: Record<string, boolean | string>;
  connected_clients: number;
  data_source?: string;
  metadata?: { name: string; generated_at: string; random_seed: number; data_source: string };
  summary?: CampusSummary;
}

export interface CampusSummary {
  buildings: number;
  floors: number;
  zones: number;
  sensors: number;
  roads: number;
  gates: number;
  exits: number;
  occupancy: number;
  occupancy_pct: number;
  risk_score: number;
  risk_level: RiskLevel;
  active_incidents: number;
  active_simulations: number;
}

export interface SensorReadingPoint {
  value: number;
  at: string;
  timestamp: string;
  quality: string;
  source: string;
}

export interface SensorHistory {
  sensor: Sensor;
  data_source: string;
  source: string;
  live: number[];
  persisted: SensorReadingPoint[];
}

export interface SimHistoryItem {
  id: string;
  simulation_code?: string;
  scenario: string;
  scenario_type?: string;
  target_id: string | null;
  target_type?: string | null;
  status: string;
  progress: number;
  current_step?: number;
  total_steps?: number;
  simulation_speed?: number;
  peak_risk: number;
  people_affected: number;
  recovery_time_s: number;
  severity: string;
  created_at: string;
  ended_at: string | null;
  params: Record<string, unknown>;
  parameters?: Record<string, unknown>;
  result: Record<string, unknown>;
  results?: Record<string, unknown>;
}

export interface BuildingDetail extends Building {
  zones: Zone[];
  sensors: Sensor[];
  risk_detail: RiskResult;
  exits: (RoadNode & { risk: number })[];
  routes: Route[];
  incidents: Incident[];
  predictions: Prediction[];
  zone_count?: number;
  sensor_count?: number;
  floor_count?: number;
}

export interface ZoneDetail extends Zone {
  building: Building | null;
  sensors: Sensor[];
  risk_detail: RiskResult;
}

// ------------------------------------------------------------------ Phase 7
// Route & Evacuation Optimization (§39-§43)

export type RouteMode = 'shortest' | 'fastest' | 'safest' | 'balanced' | 'emergency';
export type RoutePlanStatus =
  | 'RECOMMENDED' | 'ALTERNATIVE' | 'NOT_RECOMMENDED' | 'BLOCKED' | 'NO_SAFE_ROUTE';
export type RouteSafety = 'SAFE' | 'WARNING' | 'HIGH_RISK';
export type EvacuationState = 'IDLE' | 'STANDBY' | 'ACTIVE' | 'CRITICAL';
export type RoutePlanKind = 'point' | 'evacuation' | 'emergency';

/** A single computed path with full §25 metrics. */
export interface RouteMetrics {
  origin: string;
  origin_name?: string;
  destination: string | null;
  destination_name: string;
  mode: RouteMode | string;
  path: string[];
  node_path: string[];
  road_path: string[];
  distance: number;
  estimated_time: number;
  traversal_time?: number;
  queue_time?: number;
  risk_score: number;
  max_risk?: number;
  congestion_score: number;
  congestion_label: string;
  safety: RouteSafety | string;
  status: string;
  confidence?: string;
  people?: number;
  exit_capacity?: number | null;
  reason: string;
  bottlenecks: RouteBottleneck[];
}

/** Cross-mode comparison row (§9). */
export interface RouteComparisonRow {
  mode: RouteMode;
  distance: number;
  estimated_time: number;
  risk_score: number;
  congestion_score: number;
  status: string;
  safety: string;
  recommended?: boolean;
}

export interface RouteComparison {
  origin: string;
  destination: string;
  rows: RouteComparisonRow[];
  recommended_mode: RouteMode | null;
}

/** Active plan as returned by `_plan_response` (§25). */
export interface RoutePlan {
  route_id: string;
  kind: RoutePlanKind;
  mode: RouteMode;
  status: RoutePlanStatus | string;
  reason: string;
  path: string[];
  node_path: string[];
  road_path: string[];
  origin: string | null;
  destination: string | null;
  destination_name: string;
  distance: number;
  estimated_time: number;
  risk_score: number;
  congestion_score: number;
  congestion_label: string;
  safety: RouteSafety | string;
  confidence: string;
  people_at_risk: number;
  bottlenecks: RouteBottleneck[];
  simulation_id: string | null;
  route_version: number;
  created_at: string | null;
  updated_at: string | null;
  source: string;
  alternatives: RouteMetrics[];
  evacuation: BuildingEvacuationPlan | null;
  vehicle: string | null;
}

export interface RouteAlternativesResponse {
  origin: string;
  destination: string;
  mode: RouteMode;
  routes: RouteMetrics[];
  comparison: RouteComparison;
  simulation_id: string | null;
  route_version: number;
}

export interface EvacuationExitRole {
  id: string;
  name: string;
  role: 'PRIMARY' | 'SECONDARY' | 'UNAVAILABLE';
  available: boolean;
  risk?: number;
}

/** §15 building evacuation plan. */
export interface BuildingEvacuationPlan {
  building_id: string;
  building_name: string;
  status: string;
  mode: RouteMode;
  people_at_risk: number;
  occupancy: number;
  occupancy_pct: number;
  affected: boolean;
  primary_route: RouteMetrics;
  routes: RouteMetrics[];
  exits: EvacuationExitRole[];
  primary_exit: string;
  secondary_exit: string;
  estimated_evacuation_s: number;
  route_risk: number;
  route_status: string;
  has_safe_route: boolean;
  reason: string;
  simulation_id?: string | null;
  route_version?: number;
  generated_at?: string;
}

export interface EvacuationExitLoad {
  exit_id: string;
  name: string;
  people: number;
  capacity: number;
  pressure: number;
}

/** §13 structured bottleneck — no LLM output. */
export interface RouteBottleneck {
  location: string;
  location_id: string;
  kind: 'EDGE' | 'EXIT' | 'NODE';
  severity: 'LOW' | 'MEDIUM' | 'HIGH';
  estimated_people: number;
  capacity: number;
  congestion: number;
  risk: number;
  recommendation: string;
  shared_by: string[];
}

export interface EvacuationTotals {
  buildings: number;
  safe_routes: number;
  blocked_routes: number;
  bottlenecks: number;
}

/** Campus evacuation overview (`GET /api/routes/evacuation`). */
export interface EvacuationOverview {
  status: EvacuationState;
  mode: RouteMode;
  people_at_risk: number;
  critical_buildings: string[];
  blocked_buildings: string[];
  totals: EvacuationTotals;
  bottleneck_count: number;
  simulation_id: string | null;
  route_version: number;
  generated_at: string | null;
  buildings: BuildingEvacuationPlan[];
  exits: EvacuationExitLoad[];
  bottlenecks: RouteBottleneck[];
}

/** `GET /api/evacuation/status` — overview + active plan + live history. */
export interface EvacuationStatus extends Omit<EvacuationOverview,
  'buildings' | 'exits' | 'bottlenecks'> {
  active_plan: RoutePlan | null;
  route_history_recent: RouteHistoryRow[];
}

export interface RouteHistoryRow {
  route_id: string;
  kind?: string;
  mode: RouteMode | string;
  status: string;
  route_version: number;
  origin?: string | null;
  destination?: string | null;
  reason?: string;
  created_at: string;
  simulation_id?: string | null;
  distance?: number;
  estimated_time?: number;
  risk_score?: number;
  event?: string;
}

/** §16 emergency vehicle route. */
export interface EmergencyRoutePlan {
  status: 'SAFE' | 'WARNING' | 'BLOCKED' | 'NO_SAFE_ROUTE';
  reason: string;
  vehicle: string;
  vehicle_label: string;
  origin: string;
  origin_name?: string;
  destination: string;
  destination_name?: string;
  path: string[];
  node_path?: string[];
  road_path: string[];
  distance: number;
  eta_s: number;
  estimated_time?: number;
  risk_score: number;
  max_risk?: number;
  congestion_score?: number;
  blocked_roads_avoided: string[];
  access_restrictions: string[];
}

export interface EmergencyRoutesResponse {
  status: string;
  reason?: string;
  routes: EmergencyRoutePlan[];
  incident_node: string | null;
  incident_name?: string;
  simulation_id: string | null;
  generated_at: string;
  vehicles?: string[];
}

export interface RouteGraphInfo {
  nodes: Array<Record<string, unknown>>;
  edges: Array<Record<string, unknown>>;
  counts: { nodes: number; edges: number };
  static: boolean;
  mode: RouteMode;
  simulation_id: string | null;
}
