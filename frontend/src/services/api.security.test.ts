import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError, setToken } from './api';

const fetchMock = vi.fn();

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json', ...headers },
  });
}

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock);
  fetchMock.mockReset();
  localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe('Phase 10 — request auth header', () => {
  it('attaches the bearer token when present', async () => {
    setToken('tok-123');
    fetchMock.mockImplementation(() => jsonResponse(200, { ok: true }));
    await api.me();
    const [, init] = fetchMock.mock.calls[0];
    expect((init?.headers as Record<string, string>).Authorization).toBe('Bearer tok-123');
  });

  it('sends no Authorization header without a token', async () => {
    fetchMock.mockImplementation(() => jsonResponse(200, {}));
    await api.health();
    const [, init] = fetchMock.mock.calls[0];
    expect((init?.headers as Record<string, string>).Authorization).toBeUndefined();
  });

  it('never embeds the token in the request URL', async () => {
    setToken('tok-123');
    fetchMock.mockImplementation(() => jsonResponse(200, {}));
    await api.me();
    expect(String(fetchMock.mock.calls[0][0])).not.toContain('tok-123');
  });
});

describe('Phase 10 — 401 handling (§24.7)', () => {
  it('clears the token and dispatches ts:unauthorized', async () => {
    setToken('expired');
    const events: string[] = [];
    const listener = () => events.push('unauthorized');
    window.addEventListener('ts:unauthorized', listener);
    fetchMock.mockImplementation(() => jsonResponse(401, { detail: 'Token expired' }));
    try {
      await expect(api.me()).rejects.toMatchObject({ status: 401 });
      expect(localStorage.getItem('ts_token')).toBeNull();
      expect(events).toEqual(['unauthorized']);
    } finally {
      window.removeEventListener('ts:unauthorized', listener);
    }
  });
});

describe('Phase 10 — 403 handling (§24.10)', () => {
  it('surfaces the server detail when provided', async () => {
    fetchMock.mockImplementation(() => jsonResponse(403, { detail: 'Account disabled' }));
    await expect(api.listUsers()).rejects.toMatchObject({
      status: 403, message: 'Account disabled',
    });
  });

  it('falls back to a friendly access-denied message', async () => {
    fetchMock.mockImplementation(() => jsonResponse(403, {}));
    await expect(api.listUsers()).rejects.toMatchObject({
      status: 403, message: 'Access denied — your role does not permit this action',
    });
  });

  it('does not dispatch ts:unauthorized on 403', async () => {
    const listener = vi.fn();
    window.addEventListener('ts:unauthorized', listener);
    fetchMock.mockImplementation(() => jsonResponse(403, { detail: 'nope' }));
    try {
      await expect(api.auditLogs()).rejects.toBeInstanceOf(ApiError);
      expect(listener).not.toHaveBeenCalled();
    } finally {
      window.removeEventListener('ts:unauthorized', listener);
    }
  });
});

describe('Phase 10 — 429 handling (§13)', () => {
  it('parses Retry-After and exposes it on the error', async () => {
    fetchMock.mockImplementation(() => jsonResponse(429, { detail: 'Too many requests' },
      { 'retry-after': '17' }));
    const err = await api.login('admin', 'x').catch((e: ApiError) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(429);
    expect((err as ApiError).retryAfter).toBe(17);
    expect((err as ApiError).message).toBe('Too many requests');
  });

  it('builds a helpful default message when no detail is present', async () => {
    fetchMock.mockImplementation(() => jsonResponse(429, {}, { 'retry-after': '5' }));
    const err = await api.login('admin', 'x').catch((e: ApiError) => e);
    expect((err as ApiError).message).toContain('retry in 5s');
  });
});

describe('Phase 10 — auth surface endpoints (§5/§6/§15/§17)', () => {
  it('logout POSTs to /api/auth/logout', async () => {
    setToken('tok');
    fetchMock.mockImplementation(() => jsonResponse(200, { ok: true }));
    await api.logout();
    expect(String(fetchMock.mock.calls[0][0])).toBe('/api/auth/logout');
    expect(fetchMock.mock.calls[0][1]?.method).toBe('POST');
  });

  it('changePassword POSTs current + new password', async () => {
    setToken('tok');
    fetchMock.mockImplementation(() => jsonResponse(200, { ok: true, access_token: 'n' }));
    await api.changePassword('OldPass123', 'NewPass123');
    expect(String(fetchMock.mock.calls[0][0])).toBe('/api/auth/change-password');
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      current_password: 'OldPass123', new_password: 'NewPass123',
    });
  });

  it('listUsers / auditLogs / demoAccounts hit the expected routes', async () => {
    setToken('tok');
    fetchMock.mockImplementation(() => jsonResponse(200, { users: [], records: [], actions: [] }));
    await api.listUsers({ q: 'ada', role: 'ADMIN' });
    expect(String(fetchMock.mock.calls[0][0])).toContain('/api/users?q=ada&role=ADMIN');
    await api.auditLogs({ action: 'auth.login', outcome: 'DENIED' });
    expect(String(fetchMock.mock.calls[1][0])).toContain('/api/audit?action=auth.login&outcome=DENIED');
    await api.demoAccounts();
    expect(String(fetchMock.mock.calls[2][0])).toBe('/api/auth/demo');
    // no password material in any of the request bodies
    expect(fetchMock.mock.calls[0][1]?.body).toBeUndefined();
  });

  it('resetUserPassword is a POST without the password in the URL by default', async () => {
    setToken('tok');
    fetchMock.mockImplementation(() => jsonResponse(200, { ok: true, temporary_password: 'x' }));
    await api.resetUserPassword('u_123');
    expect(String(fetchMock.mock.calls[0][0])).toBe('/api/users/u_123/reset-password');
    expect(fetchMock.mock.calls[0][1]?.method).toBe('POST');
  });
});
