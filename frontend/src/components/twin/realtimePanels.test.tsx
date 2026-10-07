import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useTwinStore } from '../../store/useTwinStore';
import type { LiveLogEntry, RealtimeStatus, SystemStatusInfo, User } from '../../types';
import LiveEvents from './LiveEvents';
import SimControlPanel from './SimControlPanel';
import SystemStatus from './SystemStatus';

const m = vi.hoisted(() => ({
  api: {
    realtimeStatus: vi.fn(),
    realtimeAction: vi.fn(),
    realtimeSpeed: vi.fn(),
  },
  getToken: vi.fn((): string | null => null),
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

function makeRealtime(over: Partial<RealtimeStatus> = {}): RealtimeStatus {
  return {
    status: 'RUNNING', speed: 1, simulation_time: 4000, clock: 40000, clock_hour: 11.5,
    last_tick: '2026-10-05T11:30:00Z', tick_count: 5, sensor_interval: 2, enabled: true,
    connected_clients: 1, data_source: 'SIMULATED', seed: 42, scenario: null,
    scenario_status: null, ...over,
  };
}

function makeSystemStatus(over: Partial<SystemStatusInfo> = {}): SystemStatusInfo {
  return {
    backend: true, database: true, websocket: true, simulator: 'RUNNING', ai: true,
    connected_clients: 2, clock_hour: 11.5, speed: 2, risk_level: 'LOW', incidents: 0,
    ...over,
  };
}

function setUser(role: User['role']) {
  useTwinStore.setState({ user: { id: 'u1', username: role.toLowerCase(), role } });
}

beforeEach(() => {
  m.api.realtimeAction.mockReset();
  m.api.realtimeSpeed.mockReset();
  m.api.realtimeStatus.mockResolvedValue(makeRealtime());
  useTwinStore.setState({
    realtime: makeRealtime(),
    realtimeBusy: false,
    systemStatus: null,
    liveLog: [],
    user: null,
    connection: 'CONNECTED',
    snapshot: null,
  });
});

describe('SimControlPanel', () => {
  it('renders live status, sim clock and speed', () => {
    render(<SimControlPanel />);
    expect(screen.getByTestId('sim-status-chip')).toHaveTextContent('RUNNING');
    expect(screen.getByTestId('sim-clock')).toHaveTextContent('11:30');
    expect(screen.getByText('SIMULATED')).toBeInTheDocument();
  });

  it('sends pause when the simulator is running', async () => {
    m.api.realtimeAction.mockResolvedValue(makeRealtime({ status: 'PAUSED' }));
    setUser('OPERATOR');
    render(<SimControlPanel />);
    await userEvent.click(screen.getByRole('button', { name: /pause/i }));
    expect(m.api.realtimeAction).toHaveBeenCalledWith('pause');
    expect(useTwinStore.getState().realtime?.status).toBe('PAUSED');
  });

  it('shows Start only when the simulator is stopped', () => {
    useTwinStore.setState({ realtime: makeRealtime({ status: 'STOPPED' }) });
    setUser('OPERATOR');
    render(<SimControlPanel />);
    expect(screen.getByRole('button', { name: /start simulation/i })).toBeEnabled();
    expect(screen.queryByRole('button', { name: /pause/i })).not.toBeInTheDocument();
    expect(screen.getByTestId('sim-status-chip')).toHaveTextContent('STOPPED');
  });

  it('disables controls for read-only roles (viewer)', () => {
    setUser('VIEWER');
    render(<SimControlPanel />);
    expect(screen.getByRole('button', { name: /pause/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /reset/i })).toBeDisabled();
    expect(screen.getByText(/read-only access/i)).toBeInTheDocument();
  });

  it('sends the selected speed for operators', async () => {
    m.api.realtimeSpeed.mockResolvedValue(makeRealtime({ speed: 5 }));
    setUser('ADMIN');
    render(<SimControlPanel />);
    await userEvent.click(screen.getByRole('button', { name: '5x' }));
    expect(m.api.realtimeSpeed).toHaveBeenCalledWith(5);
    expect(useTwinStore.getState().realtime?.speed).toBe(5);
  });
});

describe('SystemStatus', () => {
  it('renders the streamed system status payload', () => {
    useTwinStore.setState({ systemStatus: makeSystemStatus({ database: false, speed: 2 }) });
    render(<SystemStatus />);
    expect(screen.getByTestId('system-status')).toHaveTextContent('STREAMING');
    expect(screen.getByText('DOWN')).toBeInTheDocument(); // database
    expect(screen.getByText('RUNNING · 2x')).toBeInTheDocument();
    expect(screen.getByText('READY')).toBeInTheDocument(); // AI
  });

  it('falls back to realtime/snapshot facts before the first status event', () => {
    useTwinStore.setState({
      systemStatus: null,
      realtime: makeRealtime({ status: 'PAUSED', speed: 10 }),
      snapshot: null,
    });
    render(<SystemStatus />);
    expect(screen.getByText('PAUSED · 10x')).toBeInTheDocument();
    expect(screen.getByText('11:30')).toBeInTheDocument();
  });
});

describe('LiveEvents', () => {
  it('shows an honest empty state when nothing has been observed', () => {
    render(<LiveEvents />);
    expect(screen.getByTestId('live-events')).toHaveTextContent('No live events observed yet');
  });

  it('renders observed events newest-first', () => {
    const entries: LiveLogEntry[] = [
      { id: 2, ts: Date.now(), level: 'info', kind: 'control', title: 'Simulation resumed', detail: '11:30 · 2x' },
      { id: 1, ts: Date.now() - 5000, level: 'warn', kind: 'sim_status', title: 'Simulator paused' },
    ];
    useTwinStore.setState({ liveLog: entries });
    render(<LiveEvents />);
    const items = screen.getAllByTestId('live-event-item');
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent('Simulation resumed');
    expect(items[1]).toHaveTextContent('Simulator paused');
  });
});
