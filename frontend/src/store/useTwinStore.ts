import { create } from 'zustand';
import { api, ApiError, getToken, setToken } from '../services/api';
import { TwinSocket } from '../services/ws';
import type {
  ActiveSim, AIEvent, AnalystReport, AnalystStatus, Anomaly, BuildingDetail,
  BuildingEvacuationPlan, ConnectionStatus, EmergencyRoutePlan, EvacuationOverview,
  EvacuationStatus, Incident, LiveLogEntry, LivePoint, MetricSample, Prediction,
  PublishedRisk, RealtimeStatus, ReplayFrame, ReplayPayload, RiskLevel, RiskResult,
  Route, RouteAlternativesResponse, RouteBottleneck, RouteHistoryRow, RouteMode,
  RoutePlan, Sensor, SensorAiStatus, SensorHistory, SimEvent, SimStatus, Snapshot,
  SimHistoryItem, SystemStatusInfo, User, Zone,
} from '../types';
import { VIEW_MODE_LAYERS, type SensorFilter, type ViewMode } from '../types/twin';

export interface Toggles {
  buildings: boolean;
  roads: boolean;
  sensors: boolean;
  zones: boolean;
  labels: boolean;
  parking: boolean;
  trees: boolean;
  grid: boolean;
  heatmap: boolean;
  occupancy: boolean;
  routes: boolean;
  night: boolean;
  /** Phase 5 — RISK MODE tint (set by view mode 'risk' or the layer chip). */
  risk: boolean;
}

interface Toast {
  id: number;
  level: 'info' | 'warn' | 'error' | 'success';
  title: string;
  message: string;
}

interface TwinStore {
  token: string | null;
  user: User | null;
  authError: string | null;
  authLoading: boolean;

  connection: ConnectionStatus;
  backendOffline: boolean;
  snapshot: Snapshot | null;
  lastUpdate: number;
  health: Record<string, string> | null;

  // Phase 4 — realtime simulation state
  realtime: RealtimeStatus | null;
  systemStatus: SystemStatusInfo | null;
  liveLog: LiveLogEntry[];
  metricHistory: MetricSample[];
  sensorLiveWindow: LivePoint[];
  realtimeBusy: boolean;

  // Phase 5 — AI intelligence slice (bounded, WS-fed)
  anomalies: Anomaly[];
  sensorAiStatus: Record<string, SensorAiStatus>;
  anomalyDataQuality: 'OK' | 'LIMITED' | 'INSUFFICIENT';
  aiPredictions: Prediction[];
  aiEvents: AIEvent[];
  aiStatus: Record<string, unknown> | null;
  aiDegraded: boolean;
  aiLastUpdated: number;
  aiRefreshing: boolean;
  /** Phase 5 — stabilised (EMA+hysteresis) campus risk from /api/risk + risk.update. */
  riskPublished: PublishedRisk | null;
  /** Phase 5 — stabilised per-building risk from /api/risk.published.buildings. */
  riskPublishedBuildings: Record<string, PublishedRisk | null>;

  selectedBuildingId: string | null;
  buildingDetail: BuildingDetail | null;
  buildingLoading: boolean;
  buildingError: string | null;

  selectedFloorId: string | null;
  selectedSensorId: string | null;
  sensorHistory: SensorHistory | null;
  sensorHistoryLoading: boolean;
  sensorHistoryError: string | null;

  toggles: Toggles;
  viewMode: ViewMode;
  sensorFilter: SensorFilter;
  timeline: SimEvent[];
  analyst: AnalystReport | null;
  /** Phase 8 §60 — analyst health block (ONLINE/FALLBACK/DEGRADED/OFFLINE). */
  analystStatus: AnalystStatus | null;
  aiFallback: boolean;
  history: SimHistoryItem[];
  historyLoading: boolean;
  toast: Toast | null;
  demoOpen: boolean;
  demoStep: number;
  demoRunning: boolean;
  focusRequest: { x: number; z: number; seq: number } | null;
  cameraView: { view: 'iso' | 'top' | 'front' | 'north'; seq: number } | null;

  // Phase 7 — route & evacuation optimization (§7-§16)
  routePlan: RoutePlan | null;
  routeAlternatives: RouteAlternativesResponse | null;
  buildingEvacuation: BuildingEvacuationPlan | null;
  evacuation: EvacuationOverview | null;
  evacuationStatus: EvacuationStatus | null;
  routeBottlenecks: RouteBottleneck[];
  emergencyRoutes: EmergencyRoutePlan[];
  routeHistory: RouteHistoryRow[];
  routeLoading: boolean;
  routeError: string | null;
  routePanelOpen: boolean;

  // Phase 9 §63 — simulation replay (separate from live state)
  replay: ReplayPayload | null;
  replaySimId: string | null;
  replayT: number;
  replayPlaying: boolean;
  replaySpeed: number;
  replayLoading: boolean;
  replayError: string | null;
  /** Derived 3D view for the active replay — CampusScene renders this instead of live. */
  replaySnapshot: Snapshot | null;

  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  /** Phase 10 §11 — change own password; server revokes all sessions and
   * returns a fresh token which becomes the active session. */
  changePassword: (current_password: string, new_password: string) => Promise<void>;
  boot: () => Promise<void>;
  retryConnection: () => Promise<void>;
  setConnection: (s: ConnectionStatus) => void;
  onSocketMessage: (msg: { type: string; payload?: unknown; data?: unknown }) => void;
  realtimeAction: (action: 'start' | 'pause' | 'resume' | 'reset') => Promise<void>;
  setRealtimeSpeed: (speed: number) => Promise<void>;
  refreshRealtime: () => Promise<void>;
  selectBuilding: (id: string | null) => Promise<void>;
  selectFloor: (floorId: string | null) => void;
  selectSensor: (id: string | null) => void;
  loadSensorHistory: (id: string) => Promise<void>;
  toggle: (key: keyof Toggles) => void;
  setViewMode: (mode: ViewMode) => void;
  setSensorFilter: (f: SensorFilter) => void;
  refreshHistory: () => Promise<void>;
  refreshAnalyst: () => Promise<void>;
  refreshAi: () => Promise<void>;
  pushToast: (level: Toast['level'], title: string, message: string) => void;
  dismissToast: () => void;
  setDemo: (open: boolean) => void;
  setDemoStep: (step: number) => void;
  setDemoRunning: (running: boolean) => void;
  focusCamera: (x: number, z: number) => void;
  setCameraView: (view: 'iso' | 'top' | 'front' | 'north') => void;
  handleApiError: (err: unknown) => void;
  // Phase 7 — route & evacuation actions (§25/§26)
  refreshRouteData: () => Promise<void>;
  refreshEvacuationOverview: () => Promise<void>;
  calculateRoute: (origin: string, destination: string, mode?: RouteMode,
                   people?: number) => Promise<void>;
  loadRouteAlternatives: (origin: string, destination: string,
                          mode?: RouteMode) => Promise<void>;
  loadBuildingEvacuation: (buildingId: string, mode?: RouteMode) => Promise<void>;
  loadEmergencyRoutes: () => Promise<void>;
  refreshRouteHistory: () => Promise<void>;
  setRoutePanelOpen: (open: boolean) => void;
  // Phase 9 §63 — replay actions
  loadReplay: (simId: string) => Promise<void>;
  closeReplay: () => void;
  setReplayT: (t: number) => void;
  setReplaySpeed: (speed: number) => void;
  setReplayPlaying: (playing: boolean) => void;
  stepReplay: (dir: -1 | 1) => void;
  tickReplay: (dtSeconds: number) => void;
}

