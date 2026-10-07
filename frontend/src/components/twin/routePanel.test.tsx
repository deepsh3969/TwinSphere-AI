import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { makeSnapshot } from '../../testFixtures';
import type { BuildingEvacuationPlan, EvacuationOverview, RouteBottleneck, RoutePlan } from '../../types';
import { useTwinStore } from '../../store/useTwinStore';
import RoutePanel from './RoutePanel';

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
  getToken: vi.fn((): string | null => 'test-token'),
  setToken: vi.fn(),
}));

vi.mock('../../services/api', () => ({
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

vi.mock('../../services/ws', () => ({
  TwinSocket: class {
    connect = vi.fn();
    disconnect = vi.fn();
  },
}));

const NODES = [
  { id: 'ex_eng_s', name: 'Engineering South Exit', x: 40, z: -10, kind: 'EXIT', is_exit: true },
  { id: 'gate_main', name: 'Main Gate', x: 0, z: -90, kind: 'GATE', is_exit: false },
];

function makeOverview(over: Partial<EvacuationOverview> = {}): EvacuationOverview {
  return {
    status: 'ACTIVE',
    mode: 'balanced',
    people_at_risk: 240,
    critical_buildings: [],
    blocked_buildings: [],
    totals: { buildings: 6, safe_routes: 5, blocked_routes: 1, bottlenecks: 1 },
    bottleneck_count: 1,
    simulation_id: 'sim_1',
    route_version: 4,
    generated_at: '2026-10-06T10:00:00+00:00',
    buildings: [],
    exits: [],
    bottlenecks: [],
    ...over,
  };
}

function makePlan(over: Partial<RoutePlan> = {}): RoutePlan {
  return {
    route_id: 'rte_t1',
    kind: 'point',
    mode: 'safest',
    status: 'RECOMMENDED',
    reason: 'avoids the hazard zone on Central Road',
    path: ['ex_eng_s', 'gate_main'],
    node_path: ['ex_eng_s', 'court_c', 'gate_main'],
    road_path: ['r_eng_s'],
    origin: 'ex_eng_s',
    destination: 'gate_main',
    destination_name: 'Main Gate',
    distance: 146,
    estimated_time: 108,
    risk_score: 4,
    congestion_score: 0.1,
    congestion_label: 'LOW',
    safety: 'SAFE',
    confidence: 'HIGH',
    people_at_risk: 0,
    bottlenecks: [],
    simulation_id: 'sim_1',
    route_version: 4,
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
    ...makeOverview(), active_plan: makePlan(), route_history_recent: [],
  });
  m.api.routeHistory.mockResolvedValue({
    history: [{ route_id: 'rte_t1', mode: 'safest', status: 'RECOMMENDED', route_version: 4,
                origin: 'ex_eng_s', destination: 'gate_main', risk_score: 4,
                created_at: '2026-10-06T10:00:00+00:00' }],
    recent_in_memory: [],
  });
  m.api.emergencyResponseRoutes.mockResolvedValue({
    status: 'NO_SAFE_ROUTE', routes: [], incident_node: null,
    simulation_id: 'sim_1', generated_at: 'T', vehicles: [],
  });
  m.api.routeCalculate.mockResolvedValue(makePlan({ route_id: 'rte_new', route_version: 5 }));
  m.api.routeAlternatives.mockResolvedValue({
    origin: 'ex_eng_s', destination: 'gate_main', mode: 'balanced', routes: [],
    comparison: {
      origin: 'ex_eng_s', destination: 'gate_main', recommended_mode: 'safest',
      rows: [
        { mode: 'balanced', distance: 160, estimated_time: 120, risk_score: 8,
          congestion_score: 0.2, status: 'ALTERNATIVE', safety: 'SAFE' },
        { mode: 'safest', distance: 146, estimated_time: 108, risk_score: 4,
          congestion_score: 0.1, status: 'RECOMMENDED', safety: 'SAFE', recommended: true },
      ],
    },
    simulation_id: 'sim_1', route_version: 4,
  });
  m.api.routeRecalculate.mockResolvedValue(makePlan({ route_version: 5 }));
  m.api.evacuationBuilding.mockResolvedValue({
    building_id: 'eng', building_name: 'Engineering', status: 'ACTIVE',
    mode: 'safest', people_at_risk: 120, occupancy: 300, occupancy_pct: 55,
    affected: true, primary_route: {}, routes: [],
    exits: [
      { id: 'ex_eng_s', name: 'South Exit', x: 40, z: -10, kind: 'EXIT',
        role: 'PRIMARY', people: 180, capacity: 250, congestion: 0.4, safe: true },
      { id: 'ex_eng_n', name: 'North Exit', x: 40, z: 30, kind: 'EXIT',
        role: 'SECONDARY', people: 80, capacity: 250, congestion: 0.2, safe: true },
    ],
    primary_exit: 'South Exit', secondary_exit: 'North Exit',
    estimated_evacuation_s: 215, route_risk: 6, route_status: 'RECOMMENDED',
    has_safe_route: true, reason: '',
  } as unknown as BuildingEvacuationPlan);

  useTwinStore.setState({
    snapshot: makeSnapshot({ nodes: NODES }),
    routePlan: null,
    routeAlternatives: null,
    buildingEvacuation: null,
    evacuation: makeOverview(),
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
      occupancy: true, routes: true, night: false, risk: false,
    },
  });
});

