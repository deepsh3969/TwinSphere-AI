import { beforeEach, describe, expect, it, vi } from 'vitest';
import replayJson from '../testData/replay_payload.json';
import { makeSnapshot } from '../testFixtures';
import type { ReplayPayload, Snapshot } from '../types';
import { ApiError } from '../services/api';
import { frameAt, useTwinStore } from './useTwinStore';

const m = vi.hoisted(() => ({
  api: { replay: vi.fn() },
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

const payload = replayJson as unknown as ReplayPayload;
const last = payload.frames[payload.frames.length - 1];
const mid = payload.frames[30];

function baseSnapshot(): Snapshot {
  return makeSnapshot({
    risk: { score: 30, level: 'MODERATE', factors: [], explanation: 'baseline' },
    metrics: {
      occupancy: 1000, occupancy_pct: 40, energy: 120, temperature: 24, water: 0,
      risk: 30, risk_level: 'MODERATE', incidents: 0, people_at_risk: 0,
      anomalies: 0, clock_hour: 12, status: 'NORMAL', recovery_progress: 0,
    },
  });
}

async function load() {
  m.api.replay.mockResolvedValue(payload);
  await useTwinStore.getState().loadReplay(payload.simulation.id);
  return useTwinStore.getState();
}

beforeEach(() => {
  useTwinStore.setState({
    snapshot: baseSnapshot(),
    replay: null,
    replaySimId: null,
    replayT: 0,
    replayPlaying: false,
    replaySpeed: 1,
    replayLoading: false,
    replayError: null,
    replaySnapshot: null,
  });
});

describe('frameAt (§61 frame math)', () => {
  it('returns null for an empty frame list', () => {
    expect(frameAt([], 10)).toBeNull();
  });

  it('returns the first frame for t before the run starts', () => {
    expect(frameAt(payload.frames, -5)?.t).toBe(0);
  });

  it('returns the last frame at or before t', () => {
    expect(frameAt(payload.frames, mid.t - 0.01)?.t).toBe(payload.frames[29].t);
    expect(frameAt(payload.frames, mid.t)?.t).toBe(mid.t);
    expect(frameAt(payload.frames, mid.t + 1000)?.t).toBe(last.t);
  });
});

describe('loadReplay', () => {
  it('stores the payload, resets transport and derives frame-0 snapshot', async () => {
    const st = await load();
    expect(m.api.replay).toHaveBeenCalledWith(payload.simulation.id);
    expect(st.replaySimId).toBe(payload.simulation.id);
    expect(st.replayT).toBe(0);
    expect(st.replayPlaying).toBe(false);
    expect(st.replayLoading).toBe(false);
    expect(st.replayError).toBeNull();

    const snap = st.replaySnapshot!;
    expect(snap).not.toBeNull();
    expect(snap.status).toBe(payload.frames[0].status);
    expect(snap.metrics.people_at_risk).toBe(payload.frames[0].people_at_risk);
    expect(snap.risk.score).toBe(payload.frames[0].risk.campus);
    expect(snap.active_sim?.simulation_code).toBe(payload.simulation.code);
    expect(snap.active_sim?.t).toBe(0);
  });

  it('applies the risk band that matches the backend thresholds', async () => {
    const st = await load();
    useTwinStore.getState().setReplayT(mid.t);
    const snap = useTwinStore.getState().replaySnapshot!;
    expect(snap.risk.score).toBeCloseTo(mid.risk.campus, 6);
    expect(snap.risk.level).toBe('HIGH');
    expect(snap.building_risk.eng.score).toBeCloseTo(mid.risk.eng, 6);
    expect(snap.building_risk.eng.level).toBe('CRITICAL');
    expect(snap.metrics.people_at_risk).toBe(mid.people_at_risk);
    expect(st.replay?.simulation.id).toBe(payload.simulation.id);
  });

  it('never mutates the live base snapshot', async () => {
    const before = JSON.stringify(useTwinStore.getState().snapshot);
    await load();
    useTwinStore.getState().setReplayT(mid.t);
    useTwinStore.getState().closeReplay();
    expect(JSON.stringify(useTwinStore.getState().snapshot)).toBe(before);
  });

  it('reports an ApiError message and clears the payload on failure', async () => {
    m.api.replay.mockRejectedValue(new ApiError(404, 'simulation not found'));
    await useTwinStore.getState().loadReplay('sim_missing');
    const st = useTwinStore.getState();
    expect(st.replayError).toBe('simulation not found');
    expect(st.replay).toBeNull();
    expect(st.replaySnapshot).toBeNull();
    expect(st.replayLoading).toBe(false);
  });

  it('falls back to a generic message for non-ApiError failures', async () => {
    m.api.replay.mockRejectedValue(new Error('boom'));
    await useTwinStore.getState().loadReplay('sim_x');
    expect(useTwinStore.getState().replayError).toBe('Failed to load replay');
  });
});

describe('replay transport (§63)', () => {
  it('setReplayT clamps to [0, duration]', async () => {
    await load();
    const s = useTwinStore.getState();
    s.setReplayT(-20);
    expect(useTwinStore.getState().replayT).toBe(0);
    useTwinStore.getState().setReplayT(payload.duration_s + 50);
    expect(useTwinStore.getState().replayT).toBe(payload.duration_s);
  });

  it('stepReplay moves by max(frame_step_s, 1) and pauses playback', async () => {
    await load();
    const step = Math.max(payload.frame_step_s, 1);
    useTwinStore.getState().setReplayPlaying(true);
    useTwinStore.getState().stepReplay(1);
    expect(useTwinStore.getState().replayT).toBeCloseTo(step, 6);
    expect(useTwinStore.getState().replayPlaying).toBe(false);
    useTwinStore.getState().stepReplay(-1);
    expect(useTwinStore.getState().replayT).toBeCloseTo(0, 6);
    useTwinStore.getState().stepReplay(-1);
    expect(useTwinStore.getState().replayT).toBe(0);
  });

  it('pressing PLAY at the end rewinds to the start', async () => {
    await load();
    useTwinStore.getState().setReplayT(payload.duration_s);
    expect(useTwinStore.getState().replayT).toBe(payload.duration_s);
    useTwinStore.getState().setReplayPlaying(true);
    expect(useTwinStore.getState().replayT).toBe(0);
    expect(useTwinStore.getState().replayPlaying).toBe(true);
  });

  it('tickReplay advances by dt * speed only while playing', async () => {
    await load();
    useTwinStore.getState().setReplaySpeed(5);
    useTwinStore.getState().tickReplay(1);
    expect(useTwinStore.getState().replayT).toBe(0);

    useTwinStore.getState().setReplayPlaying(true);
    useTwinStore.getState().tickReplay(2);
    expect(useTwinStore.getState().replayT).toBeCloseTo(10, 6);
    useTwinStore.getState().tickReplay(-1);
    expect(useTwinStore.getState().replayT).toBeCloseTo(10, 6);
  });

  it('tickReplay clamps at the duration and stops playback', async () => {
    await load();
    useTwinStore.getState().setReplayPlaying(true);
    useTwinStore.getState().tickReplay(payload.duration_s + 999);
    const st = useTwinStore.getState();
    expect(st.replayT).toBe(payload.duration_s);
    expect(st.replayPlaying).toBe(false);
    expect(st.replaySnapshot?.status).toBe(last.status);
  });

  it('speed chips persist between transport actions', async () => {
    await load();
    for (const sp of payload.speeds) {
      useTwinStore.getState().setReplaySpeed(sp);
      expect(useTwinStore.getState().replaySpeed).toBe(sp);
    }
  });

  it('closeReplay clears the whole replay slice', async () => {
    await load();
    useTwinStore.getState().setReplayT(mid.t);
    useTwinStore.getState().closeReplay();
    const st = useTwinStore.getState();
    expect(st.replay).toBeNull();
    expect(st.replaySimId).toBeNull();
    expect(st.replayT).toBe(0);
    expect(st.replayPlaying).toBe(false);
    expect(st.replaySpeed).toBe(1);
    expect(st.replayError).toBeNull();
    expect(st.replaySnapshot).toBeNull();
  });
});

describe('replay snapshot derivation is deterministic (§61)', () => {
  it('produces identical snapshots for identical times', async () => {
    await load();
    useTwinStore.getState().setReplayT(mid.t);
    const a = JSON.stringify(useTwinStore.getState().replaySnapshot);
    useTwinStore.getState().setReplayT(0);
    useTwinStore.getState().setReplayT(mid.t);
    const b = JSON.stringify(useTwinStore.getState().replaySnapshot);
    expect(b).toBe(a);
  });

  it('reflects persisted zone fire only for burning zones', async () => {
    await load();
    useTwinStore.getState().setReplayT(0);
    const start = useTwinStore.getState().replaySnapshot!;
    const startBurning = new Set(payload.frames[0].burning_zones);
    for (const z of start.zones) {
      if (startBurning.has(z.id)) expect(z.status).toBe('FIRE');
      else expect(z.status).toBe('NORMAL');
    }

    useTwinStore.getState().setReplayT(mid.t);
    const peak = useTwinStore.getState().replaySnapshot!;
    const midBurning = new Set(mid.burning_zones);
    for (const z of peak.zones) {
      if (midBurning.has(z.id)) expect(z.status).toBe('FIRE');
      else expect(z.status).toBe('NORMAL');
    }
    expect(midBurning.size).toBeGreaterThan(startBurning.size);
  });
});
