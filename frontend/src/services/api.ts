import type {
  ActiveSim, AIEventsResponse, AnalystReport, AnomaliesResponse, Anomaly,
  AiAnalyticsResponse, BuildingsAnalyticsResponse, BuildingAnalyticsDetailResponse,
  BuildingsCompareResponse, BuildingDetail, BuildingEvacuationPlan,
  CampusHealthResponse, EnergyAnalyticsResponse, EmergencyRoutesResponse,
  EnvironmentAnalyticsResponse, EvacuationOverview, EvacuationStatus, Floor,
  FloorDetail, Incident, IncidentDetailResponse, IncidentListResponse,
  IncidentReportResponse, OccupancyAnalyticsResponse, OverviewResponse,
  Prediction, PredictionsResponse,
  RealtimeStatus, Recommendation, ReplayFrame, ReplayPayload, RiskAnalyticsResponse,
  RiskResponse, RiskResult, RouteAlternativesResponse, RouteGraphInfo,
  RouteHistoryRow, RouteMode, RoutePlan, RoutesAnalyticsResponse, Sensor,
  SensorHealthDetailResponse, SensorHealthResponse, SensorHistory, SimHistoryItem,
  SimulationCompareResponse, SimulationDetailResponse, SimulationEventsResponse,
  SimulationListResponse, SimulationResults, Snapshot, SystemStatusResponse, User,
  WhatChangedResponse, Zone, ZoneDetail,
} from '../types';

const API_BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? '';

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function getToken(): string | null {
  return localStorage.getItem('ts_token');
}

export function setToken(token: string | null) {
  if (token) localStorage.setItem('ts_token', token);
  else localStorage.removeItem('ts_token');
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> | undefined),
  };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  } catch {
    throw new ApiError(0, 'BACKEND OFFLINE — cannot reach server');
  }
  if (res.status === 401) {
    setToken(null);
    window.dispatchEvent(new CustomEvent('ts:unauthorized'));
    throw new ApiError(401, 'Session expired — please sign in again');
  }
  const text = await res.text();
  const data = text ? JSON.parse(text) : {};
  if (!res.ok) {
    throw new ApiError(res.status, (data as { detail?: string }).detail ?? `Request failed (${res.status})`);
  }
  return data as T;
}

/** Strip empty values from query params (shared by Phase 5 AI filters). */
function query(params?: Record<string, string | number | undefined | null>): string {
  if (!params) return '';
  const entries = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => [k, String(v)]);
  const qs = new URLSearchParams(entries).toString();
  return qs ? `?${qs}` : '';
}

/** Fetch a CSV/text resource with the same auth + error handling as `request`. */
async function requestText(path: string): Promise<string> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { headers });
  } catch {
    throw new ApiError(0, 'BACKEND OFFLINE — cannot reach server');
  }
  if (res.status === 401) {
    setToken(null);
    window.dispatchEvent(new CustomEvent('ts:unauthorized'));
    throw new ApiError(401, 'Session expired — please sign in again');
  }
  const text = await res.text();
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      detail = (JSON.parse(text) as { detail?: string }).detail ?? detail;
    } catch { /* not JSON — keep generic message */ }
    throw new ApiError(res.status, detail);
  }
  return text;
}