let socket: TwinSocket | null = null;
let healthTimer: number | null = null;
let toastSeq = 0;
let liveLogSeq = 0;
let lastControlAt = 0;

// bounded live buffers (Phase 4 §45/§47) — never let live data grow unbounded
const LIVE_LOG_CAP = 40;
const METRIC_HISTORY_CAP = 30;
const SENSOR_WINDOW_CAP = 120;
const METRIC_SAMPLE_MS = 1500;

// bounded AI buffers (Phase 5 §53)
const ANOMALIES_CAP = 50;
const AI_PREDICTIONS_CAP = 60;
const AI_EVENTS_CAP = 40;

function appendLiveLog(level: LiveLogEntry['level'], kind: LiveLogEntry['kind'],
                       title: string, detail?: string) {
  const entry: LiveLogEntry = { id: ++liveLogSeq, ts: Date.now(), level, kind, title, detail };
  const log = [entry, ...useTwinStore.getState().liveLog].slice(0, LIVE_LOG_CAP);
  useTwinStore.setState({ liveLog: log });
}

/** Push a bounded metric trend sample from the current snapshot metrics. */
function pushMetricSample() {
  const st = useTwinStore.getState();
  const metrics = st.snapshot?.metrics;
  if (!metrics) return;
  const now = Date.now();
  const last = st.metricHistory[st.metricHistory.length - 1];
  if (last && now - last.t < METRIC_SAMPLE_MS) return;
  const sample: MetricSample = {
    t: now,
    occupancy_pct: metrics.occupancy_pct ?? 0,
    energy: metrics.energy ?? 0,
    temperature: metrics.temperature ?? 0,
    risk: metrics.risk ?? 0,
    water: metrics.water ?? 0,
  };
  useTwinStore.setState({
    metricHistory: [...st.metricHistory, sample].slice(-METRIC_HISTORY_CAP),
  });
}

/** Append a live chart point for the selected sensor (bounded window). */
function pushSensorPoint(sensorId: string, value: number) {
  const st = useTwinStore.getState();
  if (st.selectedSensorId !== sensorId) return;
  const now = Date.now();
  const last = st.sensorLiveWindow[st.sensorLiveWindow.length - 1];
  if (last && now - last.t < 1400) return;
  useTwinStore.setState({
    sensorLiveWindow: [...st.sensorLiveWindow, { t: now, value }].slice(-SENSOR_WINDOW_CAP),
  });
}

/** 10.5 → "10:30" (sim clock hour). */
function fmtHour(hour: number | undefined | null): string {
  if (hour == null) return '—';
  const h = Math.floor(((hour % 24) + 24) % 24);
  const m = Math.floor((hour - Math.floor(hour)) * 60);
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
}

/**
 * WS `state` frames come from `state.snapshot()` which does NOT carry the
 * campus-only keys added by GET /api/campus (summary, data_source, metadata,
 * route_report). Merge instead of replace so those survive live pushes.
 */
const CAMPUS_ONLY_KEYS = ['summary', 'data_source', 'metadata', 'route_report'] as const;

/**
 * Phase 7 — build the flattened RoutePlan (§25 `_plan_response` shape) from a
 * `route.*` / `emergency_route.updated` WS payload (`_activate_plan` envelope).
 */
function planFromEvent(payload: Record<string, unknown>): RoutePlan | null {
  if (typeof payload.route_id !== 'string' || !payload.route) return null;
  const r = payload.route as Record<string, unknown>;
  const str = (v: unknown, d = '') => (typeof v === 'string' ? v : d);
  const num = (v: unknown, d = 0) => (typeof v === 'number' ? v : d);
  const arr = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string =>
    typeof x === 'string') : []);
  return {
    route_id: payload.route_id,
    kind: (str(payload.kind, 'point') as RoutePlan['kind']),
    mode: (str(payload.mode, 'balanced') as RoutePlan['mode']),
    status: str(payload.status, ''),
    reason: str(payload.reason),
    path: arr(r.path),
    node_path: arr(r.node_path),
    road_path: arr(r.road_path),
    origin: typeof payload.origin === 'string' ? payload.origin : null,
    destination: typeof payload.destination === 'string' ? payload.destination : null,
    destination_name: str(r.destination_name),
    distance: num(r.distance),
    estimated_time: num(r.estimated_time),
    risk_score: num(r.risk_score),
    congestion_score: num(r.congestion_score),
    congestion_label: str(r.congestion_label, 'LOW'),
    safety: str(r.safety, 'SAFE'),
    confidence: str(r.confidence, 'HIGH'),
    people_at_risk: num(payload.people_at_risk),
    bottlenecks: Array.isArray(r.bottlenecks) ? r.bottlenecks as RouteBottleneck[] : [],
    simulation_id: typeof payload.simulation_id === 'string' ? payload.simulation_id : null,
    route_version: num(payload.route_version, 1),
    created_at: str(payload.created_at) || null,
    updated_at: str(payload.timestamp) || null,
    source: 'ws',
    alternatives: Array.isArray(payload.alternatives)
      ? payload.alternatives as RoutePlan['alternatives'] : [],
    evacuation: null,
    vehicle: typeof payload.vehicle === 'string' ? payload.vehicle : null,
  };
}

function mergeSnapshot(prev: Snapshot | null, payload: Snapshot): Snapshot {
  if (!prev) return payload;
  const prevRec = prev as unknown as Record<string, unknown>;
  const payloadRec = payload as unknown as Record<string, unknown>;
  const merged: Record<string, unknown> = { ...prevRec, ...payloadRec };
  for (const key of CAMPUS_ONLY_KEYS) {
    if (!(key in payloadRec) && key in prevRec) {
      merged[key] = prevRec[key];
    }
  }
  return merged as unknown as Snapshot;
}

// ---- Phase 9 §63 — replay helpers ------------------------------------------
/** Risk band matching backend `state.risk_level` thresholds. */
function riskBand(score: number): RiskLevel {
  if (score <= 20) return 'LOW';
  if (score <= 40) return 'MODERATE';
  if (score <= 60) return 'ELEVATED';
  if (score <= 80) return 'HIGH';
  return 'CRITICAL';
}

/** Last frame at or before `t` (first frame as fallback for t before start). */
export function frameAt(frames: ReplayFrame[], t: number): ReplayFrame | null {
  if (!frames.length) return null;
  let best = frames[0];
  for (const f of frames) {
    if (f.t <= t + 1e-6) best = f;
    else break;
  }
  return best;
}

/**
 * Derive a render snapshot for replay time `t` from persisted frames.
 * Topology comes from the live base; dynamic fields are replaced strictly
 * from the frame (persisted events/risk/occupancy) — never synthesised.
 */
