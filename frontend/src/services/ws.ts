import type { ConnectionStatus } from '../types';

export interface WSMessage {
  type:
    | 'state' | 'simulation' | 'event' | 'analyst' | 'pong'
    // Phase 4 typed live events (versioned envelopes carry `data`)
    | 'sensor.batch_update' | 'occupancy.update' | 'building.update'
    | 'simulation.status' | 'system.status'
    // Phase 5 AI cycle events (ai scheduler fan-out)
    | 'ai.anomaly' | 'ai.prediction' | 'risk.update'
    // Phase 6 emergency simulation events (§27)
    | 'simulation.created' | 'simulation.started' | 'simulation.paused'
    | 'simulation.resumed' | 'simulation.reset' | 'simulation.completed'
    | 'simulation.recovery_started' | 'simulation.recovery_progress'
    | 'simulation.recovered' | 'simulation.tick' | 'simulation.zone_update'
    | 'simulation.sensor_update' | 'simulation.risk_update'
    // Phase 7 route & evacuation events (§26)
    | 'route.calculated' | 'route.updated' | 'route.invalidated'
    | 'route.recalculated' | 'emergency_route.updated'
    | 'evacuation.started' | 'evacuation.updated' | 'evacuation.completed'
    | 'bottleneck.detected' | 'bottleneck.cleared'
    // Phase 8 analyst decision-support events (§58)
    | 'analyst.analysis_started' | 'analyst.analysis_completed'
    | 'analyst.analysis_updated' | 'analyst.recommendation_created'
    | 'analyst.alert_created';
  payload?: unknown;
  data?: unknown;
  event?: string;
  event_version?: number;
  timestamp?: string;
  source?: string;
}

type StatusHandler = (status: ConnectionStatus) => void;
type MessageHandler = (msg: WSMessage) => void;

const WS_BASE = (import.meta.env.VITE_WS_URL as string | undefined) ?? '';

/** Client→server heartbeat: proves the uplink works even when the server is
 * quiet (Phase 4 §14). Backend answers literal "ping" with a pong frame. */
const PING_INTERVAL_MS = 4000;

export class TwinSocket {
  private ws: WebSocket | null = null;
  private retries = 0;
  private timer: number | null = null;
  private silentTimer: number | null = null;
  private pingTimer: number | null = null;
  private stopped = false;
  status: ConnectionStatus = 'OFFLINE';

  constructor(
    private onStatus: StatusHandler,
    private onMessage: MessageHandler,
  ) {}

  private resolveUrl(): string {
    const token = localStorage.getItem('ts_token');
    if (WS_BASE) {
      return `${WS_BASE}${token ? `?token=${encodeURIComponent(token)}` : ''}`;
    }
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    return `${proto}://${window.location.host}/ws${token ? `?token=${encodeURIComponent(token)}` : ''}`;
  }

  connect() {
    this.stopped = false;
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) return;
    try {
      this.ws = new WebSocket(this.resolveUrl());
    } catch {
      this.setStatus('OFFLINE');
      this.scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      this.retries = 0;
      this.setStatus('CONNECTED');
      this.armSilenceTimer();
      this.startPing();
    };
    this.ws.onmessage = (ev) => {
      this.armSilenceTimer();
      if (this.status !== 'CONNECTED') this.setStatus('CONNECTED');
      try {
        const msg = JSON.parse(ev.data as string) as WSMessage;
        if (msg.type !== 'pong') this.onMessage(msg);
      } catch {
        /* ignore malformed frames */
      }
    };
    this.ws.onclose = () => {
      this.ws = null;
      this.stopPing();
      if (this.stopped) return;
      this.setStatus('OFFLINE');
      this.scheduleReconnect();
    };
    this.ws.onerror = () => {
      try { this.ws?.close(); } catch { /* noop */ }
    };
  }

  private startPing() {
    this.stopPing();
    this.pingTimer = window.setInterval(() => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        try { this.ws.send('ping'); } catch { /* noop */ }
      }
    }, PING_INTERVAL_MS);
  }

  private stopPing() {
    if (this.pingTimer) { window.clearInterval(this.pingTimer); this.pingTimer = null; }
  }

  private armSilenceTimer() {
    if (this.silentTimer) window.clearTimeout(this.silentTimer);
    this.silentTimer = window.setTimeout(() => {
      if (this.status === 'CONNECTED') this.setStatus('DEGRADED');
    }, 6000);
  }

  private setStatus(status: ConnectionStatus) {
    if (this.status === status) return;
    this.status = status;
    this.onStatus(status);
  }

  private scheduleReconnect() {
    if (this.stopped || this.timer) return;
    const delay = Math.min(15000, 1000 * 2 ** this.retries);
    this.retries += 1;
    this.timer = window.setTimeout(() => {
      this.timer = null;
      this.connect();
    }, delay);
  }

  disconnect() {
    this.stopped = true;
    if (this.timer) { window.clearTimeout(this.timer); this.timer = null; }
    if (this.silentTimer) { window.clearTimeout(this.silentTimer); this.silentTimer = null; }
    this.stopPing();
    this.ws?.close();
    this.ws = null;
    this.setStatus('OFFLINE');
  }
}
