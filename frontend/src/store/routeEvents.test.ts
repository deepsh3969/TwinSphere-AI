import { beforeEach, describe, expect, it, vi } from 'vitest';
import { makeSnapshot } from '../testFixtures';
import type { EvacuationOverview, RoutePlan } from '../types';
import { useTwinStore } from './useTwinStore';

const m = vi.hoisted(() => ({
  api: {
    routesEvacuation: vi.fn(),
    evacuationStatus: vi.fn(),
    evacuationBuilding: vi.fn(),
    routeCalculate: vi.fn(),
    routeAlternatives: vi.fn(),
    routeRecalculate: vi.fn(),
    routeHistory: vi.fn(),
    routeDetail: vi.fn(),
    emergencyResponseRoutes: vi.fn(),
    emergencyRoutes: vi.fn(),
    routeBottlenecks: vi.fn(),
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

const ROUTE_EVENT = {
  route_id: 'rte_ws1',
  kind: 'point',
  mode: 'balanced',
  status: 'RECOMMENDED',
  route_version: 3,
  simulation_id: null,
  origin: 'ex_eng_s',
  destination: 'gate_main',
  reason: 'balanced path',
  route: {
    path: ['ex_eng_s', 'gate_main'],
    node_path: ['ex_eng_s', 'court_c', 'gate_main'],
    road_path: ['r_eng_s', 'r_court_main'],
    distance: 146,
    estimated_time: 108,
    risk_score: 4,
    congestion_score: 0.1,
    congestion_label: 'LOW',
    safety: 'SAFE',
    destination_name: 'Main Gate',
    bottlenecks: [],
  },
  alternatives: [],
  people_at_risk: 0,
  timestamp: '2026-10-06T10:00:00+00:00',
};

function makeOverview(over: Partial<EvacuationOverview> = {}): EvacuationOverview {
  return {
    status: 'IDLE',
    mode: 'balanced',
    people_at_risk: 0,
    critical_buildings: [],
    blocked_buildings: [],
    totals: { buildings: 6, safe_routes: 6, blocked_routes: 0, bottlenecks: 0 },
    bottleneck_count: 0,
    simulation_id: null,
    route_version: 1,
    generated_at: '2026-10-06T10:00:00+00:00',
    buildings: [],
    exits: [],
    bottlenecks: [],
    ...over,
  };
}

function makePlan(over: Partial<RoutePlan> = {}): RoutePlan {
  return {
    route_id: 'rte_api1',
    kind: 'point',
    mode: 'balanced',
    status: 'RECOMMENDED',
    reason: '',
    path: ['a', 'b'],
    node_path: ['a', 'b'],
    road_path: ['r1'],
    origin: 'a',
    destination: 'b',
    destination_name: 'Gate',
    distance: 100,
    estimated_time: 80,
    risk_score: 2,
    congestion_score: 0,
    congestion_label: 'LOW',
    safety: 'SAFE',
    confidence: 'HIGH',
    people_at_risk: 0,
    bottlenecks: [],
    simulation_id: null,
    route_version: 1,
    created_at: 'T',
    updated_at: 'T',
    source: 'api',
    alternatives: [],
    evacuation: null,
    vehicle: null,
    ...over,
  };
}

beforeEach(() => {
  m.api.routesEvacuation.mockResolvedValue(makeOverview());
  m.api.evacuationStatus.mockResolvedValue({
    ...makeOverview(),
    active_plan: null,
    route_history_recent: [],
  });
  m.api.routeHistory.mockResolvedValue({ history: [], recent_in_memory: [] });
  m.api.emergencyResponseRoutes.mockResolvedValue({
    status: 'NO_SAFE_ROUTE', routes: [], incident_node: null,
    simulation_id: null, generated_at: 'T', vehicles: [],
  });
  m.api.routeCalculate.mockResolvedValue(makePlan());
  m.api.evacuationBuilding.mockResolvedValue({
    building_id: 'eng', building_name: 'Engineering', status: 'READY',
    mode: 'balanced', people_at_risk: 0, occupancy: 200, occupancy_pct: 40,
    affected: false, primary_route: {}, routes: [], exits: [],
    primary_exit: 'East', secondary_exit: '', estimated_evacuation_s: 90,
    route_risk: 5, route_status: 'RECOMMENDED', has_safe_route: true, reason: '',
  });
  m.api.routeAlternatives.mockResolvedValue({
    origin: 'a', destination: 'b', mode: 'balanced', routes: [],
    comparison: { origin: 'a', destination: 'b', rows: [], recommended_mode: 'balanced' },
    simulation_id: null, route_version: 1,
  });

  useTwinStore.setState({
    snapshot: makeSnapshot(),
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
    toast: null,
    toggles: {
      buildings: true, roads: true, sensors: true, zones: false, labels: true,
      parking: true, trees: true, grid: true, heatmap: false,
      occupancy: true, routes: false, night: false, risk: false,
    },
  });
});

describe('route.* WS events', () => {
  it('route.calculated stores the flattened plan and history row', () => {
    useTwinStore.getState().onSocketMessage({ type: 'route.calculated', data: ROUTE_EVENT });
    const st = useTwinStore.getState();
    expect(st.routePlan?.route_id).toBe('rte_ws1');
    expect(st.routePlan?.distance).toBe(146);
    expect(st.routePlan?.mode).toBe('balanced');
    expect(st.routePlan?.destination_name).toBe('Main Gate');
    expect(st.routePlan?.road_path).toEqual(['r_eng_s', 'r_court_main']);
    expect(st.routeHistory[0].route_id).toBe('rte_ws1');
    expect(st.routeHistory[0].event).toBe('route.calculated');
  });

  it('route.updated replaces the plan (higher version wins ordering)', () => {
    useTwinStore.getState().onSocketMessage({ type: 'route.calculated', data: ROUTE_EVENT });
    useTwinStore.getState().onSocketMessage({
      type: 'route.recalculated',
      data: { ...ROUTE_EVENT, route_id: 'rte_ws2', route_version: 4, status: 'ALTERNATIVE' },
    });
    const st = useTwinStore.getState();
    expect(st.routePlan?.route_id).toBe('rte_ws2');
    expect(st.routePlan?.status).toBe('ALTERNATIVE');
    expect(st.routeHistory).toHaveLength(2);
  });

  it('route.invalidated raises a warning toast with the reason', () => {
    useTwinStore.getState().onSocketMessage({
      type: 'route.invalidated',
      data: { route_id: 'rte_ws1', route_version: 3, reason: 'edge_blocked',
              reasons: ['edge_blocked'], blocked_paths: ['r_eng_s'] },
    });
    const st = useTwinStore.getState();
    expect(st.toast?.level).toBe('warn');
    expect(st.toast?.title).toBe('ROUTE INVALIDATED');
    expect(st.toast?.message).toBe('edge_blocked');
  });
});

describe('evacuation.* + bottleneck.* WS events', () => {
  it('evacuation.started activates status, toast and forces the routes layer', () => {
    useTwinStore.getState().onSocketMessage({
      type: 'evacuation.started',
      data: { status: 'ACTIVE', previous_status: 'IDLE', people_at_risk: 420,
              critical_buildings: ['eng'], simulation_id: 'sim_1' },
    });
    const st = useTwinStore.getState();
    expect(st.evacuation?.status).toBe('ACTIVE');
    expect(st.evacuation?.people_at_risk).toBe(420);
    expect(st.toast?.title).toBe('EVACUATION ACTIVE');
    expect(st.toggles.routes).toBe(true);
  });

  it('evacuation.completed clears to a success toast', () => {
    useTwinStore.setState({ evacuation: makeOverview({ status: 'CRITICAL', people_at_risk: 99 }) });
    useTwinStore.getState().onSocketMessage({
      type: 'evacuation.completed',
      data: { status: 'IDLE', previous_status: 'CRITICAL', reason: 'risk returned to safe levels' },
    });
    const st = useTwinStore.getState();
    expect(st.evacuation?.status).toBe('IDLE');
    expect(st.toast?.level).toBe('success');
    expect(st.toast?.title).toBe('EVACUATION CLEARED');
  });

  it('bottleneck.detected prepends and bottleneck.cleared removes', () => {
    const bn = {
      location: 'North Spur', location_id: 'r_north_s', kind: 'EDGE' as const,
      severity: 'HIGH' as const, estimated_people: 620, capacity: 400,
      congestion: 0.8, risk: 12, recommendation: 'Reroute around the congested segment',
      shared_by: ['Engineering'],
    };
    useTwinStore.getState().onSocketMessage({
      type: 'bottleneck.detected', data: { bottleneck: bn },
    });
    expect(useTwinStore.getState().routeBottlenecks).toHaveLength(1);
    expect(useTwinStore.getState().toast?.title).toContain('BOTTLENECK');

    useTwinStore.getState().onSocketMessage({
      type: 'bottleneck.cleared', data: { location_id: 'r_north_s' },
    });
    expect(useTwinStore.getState().routeBottlenecks).toHaveLength(0);
  });
});

describe('route actions', () => {
  it('calculateRoute posts, stores the plan and enables the routes layer', async () => {
    await useTwinStore.getState().calculateRoute('ex_eng_s', 'gate_main', 'safest', 120);
    expect(m.api.routeCalculate).toHaveBeenCalledWith({
      origin: 'ex_eng_s', destination: 'gate_main', mode: 'safest', people: 120,
    });
    const st = useTwinStore.getState();
    expect(st.routePlan?.route_id).toBe('rte_api1');
    expect(st.routeHistory[0].route_id).toBe('rte_api1');
    expect(st.toggles.routes).toBe(true);
    expect(st.routeError).toBeNull();
  });

  it('calculateRoute surfaces API errors honestly', async () => {
    const { ApiError } = await import('../services/api');
    m.api.routeCalculate.mockRejectedValue(new ApiError(400, 'Unknown origin node'));
    await useTwinStore.getState().calculateRoute('nope', 'gate_main');
    const st = useTwinStore.getState();
    expect(st.routePlan).toBeNull();
    expect(st.routeError).toContain('Unknown origin node');
  });

  it('refreshRouteData merges overview, status, history and emergency routes', async () => {
    m.api.routesEvacuation.mockResolvedValue(makeOverview({
      status: 'ACTIVE', people_at_risk: 300, bottleneck_count: 1,
      bottlenecks: [{
        location: 'Gate Main', location_id: 'gate_main', kind: 'EXIT',
        severity: 'MEDIUM', estimated_people: 700, capacity: 500,
        congestion: 0.4, risk: 0, recommendation: 'Distribute evacuation toward an alternative gate',
        shared_by: ['exit capacity'],
      }],
    }));
    m.api.routeHistory.mockResolvedValue({
      history: [{ route_id: 'rte_h1', mode: 'balanced', status: 'RECOMMENDED',
                  route_version: 2, created_at: 'T' }],
      recent_in_memory: [],
    });
    m.api.emergencyResponseRoutes.mockResolvedValue({
      status: 'ok', incident_node: null, simulation_id: null, generated_at: 'T',
      routes: [{
        status: 'SAFE', reason: '', vehicle: 'fire_truck', vehicle_label: 'Fire Truck',
        origin: 'gate_east', destination: 'ex_eng_s', path: ['gate_east', 'ex_eng_s'],
        road_path: ['r_east'], distance: 200, eta_s: 24, risk_score: 10,
        blocked_roads_avoided: [], access_restrictions: [],
      }],
    });
    await useTwinStore.getState().refreshRouteData();
    const st = useTwinStore.getState();
    expect(st.evacuation?.status).toBe('ACTIVE');
    expect(st.routeBottlenecks).toHaveLength(1);
    expect(st.routeHistory[0].route_id).toBe('rte_h1');
    expect(st.emergencyRoutes[0].vehicle).toBe('fire_truck');
    expect(st.routeLoading).toBe(false);
  });

  it('loadBuildingEvacuation stores the §15 plan and ensures the layer', async () => {
    await useTwinStore.getState().loadBuildingEvacuation('eng', 'safest');
    expect(m.api.evacuationBuilding).toHaveBeenCalledWith('eng', 'safest');
    expect(useTwinStore.getState().buildingEvacuation?.building_id).toBe('eng');
    expect(useTwinStore.getState().toggles.routes).toBe(true);
  });

  it('setRoutePanelOpen toggles the panel', () => {
    useTwinStore.getState().setRoutePanelOpen(true);
    expect(useTwinStore.getState().routePanelOpen).toBe(true);
    useTwinStore.getState().setRoutePanelOpen(false);
    expect(useTwinStore.getState().routePanelOpen).toBe(false);
  });
});
