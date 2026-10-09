import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import replayJson from '../../testData/replay_payload.json';
import { makeSnapshot } from '../../testFixtures';
import type { ReplayPayload } from '../../types';
import { useTwinStore } from '../../store/useTwinStore';
import ReplayControls, { ReplayBanner } from './ReplayControls';

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
const step = Math.max(payload.frame_step_s, 1);

function setState(
  over: Partial<ReturnType<typeof useTwinStore.getState>> = {},
) {
  act(() => {
    useTwinStore.setState({
    snapshot: makeSnapshot({
      risk: { score: 30, level: 'MODERATE', factors: [], explanation: '' },
      metrics: {
        occupancy: 1000, occupancy_pct: 40, energy: 120, temperature: 24, water: 0,
        risk: 30, risk_level: 'MODERATE', incidents: 0, people_at_risk: 0,
        anomalies: 0, clock_hour: 12, status: 'NORMAL', recovery_progress: 0,
      },
    }),
    replay: payload,
    replaySimId: payload.simulation.id,
    replayT: 0,
    replayPlaying: false,
    replaySpeed: 1,
    replayLoading: false,
    replayError: null,
    replaySnapshot: null,
    ...over,
    });
  });
}

beforeEach(() => setState());

describe('ReplayControls transport (§63)', () => {
  it('renders nothing when no replay payload is loaded', () => {
    setState({ replay: null, replaySnapshot: null });
    const { container } = render(<ReplayControls />);
    expect(container.querySelector('[data-testid="replay-controls"]')).toBeNull();
  });

  it('shows transport, speeds, scrubber and persisted timeline for a payload', () => {
    render(<ReplayControls />);
    expect(screen.getByTestId('replay-controls')).toBeInTheDocument();
    expect(screen.getByTitle('Play replay')).toBeInTheDocument();
    expect(screen.getByTitle('Step forward one frame')).toBeInTheDocument();
    expect(screen.getByTitle('Restart replay')).toBeInTheDocument();
    expect(screen.getByLabelText('Replay position')).toBeInTheDocument();
    expect(screen.getByText(new RegExp(`${payload.frames.length} frames`))).toBeInTheDocument();
    expect(screen.getByText(new RegExp(`/\\s*${payload.duration_s.toFixed(0)}s`))).toBeInTheDocument();
    for (const sp of payload.speeds) {
      expect(screen.getByTitle(`${sp}x speed`)).toBeInTheDocument();
    }
    for (const ev of payload.events.slice(0, 5)) {
      expect(
        screen.getByText((content) => content.includes(ev.message)),
      ).toBeInTheDocument();
    }
  });

  it('toggles play/pause without touching live state', () => {
    render(<ReplayControls />);
    const play = screen.getByTitle('Play replay');
    fireEvent.click(play);
    expect(useTwinStore.getState().replayPlaying).toBe(true);
    expect(screen.getByTitle('Pause replay')).toBeInTheDocument();

    fireEvent.click(screen.getByTitle('Pause replay'));
    expect(useTwinStore.getState().replayPlaying).toBe(false);
    expect(screen.getByTitle('Play replay')).toBeInTheDocument();
  });

  it('steps one frame forward and back, pausing playback', () => {
    render(<ReplayControls />);
    fireEvent.click(screen.getByTitle('Step forward one frame'));
    expect(useTwinStore.getState().replayT).toBeCloseTo(step, 6);
    expect(useTwinStore.getState().replayPlaying).toBe(false);

    fireEvent.click(screen.getByTitle('Step back one frame'));
    expect(useTwinStore.getState().replayT).toBeCloseTo(0, 6);
  });

  it('restarts from T+0 and keeps it clamped', () => {
    setState({ replayT: 120 });
    render(<ReplayControls />);
    expect(screen.getByText(/^T\+120\.0s/)).toBeInTheDocument();
    fireEvent.click(screen.getByTitle('Restart replay'));
    expect(useTwinStore.getState().replayT).toBe(0);
  });

  it('selects playback speed from the chips', () => {
    render(<ReplayControls />);
    fireEvent.click(screen.getByTitle('5x speed'));
    expect(useTwinStore.getState().replaySpeed).toBe(5);
    expect(screen.getByTitle('5x speed').className).toContain('border-brand-400');
  });

  it('scrubs the range input to an absolute time', () => {
    render(<ReplayControls />);
    fireEvent.change(screen.getByLabelText('Replay position'), { target: { value: '100' } });
    expect(useTwinStore.getState().replayT).toBe(100);
    expect(screen.getByText(/^T\+100\.0s/)).toBeInTheDocument();
  });

  it('seeks to an event when its timeline row is clicked', () => {
    render(<ReplayControls />);
    const target = payload.events[payload.events.length - 1];
    fireEvent.click(
      screen.getByText((content) => content.includes(target.message)),
    );
    expect(useTwinStore.getState().replayT).toBeCloseTo(target.t, 6);
  });

  it('shows the current frame status and last event', () => {
    render(<ReplayControls />);
    const stats = within(screen.getByTestId('replay-frame-stats'));
    expect(stats.getByText(payload.frames[0].status)).toBeInTheDocument();
    expect(stats.getByText('last event')).toBeInTheDocument();
    expect(stats.getByText(payload.frames[0].last_kind)).toBeInTheDocument();
  });

  it('exits replay back to LIVE and calls onExit', () => {
    const onExit = vi.fn();
    render(<ReplayControls onExit={onExit} />);
    fireEvent.click(screen.getByTitle('Exit replay and return to live'));
    expect(onExit).toHaveBeenCalledTimes(1);
    expect(useTwinStore.getState().replay).toBeNull();
    expect(useTwinStore.getState().replayT).toBe(0);
  });
});

describe('ReplayBanner (LIVE/REPLAY indicator)', () => {
  it('is hidden in live mode', () => {
    setState({ replay: null });
    const { container } = render(<ReplayBanner />);
    expect(container.querySelector('[data-testid="replay-banner"]')).toBeNull();
  });

  it('marks the viewport as REPLAY with the run code and time', () => {
    render(<ReplayBanner />);
    expect(screen.getByText('REPLAY')).toBeInTheDocument();
    expect(screen.getByText(new RegExp(payload.simulation.code))).toBeInTheDocument();
    expect(screen.getByText(/^T\+/)).toBeInTheDocument();
  });

  it('shows a loading/error state while the payload is unavailable', () => {
    setState({ replay: null, replayLoading: true });
    const { rerender } = render(<ReplayBanner />);
    expect(screen.getByText('Loading replay…')).toBeInTheDocument();

    setState({ replay: null, replayLoading: false, replayError: 'no such run' });
    rerender(<ReplayBanner />);
    expect(screen.getByText('no such run')).toBeInTheDocument();
  });

  it('returns to LIVE on exit', () => {
    const onExit = vi.fn();
    render(<ReplayBanner onExit={onExit} />);
    fireEvent.click(screen.getByRole('button', { name: /LIVE/ }));
    expect(onExit).toHaveBeenCalledTimes(1);
    expect(useTwinStore.getState().replay).toBeNull();
  });
});
