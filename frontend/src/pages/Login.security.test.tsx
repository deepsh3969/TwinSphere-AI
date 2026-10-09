import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useTwinStore } from '../store/useTwinStore';
import Login from './Login';

const m = vi.hoisted(() => ({
  api: {
    login: vi.fn(),
    demoAccounts: vi.fn(),
    health: vi.fn(),
    me: vi.fn(),
    logout: vi.fn(),
    register: vi.fn(),
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

function renderLogin() {
  return render(
    <MemoryRouter initialEntries={['/login']}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/dashboard" element={<div data-testid="dashboard-stub" />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  m.api.login.mockReset();
  m.api.demoAccounts.mockReset();
  m.api.demoAccounts.mockResolvedValue({
    enabled: true,
    registration_enabled: true,
    users: [
      { username: 'admin', role: 'ADMIN', desc: 'Full access' },
      { username: 'viewer', role: 'VIEWER', desc: 'Read-only' },
    ],
  });
  useTwinStore.setState({ token: null, authError: null, authLoading: false, user: null });
});

describe('Phase 10 §23 — demo accounts are server-driven', () => {
  it('renders accounts from /api/auth/demo with the DEMO development label', async () => {
    renderLogin();
    expect(await screen.findByText('admin')).toBeInTheDocument();
    expect(screen.getByText('viewer')).toBeInTheDocument();
    expect(screen.getByText(/DEMO — local development/i)).toBeInTheDocument();
    expect(m.api.demoAccounts).toHaveBeenCalledTimes(1);
  });

  it('fills only the username when a demo account is clicked (no hardcoded password)', async () => {
    renderLogin();
    const button = await screen.findByText('admin');
    fireEvent.click(button.closest('button')!);
    expect(screen.getByLabelText(/username/i)).toHaveValue('admin');
    expect(screen.getByLabelText(/password/i)).toHaveValue('');
  });

  it('hides the demo section when the endpoint reports it disabled', async () => {
    m.api.demoAccounts.mockResolvedValue({ enabled: false, registration_enabled: false, users: [] });
    renderLogin();
    await waitFor(() => expect(m.api.demoAccounts).toHaveBeenCalled());
    expect(screen.queryByText(/Demo accounts/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/DEMO — local development/i)).not.toBeInTheDocument();
  });

  it('still renders the form when the demo endpoint fails', async () => {
    m.api.demoAccounts.mockRejectedValue(new Error('offline'));
    renderLogin();
    expect(await screen.findByRole('button', { name: /sign in/i })).toBeInTheDocument();
    expect(screen.queryByText(/Demo accounts/i)).not.toBeInTheDocument();
  });
});

describe('Phase 10 §24 — login errors', () => {
  it('submits typed credentials to the API', async () => {
    m.api.login.mockResolvedValue({ access_token: 't', user: { id: 'u', username: 'me', role: 'VIEWER' } });
    renderLogin();
    fireEvent.change(screen.getByLabelText(/username/i), { target: { value: 'eve' } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'guess1234' } });
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));
    await waitFor(() => expect(m.api.login).toHaveBeenCalledWith('eve', 'guess1234'));
    expect(await screen.findByTestId('dashboard-stub')).toBeInTheDocument();
  });

  it('surfaces an access-denied (403) login failure', async () => {
    const { ApiError } = await import('../services/api');
    m.api.login.mockRejectedValue(new ApiError(403, 'Account disabled'));
    renderLogin();
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));
    expect(await screen.findByText('Account disabled')).toBeInTheDocument();
    expect(screen.queryByTestId('dashboard-stub')).not.toBeInTheDocument();
  });

  it('surfaces invalid credentials (401) from the store', async () => {
    const { ApiError } = await import('../services/api');
    m.api.login.mockRejectedValue(new ApiError(401, 'Invalid credentials'));
    renderLogin();
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));
    expect(await screen.findByText('Invalid credentials')).toBeInTheDocument();
  });
});
