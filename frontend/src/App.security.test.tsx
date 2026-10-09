import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';
import { useTwinStore } from './store/useTwinStore';
import type { Role, UserProfile } from './types';

// Route-level isolation: only Login (real), AdminUsers (real) and AuditLog
// (real) matter here — every other page is a light stub.
vi.mock('./pages/Landing', () => ({ default: () => <div data-testid="landing-stub" /> }));
vi.mock('./pages/Dashboard', () => ({ default: () => <div data-testid="dashboard-stub" /> }));
vi.mock('./pages/TwinExplorer', () => ({ default: () => <div>twin</div> }));
vi.mock('./pages/SimulationCenter', () => ({ default: () => <div>sim</div> }));
vi.mock('./pages/AIIntelligence', () => ({ default: () => <div>ai</div> }));
vi.mock('./pages/Analytics', () => ({ default: () => <div>analytics</div> }));
vi.mock('./pages/History', () => ({ default: () => <div>history</div> }));
vi.mock('./pages/Settings', () => ({ default: () => <div>settings</div> }));
vi.mock('./components/3d/CampusScene', () => ({ default: () => <div data-testid="campus-scene" /> }));

const m = vi.hoisted(() => ({
  api: {
    login: vi.fn(),
    register: vi.fn(),
    logout: vi.fn(),
    me: vi.fn(),
    health: vi.fn(),
    campus: vi.fn(),
    simulations: vi.fn(),
    realtimeStatus: vi.fn(),
    analyst: vi.fn(),
    analystStatus: vi.fn(),
    anomalies: vi.fn(),
    aiPredictions: vi.fn(),
    aiEvents: vi.fn(),
    aiStatus: vi.fn(),
    risk: vi.fn(),
    routesEvacuation: vi.fn(),
    evacuationStatus: vi.fn(),
    routeHistory: vi.fn(),
    emergencyResponseRoutes: vi.fn(),
    demoAccounts: vi.fn(),
    listUsers: vi.fn(),
    auditLogs: vi.fn(),
    auditActions: vi.fn(),
  },
  getToken: vi.fn((): string | null => null),
  setToken: vi.fn(),
}));