export const api = {
  health: () => request<Record<string, string>>('/health'),

  login: (username: string, password: string) =>
    request<{ access_token: string; user: User }>('/api/auth/login', {
      method: 'POST', body: JSON.stringify({ username, password }),
    }),
  register: (username: string, email: string, password: string, role: string) =>
    request<{ access_token: string; user: User }>('/api/auth/register', {
      method: 'POST', body: JSON.stringify({ username, email, password, role }),
    }),

  campus: () => request<Snapshot>('/api/campus'),
  buildings: (params?: { type?: string; status?: string }) => {
    const q = params ? '?' + new URLSearchParams(params as Record<string, string>).toString() : '';
    return request<BuildingDetail[]>(`/api/buildings${q}`);
  },
  building: (id: string) => request<BuildingDetail>(`/api/buildings/${id}`),
  buildingFloors: (id: string) => request<Floor[]>(`/api/buildings/${id}/floors`),
  floors: (buildingId?: string) =>
    request<Floor[]>(`/api/floors${buildingId ? `?building_id=${buildingId}` : ''}`),
  floor: (id: string) => request<FloorDetail>(`/api/floors/${id}`),
  zones: (params?: { building_id?: string; floor_id?: string; floor?: number;
                     zone_type?: string; risk_level?: string }) => {
    const q = params
      ? '?' + new URLSearchParams(
          Object.entries(params)
            .filter(([, v]) => v !== undefined && v !== null && v !== '')
            .map(([k, v]) => [k, String(v)]),
        ).toString()
      : '';
    return request<Zone[]>(`/api/zones${q}`);
  },
  zone: (id: string) => request<ZoneDetail>(`/api/zones/${id}`),
  sensors: (params?: { type?: string; building_id?: string; zone_id?: string; status?: string }) => {
    const q = params
      ? '?' + new URLSearchParams(
          Object.entries(params)
            .filter(([, v]) => v !== undefined && v !== null && v !== '')
            .map(([k, v]) => [k, String(v)]),
        ).toString()
      : '';
    return request<Sensor[]>(`/api/sensors${q}`);
  },
  sensorHistory: (id: string, params?: { limit?: number; start?: string; end?: string }) => {
    const q = params
      ? '?' + new URLSearchParams(
          Object.entries(params)
            .filter(([, v]) => v !== undefined && v !== null && v !== '')
            .map(([k, v]) => [k, String(v)]),
        ).toString()
      : '';
    return request<SensorHistory>(`/api/sensors/${id}/history${q}`);
  },
  risk: () => request<RiskResponse>('/api/risk'),
  riskFor: (entityId: string) =>
    request<RiskResult & { entity_id: string; published?: import('../types').PublishedRisk | null;
                           history?: import('../types').RiskHistoryPoint[] }>(`/api/risk/${entityId}`),
  routes: (recompute = false) =>
    request<{ routes: import('../types').Route[]; report: Record<string, unknown> }>(
      `/api/routes${recompute ? '?recompute=true' : ''}`),
  predictions: (horizonMin = 20) =>
    request<PredictionsResponse>(`/api/ai/predictions?horizon_min=${horizonMin}`),
  storedPredictions: () =>
    request<{ predictions: Prediction[]; count: number; data_source: string }>('/api/predictions'),
  // Phase 5 — AI anomaly surface (filters per spec §51)
  anomalies: (params?: { severity?: string; building_id?: string; sensor_id?: string;
                         metric?: string; start?: string; end?: string; limit?: number }) =>
    request<AnomaliesResponse>(`/api/ai/anomalies${query(params)}`),
  anomaly: (id: string) => request<Anomaly>(`/api/ai/anomalies/${encodeURIComponent(id)}`),
  aiPredictions: (params?: { horizon_min?: number; entity_id?: string; metric?: string;
                             limit?: number }) =>
    request<PredictionsResponse>(`/api/ai/predictions${query(params)}`),
  predictionFor: (entityId: string) =>
    request<PredictionsResponse & { entity_id: string }>(`/api/ai/predictions/${entityId}`),
  aiEvents: (limit?: number) => request<AIEventsResponse>(`/api/ai/events${query({ limit })}`),
  analyst: () => request<AnalystReport>('/api/ai/analyst'),
  analyze: (question: string, mode?: string) =>
    request<AnalystReport>('/api/ai/analyze', {
      method: 'POST',
      body: JSON.stringify(mode ? { question, mode } : { question }),
    }),
  aiStatus: () => request<Record<string, unknown>>('/api/ai/status'),

  // Phase 8 §57-§60 — persisted analyses, decisions, evidence + analyst health
  analystStatus: () =>
    request<{ analyst: import('../types').AnalystStatus } & Record<string, unknown>>(
      '/api/ai/status'),
  listAnalyses: (limit = 20) =>
    request<{ analyses: AnalystReport[]; count: number }>(`/api/ai/analysis?limit=${limit}`),
  latestAnalysis: () => request<AnalystReport>('/api/ai/analysis/latest'),
  analysis: (id: string) => request<AnalystReport>(`/api/ai/analysis/${encodeURIComponent(id)}`),
  analystRecommendations: (params?: { status?: string; analysis_id?: string }) =>
    request<{ recommendations: import('../types').AnalystRecommendationRow[]; count: number }>(
      `/api/ai/recommendations${query(params)}`),
  decideAnalystRecommendation: (id: string, decision: import('../types').AnalystDecision) =>
    request<{ recommendation_id: string; status: string }>(
      `/api/ai/recommendations/${encodeURIComponent(id)}/decision`, {
        method: 'POST', body: JSON.stringify({ decision }),
      }),
  analystEvidence: (id: string) =>
    request<import('../types').AnalystEvidenceItem>(
      `/api/ai/evidence/${encodeURIComponent(id)}`),

  recommendations: (status?: string) =>
    request<Recommendation[]>(`/api/recommendations${status ? `?status=${status}` : ''}`),
  applyRecommendation: (id: string) =>
    request<Recommendation>(`/api/recommendations/${id}/apply`, { method: 'POST' }),

  incidents: (status?: string) => request<Incident[]>(`/api/incidents${status ? `?status=${status}` : ''}`),
  incident: (id: string) => request<Incident>(`/api/incidents/${id}`),
  createIncident: (body: Record<string, unknown>) =>
    request<Incident>('/api/incidents', { method: 'POST', body: JSON.stringify(body) }),
  resolveIncident: (id: string) =>
    request<Incident>(`/api/incidents/${id}/resolve`, { method: 'POST' }),
  alerts: () => request<import('../types').Alert[]>('/api/alerts'),

  simulations: () => request<{ active: ActiveSim | null; history: SimHistoryItem[] }>('/api/simulations'),
  activeSim: () => request<ActiveSim | null>('/api/simulations/active'),
  createSimulation: (scenario: string, target_id: string | null, params: Record<string, unknown>) =>
    request<ActiveSim>('/api/simulations', {
      method: 'POST', body: JSON.stringify({ scenario, target_id, params }),
    }),
  simAction: (id: string, action: 'start' | 'pause' | 'resume' | 'reset' | 'recover') =>
    request<ActiveSim>(`/api/simulations/${id}/${action}`, { method: 'POST' }),
  simEvents: (id: string) =>
    request<{ persisted: import('../types').SimEvent[]; live: import('../types').SimEvent[] }>(
      `/api/simulations/${id}/events`),
  // Phase 6 §53 — simulation detail + honest results block (§48)
  simulationDetail: (id: string) => request<ActiveSim>(`/api/simulations/${id}`),
  simulationResults: (id: string) =>
    request<{ simulation_id: string; status: string; live: boolean; results: SimulationResults }>(
      `/api/simulations/${id}/results`),

  analytics: (range: string) =>
    request<Record<string, Array<Record<string, number | string>>>>(`/api/analytics/timeseries?range=${range}`),
  occupancyHistory: (buildingId?: string) =>
    request<Array<Record<string, unknown>>>(
      `/api/occupancy-history${buildingId ? `?building_id=${buildingId}` : ''}`),

  settings: () => request<Record<string, unknown>>('/api/settings'),
  updateSettings: (body: { speed?: number; sensor_interval?: number; random_seed?: number }) =>
    request<Record<string, unknown>>('/api/settings', { method: 'POST', body: JSON.stringify(body) }),
  demoScript: () => request<{ steps: Array<Record<string, unknown>> }>('/api/demo/script'),
  demoReset: () => request<Record<string, unknown>>('/api/demo/reset', { method: 'POST' }),
  systemStatus: () => request<Record<string, unknown>>('/api/system/status'),

  // Phase 4 — realtime campus simulation controls (§36)
  realtimeStatus: () => request<RealtimeStatus>('/api/realtime/status'),
  realtimeAction: (action: 'start' | 'pause' | 'resume' | 'reset') =>
    request<RealtimeStatus>(`/api/realtime/${action}`, { method: 'POST' }),
  realtimeSpeed: (speed: number) =>
    request<RealtimeStatus>('/api/realtime/speed', {
      method: 'POST', body: JSON.stringify({ speed }),
    }),

  // Phase 7 §39-§43 — route & evacuation optimization
  routeGraph: () => request<RouteGraphInfo>('/api/routes/graph'),
  routeCalculate: (body: {
    origin: string; destination: string; mode?: RouteMode;
    people?: number; alternatives?: number; simulation_id?: string;
  }) => request<RoutePlan>('/api/routes/calculate', {
    method: 'POST', body: JSON.stringify(body),
  }),
  routeRecalculate: (body: { mode?: RouteMode; reason?: string; simulation_id?: string } = {}) =>
    request<{ recalculated: boolean; route: RoutePlan; route_version: number }>(
      '/api/routes/recalculate', { method: 'POST', body: JSON.stringify(body) }),
  routeAlternatives: (origin: string, destination: string, mode: RouteMode = 'balanced', limit = 3) =>
    request<RouteAlternativesResponse>(
      `/api/routes/alternatives${query({ origin, destination, mode, limit })}`),
  routesEvacuation: (mode?: RouteMode) =>
    request<EvacuationOverview>(`/api/routes/evacuation${query({ mode })}`),
  evacuationStatus: () => request<EvacuationStatus>('/api/evacuation/status'),
  evacuationBuilding: (buildingId: string, mode?: RouteMode) =>
    request<BuildingEvacuationPlan>(
      `/api/evacuation/building/${buildingId}${query({ mode })}`),
  emergencyRoutes: (opts: { vehicle?: string; origin?: string; destination?: string } = {}) =>
    request<EmergencyRoutesResponse>(`/api/routes/emergency${query(opts)}`),
  emergencyResponseRoutes: (opts: { vehicle?: string; origin?: string; destination?: string } = {}) =>
    request<EmergencyRoutesResponse>(`/api/emergency-response/routes${query(opts)}`),
  routeBottlenecks: () =>
    request<{
      bottlenecks: import('../types').RouteBottleneck[];
      exits: import('../types').EvacuationExitLoad[];
      status: string; simulation_id: string | null;
    }>('/api/routes/bottlenecks'),
  routeHistory: (limit = 50) =>
    request<{ history: RouteHistoryRow[]; recent_in_memory: RouteHistoryRow[] }>(
      `/api/routes/history?limit=${limit}`),
  routeDetail: (routeId: string) => request<RoutePlan>(`/api/routes/${routeId}`),

  // Phase 9 §60 — server-side analytics aggregation
  analyticsOverview: (params?: { range?: string; start?: string; end?: string }) =>
    request<OverviewResponse>(`/api/analytics/overview${query(params)}`),
  riskAnalytics: (params?: { range?: string; start?: string; end?: string;
                             building_id?: string }) =>
    request<RiskAnalyticsResponse>(`/api/analytics/risk${query(params)}`),
  occupancyAnalytics: (params?: { range?: string; start?: string; end?: string;
                                  building_id?: string }) =>
    request<OccupancyAnalyticsResponse>(`/api/analytics/occupancy${query(params)}`),
  energyAnalytics: (params?: { range?: string; start?: string; end?: string;
                               building_id?: string }) =>
    request<EnergyAnalyticsResponse>(`/api/analytics/energy${query(params)}`),
  environmentAnalytics: (params?: { range?: string; start?: string; end?: string;
                                    building_id?: string }) =>
    request<EnvironmentAnalyticsResponse>(`/api/analytics/environment${query(params)}`),
  sensorHealth: (params?: { range?: string; start?: string; end?: string }) =>
    request<SensorHealthResponse>(`/api/analytics/sensors${query(params)}`),
  sensorHealthDetail: (id: string, params?: { range?: string; start?: string; end?: string }) =>
    request<SensorHealthDetailResponse>(
      `/api/analytics/sensors/${encodeURIComponent(id)}${query(params)}`),
  buildingsAnalytics: (params?: { range?: string; start?: string; end?: string }) =>
    request<BuildingsAnalyticsResponse>(`/api/analytics/buildings${query(params)}`),
  buildingAnalytics: (id: string, params?: { range?: string; start?: string; end?: string }) =>
    request<BuildingAnalyticsDetailResponse>(
      `/api/analytics/buildings/${encodeURIComponent(id)}${query(params)}`),
  compareBuildings: (ids: string, params?: { range?: string; start?: string; end?: string }) =>
    request<BuildingsCompareResponse>(
      `/api/analytics/buildings/compare${query({ ids, ...params })}`),
  routesAnalytics: (params?: { range?: string; start?: string; end?: string }) =>
    request<RoutesAnalyticsResponse>(`/api/analytics/routes${query(params)}`),
  aiAnalytics: (params?: { range?: string; start?: string; end?: string }) =>
    request<AiAnalyticsResponse>(`/api/analytics/ai${query(params)}`),
  analyticsSystem: () => request<SystemStatusResponse>('/api/analytics/system'),
  campusHealth: (params?: { range?: string; start?: string; end?: string }) =>
    request<CampusHealthResponse>(`/api/analytics/health${query(params)}`),
  whatChanged: (ago = 60) =>
    request<WhatChangedResponse>(`/api/analytics/what-changed${query({ ago })}`),
  exportAnalytics: (kind: string, params?: { range?: string; start?: string; end?: string }) =>
    requestText(`/api/analytics/export${query({ kind, ...params })}`),

  // Phase 9 §62 — historical intelligence
  historyIncidents: (params?: { page?: number; page_size?: number; status?: string;
                                severity?: string; kind?: string; building_id?: string;
                                simulation_id?: string; q?: string; sort?: string;
                                order?: string }) =>
    request<IncidentListResponse>(`/api/history/incidents${query(params)}`),
  historyIncident: (id: string) =>
    request<IncidentDetailResponse>(`/api/history/incidents/${encodeURIComponent(id)}`),
  incidentReport: (id: string) =>
    request<IncidentReportResponse>(
      `/api/history/incidents/${encodeURIComponent(id)}/report`),
  incidentExport: (id: string, format: 'csv' | 'json' = 'csv') =>
    requestText(
      `/api/history/incidents/${encodeURIComponent(id)}/export${query({ format })}`),
  historySimulations: (params?: { page?: number; page_size?: number; scenario?: string;
                                  status?: string; severity?: string; q?: string;
                                  sort?: string; order?: string }) =>
    request<SimulationListResponse>(`/api/history/simulations${query(params)}`),
  historySimulation: (id: string) =>
    request<SimulationDetailResponse>(
      `/api/history/simulations/${encodeURIComponent(id)}`),
  historySimEvents: (id: string) =>
    request<SimulationEventsResponse>(
      `/api/history/simulations/${encodeURIComponent(id)}/events`),
  compareSimulations: (a: string, b: string) =>
    request<SimulationCompareResponse>(
      `/api/history/simulations/compare${query({ a, b })}`),
  historyExport: (kind: string, params?: { range?: string; page_size?: number }) =>
    requestText(`/api/history/export${query({ kind, ...params })}`),

  // Phase 9 §63 — simulation replay
  replay: (id: string) =>
    request<ReplayPayload>(`/api/history/simulations/${encodeURIComponent(id)}/replay`),
  replayFrame: (id: string, t: number) =>
    request<ReplayFrame>(
      `/api/history/simulations/${encodeURIComponent(id)}/frame${query({ t })}`),
};
