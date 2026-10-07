import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { makeBuildingDetail, makeHistory, makeSnapshot } from '../testFixtures';
import { useTwinStore } from '../store/useTwinStore';
import TwinExplorer from './TwinExplorer';

vi.mock('../components/3d/CampusScene', () => ({
  default: () => <div data-testid="campus-scene" />,
}));

const m = vi.hoisted(() => ({
  api: {
    login: vi.fn(),
    register: vi.fn(),
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

function readyStore() {
  useTwinStore.setState({
    snapshot: makeSnapshot(),
    connection: 'CONNECTED',
    backendOffline: false,
    token: 'test-token',
    lastUpdate: Date.now(),
  });
}

beforeEach(() => {
  m.api.building.mockResolvedValue(makeBuildingDetail());
  m.api.buildingFloors.mockResolvedValue([]);
  m.api.sensorHistory.mockResolvedValue(makeHistory());
  m.api.sensors.mockResolvedValue([]);
  m.api.zones.mockResolvedValue([]);
  // pending forever: useCampus' summary refresh must not resolve mid-test
  m.api.campus.mockImplementation(() => new Promise(() => {}));
  m.api.health.mockResolvedValue({ status: 'ok' });
  m.api.analystStatus.mockResolvedValue({ analyst: { status: 'FALLBACK' } });

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
  });
});

describe('TwinExplorer page states', () => {
  it('shows the staged loader while campus data is absent', () => {
    render(<TwinExplorer />);
    expect(screen.getByTestId('twin-loader')).toBeInTheDocument();
    expect(screen.getByText('INITIALIZING DIGITAL TWIN')).toBeInTheDocument();
  });

  it('shows the connection error panel and retries on demand', async () => {
    useTwinStore.setState({ snapshot: null, backendOffline: true });
    const retry = vi.fn();
    useTwinStore.setState({ retryConnection: retry });

    render(<TwinExplorer />);
    expect(screen.getByTestId('twin-error')).toBeInTheDocument();
    expect(screen.getByText('DIGITAL TWIN CONNECTION ERROR')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /retry connection/i }));
    expect(retry).toHaveBeenCalledTimes(1);
  });

  it('renders the twin shell once data is ready', () => {
    readyStore();
    render(<TwinExplorer />);

    expect(screen.getByTestId('campus-scene')).toBeInTheDocument();
    expect(screen.getByText('Twin View')).toBeInTheDocument();
    expect(screen.getByText('DIGITAL TWIN')).toBeInTheDocument();
    expect(screen.getByText('CAMPUS OVERVIEW')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Computer Science Block/ })).toBeInTheDocument();
    expect(screen.getAllByText('SIMULATED').length).toBeGreaterThan(0);
  });
});

describe('TwinExplorer interactions', () => {
  it('toggles a layer from the layer panel', async () => {
    readyStore();
    render(<TwinExplorer />);

    const zonesBox = screen.getByRole('checkbox', { name: 'Zones' });
    expect(zonesBox).toHaveAttribute('aria-checked', 'false');

    await userEvent.click(zonesBox);
    expect(useTwinStore.getState().toggles.zones).toBe(true);
    expect(screen.getByRole('checkbox', { name: 'Zones' })).toHaveAttribute('aria-checked', 'true');
  });

  it('switches view modes from the toolbar', async () => {
    readyStore();
    render(<TwinExplorer />);

    await userEvent.click(screen.getByRole('button', { name: 'Sensors' }));
    expect(useTwinStore.getState().viewMode).toBe('sensors');
    expect(useTwinStore.getState().toggles.labels).toBe(false);
  });

  it('opens the building inspector from the rail with derived floor chips', async () => {
    readyStore();
    render(<TwinExplorer />);

    await userEvent.click(screen.getByRole('button', { name: /Computer Science Block/ }));
    expect(await screen.findByLabelText('Close inspector')).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: 'All Floors' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Ground' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Computer Science Block/ })).toBeInTheDocument();
    expect(useTwinStore.getState().selectedBuildingId).toBe('b-cs');
  });

  it('drills building → sensor chip → sensor inspector with 24 h history', async () => {
    readyStore();
    render(<TwinExplorer />);

    await userEvent.click(screen.getByRole('button', { name: /Computer Science Block/ }));
    await screen.findByRole('button', { name: 'All Floors' });

    await userEvent.click(screen.getByRole('button', { name: 'T-001' }));
    expect(await screen.findByText(/Last 24 Hours/)).toBeInTheDocument();
    expect(useTwinStore.getState().selectedSensorId).toBe('sensor-1');
    await waitFor(() => expect(useTwinStore.getState().sensorHistory).not.toBeNull());
  });

  it('returns to the campus overview when the sensor inspector closes', async () => {
    readyStore();
    useTwinStore.setState({ selectedSensorId: 'sensor-1', sensorHistory: makeHistory() });

    render(<TwinExplorer />);
    expect(screen.getByText(/Last 24 Hours/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Close sensor inspector' }));
    expect(screen.getByText('CAMPUS OVERVIEW')).toBeInTheDocument();
    expect(useTwinStore.getState().selectedSensorId).toBeNull();
  });

  it('shows the realtime sim panel and the live tab (Phase 4)', async () => {
    readyStore();
    render(<TwinExplorer />);

    // sim controls live in the viewport (desktop rail area)
    expect(screen.getByTestId('sim-control-panel')).toBeInTheDocument();
    expect(screen.getByTestId('live-badge')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'live' }));
    expect(screen.getByTestId('live-tab')).toBeInTheDocument();
    expect(screen.getByTestId('system-status')).toBeInTheDocument();
    expect(screen.getByTestId('live-events')).toBeInTheDocument();
  });
});