vi.mock('./services/api', () => ({
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

vi.mock('./services/ws', () => ({
  TwinSocket: class {
    connect = vi.fn();
    disconnect = vi.fn();
  },
}));

function profile(role: Role, username = 'tester'): UserProfile {
  return {
    id: `u_${username}`, username, email: `${username}@t.local`,
    role, is_active: true,
  };
}

function seedAuth(token: string | null, user: UserProfile | null) {
  useTwinStore.setState({ token, user, authError: null, authLoading: false });
}

beforeEach(() => {
  localStorage.clear();
  for (const fn of Object.values(m.api)) fn.mockReset();
  m.api.logout.mockResolvedValue({ ok: true });
  m.api.health.mockResolvedValue({ status: 'ok' });
  m.api.me.mockResolvedValue(profile('ADMIN'));
  m.api.campus.mockResolvedValue(null);
  m.api.simulations.mockResolvedValue({ active: null, history: [] });
  m.api.realtimeStatus.mockResolvedValue(null);
  m.api.analyst.mockResolvedValue({ source: 'local_fallback' });
  m.api.analystStatus.mockResolvedValue(null);
  m.api.anomalies.mockResolvedValue(null);
  m.api.aiPredictions.mockResolvedValue(null);
  m.api.aiEvents.mockResolvedValue(null);
  m.api.aiStatus.mockResolvedValue(null);
  m.api.risk.mockResolvedValue(null);
  m.api.routesEvacuation.mockResolvedValue(null);
  m.api.evacuationStatus.mockResolvedValue(null);
  m.api.routeHistory.mockResolvedValue(null);
  m.api.emergencyResponseRoutes.mockResolvedValue(null);
  m.api.demoAccounts.mockResolvedValue({ enabled: false, registration_enabled: false, users: [] });
  m.api.listUsers.mockResolvedValue({
    users: [profile('ADMIN', 'admin')], total: 1, page: 1, page_size: 10, pages: 1,
    active_admins: 1,
  });
  m.api.auditLogs.mockResolvedValue({
    records: [], total: 0, page: 1, page_size: 25, pages: 1, scope: 'operational',
  });
  m.api.auditActions.mockResolvedValue({ actions: [], actors: [], outcomes: [] });
  seedAuth(null, null);
});

describe('Phase 10 §9/§23 — authentication gate', () => {
  it('redirects anonymous visitors away from protected admin routes to /login', async () => {
    window.history.pushState({}, '', '/admin/users');
    render(<App />);
    expect(await screen.findByText(/Operator sign in/i)).toBeInTheDocument();
    expect(screen.queryByTestId('users-table')).not.toBeInTheDocument();
    expect(window.location.pathname).toBe('/login');
  });
});

describe('Phase 10 §9 — role-gated admin routes', () => {
  it('hydrates the profile and renders User Administration for an ADMIN', async () => {
    window.history.pushState({}, '', '/admin/users');
    seedAuth('token-abc', null); // profile not loaded yet → /me decides
    m.api.me.mockResolvedValue(profile('ADMIN', 'boss'));
    render(<App />);
    expect(await screen.findByTestId('users-table')).toBeInTheDocument();
    // heading + role-aware nav entry
    expect(screen.getAllByText(/User Administration/i).length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText(/Audit Log/i).length).toBeGreaterThanOrEqual(1);
  });

  it('kicks a VIEWER from /admin/users back to the dashboard', async () => {
    window.history.pushState({}, '', '/admin/users');
    m.api.me.mockResolvedValue(profile('VIEWER', 'watcher'));
    seedAuth('token-abc', profile('VIEWER', 'watcher'));
    render(<App />);
    expect(await screen.findByTestId('dashboard-stub')).toBeInTheDocument();
    expect(screen.queryByTestId('users-table')).not.toBeInTheDocument();
    expect(window.location.pathname).toBe('/dashboard');
  });

  it('lets an OPERATOR open the audit log but not user administration', async () => {
    window.history.pushState({}, '', '/admin/audit');
    m.api.me.mockResolvedValue(profile('OPERATOR', 'op'));
    seedAuth('token-abc', profile('OPERATOR', 'op'));
    m.api.auditLogs.mockResolvedValue({
      records: [], total: 0, page: 1, page_size: 25, pages: 1, scope: 'operational',
    });
    render(<App />);
    expect(await screen.findByTestId('audit-table')).toBeInTheDocument();
    expect(screen.getByText(/OPERATIONAL SCOPE/i)).toBeInTheDocument();
    // no user administration nav entry for operators
    expect(screen.queryByText(/User Administration/i)).not.toBeInTheDocument();
  });

  it('kicks a VIEWER from /admin/audit back to the dashboard', async () => {
    window.history.pushState({}, '', '/admin/audit');
    m.api.me.mockResolvedValue(profile('VIEWER', 'watcher'));
    seedAuth('token-abc', profile('VIEWER', 'watcher'));
    render(<App />);
    expect(await screen.findByTestId('dashboard-stub')).toBeInTheDocument();
    expect(screen.queryByTestId('audit-table')).not.toBeInTheDocument();
  });

  it('shows the loading placeholder until the profile arrives', async () => {
    window.history.pushState({}, '', '/admin/users');
    seedAuth('token-abc', null);
    let release: (v: UserProfile) => void = () => {};
    m.api.me.mockReturnValue(new Promise((res) => { release = res; }));
    render(<App />);
    expect(screen.getByText(/Loading session/i)).toBeInTheDocument();
    release(profile('ADMIN', 'boss'));
    await waitFor(() => expect(screen.getByTestId('users-table')).toBeInTheDocument());
  });
});

describe('Phase 10 §24.7 — 401 during session', () => {
  it('signs the user out when ts:unauthorized fires', async () => {
    window.history.pushState({}, '', '/admin/users');
    seedAuth('token-abc', profile('ADMIN', 'boss'));
    render(<App />);
    await screen.findByTestId('users-table');
    window.dispatchEvent(new CustomEvent('ts:unauthorized'));
    expect(await screen.findByText(/Operator sign in/i)).toBeInTheDocument();
    expect(useTwinStore.getState().token).toBeNull();
    expect(m.api.logout).toHaveBeenCalled();
  });
});
