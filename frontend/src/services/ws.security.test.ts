import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TwinSocket } from './ws';

class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  static instances: MockWebSocket[] = [];

  url: string;
  readyState = MockWebSocket.CONNECTING;
  sent: string[] = [];
  closeCalls = 0;
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: ((ev: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  send(data: string) { this.sent.push(data); }
  close() { this.closeCalls += 1; this.readyState = MockWebSocket.CLOSED; }

  static last(): MockWebSocket {
    return MockWebSocket.instances[MockWebSocket.instances.length - 1];
  }
}

let events: string[] = [];
const unauthorized = () => events.push('unauthorized');

beforeEach(() => {
  MockWebSocket.instances = [];
  events = [];
  localStorage.clear();
  vi.stubGlobal('WebSocket', MockWebSocket);
  window.addEventListener('ts:unauthorized', unauthorized);
});

afterEach(() => {
  window.removeEventListener('ts:unauthorized', unauthorized);
  vi.unstubAllGlobals();
  localStorage.clear();
});

function makeSocket() {
  return new TwinSocket(
    () => { /* status */ },
    () => { /* message */ },
  );
}

describe('Phase 10 §22 — WebSocket token transport', () => {
  it('never puts the token in the URL (server refuses query tokens)', () => {
    localStorage.setItem('ts_token', 'secret-token');
    const sock = makeSocket();
    sock.connect();
    const ws = MockWebSocket.last();
    expect(ws.url).toBe(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
    expect(ws.url).not.toContain('token');
    expect(ws.url).not.toContain('secret-token');
    sock.disconnect();
  });

  it('sends an auth message as the first frame after open', () => {
    localStorage.setItem('ts_token', 'secret-token');
    const sock = makeSocket();
    sock.connect();
    const ws = MockWebSocket.last();
    ws.readyState = MockWebSocket.OPEN;
    ws.onopen?.();
    expect(ws.sent).toHaveLength(1);
    expect(JSON.parse(ws.sent[0])).toEqual({ type: 'auth', token: 'secret-token' });
    sock.disconnect();
  });

  it('closes without sending anything when no token exists', () => {
    const sock = makeSocket();
    sock.connect();
    const ws = MockWebSocket.last();
    ws.readyState = MockWebSocket.OPEN;
    ws.onopen?.();
    expect(ws.sent).toHaveLength(0);
    expect(ws.closeCalls).toBeGreaterThan(0);
    sock.disconnect();
  });
});

describe('Phase 10 §22 — close code 4401 handling', () => {
  it('dispatches ts:unauthorized when the presented session is revoked', () => {
    localStorage.setItem('ts_token', 'secret-token');
    const sock = makeSocket();
    sock.connect();
    const ws = MockWebSocket.last();
    ws.readyState = MockWebSocket.OPEN;
    ws.onopen?.();
    ws.onclose?.({ code: 4401 });
    expect(events).toEqual(['unauthorized']);
    sock.disconnect();
  });

  it('does NOT sign the user out when the token was renewed locally (password change)', () => {
    localStorage.setItem('ts_token', 'old-token');
    const sock = makeSocket();
    sock.connect();
    const ws = MockWebSocket.last();
    ws.readyState = MockWebSocket.OPEN;
    ws.onopen?.();
    // session renewed while the old socket was still open
    localStorage.setItem('ts_token', 'new-token');
    ws.onclose?.({ code: 4401 });
    expect(events).toEqual([]);
    sock.disconnect();
  });

  it('ignores ordinary network closes (reconnect path, no logout)', () => {
    localStorage.setItem('ts_token', 'secret-token');
    const sock = makeSocket();
    sock.connect();
    const ws = MockWebSocket.last();
    ws.readyState = MockWebSocket.OPEN;
    ws.onopen?.();
    ws.onclose?.({ code: 1006 });
    expect(events).toEqual([]);
    sock.disconnect();
  });
});

describe('Phase 10 §22 — inbound frames', () => {
  it('passes typed frames through and drops pong keep-alives', () => {
    localStorage.setItem('ts_token', 'secret-token');
    const received: Array<{ type?: string }> = [];
    const sock = new TwinSocket(() => { /* status */ }, (msg) => received.push(msg));
    sock.connect();
    const ws = MockWebSocket.last();
    ws.readyState = MockWebSocket.OPEN;
    ws.onopen?.();
    ws.onmessage?.({ data: JSON.stringify({ type: 'state', payload: {} }) });
    ws.onmessage?.({ data: JSON.stringify({ type: 'pong' }) });
    expect(received).toHaveLength(1);
    expect(received[0].type).toBe('state');
    // malformed frames are ignored, not thrown
    ws.onmessage?.({ data: 'not json' });
    expect(received).toHaveLength(1);
    sock.disconnect();
  });
});