// Phase 11 — persisted event list is immutable per payload; map it once so
// per-tick snapshot rebuilds share one stable array reference.
const replayEventsCache = new WeakMap<ReplayPayload, Array<{ t: number; kind: string; message: string }>>();
function replayEvents(payload: ReplayPayload) {
  let evs = replayEventsCache.get(payload);
  if (!evs) {
    evs = payload.events.map((e) => ({ t: e.t, kind: e.kind, message: e.message }));
    replayEventsCache.set(payload, evs);
  }
  return evs;
}

function buildReplaySnapshot(base: Snapshot | null, payload: ReplayPayload,
                             t: number): Snapshot | null {
  if (!base) return null;
  const frame = frameAt(payload.frames, t);
  if (!frame) return null;

  const burning = new Set(frame.burning_zones);
  const frac = Math.max(0, Math.min(1, frame.fire_fraction));
  const zones = base.zones.map((z) => {
    if (burning.has(z.id)) {
      return { ...z, fire: Math.max(0.4, frac), smoke: Math.max(z.smoke, 1 + 5 * frac),
               status: 'FIRE' as const };
    }
    if (z.fire > 0 || z.smoke > 4 || z.status !== 'NORMAL') {
      return { ...z, fire: 0, smoke: 0, status: 'NORMAL' as const };
    }
    return z;
  });

  const campusScore = frame.risk.campus;
  const risk: RiskResult = typeof campusScore === 'number'
    ? { ...base.risk, score: campusScore, level: riskBand(campusScore) }
    : base.risk;

  const buildingRisk: Record<string, RiskResult> = { ...base.building_risk };
  for (const [entity, score] of Object.entries(frame.risk)) {
    if (entity === 'campus' || typeof score !== 'number') continue;
    const prev = buildingRisk[entity];
    buildingRisk[entity] = {
      score, level: riskBand(score),
      factors: prev?.factors ?? [],
      explanation: prev?.explanation ?? '',
    };
  }

  const sim = payload.simulation;
  const simStatuses = ['CREATED', 'RUNNING', 'PAUSED', 'AWAITING_RECOVERY',
                       'RECOVERING', 'COMPLETED', 'RESET'];
  const active: ActiveSim = {
    id: sim.id,
    simulation_code: sim.code,
    scenario: sim.scenario,
    target_id: sim.target_id,
    target_type: undefined,
    params: {},
    status: (simStatuses.includes(sim.status) ? sim.status : 'RUNNING') as ActiveSim['status'],
    t: frame.t,
    duration: payload.duration_s,
    progress: payload.duration_s > 0
      ? Math.min(100, (frame.t / payload.duration_s) * 100) : 100,
    peak_risk: sim.peak_risk,
    people_at_risk: frame.people_at_risk,
    phase: frame.last_kind.replace(/_/g, ' '),
    events: replayEvents(payload),
    recover_t: 0,
    recover_duration: sim.recovery_time_s,
  };

  const incidents: Incident[] = payload.incidents
    .filter((i) => i.start_t !== null && i.start_t <= frame.t + 1e-6
      && (i.end_t === null || i.end_t >= frame.t - 1e-6))
    .map((i) => ({
      id: i.id,
      incident_code: i.code,
      title: i.title,
      kind: i.kind,
      building_id: null,
      severity: i.severity,
      status: 'ACTIVE',
      description: '',
      risk_score: 0,
      started_at: i.started_wall ?? '',
      resolved_at: i.resolved_wall,
    }));

  const wallMs = frame.wall ? Date.parse(frame.wall) : Number.NaN;
  const wallDate = Number.isNaN(wallMs) ? null : new Date(wallMs);
  const clock_hour = wallDate
    ? wallDate.getUTCHours() + wallDate.getUTCMinutes() / 60
    : base.clock_hour;

  const occ = frame.occupancy;
  const occupancy = occ ?? base.metrics.occupancy;
  const occupancy_pct = occ !== null && base.metrics.occupancy > 0
    && base.metrics.occupancy_pct > 0
    ? (occ * base.metrics.occupancy_pct) / base.metrics.occupancy
    : base.metrics.occupancy_pct;

  const simStatus: SimStatus = frame.status === 'RUNNING' ? 'RUNNING'
    : frame.status === 'PAUSED' ? 'PAUSED' : 'STOPPED';

  return {
    ...base,
    clock_hour,
    sim_status: simStatus,
    status: frame.status,
    zones,
    incidents,
    risk,
    building_risk: buildingRisk,
    metrics: {
      ...base.metrics,
      occupancy,
      occupancy_pct,
      risk: risk.score,
      risk_level: risk.level,
      incidents: incidents.length,
      people_at_risk: frame.people_at_risk,
      clock_hour,
      status: frame.status,
    },
    active_sim: active,
  };
}

