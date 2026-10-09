import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  makeBuilding, makeBuildingDetail, makeHistory, makeSnapshot,
} from '../testFixtures';
import type { ActiveSim, RealtimeStatus, Snapshot, SystemStatusInfo } from '../types';
import { useTwinStore } from './useTwinStore';

const m = vi.hoisted(() => ({
  api: {
    login: vi.fn(),
    register: vi.fn(),
    logout: vi.fn(),
    me: vi.fn(),
    changePassword: vi.fn(),
    health: vi.fn(),
    campus: vi.fn(),
    simulations: vi.fn(),
    building: vi.fn(),
    buildingFloors: vi.fn(),
    sensorHistory: vi.fn(),
    sensors: vi.fn(),
    zones: vi.fn(),
    analyst: vi.fn(),
    analystStatus: vi.fn(),
    realtimeStatus: vi.fn(),
    realtimeAction: vi.fn(),
    realtimeSpeed: vi.fn(),
    anomalies: vi.fn(),
    aiPredictions: vi.fn(),
    aiEvents: vi.fn(),
    aiStatus: vi.fn(),
    risk: vi.fn(),
  },
  getToken: vi.fn((): string | null => null),
  setToken: vi.fn(),
}));

vi.mock('../services/api', () => ({
  api: m.api,
  getToken: m.getToken,
  setToken: m.setToken,
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

vi.mock('../services/ws', () => ({
  TwinSocket: class {
    connect = vi.fn();
    disconnect = vi.fn();
  },
}));

const INITIAL_TOGGLES = {
  buildings: true, roads: true, sensors: true, zones: false, labels: true,
  parking: true, trees: true, grid: true, heatmap: false,
  occupancy: true, routes: true, night: false, risk: false,
};

beforeEach(() => {
  m.api.building.mockResolvedValue(makeBuildingDetail());
  m.api.buildingFloors.mockResolvedValue([]);
  m.api.sensorHistory.mockResolvedValue(makeHistory());
  m.api.sensors.mockResolvedValue([]);
  m.api.zones.mockResolvedValue([]);
  m.api.campus.mockResolvedValue(makeSnapshot());
  m.api.health.mockResolvedValue({ status: 'ok' });
  m.api.simulations.mockResolvedValue({ active: null, history: [] });
  m.api.analyst.mockResolvedValue({ source: 'local_fallback' });
  m.api.analystStatus.mockResolvedValue({ analyst: { status: 'FALLBACK' } });
  m.api.realtimeStatus.mockResolvedValue(makeRealtime());
  m.api.realtimeAction.mockResolvedValue(makeRealtime());
  m.api.realtimeSpeed.mockResolvedValue(makeRealtime({ speed: 5 }));
  m.api.anomalies.mockResolvedValue({
    engine: 'layered-v1',
    anomalies: [{
      id: 'an-1', entity_id: 'sensor-1', entity_type: 'SENSOR', kind: 'value',
      metric: 'temperature', detector: 'threshold', anomaly_type: 'SUDDEN_SPIKE',
      location: 'Computer Science Block', score: 88, band: 'CRITICAL', status: 'ACTIVE',
      reason: 'value above threshold', first_seen: '2026-10-05T10:00:00Z',
      last_seen: '2026-10-05T10:05:00Z', observations: 2,
    }],
    sensor_status: { 'sensor-1': {
      status: 'CRITICAL', score: 88, type: 'temperature', detector: 'threshold',
      anomaly_id: 'an-1', available_samples: 20, minimum_required: 6,
    } },
    bands: {}, data_quality: 'OK', score_threshold: 75, min_samples: 6, count: 1, total: 1,
  });
  m.api.aiPredictions.mockResolvedValue({ predictions: [], count: 0, horizons: [15, 30, 60] });
  m.api.aiEvents.mockResolvedValue({ events: [], count: 0, ai_health: {} });
  m.api.aiStatus.mockResolvedValue({ phase: 'phase5', enabled: true, degraded: false });
  m.api.risk.mockResolvedValue({
    published: {
      campus: { score: 41, level: 'MODERATE', factors: [], explanation: 'smoke rising',
                raw_score: 45, trend: 'rising', changed: true },
      buildings: { 'b-cs': { score: 38, level: 'MODERATE', factors: [], explanation: '' } },
    },
  });

  useTwinStore.setState({
    token: null,
    connection: 'OFFLINE',
    backendOffline: false,
    snapshot: null,
    lastUpdate: 0,
    selectedBuildingId: null,
    buildingDetail: null,
    buildingLoading: false,
    buildingError: null,
    selectedFloorId: null,
    selectedSensorId: null,
    sensorHistory: null,
    sensorHistoryLoading: false,
    sensorHistoryError: null,
    toggles: { ...INITIAL_TOGGLES },
    viewMode: 'overview',
    sensorFilter: 'all',
    toast: null,
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
  });
});

function makeRealtime(over: Partial<RealtimeStatus> = {}): RealtimeStatus {
  return {
    status: 'RUNNING',
    speed: 1,
    simulation_time: 4000,
    clock: 40000,
    clock_hour: 11.1,
    last_tick: '2026-10-05T11:06:40Z',
    tick_count: 12,
    sensor_interval: 2,
    enabled: true,
    connected_clients: 1,
    data_source: 'SIMULATED',
    seed: 42,
    scenario: null,
    scenario_status: null,
    ...over,
  };
}

function makeSystemStatus(over: Partial<SystemStatusInfo> = {}): SystemStatusInfo {
  return {
    backend: true,
    database: true,
    websocket: true,
    simulator: 'RUNNING',
    ai: true,
    connected_clients: 1,
    clock_hour: 11.1,
    speed: 1,
    risk_level: 'LOW',
    incidents: 0,
    ...over,
  };
}

describe('layer toggles and view modes', () => {
  it('flips only the requested layer', () => {
    useTwinStore.getState().toggle('zones');
    const after = useTwinStore.getState().toggles;
    expect(after.zones).toBe(true);
    expect(after.buildings).toBe(true);
    expect(after.grid).toBe(true);
    expect(after.heatmap).toBe(false);

    useTwinStore.getState().toggle('zones');
    expect(useTwinStore.getState().toggles.zones).toBe(false);
  });

  it('applies the zones view-mode preset to the layer set', () => {
    useTwinStore.getState().setViewMode('zones');
    const state = useTwinStore.getState();
    expect(state.viewMode).toBe('zones');
    expect(state.toggles.zones).toBe(true);
    expect(state.toggles.parking).toBe(false);
    expect(state.toggles.buildings).toBe(true);
  });

  it('sets the sensor type filter', () => {
    useTwinStore.getState().setSensorFilter('temperature');
    expect(useTwinStore.getState().sensorFilter).toBe('temperature');
    useTwinStore.getState().setSensorFilter('all');
    expect(useTwinStore.getState().sensorFilter).toBe('all');
  });
});

describe('selection flow (building → floor → sensor)', () => {
  it('loads building detail and clears everything when deselected', async () => {
    await useTwinStore.getState().selectBuilding('b-cs');
    let state = useTwinStore.getState();
    expect(state.selectedBuildingId).toBe('b-cs');
    expect(state.buildingDetail?.name).toBe('Computer Science Block');
    expect(state.buildingLoading).toBe(false);
    expect(state.buildingError).toBeNull();

    useTwinStore.getState().selectFloor('b-cs-F1');
    useTwinStore.setState({ selectedSensorId: 'sensor-1', sensorHistory: makeHistory() });

    await useTwinStore.getState().selectBuilding(null);
    state = useTwinStore.getState();
    expect(state.buildingDetail).toBeNull();
    expect(state.selectedFloorId).toBeNull();
    expect(state.selectedSensorId).toBeNull();
    expect(state.sensorHistory).toBeNull();
  });

  it('clears the sensor selection when a floor is picked', () => {
    useTwinStore.setState({ selectedSensorId: 'sensor-1', sensorHistory: makeHistory() });
    useTwinStore.getState().selectFloor('b-cs-F1');
    expect(useTwinStore.getState().selectedFloorId).toBe('b-cs-F1');
    expect(useTwinStore.getState().selectedSensorId).toBeNull();
    expect(useTwinStore.getState().sensorHistory).toBeNull();
  });

  it('loads persisted history when a sensor is selected', async () => {
    useTwinStore.getState().selectSensor('sensor-1');
    await vi.waitFor(() => expect(useTwinStore.getState().sensorHistory).not.toBeNull());
    const state = useTwinStore.getState();
    expect(state.sensorHistory?.sensor.id).toBe('sensor-1');
    expect(state.sensorHistory?.data_source).toBe('SIMULATED');
    expect(state.sensorHistoryLoading).toBe(false);

    useTwinStore.getState().selectSensor(null);
    expect(useTwinStore.getState().sensorHistory).toBeNull();
  });
});

describe('WS state frame merge (campus-only keys)', () => {
  it('preserves summary/data_source when a live frame omits them', () => {
    const initial = makeSnapshot();
    useTwinStore.setState({ snapshot: initial });

    const payload = makeSnapshot({ buildings: [makeBuilding({ id: 'b-2', name: 'New Block' })] });
    delete payload.summary;
    delete payload.data_source;
    delete payload.metadata;

    useTwinStore.getState().onSocketMessage({ type: 'state', payload });
    const merged = useTwinStore.getState().snapshot;
    expect(merged?.buildings[0].id).toBe('b-2');
    expect(merged?.summary).toEqual(initial.summary);
    expect(merged?.data_source).toBe('SIMULATED');
    expect(useTwinStore.getState().lastUpdate).toBeGreaterThan(0);
  });

  it('prefers keys that are explicitly present on the live frame', () => {
    useTwinStore.setState({ snapshot: makeSnapshot({ data_source: 'LIVE' }) });
    const payload = makeSnapshot({ data_source: 'LIVE' });
    delete payload.summary;

    useTwinStore.getState().onSocketMessage({ type: 'state', payload });
    expect(useTwinStore.getState().snapshot?.data_source).toBe('LIVE');
  });
});

describe('Phase 4 — typed live WS events', () => {
  it('merges sensor.batch_update values into the snapshot', () => {
    useTwinStore.setState({ snapshot: makeSnapshot() });
    useTwinStore.getState().onSocketMessage({
      type: 'sensor.batch_update',
      data: {
        sensors: [{ id: 'sensor-1', value: 31.2, status: 'ONLINE', healthy: true, updated_at: 40000 }],
        clock: 40000,
        clock_hour: 11.1,
      },
    });
    const s = useTwinStore.getState().snapshot?.sensors[0];
    expect(s?.value).toBe(31.2);
    expect(s?.last_reading).toBe(31.2);
    expect(useTwinStore.getState().snapshot?.clock).toBe(40000);
    expect(useTwinStore.getState().lastUpdate).toBeGreaterThan(0);
  });

  it('updates campus occupancy from occupancy.update', () => {
    const metrics = {
      occupancy: 800, occupancy_pct: 40, energy: 500, temperature: 24, water: 30,
      risk: 20, risk_level: 'LOW', incidents: 0, people_at_risk: 0, anomalies: 0,
      clock_hour: 11, status: 'NORMAL', recovery_progress: 0,
    } as unknown as Snapshot['metrics'];
    useTwinStore.setState({ snapshot: makeSnapshot({ metrics }) });
    useTwinStore.getState().onSocketMessage({
      type: 'occupancy.update',
      data: { occupancy: 900, occupancy_pct: 45 },
    });
    expect(useTwinStore.getState().snapshot?.metrics.occupancy).toBe(900);
    expect(useTwinStore.getState().snapshot?.metrics.occupancy_pct).toBe(45);
  });

  it('merges building.update live fields into the matching building', () => {
    useTwinStore.setState({ snapshot: makeSnapshot() });
    useTwinStore.getState().onSocketMessage({
      type: 'building.update',
      data: { buildings: [{ id: 'b-cs', occupancy: 300, status: 'EVACUATING' }] },
    });
    const b = useTwinStore.getState().snapshot?.buildings[0];
    expect(b?.occupancy).toBe(300);
    expect(b?.status).toBe('EVACUATING');
    expect(b?.name).toBe('Computer Science Block'); // untouched fields survive
  });

  it('applies simulation.status to realtime + snapshot and logs a transition', () => {
    useTwinStore.setState({
      snapshot: makeSnapshot({ sim_status: 'RUNNING' }),
      realtime: makeRealtime({ status: 'RUNNING' }),
    });
    useTwinStore.getState().onSocketMessage({
      type: 'simulation.status',
      data: makeRealtime({ status: 'PAUSED', clock: 41000, clock_hour: 11.4 }),
    });
    const st = useTwinStore.getState();
    expect(st.realtime?.status).toBe('PAUSED');
    expect(st.snapshot?.sim_status).toBe('PAUSED');
    expect(st.snapshot?.clock).toBe(41000);
    expect(st.liveLog.some((e) => e.kind === 'sim_status' && e.title.includes('paused'))).toBe(true);
  });

  it('applies system.status and logs a database outage transition', () => {
    useTwinStore.setState({ systemStatus: makeSystemStatus() });
    useTwinStore.getState().onSocketMessage({
      type: 'system.status',
      data: makeSystemStatus({ database: false, simulator: 'PAUSED' }),
    });
    expect(useTwinStore.getState().systemStatus?.database).toBe(false);
    expect(useTwinStore.getState().systemStatus?.simulator).toBe('PAUSED');
    expect(useTwinStore.getState().liveLog.some((e) => e.level === 'error' && e.title.includes('Database'))).toBe(true);
  });

  it('logs a campus risk level transition observed on state frames', () => {
    const base = {
      occupancy: 800, occupancy_pct: 40, energy: 500, temperature: 24, water: 30,
      risk: 20, risk_level: 'LOW', incidents: 0, people_at_risk: 0, anomalies: 0,
      clock_hour: 11, status: 'NORMAL', recovery_progress: 0,
    } as unknown as Snapshot['metrics'];
    useTwinStore.setState({ snapshot: makeSnapshot({ metrics: base }) });
    useTwinStore.getState().onSocketMessage({
      type: 'state',
      payload: makeSnapshot({ metrics: { ...base, risk: 78, risk_level: 'HIGH' } as Snapshot['metrics'] }),
    });
    expect(useTwinStore.getState().liveLog.some((e) => e.kind === 'risk' && e.title.includes('HIGH'))).toBe(true);
  });

  it('keeps liveLog bounded at 40 entries', () => {
    const base = {
      occupancy: 800, occupancy_pct: 40, energy: 500, temperature: 24, water: 30,
      risk: 20, risk_level: 'LOW', incidents: 0, people_at_risk: 0, anomalies: 0,
      clock_hour: 11, status: 'NORMAL', recovery_progress: 0,
    } as unknown as Snapshot['metrics'];
    useTwinStore.setState({ snapshot: makeSnapshot({ metrics: base }) });
    for (let i = 0; i < 45; i++) {
      const level = i % 2 === 0 ? 'HIGH' : 'LOW';
      useTwinStore.getState().onSocketMessage({
        type: 'state',
        payload: makeSnapshot({ metrics: { ...base, risk_level: level } as Snapshot['metrics'] }),
      });
    }
    expect(useTwinStore.getState().liveLog.length).toBe(40);
  });

  it('keeps metricHistory bounded at 30 samples', () => {
    const old = Array.from({ length: 30 }, (_, i) => ({
      t: Date.now() - 100000 - i * 2000,
      occupancy_pct: 40, energy: 500, temperature: 24, risk: 20, water: 30,
    }));
    const metrics = {
      occupancy: 800, occupancy_pct: 41, energy: 510, temperature: 24.2, water: 30,
      risk: 21, risk_level: 'LOW', incidents: 0, people_at_risk: 0, anomalies: 0,
      clock_hour: 11, status: 'NORMAL', recovery_progress: 0,
    } as unknown as Snapshot['metrics'];
    useTwinStore.setState({ snapshot: makeSnapshot({ metrics }), metricHistory: old });
    useTwinStore.getState().onSocketMessage({ type: 'occupancy.update', data: { occupancy: 810, occupancy_pct: 41 } });
    expect(useTwinStore.getState().metricHistory.length).toBe(30);
  });

  it('keeps sensorLiveWindow bounded at 120 points for the selected sensor', () => {
    const seeded = Array.from({ length: 120 }, (_, i) => ({ t: Date.now() - 100000 - i * 2000, value: 20 + i }));
    useTwinStore.setState({ snapshot: makeSnapshot(), selectedSensorId: 'sensor-1', sensorLiveWindow: seeded });
    useTwinStore.getState().onSocketMessage({
      type: 'sensor.batch_update',
      data: { sensors: [{ id: 'sensor-1', value: 30, status: 'ONLINE', healthy: true, updated_at: 41000 }] },
    });
    const win = useTwinStore.getState().sensorLiveWindow;
    expect(win.length).toBe(120);
    expect(win[win.length - 1].value).toBe(30);
  });

  it('clears the live sensor window when a sensor is (re)selected', async () => {
    useTwinStore.setState({ snapshot: makeSnapshot(), sensorLiveWindow: [{ t: 1, value: 5 }] });
    useTwinStore.getState().selectSensor('sensor-1');
    expect(useTwinStore.getState().sensorLiveWindow).toEqual([]);
    await vi.waitFor(() => expect(useTwinStore.getState().sensorHistory).not.toBeNull());
    useTwinStore.getState().selectSensor(null);
    expect(useTwinStore.getState().sensorLiveWindow).toEqual([]);
    expect(useTwinStore.getState().sensorHistory).toBeNull();
  });
});

describe('Phase 4 — realtime controls', () => {
  it('pause sends the action, applies status and logs a control entry', async () => {
    useTwinStore.setState({ snapshot: makeSnapshot({ sim_status: 'RUNNING' }) });
    m.api.realtimeAction.mockResolvedValue(makeRealtime({ status: 'PAUSED', clock: 40000, clock_hour: 11.1 }));
    await useTwinStore.getState().realtimeAction('pause');
    expect(m.api.realtimeAction).toHaveBeenCalledWith('pause');
    const st = useTwinStore.getState();
    expect(st.realtime?.status).toBe('PAUSED');
    expect(st.snapshot?.sim_status).toBe('PAUSED');
    expect(st.realtimeBusy).toBe(false);
    expect(st.liveLog[0]).toMatchObject({ kind: 'control', title: 'Simulation paused' });
    expect(st.toast?.level).toBe('success');
  });

  it('speed change applies the new speed and logs it', async () => {
    m.api.realtimeSpeed.mockResolvedValue(makeRealtime({ speed: 5 }));
    await useTwinStore.getState().setRealtimeSpeed(5);
    expect(m.api.realtimeSpeed).toHaveBeenCalledWith(5);
    expect(useTwinStore.getState().realtime?.speed).toBe(5);
    expect(useTwinStore.getState().liveLog[0]).toMatchObject({ kind: 'control', title: 'Speed set to 5x' });
    expect(useTwinStore.getState().realtimeBusy).toBe(false);
  });

  it('surfaces control failures as a toast and unlocks the busy flag', async () => {
    const { ApiError } = await import('../services/api');
    m.api.realtimeAction.mockRejectedValue(new ApiError(403, 'forbidden'));
    await useTwinStore.getState().realtimeAction('pause');
    expect(useTwinStore.getState().realtimeBusy).toBe(false);
    // Phase 10: 403 renders as a dedicated ACCESS DENIED warning toast
    expect(useTwinStore.getState().toast).toMatchObject({ level: 'warn', title: 'ACCESS DENIED' });
    expect(useTwinStore.getState().liveLog.length).toBe(0);
  });
});

describe('Phase 5 — RISK MODE view preset', () => {
  it('turns the risk layer on when entering risk mode and off when leaving', () => {
    useTwinStore.getState().setViewMode('risk');
    const inRisk = useTwinStore.getState();
    expect(inRisk.viewMode).toBe('risk');
    expect(inRisk.toggles.risk).toBe(true);
    expect(inRisk.toggles.buildings).toBe(true);
    expect(inRisk.toggles.sensors).toBe(true);

    useTwinStore.getState().setViewMode('overview');
    expect(useTwinStore.getState().toggles.risk).toBe(false);
  });

  it('toggles the risk layer chip independently of the view mode', () => {
    useTwinStore.getState().toggle('risk');
    expect(useTwinStore.getState().toggles.risk).toBe(true);
    useTwinStore.getState().toggle('risk');
    expect(useTwinStore.getState().toggles.risk).toBe(false);
  });
});

describe('Phase 5 — AI intelligence slice', () => {
  it('refreshAi populates anomalies, sensor status and published risk', async () => {
    await useTwinStore.getState().refreshAi();
    const st = useTwinStore.getState();
    expect(st.anomalies).toHaveLength(1);
    expect(st.anomalies[0].band).toBe('CRITICAL');
    expect(st.sensorAiStatus['sensor-1'].status).toBe('CRITICAL');
    expect(st.anomalyDataQuality).toBe('OK');
    expect(st.riskPublished).toMatchObject({ score: 41, level: 'MODERATE', trend: 'rising' });
    expect(st.riskPublishedBuildings['b-cs']).toMatchObject({ score: 38, level: 'MODERATE' });
    expect(st.aiLastUpdated).toBeGreaterThan(0);
    expect(st.aiRefreshing).toBe(false);
    expect(st.aiDegraded).toBe(false);
  });

  it('marks the AI slice degraded when every AI endpoint fails', async () => {
    m.api.anomalies.mockRejectedValue(new Error('down'));
    m.api.aiPredictions.mockRejectedValue(new Error('down'));
    m.api.aiEvents.mockRejectedValue(new Error('down'));
    m.api.aiStatus.mockRejectedValue(new Error('down'));
    m.api.risk.mockRejectedValue(new Error('down'));
    await useTwinStore.getState().refreshAi();
    const st = useTwinStore.getState();
    expect(st.aiDegraded).toBe(true);
    expect(st.aiRefreshing).toBe(false);
    expect(st.riskPublished).toBeNull();
  });

  it('ai.anomaly replaces the bounded anomaly list and logs fresh detections', () => {
    useTwinStore.getState().onSocketMessage({
      type: 'ai.anomaly',
      data: {
        anomalies: [{
          id: 'an-2', entity_id: 'sensor-9', entity_type: 'SENSOR', kind: 'value',
          metric: 'smoke', detector: 'threshold', anomaly_type: 'SUDDEN_SPIKE',
          location: 'Library', score: 91, band: 'CRITICAL', status: 'ACTIVE',
          reason: 'smoke above threshold', first_seen: '2026-10-05T11:00:00Z',
          last_seen: '2026-10-05T11:00:00Z', observations: 1,
        }],
        count: 1, new: ['an-2'], data_quality: 'OK',
        sensor_status: { 'sensor-9': {
          status: 'CRITICAL', score: 91, type: 'smoke', detector: 'threshold',
          anomaly_id: 'an-2', available_samples: 10, minimum_required: 6,
        } },
        clock: 40000,
      },
    });
    const st = useTwinStore.getState();
    expect(st.anomalies).toHaveLength(1);
    expect(st.sensorAiStatus['sensor-9'].status).toBe('CRITICAL');
    expect(st.aiLastUpdated).toBeGreaterThan(0);
    expect(st.liveLog.some((e) => e.title.includes('new anomal'))).toBe(true);
  });

  it('risk.update stores published campus + buildings and merges into the snapshot', () => {
    useTwinStore.setState({ snapshot: makeSnapshot() });
    useTwinStore.getState().onSocketMessage({
      type: 'risk.update',
      data: {
        campus: { score: 55, level: 'ELEVATED', factors: [{ label: 'smoke', contribution: 20 }],
                  explanation: 'elevated by anomalies', raw_score: 62, trend: 'rising' },
        buildings: { 'b-cs': { score: 61, level: 'HIGH',
                               factors: [{ label: 'smoke', contribution: 25 }], explanation: '' } },
        raw_level: 'HIGH',
        clock: 40000,
      },
    });
    const st = useTwinStore.getState();
    expect(st.riskPublished).toMatchObject({ score: 55, level: 'ELEVATED' });
    expect(st.riskPublishedBuildings['b-cs']).toMatchObject({ score: 61, level: 'HIGH' });
    expect(st.snapshot?.metrics.risk).toBe(55);
    expect(st.snapshot?.metrics.risk_level).toBe('ELEVATED');
    expect(st.snapshot?.buildings[0]).toMatchObject({ risk: 61, risk_level: 'HIGH' });
    expect(st.snapshot?.building_risk['b-cs']?.score).toBe(61);
  });

  it('ai.prediction refreshes the bounded prediction list', () => {
    useTwinStore.getState().onSocketMessage({
      type: 'ai.prediction',
      data: {
        predictions: [{
          entity_id: 'occupancy:campus', metric: 'occupancy', model: 'baseline',
          horizon_min: 30, predicted_value: 812, confidence: 0.6, confidence_label: 'MEDIUM',
          lower_bound: 760, upper_bound: 864, samples: 40, status: 'OK',
          at: '2026-10-05T11:00:00Z',
        }],
        count: 1, horizons: [30], clock: 40000,
      },
    });
    const st = useTwinStore.getState();
    expect(st.aiPredictions).toHaveLength(1);
    expect(st.aiPredictions[0].horizon_min).toBe(30);
    expect(st.aiLastUpdated).toBeGreaterThan(0);
  });
});

function makeActiveSim(over: Partial<ActiveSim> = {}): ActiveSim {
  return {
    id: 'sim_test1', scenario: 'fire', scenario_type: 'fire',
    target_id: 'eng', target_type: 'BUILDING',
    params: { intensity: 4 }, parameters: { intensity: 4 },
    status: 'RUNNING', t: 12, duration: 330, progress: 3.6,
    peak_risk: 44, people_at_risk: 96, phase: 'spread',
    events: [], recover_t: 0, recover_duration: 130,
    weighted_people: 72, affected_zones: 2, max_people_at_risk: 96,
    peak_temperature: 118.5, peak_smoke: 64,
    ...over,
  };
}

describe('Phase 6 — simulation.* WS events', () => {
  it('simulation.tick merges live metrics into active_sim', () => {
    useTwinStore.setState({ snapshot: makeSnapshot({ active_sim: makeActiveSim() }) });
    useTwinStore.getState().onSocketMessage({
      type: 'simulation.tick',
      data: makeActiveSim({
        t: 40, progress: 12, people_at_risk: 150, affected_zones: 3,
        risk: 61, risk_level: 'HIGH', speed: 2,
        building_smoke: 42.5, building_temperature: 51.2, building_status: 'DANGER',
      }),
    });
    const sim = useTwinStore.getState().snapshot?.active_sim;
    expect(sim?.t).toBe(40);
    expect(sim?.people_at_risk).toBe(150);
    expect(sim?.affected_zones).toBe(3);
    expect(sim?.risk).toBe(61);
    expect(sim?.risk_level).toBe('HIGH');
    expect(sim?.building_status).toBe('DANGER');
    expect(useTwinStore.getState().lastUpdate).toBeGreaterThan(0);
  });

  it('simulation.zone_update applies changed zone statuses', () => {
    useTwinStore.setState({ snapshot: makeSnapshot() });
    const before = useTwinStore.getState().snapshot?.zones[0]?.status;
    useTwinStore.getState().onSocketMessage({
      type: 'simulation.zone_update',
      data: {
        simulation_id: 'sim_test1',
        changed: [{ id: 'z-cs-1', building_id: 'b-cs', status: 'FIRE',
                    fire: 0.62, smoke: 88, temperature: 140, risk_level: 'HIGH' }],
        count: 1, clock: 40040,
      },
    });
    const z = useTwinStore.getState().snapshot?.zones[0];
    expect(z?.status).toBe('FIRE');
    expect(z?.fire).toBe(0.62);
    expect(before).not.toBe('FIRE');
  });

  it('simulation.risk_update stores campus + target building risk on the snapshot', () => {
    useTwinStore.setState({
      snapshot: makeSnapshot({ active_sim: makeActiveSim({ target_id: 'b-cs' }) }),
    });
    useTwinStore.getState().onSocketMessage({
      type: 'simulation.risk_update',
      data: { simulation_id: 'sim_test1', risk: 73, level: 'HIGH',
              target_id: 'b-cs', target_risk: 88 },
    });
    const st = useTwinStore.getState();
    expect(st.snapshot?.active_sim?.risk).toBe(73);
    expect(st.snapshot?.active_sim?.risk_level).toBe('HIGH');
    expect(st.snapshot?.building_risk['b-cs']?.score).toBe(88);
  });

  it('lifecycle events update active_sim, toast and refresh history on completion', async () => {
    useTwinStore.setState({ snapshot: makeSnapshot({ active_sim: makeActiveSim() }), history: [] });
    useTwinStore.getState().onSocketMessage({
      type: 'simulation.started',
      data: makeActiveSim({ status: 'RUNNING' }),
    });
    let st = useTwinStore.getState();
    expect(st.snapshot?.active_sim?.id).toBe('sim_test1');
    expect(st.toast?.title).toBe('SIMULATION STARTED');
    expect(st.liveLog.some((e) => e.kind === 'sim_status' && e.title.includes('started'))).toBe(true);

    useTwinStore.getState().onSocketMessage({
      type: 'simulation.recovery_progress',
      data: { ...makeActiveSim({ status: 'RECOVERING' }), recovery_progress: 42 },
    });
    expect(useTwinStore.getState().snapshot?.recovery_progress).toBe(42);

    m.api.simulations.mockResolvedValue({ active: null, history: [] });
    useTwinStore.getState().onSocketMessage({
      type: 'simulation.completed',
      data: makeActiveSim({ status: 'COMPLETED', progress: 100 }),
    });
    st = useTwinStore.getState();
    expect(st.toast?.title).toBe('SIMULATION COMPLETE');
    await vi.waitFor(() => expect(m.api.simulations).toHaveBeenCalled());
  });

  it('ignores simulation.tick frames without an id', () => {
    useTwinStore.setState({ snapshot: makeSnapshot({ active_sim: makeActiveSim({ t: 5 }) }) });
    useTwinStore.getState().onSocketMessage({ type: 'simulation.tick', data: {} });
    expect(useTwinStore.getState().snapshot?.active_sim?.t).toBe(5);
  });
});

describe('Phase 10 � session security', () => {
  it('logout revokes the token server-side and clears the session', async () => {
    m.api.logout.mockResolvedValue({ ok: true });
    useTwinStore.setState({
      token: 'live-token',
      user: { id: 'u_admin', username: 'admin', role: 'ADMIN' },
      snapshot: makeSnapshot(),
      connection: 'CONNECTED',
    });
    useTwinStore.getState().logout();
    expect(m.api.logout).toHaveBeenCalledTimes(1);
    expect(m.setToken).toHaveBeenCalledWith(null);
    const st = useTwinStore.getState();
    expect(st.token).toBeNull();
    expect(st.user).toBeNull();
    expect(st.snapshot).toBeNull();
    expect(st.connection).toBe('OFFLINE');
  });

  it('logout still clears everything when the revocation call fails', () => {
    m.api.logout.mockRejectedValue(new Error('network down'));
    useTwinStore.setState({ token: 'live-token', user: { id: 'u_x', username: 'x', role: 'VIEWER' } });
    expect(() => useTwinStore.getState().logout()).not.toThrow();
    expect(useTwinStore.getState().token).toBeNull();
    expect(useTwinStore.getState().user).toBeNull();
  });

  it('logout with no token does not call the server', () => {
    useTwinStore.setState({ token: null });
    useTwinStore.getState().logout();
    expect(m.api.logout).not.toHaveBeenCalled();
  });

  it('changePassword stores the freshly issued token', async () => {
    m.api.changePassword.mockResolvedValue({ ok: true, access_token: 'brand-new' });
    useTwinStore.setState({ token: 'old-token' });
    await useTwinStore.getState().changePassword('OldPass123', 'NewPass123');
    expect(m.api.changePassword).toHaveBeenCalledWith('OldPass123', 'NewPass123');
    expect(m.setToken).toHaveBeenCalledWith('brand-new');
    expect(useTwinStore.getState().token).toBe('brand-new');
  });

  it('changePassword propagates validation failures without touching the session', async () => {
    const { ApiError } = await import('../services/api');
    m.api.changePassword.mockRejectedValue(new ApiError(400, 'Current password is incorrect'));
    useTwinStore.setState({ token: 'old-token' });
    await expect(useTwinStore.getState().changePassword('wrong', 'whatever1'))
      .rejects.toMatchObject({ status: 400 });
    expect(useTwinStore.getState().token).toBe('old-token');
    expect(m.setToken).not.toHaveBeenCalledWith('brand-new');
  });

  it('handleApiError renders rate limiting (429) as a warn toast', async () => {
    const { ApiError } = await import('../services/api');
    useTwinStore.getState().handleApiError(new ApiError(429, 'Too many requests � retry in 12s'));
    expect(useTwinStore.getState().toast).toMatchObject({
      level: 'warn', title: 'RATE LIMITED',
    });
  });

  it('handleApiError renders forbidden (403) as an access-denied warn toast', async () => {
    const { ApiError } = await import('../services/api');
    useTwinStore.getState().handleApiError(new ApiError(403, 'Access denied � your role does not permit this action'));
    expect(useTwinStore.getState().toast).toMatchObject({
      level: 'warn', title: 'ACCESS DENIED',
    });
  });
});