describe('RoutePanel', () => {
  it('renders the evacuation strip, calculator and default empty states', () => {
    render(<RoutePanel />);
    expect(screen.getByText('Routes & Evacuation')).toBeTruthy();
    expect(screen.getAllByText('ACTIVE').length).toBeGreaterThanOrEqual(2); // header + strip
    expect(screen.getByText('240')).toBeTruthy(); // people at risk
    expect(screen.getByText('Route calculator (A*)')).toBeTruthy();
    expect(screen.getByText('No active plan — calculate a route or start an emergency simulation.'))
      .toBeTruthy();
    expect(screen.getByText('No capacity bottlenecks detected.')).toBeTruthy();
  });

  it('renders the active plan with metrics, status chip and reason', () => {
    useTwinStore.setState({ routePlan: makePlan() });
    render(<RoutePanel />);
    expect(screen.getByText('RECOMMENDED')).toBeTruthy();
    expect(screen.getByText('146m')).toBeTruthy();
    expect(screen.getByText('1m 48s')).toBeTruthy(); // ETA formatting
    expect(screen.getByText('avoids the hazard zone on Central Road')).toBeTruthy();
    expect(screen.getAllByText('v4').length).toBeGreaterThanOrEqual(2); // header + plan
  });

  it('Calculate posts origin, destination and the selected mode', async () => {
    const user = userEvent.setup();
    render(<RoutePanel />);
    await waitFor(() => {
      expect((screen.getByLabelText(/Origin/) as HTMLSelectElement).value).toBe('ex_eng_s');
    });
    await user.click(screen.getByRole('button', { name: /safest/i }));
    await user.click(screen.getByRole('button', { name: /Calculate/i }));
    await waitFor(() => {
      expect(m.api.routeCalculate).toHaveBeenCalledWith({
        origin: 'ex_eng_s', destination: 'gate_main', mode: 'safest',
      });
    });
  });

  it('Compare loads the cross-mode comparison table', async () => {
    const user = userEvent.setup();
    render(<RoutePanel />);
    await user.click(screen.getByRole('button', { name: 'Compare' }));
    await waitFor(() => {
      expect(screen.getByText('Cross-mode comparison')).toBeTruthy();
      expect(screen.getAllByText('safest').length).toBeGreaterThanOrEqual(2); // chip + table row
    });
    expect(m.api.routeAlternatives).toHaveBeenCalledWith(
      'ex_eng_s', 'gate_main', 'balanced');
  });

  it('Recalculate calls the refresh endpoint', async () => {
    useTwinStore.setState({ routePlan: makePlan() });
    const user = userEvent.setup();
    render(<RoutePanel />);
    await user.click(screen.getByRole('button', { name: /Recalculate/i }));
    await waitFor(() => expect(m.api.routeRecalculate).toHaveBeenCalledWith({ mode: 'safest' }));
  });

  it('plans a building evacuation via the Plan button', async () => {
    const user = userEvent.setup();
    render(<RoutePanel />);
    await user.click(screen.getByRole('button', { name: /Plan/i }));
    await waitFor(() => {
      expect(m.api.evacuationBuilding).toHaveBeenCalledWith('eng', 'balanced');
      expect(screen.getByText('South Exit · primary')).toBeTruthy();
      expect(screen.getByText(/120 at risk/)).toBeTruthy();
    });
  });

  it('lists detected bottlenecks with capacity and recommendation', () => {
    const bn: RouteBottleneck = {
      location: 'North Spur', location_id: 'r_north_s', kind: 'EDGE', severity: 'HIGH',
      estimated_people: 620, capacity: 400, congestion: 0.8, risk: 12,
      recommendation: 'Reroute around the congested segment', shared_by: ['Engineering'],
    };
    useTwinStore.setState({ routeBottlenecks: [bn] });
    render(<RoutePanel />);
    expect(screen.getByText('North Spur')).toBeTruthy();
    expect(screen.getByText('HIGH · EDGE')).toBeTruthy();
    expect(screen.getByText(/620 people \/ 400 capacity/)).toBeTruthy();
    expect(screen.getByText('Reroute around the congested segment')).toBeTruthy();
  });

  it('shows route history rows when present', () => {
    useTwinStore.setState({
      routeHistory: [{
        route_id: 'rte_t1', mode: 'safest', status: 'RECOMMENDED', route_version: 4,
        origin: 'ex_eng_s', destination: 'gate_main', risk_score: 4, event: 'route.calculated',
        created_at: '2026-10-06T10:00:00+00:00',
      }],
    });
    render(<RoutePanel />);
    expect(screen.getByText(/route calculated/i)).toBeTruthy();
  });

  it('overlay variant exposes a close button', async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<RoutePanel onClose={onClose} />);
    await user.click(screen.getByTitle('Close'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('disables Calculate when origin equals destination', () => {
    useTwinStore.setState({
      snapshot: makeSnapshot({ nodes: [NODES[0]] }),
      evacuation: makeOverview(),
    });
    render(<RoutePanel />);
    const calc = screen.getByRole('button', { name: /Calculate/i }) as HTMLButtonElement;
    expect(calc.disabled).toBe(true);
  });
});