export const useTwinStore = create<TwinStore>((set, get) => ({
  token: getToken(),
  user: null,
  authError: null,
  authLoading: false,

  connection: 'OFFLINE',
  backendOffline: false,
  snapshot: null,
  lastUpdate: 0,
  health: null,

  realtime: null,
  systemStatus: null,
  liveLog: [],
  metricHistory: [],
  sensorLiveWindow: [],
  realtimeBusy: false,

  anomalies: [],
  sensorAiStatus: {},
  anomalyDataQuality: 'OK',
  aiPredictions: [],
  aiEvents: [],
  aiStatus: null,
  aiDegraded: false,
  aiLastUpdated: 0,
  aiRefreshing: false,
  riskPublished: null,
  riskPublishedBuildings: {},

  selectedBuildingId: null,
  buildingDetail: null,
  buildingLoading: false,
  buildingError: null,

  selectedFloorId: null,
  selectedSensorId: null,
  sensorHistory: null,
  sensorHistoryLoading: false,
  sensorHistoryError: null,

  toggles: {
    buildings: true, roads: true, sensors: true, zones: false, labels: true,
    parking: true, trees: true, grid: true, heatmap: false,
    occupancy: true, routes: true, night: false, risk: false,
  },
  viewMode: 'overview',
  sensorFilter: 'all',
  timeline: [],
  analyst: null,
  analystStatus: null,
  aiFallback: false,
  history: [],
  historyLoading: false,
  toast: null,
  demoOpen: false,
  demoStep: 0,
  demoRunning: false,
  focusRequest: null,
  cameraView: null,

  routePlan: null,
  routeAlternatives: null,
  buildingEvacuation: null,
  evacuation: null,
  evacuationStatus: null,
  routeBottlenecks: [],
  emergencyRoutes: [],
  routeHistory: [],
  routeLoading: false,
  routeError: null,
  routePanelOpen: false,

  replay: null,
  replaySimId: null,
  replayT: 0,
  replayPlaying: false,
  replaySpeed: 1,
  replayLoading: false,
  replayError: null,
  replaySnapshot: null,

  async login(username, password) {
    set({ authLoading: true, authError: null });
    try {
      const res = await api.login(username, password);
      setToken(res.access_token);
      set({ token: res.access_token, user: res.user, authLoading: false });
    } catch (err) {
      set({ authLoading: false, authError: err instanceof ApiError ? err.message : 'Login failed' });
      throw err;
    }
  },

  logout() {
    // Best-effort server-side revocation of the presented token (Phase 10 §5);
    // local state is cleared regardless so a failed call cannot trap the user.
    if (get().token) void api.logout().catch(() => { /* already invalid */ });
    setToken(null);
    socket?.disconnect();
    socket = null;
    if (healthTimer) { window.clearInterval(healthTimer); healthTimer = null; }
    set({
      token: null, user: null, snapshot: null, connection: 'OFFLINE', timeline: [],
      analyst: null, analystStatus: null, realtime: null, systemStatus: null, liveLog: [],
      metricHistory: [], sensorLiveWindow: [],
      anomalies: [], sensorAiStatus: {}, anomalyDataQuality: 'OK',
      aiPredictions: [], aiEvents: [], aiStatus: null, aiDegraded: false,
      aiLastUpdated: 0, riskPublished: null, riskPublishedBuildings: {},
    });
  },

  async changePassword(current_password, new_password) {
    const res = await api.changePassword(current_password, new_password);
    setToken(res.access_token);
    // Old tokens are revoked server-side — drop the socket so the next boot()
    // reconnects with the fresh token (BootGate reacts to the token change).
    socket?.disconnect();
    socket = null;
    set({ token: res.access_token });
  },

  async boot() {
    const state = useTwinStore.getState();
    if (!state.token) return;

    if (!socket) {
      socket = new TwinSocket(
        (status) => set({ connection: status }),
        (msg) => get().onSocketMessage(msg),
      );
    }
    socket.connect();

    const pollHealth = async () => {
      try {
        const h = await api.health();
        set({ health: h, backendOffline: false });
      } catch {
        set({ backendOffline: true });
      }
    };
    await pollHealth();
    if (!healthTimer) healthTimer = window.setInterval(pollHealth, 10000);

    // Phase 10 — hydrate the authoritative profile (role can change server-side)
    try {
      const me = await api.me();
      set({ user: me });
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) return; // session dead
    }

    try {
      const [campus, hist, rt] = await Promise.all([
        api.campus().catch(() => null),
        api.simulations().catch(() => null),
        api.realtimeStatus().catch(() => null),
      ]);
      if (campus) set({ snapshot: mergeSnapshot(get().snapshot, campus), lastUpdate: Date.now() });
      if (hist) set({ history: hist.history });
      if (rt) set({ realtime: rt });
      pushMetricSample();
      void get().refreshAnalyst();
      void get().refreshAi();
      void get().refreshRouteData();   // Phase 7 — seed evacuation + active plan
    } catch (err) {
      get().handleApiError(err);
    }
  },

  async retryConnection() {
    set({ backendOffline: false });
    socket?.disconnect();
    socket = null;
    await get().boot();
  },

  setConnection(s) { set({ connection: s }); },

  onSocketMessage(msg) {
    const data = (msg.data ?? msg.payload) as Record<string, unknown> | undefined;

    if (msg.type === 'state') {
      const payload = msg.payload as Snapshot;
      const prevRisk = get().snapshot?.metrics?.risk_level;
      set({
        snapshot: mergeSnapshot(get().snapshot, payload),
        lastUpdate: Date.now(),
        backendOffline: false,
      });
      pushMetricSample();
      const sensor = payload.sensors?.find((s) => s.id === get().selectedSensorId);
      if (sensor) pushSensorPoint(sensor.id, sensor.value);
      const riskLevel = payload.metrics?.risk_level;
      if (prevRisk && riskLevel && riskLevel !== prevRisk) {
        appendLiveLog(riskLevel === 'LOW' ? 'success' : 'warn', 'risk',
          `Campus risk → ${riskLevel}`, `Score ${payload.metrics?.risk ?? '—'}`);
      }
      return;
    }
    if (msg.type === 'simulation') {
      const sim = msg.payload as ActiveSim;
      const snap = get().snapshot;
      if (snap) set({ snapshot: { ...snap, active_sim: sim } });
      return;
    }
    if (msg.type === 'event') {
      const ev = msg.payload as SimEvent;
      const timeline = [ev, ...get().timeline].slice(0, 120);
      set({ timeline });
      if (ev.kind === 'response_recommended' || ev.kind === 'overloaded' || ev.kind === 'completed') {
        get().pushToast(ev.kind === 'completed' ? 'success' : 'warn', ev.kind.replace(/_/g, ' ').toUpperCase(), ev.message);
      }
      return;
    }
    if (msg.type === 'analyst') {
      const report = msg.payload as AnalystReport;
      set({ analyst: report, aiFallback: report.source === 'local_fallback' });
      return;
    }

    // Phase 8 §58 — typed analyst.* events (versioned envelope carries `data`)
    if (msg.type === 'analyst.analysis_completed' || msg.type === 'analyst.analysis_updated') {
      const report = data as AnalystReport | undefined;
      if (report?.analysis_id && report.source) {
        set({ analyst: report, aiFallback: report.source === 'local_fallback' });
      }
      return;
    }

    // ---- Phase 4 typed live events (versioned envelopes carry `data`) ----
    if (msg.type === 'sensor.batch_update') {
      const payload = data as { sensors?: Array<Pick<Sensor, 'id' | 'value' | 'status' | 'healthy' | 'updated_at'>>;
                                clock?: number; clock_hour?: number } | undefined;
      if (!payload?.sensors?.length) return;
      const snap = get().snapshot;
      if (snap) {
        const byId = new Map(payload.sensors.map((s) => [s.id, s]));
        const sensors = snap.sensors.map((s) => {
          const upd = byId.get(s.id);
          return upd
            ? { ...s, value: upd.value, last_reading: upd.value, status: upd.status, healthy: upd.healthy, updated_at: upd.updated_at }
            : s;
        });
        set({
          snapshot: {
            ...snap, sensors,
            ...(payload.clock != null ? { clock: payload.clock } : {}),
            ...(payload.clock_hour != null ? { clock_hour: payload.clock_hour } : {}),
          },
          lastUpdate: Date.now(),
          backendOffline: false,
        });
      }
      for (const s of payload.sensors) pushSensorPoint(s.id, s.value);
      return;
    }

    if (msg.type === 'occupancy.update') {
      const payload = data as { occupancy?: number; occupancy_pct?: number } | undefined;
      if (!payload || payload.occupancy == null) return;
      const snap = get().snapshot;
      if (snap?.metrics) {
        set({
          snapshot: {
            ...snap,
            metrics: {
              ...snap.metrics,
              occupancy: payload.occupancy as number,
              occupancy_pct: payload.occupancy_pct ?? snap.metrics.occupancy_pct,
            },
          },
          lastUpdate: Date.now(),
        });
      }
      pushMetricSample();
      return;
    }

    if (msg.type === 'building.update') {
      const payload = data as { buildings?: Array<Partial<BuildingDetail> & { id: string }> } | undefined;
      if (!payload?.buildings?.length) return;
      const snap = get().snapshot;
      if (snap) {
        const byId = new Map(payload.buildings.map((b) => [b.id, b]));
        set({
          snapshot: {
            ...snap,
            buildings: snap.buildings.map((b) => {
              const upd = byId.get(b.id);
              return upd ? ({ ...b, ...upd } as BuildingDetail) : b;
            }),
          },
          lastUpdate: Date.now(),
          backendOffline: false,
        });
      }
      return;
    }

    if (msg.type === 'simulation.status') {
      const payload = data as RealtimeStatus | undefined;
      if (!payload?.status) return;
      const prev = get().realtime;
      set({ realtime: payload, lastUpdate: Date.now() });
      const snap = get().snapshot;
      if (snap) {
        set({
          snapshot: {
            ...snap,
            sim_status: payload.status,
            speed: payload.speed,
            clock: payload.clock,
            clock_hour: payload.clock_hour,
          },
        });
      }
      // control actions already log locally — only log remote/periodic changes
      if (prev && prev.status !== payload.status && Date.now() - lastControlAt > 4000) {
        const label = payload.status === 'RUNNING' ? 'resumed'
          : payload.status === 'PAUSED' ? 'paused' : 'stopped';
        appendLiveLog(payload.status === 'RUNNING' ? 'info' : 'warn', 'sim_status',
          `Simulator ${label}`, `Clock ${fmtHour(payload.clock_hour)} · ${payload.speed}x`);
      }
      return;
    }

    if (msg.type === 'system.status') {
      const payload = data as SystemStatusInfo | undefined;
      if (!payload) return;
      const prev = get().systemStatus;
      set({ systemStatus: payload, lastUpdate: Date.now() });
      if (prev) {
        if (prev.database && !payload.database) {
          appendLiveLog('error', 'system', 'Database unreachable', 'Readings are not being persisted.');
        } else if (!prev.websocket && payload.websocket) {
          appendLiveLog('info', 'system', 'WebSocket streaming enabled');
        } else if (prev.backend && !payload.backend) {
          appendLiveLog('error', 'system', 'Backend health degraded');
        }
      }
      return;
    }

    // ---- Phase 5 AI cycle events (scheduler fan-out every AI interval) ----
    if (msg.type === 'ai.anomaly') {
      const payload = data as { anomalies?: Anomaly[]; count?: number; new?: string[];
                                data_quality?: 'OK' | 'LIMITED' | 'INSUFFICIENT';
                                sensor_status?: Record<string, SensorAiStatus>;
                                clock?: number } | undefined;
      if (!payload) return;
      const anomalies = (payload.anomalies ?? []).slice(0, ANOMALIES_CAP);
      const newIds = payload.new ?? [];
      set({
        anomalies,
        sensorAiStatus: payload.sensor_status ?? get().sensorAiStatus,
        anomalyDataQuality: payload.data_quality ?? get().anomalyDataQuality,
        aiLastUpdated: Date.now(),
      });
      const fresh = newIds.length
        ? anomalies.filter((a) => a.id != null && newIds.includes(a.id))
        : [];
      if (fresh.length) {
        const first = fresh[0];
        appendLiveLog('warn', 'system',
          `${fresh.length} new anomal${fresh.length > 1 ? 'ies' : 'y'} detected`,
          `${first.location} · ${first.metric} · score ${first.score}`);
      }
      return;
    }

    if (msg.type === 'ai.prediction') {
      const payload = data as { predictions?: Prediction[]; count?: number;
                                horizons?: number[]; clock?: number } | undefined;
      if (!payload?.predictions) return;
      set({
        aiPredictions: payload.predictions.slice(0, AI_PREDICTIONS_CAP),
        aiLastUpdated: Date.now(),
      });
      return;
    }

    if (msg.type === 'risk.update') {
      const payload = data as { campus?: PublishedRisk;
                                buildings?: Record<string, PublishedRisk>;
                                raw_level?: RiskLevel; clock?: number } | undefined;
      const campus = payload?.campus;
      if (!campus?.level) return;
      const snap = get().snapshot;
      const prevLevel = snap?.metrics?.risk_level;
      if (snap) {
        const buildings = snap.buildings.map((b) => {
          const pub = payload!.buildings?.[b.id];
          return pub?.score != null
            ? { ...b, risk: pub.score, risk_level: pub.level ?? b.risk_level }
            : b;
        });
        const buildingRisk = { ...snap.building_risk };
        for (const [id, pub] of Object.entries(payload!.buildings ?? {})) {
          if (pub?.score == null) continue;
          const prev = buildingRisk[id];
          buildingRisk[id] = prev
            ? { ...prev, score: pub.score, level: pub.level ?? prev.level }
            : { score: pub.score, level: pub.level ?? 'LOW',
                factors: pub.factors ?? [], explanation: pub.explanation ?? '' };
        }
        set({
          snapshot: {
            ...snap, buildings, building_risk: buildingRisk,
            metrics: {
              ...snap.metrics,
              risk: campus.score ?? snap.metrics.risk,
              risk_level: campus.level ?? snap.metrics.risk_level,
            },
          },
          lastUpdate: Date.now(),
          backendOffline: false,
        });
      }
      set({
        riskPublished: campus,
        ...(payload?.buildings ? { riskPublishedBuildings: payload.buildings } : {}),
      });
      if (prevLevel && campus.level !== prevLevel) {
        appendLiveLog(campus.level === 'LOW' ? 'success' : 'warn', 'risk',
          `Campus risk → ${campus.level}`,
          `Published score ${campus.score ?? '—'} (smoothed) · raw ${payload?.raw_level ?? '—'}`);
      }
      return;
    }

    // ---- Phase 6 emergency simulation events (§27/§28) ----
    if (msg.type === 'simulation.tick') {
      const payload = data as Partial<ActiveSim> | undefined;
      if (!payload?.id) return;
      const snap = get().snapshot;
      if (snap) {
        // Phase 11 — mirror the live event list with a bounded window
        // (server keeps the full history; the client only renders the tail).
        set({
          snapshot: {
            ...snap,
            active_sim: { ...payload, events: (payload.events ?? []).slice(-120) } as ActiveSim,
          },
          lastUpdate: Date.now(),
        });
      }
      return;
    }

    if (msg.type === 'simulation.zone_update') {
      const payload = data as { changed?: Array<Pick<Zone, 'id' | 'status'> & Partial<Zone>>;
                                count?: number; clock?: number } | undefined;
      if (!payload?.changed?.length) return;
      const snap = get().snapshot;
      if (snap) {
        const byId = new Map(payload.changed.map((z) => [z.id, z]));
        set({
          snapshot: {
            ...snap,
            zones: snap.zones.map((z) => {
              const upd = byId.get(z.id);
              return upd ? { ...z, ...upd, status: upd.status ?? z.status } as Zone : z;
            }),
          },
          lastUpdate: Date.now(),
        });
      }
      return;
    }

    if (msg.type === 'simulation.risk_update') {
      const payload = data as { simulation_id?: string; risk?: number; level?: string;
                                target_id?: string | null; target_risk?: number } | undefined;
      if (payload?.risk == null) return;
      const snap = get().snapshot;
      if (snap?.active_sim) {
        set({ snapshot: { ...snap, active_sim: { ...snap.active_sim, risk: payload.risk, risk_level: payload.level ?? snap.active_sim.risk_level } } });
      }
      if (payload.target_id && payload.target_risk != null) {
        const s2 = get().snapshot;
        if (s2) {
          const lvl = (payload.level ?? 'LOW') as RiskLevel;
          const prev = s2.building_risk[payload.target_id];
          set({
            snapshot: {
              ...s2,
              building_risk: {
                ...s2.building_risk,
                [payload.target_id]: prev
                  ? { ...prev, score: payload.target_risk }
                  : { score: payload.target_risk, level: lvl, factors: [], explanation: '' },
              },
            },
          });
        }
      }
      return;
    }

    if (msg.type.startsWith('simulation.') && msg.type !== 'simulation.tick'
        && msg.type !== 'simulation.zone_update' && msg.type !== 'simulation.risk_update'
        && msg.type !== 'simulation.status') {
      // Lifecycle events: created/started/paused/resumed/reset/recovery_*/completed
      const payload = data as (Partial<ActiveSim> & { clock?: number; recovery_progress?: number }) | undefined;
      if (!payload?.id) return;
      const sim = payload as ActiveSim;
      const snap = get().snapshot;
      if (snap) set({ snapshot: { ...snap, active_sim: sim }, lastUpdate: Date.now() });
      if (payload.recovery_progress != null) {
        const s = get().snapshot;
        if (s) set({ snapshot: { ...s, recovery_progress: payload.recovery_progress } });
      }
      const toastByType: Record<string, ['success' | 'warn', string]> = {
        'simulation.started': ['success', 'SIMULATION STARTED'],
        'simulation.paused': ['warn', 'SIMULATION PAUSED'],
        'simulation.resumed': ['success', 'SIMULATION RESUMED'],
        'simulation.completed': ['success', 'SIMULATION COMPLETE'],
        'simulation.recovered': ['success', 'RECOVERY COMPLETE'],
        'simulation.reset': ['warn', 'SIMULATION RESET'],
        'simulation.recovery_started': ['warn', 'RECOVERY IN PROGRESS'],
      };
      const toast = toastByType[msg.type];
      if (toast) {
        get().pushToast(toast[0], toast[1],
          `${String(sim.scenario ?? '').toUpperCase()} · ${sim.target_id ?? 'campus'}`);
      }
      appendLiveLog(msg.type === 'simulation.reset' || msg.type === 'simulation.paused' ? 'warn' : 'info',
        'sim_status', msg.type.replace('simulation.', '').replace(/_/g, ' '),
        `${String(sim.scenario ?? '').toUpperCase()} · ${sim.target_id ?? ''}`);
      if (msg.type === 'simulation.completed' || msg.type === 'simulation.reset'
          || msg.type === 'simulation.recovered') {
        void get().refreshHistory();
      }
      return;
    }

    // ---- Phase 7 route & evacuation events (§26) ----
    if (msg.type.startsWith('route.') || msg.type.startsWith('evacuation.')
        || msg.type.startsWith('bottleneck.') || msg.type.startsWith('emergency_route.')) {
      const payload = data as Record<string, unknown> | undefined;
      if (!payload) return;

      if (msg.type === 'route.calculated' || msg.type === 'route.updated'
          || msg.type === 'route.recalculated' || msg.type === 'emergency_route.updated') {
        const plan = planFromEvent(payload);
        if (plan) {
          const hist: RouteHistoryRow = {
            route_id: plan.route_id, kind: plan.kind, mode: plan.mode,
            status: plan.status, route_version: plan.route_version,
            origin: plan.origin, destination: plan.destination,
            reason: plan.reason, created_at: plan.updated_at ?? new Date().toISOString(),
            simulation_id: plan.simulation_id, distance: plan.distance,
            estimated_time: plan.estimated_time, risk_score: plan.risk_score,
            event: msg.type,
          };
          set({
            routePlan: plan,
            routeHistory: [hist, ...get().routeHistory].slice(0, 40),
            routeError: null,
            lastUpdate: Date.now(),
          });
        }
        appendLiveLog('info', 'risk', msg.type.replace(/[._]/g, ' '),
          String(payload.route_id ?? ''));
        return;
      }

      if (msg.type === 'route.invalidated') {
        const reason = String(payload.reason ?? 'environment changed');
        set({ routeError: null, lastUpdate: Date.now() });
        get().pushToast('warn', 'ROUTE INVALIDATED', reason);
        appendLiveLog('warn', 'risk', 'route invalidated', reason);
        return;
      }

      if (msg.type.startsWith('evacuation.')) {
        const status = payload.status as EvacuationStatus['status'] | undefined;
        const prevEv = get().evacuation;
        if (status) {
          set({
            evacuation: {
              ...(prevEv ?? {} as EvacuationOverview),
              status,
              people_at_risk: Number(payload.people_at_risk ?? prevEv?.people_at_risk ?? 0),
              critical_buildings: (payload.critical_buildings as string[] | undefined)
                ?? prevEv?.critical_buildings ?? [],
            } as EvacuationOverview,
            lastUpdate: Date.now(),
          });
        }
        if (msg.type === 'evacuation.started') {
          if (!get().toggles.routes) get().toggle('routes');   // show the response
          get().pushToast('warn', 'EVACUATION ACTIVE',
            `${String(payload.people_at_risk ?? 0)} people at risk`);
          appendLiveLog('warn', 'risk', 'evacuation started',
            `status ${String(status ?? '')}`);
        } else if (msg.type === 'evacuation.completed') {
          get().pushToast('success', 'EVACUATION CLEARED',
            String(payload.reason ?? 'risk returned to safe levels'));
          appendLiveLog('info', 'risk', 'evacuation cleared', String(status ?? ''));
        } else {
          appendLiveLog('warn', 'risk', 'evacuation updated', String(status ?? ''));
        }
        void get().refreshEvacuationOverview();
        return;
      }

      if (msg.type === 'bottleneck.detected') {
        const bn = payload.bottleneck as RouteBottleneck | undefined;
        if (bn?.location_id) {
          set({
            routeBottlenecks: [bn, ...get().routeBottlenecks
              .filter((b) => b.location_id !== bn.location_id)].slice(0, 20),
          });
          get().pushToast('warn', `BOTTLENECK · ${bn.severity}`,
            `${bn.location} — ${bn.recommendation}`);
          appendLiveLog('warn', 'risk', 'bottleneck detected', bn.location);
        }
        return;
      }

      if (msg.type === 'bottleneck.cleared') {
        const loc = String(payload.location_id ?? '');
        set({ routeBottlenecks: get().routeBottlenecks.filter((b) => b.location_id !== loc) });
        appendLiveLog('info', 'risk', 'bottleneck cleared', loc);
        return;
      }
    }
  },

  async selectBuilding(id) {
    if (!id) {
      set({
        selectedBuildingId: null, buildingDetail: null, buildingError: null,
        selectedFloorId: null, selectedSensorId: null, sensorHistory: null,
      });
      return;
    }
    if (id !== get().selectedBuildingId) {
      set({ selectedFloorId: null, selectedSensorId: null, sensorHistory: null, sensorHistoryError: null });
    }
    set({ selectedBuildingId: id, buildingLoading: true, buildingError: null });
    try {
      const detail = await api.building(id);
      set({ buildingDetail: detail, buildingLoading: false });
    } catch (err) {
      set({
        buildingLoading: false,
        buildingError: err instanceof ApiError ? err.message : 'Failed to load building',
      });
      get().handleApiError(err);
    }
  },

  selectFloor(floorId) {
    set({ selectedFloorId: floorId, selectedSensorId: null, sensorHistory: null, sensorHistoryError: null });
  },

  selectSensor(id) {
    if (!id) {
      set({ selectedSensorId: null, sensorHistory: null, sensorHistoryLoading: false, sensorHistoryError: null, sensorLiveWindow: [] });
      return;
    }
    set({ selectedSensorId: id, sensorHistory: null, sensorHistoryError: null, sensorLiveWindow: [] });
    void get().loadSensorHistory(id);
  },

  async loadSensorHistory(id) {
    set({ sensorHistoryLoading: true, sensorHistoryError: null });
    try {
      const history = await api.sensorHistory(id, { limit: 288 });
      if (get().selectedSensorId === id) set({ sensorHistory: history, sensorHistoryLoading: false });
    } catch (err) {
      if (get().selectedSensorId === id) {
        set({
          sensorHistoryLoading: false,
          sensorHistoryError: err instanceof ApiError ? err.message : 'Failed to load history',
        });
      }
    }
  },

  toggle(key) {
    set({ toggles: { ...get().toggles, [key]: !get().toggles[key] } });
  },

  setViewMode(mode) {
    set({
      viewMode: mode,
      toggles: { ...get().toggles, ...VIEW_MODE_LAYERS[mode] },
    });
  },

  setSensorFilter(f) {
    set({ sensorFilter: f });
  },

  async refreshHistory() {
    set({ historyLoading: true });
    try {
      const res = await api.simulations();
      set({ history: res.history, historyLoading: false });
    } catch (err) {
      set({ historyLoading: false });
      get().handleApiError(err);
    }
  },

  async refreshAnalyst() {
    try {
      const [report, statusRes] = await Promise.all([
        api.analyst(),
        api.analystStatus().catch(() => null),
      ]);
      set({
        analyst: report,
        analystStatus: statusRes?.analyst ?? null,
        aiFallback: report.source === 'local_fallback',
      });
    } catch (err) {
      set({ aiFallback: true });
      get().handleApiError(err);
    }
  },

  async refreshAi() {
    if (get().aiRefreshing) return;
    set({ aiRefreshing: true });
    try {
      const [a, p, e, s, r] = await Promise.all([
        api.anomalies({ limit: ANOMALIES_CAP }).catch(() => null),
        api.aiPredictions({ limit: AI_PREDICTIONS_CAP }).catch(() => null),
        api.aiEvents(AI_EVENTS_CAP).catch(() => null),
        api.aiStatus().catch(() => null),
        api.risk().catch(() => null),
      ]);
      set({
        ...(a ? {
          anomalies: a.anomalies.slice(0, ANOMALIES_CAP),
          sensorAiStatus: a.sensor_status ?? {},
          anomalyDataQuality: a.data_quality,
        } : {}),
        ...(p ? { aiPredictions: p.predictions.slice(0, AI_PREDICTIONS_CAP) } : {}),
        ...(e ? { aiEvents: e.events.slice(0, AI_EVENTS_CAP) } : {}),
        ...(s ? { aiStatus: s } : {}),
        // health unknown (status unreachable) → honest degraded state
        aiDegraded: s ? s.degraded === true : true,
        ...(r?.published?.campus ? { riskPublished: r.published.campus } : {}),
        ...(r?.published?.buildings ? { riskPublishedBuildings: r.published.buildings } : {}),
        aiLastUpdated: Date.now(),
        aiRefreshing: false,
      });
    } catch {
      // silent: AI slice shows degraded state instead of toasting every poll
      set({ aiRefreshing: false, aiDegraded: true });
    }
  },

  async refreshRealtime() {
    try {
      const status = await api.realtimeStatus();
      set({ realtime: status });
    } catch {
      /* status panel falls back to snapshot/live events */
    }
  },

  // ---- Phase 7 route & evacuation actions (§17/§25) ----
  async refreshRouteData() {
    set({ routeLoading: true, routeError: null });
    try {
      const [overview, status, history, emergency] = await Promise.all([
        api.routesEvacuation().catch(() => null),
        api.evacuationStatus().catch(() => null),
        api.routeHistory(20).catch(() => null),
        api.emergencyResponseRoutes().catch(() => null),
      ]);
      set({
        ...(overview ? {
          evacuation: overview,
          routeBottlenecks: overview.bottlenecks.slice(0, 20),
        } : {}),
        ...(status ? {
          evacuationStatus: status,
          routePlan: status.active_plan ?? get().routePlan,
          routeHistory: status.route_history_recent?.length
            ? status.route_history_recent : get().routeHistory,
        } : {}),
        ...(history ? { routeHistory: history.history.slice(0, 40) } : {}),
        ...(emergency ? { emergencyRoutes: emergency.routes } : {}),
        routeLoading: false,
      });
    } catch (err) {
      set({ routeLoading: false, routeError: err instanceof ApiError ? err.message : 'Route data failed' });
    }
  },

  async refreshEvacuationOverview() {
    try {
      const overview = await api.routesEvacuation();
      set({
        evacuation: overview,
        routeBottlenecks: overview.bottlenecks.slice(0, 20),
      });
    } catch { /* overview keeps last known state */ }
  },

  async calculateRoute(origin, destination, mode = 'balanced', people) {
    set({ routeLoading: true, routeError: null });
    try {
      const plan = await api.routeCalculate({ origin, destination, mode, people });
      const row: RouteHistoryRow = {
        route_id: plan.route_id, kind: plan.kind, mode: plan.mode,
        status: plan.status, route_version: plan.route_version,
        origin: plan.origin, destination: plan.destination,
        reason: plan.reason, created_at: plan.created_at ?? new Date().toISOString(),
        simulation_id: plan.simulation_id, distance: plan.distance,
        estimated_time: plan.estimated_time, risk_score: plan.risk_score,
        event: 'calculated',
      };
      set({
        routePlan: plan,
        routeAlternatives: null,
        routeLoading: false,
        routeHistory: [row, ...get().routeHistory].slice(0, 40),
      });
      if (!get().toggles.routes) get().toggle('routes');
    } catch (err) {
      set({
        routeLoading: false,
        routeError: err instanceof ApiError ? err.message : 'Route calculation failed',
      });
      get().handleApiError(err);
    }
  },

  async loadRouteAlternatives(origin, destination, mode = 'balanced') {
    set({ routeLoading: true, routeError: null });
    try {
      const data = await api.routeAlternatives(origin, destination, mode);
      set({ routeAlternatives: data, routeLoading: false });
    } catch (err) {
      set({
        routeLoading: false,
        routeError: err instanceof ApiError ? err.message : 'Alternatives failed',
      });
    }
  },

  async loadBuildingEvacuation(buildingId, mode) {
    set({ routeLoading: true, routeError: null });
    try {
      const plan = await api.evacuationBuilding(buildingId, mode);
      set({ buildingEvacuation: plan, routeLoading: false });
      if (!get().toggles.routes) get().toggle('routes');
      void get().refreshEvacuationOverview();
    } catch (err) {
      set({
        routeLoading: false,
        routeError: err instanceof ApiError ? err.message : 'Evacuation plan failed',
      });
      get().handleApiError(err);
    }
  },

  async loadEmergencyRoutes() {
    try {
      const data = await api.emergencyResponseRoutes();
      set({ emergencyRoutes: data.routes });
    } catch { /* panel keeps last known routes */ }
  },

  async refreshRouteHistory() {
    try {
      const data = await api.routeHistory(40);
      set({ routeHistory: data.history.slice(0, 40) });
    } catch { /* history list keeps last known rows */ }
  },

  setRoutePanelOpen(open) {
    set({ routePanelOpen: open });
  },

  // ---- Phase 9 §63 — simulation replay ----
  async loadReplay(simId) {
    set({ replayLoading: true, replayError: null, replayPlaying: false });
    try {
      const payload = await api.replay(simId);
      set({
        replay: payload,
        replaySimId: simId,
        replayT: 0,
        replayLoading: false,
        replaySnapshot: buildReplaySnapshot(get().snapshot, payload, 0),
      });
    } catch (err) {
      set({
        replayLoading: false,
        replayError: err instanceof ApiError ? err.message : 'Failed to load replay',
        replay: null,
        replaySimId: null,
        replaySnapshot: null,
      });
    }
  },

  closeReplay() {
    set({
      replay: null,
      replaySimId: null,
      replayT: 0,
      replayPlaying: false,
      replayError: null,
      replayLoading: false,
      replaySnapshot: null,
    });
  },

  setReplayT(t) {
    const payload = get().replay;
    if (!payload) return;
    const clamped = Math.max(0, Math.min(payload.duration_s, t));
    set({
      replayT: clamped,
      replaySnapshot: buildReplaySnapshot(get().snapshot, payload, clamped),
    });
  },

  setReplaySpeed(speed) {
    set({ replaySpeed: speed });
  },

  setReplayPlaying(playing) {
    const payload = get().replay;
    if (!payload) {
      set({ replayPlaying: false });
      return;
    }
    // pressing PLAY at the end rewinds to the start
    const atEnd = get().replayT >= payload.duration_s - 1e-6;
    const t = playing && atEnd ? 0 : get().replayT;
    set({
      replayPlaying: playing,
      replayT: t,
      replaySnapshot: buildReplaySnapshot(get().snapshot, payload, t),
    });
  },

  stepReplay(dir) {
    const payload = get().replay;
    if (!payload) return;
    const step = Math.max(payload.frame_step_s, 1);
    set({ replayPlaying: false });
    get().setReplayT(get().replayT + dir * step);
  },

  tickReplay(dt) {
    const st = get();
    const payload = st.replay;
    if (!st.replayPlaying || !payload || dt <= 0) return;
    const next = st.replayT + dt * st.replaySpeed;
    if (next >= payload.duration_s) {
      set({
        replayT: payload.duration_s,
        replayPlaying: false,
        replaySnapshot: buildReplaySnapshot(st.snapshot, payload, payload.duration_s),
      });
      return;
    }
    // Phase 11 — frame-rate ticks land between persisted frames (1-2s apart);
    // only rebuild the derived snapshot when the underlying frame changes.
    const prevFrame = frameAt(payload.frames, st.replayT);
    const nextFrame = frameAt(payload.frames, next);
    if (st.replaySnapshot && prevFrame && nextFrame && nextFrame === prevFrame) {
      set({ replayT: next });
      return;
    }
    set({
      replayT: next,
      replaySnapshot: buildReplaySnapshot(st.snapshot, payload, next),
    });
  },

  async realtimeAction(action) {
    if (get().realtimeBusy) return;
    set({ realtimeBusy: true });
    try {
      const status = await api.realtimeAction(action);
      lastControlAt = Date.now();
      set({ realtime: status, realtimeBusy: false });
      const snap = get().snapshot;
      if (snap) {
        set({
          snapshot: {
            ...snap,
            sim_status: status.status,
            speed: status.speed,
            clock: status.clock,
            clock_hour: status.clock_hour,
          },
        });
      }
      const labels: Record<string, string> = {
        start: 'Simulation started', pause: 'Simulation paused',
        resume: 'Simulation resumed', reset: 'Simulation reset to 10:00',
      };
      appendLiveLog(action === 'reset' ? 'warn' : 'info', 'control', labels[action],
        `${fmtHour(status.clock_hour)} · ${status.speed}x`);
      get().pushToast('success', labels[action].toUpperCase(),
        `${fmtHour(status.clock_hour)} · speed ${status.speed}x`);
    } catch (err) {
      set({ realtimeBusy: false });
      get().handleApiError(err);
    }
  },

  async setRealtimeSpeed(speed) {
    if (get().realtimeBusy) return;
    set({ realtimeBusy: true });
    try {
      const status = await api.realtimeSpeed(speed);
      lastControlAt = Date.now();
      set({ realtime: status, realtimeBusy: false });
      const snap = get().snapshot;
      if (snap) set({ snapshot: { ...snap, speed: status.speed } });
      appendLiveLog('info', 'control', `Speed set to ${speed}x`);
    } catch (err) {
      set({ realtimeBusy: false });
      get().handleApiError(err);
    }
  },

  pushToast(level, title, message) {
    const id = ++toastSeq;
    set({ toast: { id, level, title, message } });
    window.setTimeout(() => {
      if (get().toast?.id === id) set({ toast: null });
    }, 6000);
  },

  dismissToast() { set({ toast: null }); },
  setDemo(open) { set({ demoOpen: open, demoStep: open ? get().demoStep : 0 }); },
  setDemoStep(step) { set({ demoStep: step }); },
  setDemoRunning(running) { set({ demoRunning: running }); },
  focusCamera(x, z) {
    set({ focusRequest: { x, z, seq: (get().focusRequest?.seq ?? 0) + 1 } });
  },
  setCameraView(view) {
    set({ cameraView: { view, seq: (get().cameraView?.seq ?? 0) + 1 } });
  },

  handleApiError(err) {
    if (err instanceof ApiError) {
      if (err.status === 0) {
        set({ backendOffline: true });
        get().pushToast('error', 'BACKEND OFFLINE', 'Cannot reach the TwinSphere API server.');
      } else if (err.status === 401) {
        get().pushToast('error', 'SESSION EXPIRED', 'Please sign in again.');
      } else if (err.status === 403) {
        get().pushToast('warn', 'ACCESS DENIED', err.message);
      } else if (err.status === 429) {
        get().pushToast('warn', 'RATE LIMITED', err.message);
      } else {
        get().pushToast('error', 'REQUEST FAILED', err.message);
      }
    } else if (err instanceof Error) {
      get().pushToast('error', 'ERROR', err.message);
    }
  },
}));

export function getSocket(): TwinSocket | null {
  return socket;
}

export type { Route };
