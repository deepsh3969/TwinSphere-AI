import { useEffect, useMemo } from 'react';
import { IconPause, IconPlay, IconRefresh, IconTarget, IconX } from '../Icons';
import { frameAt, useTwinStore } from '../../store/useTwinStore';
import { fmtNum, scenarioLabel } from '../../utils/colors';

const CATEGORY_COLOR: Record<string, string> = {
  SIMULATION: 'border-sky-700 text-sky-300',
  RISK: 'border-red-700 text-red-300',
  ROUTE: 'border-violet-700 text-violet-300',
  AI: 'border-amber-700 text-amber-300',
  RECOVERY: 'border-emerald-700 text-emerald-300',
  INCIDENT: 'border-orange-700 text-orange-300',
};

/** Compact LIVE/REPLAY indicator shown in the viewport status overlay. */
export function ReplayBanner({ onExit }: { onExit?: () => void }) {
  const payload = useTwinStore((s) => s.replay);
  const t = useTwinStore((s) => s.replayT);
  const loading = useTwinStore((s) => s.replayLoading);
  const error = useTwinStore((s) => s.replayError);
  const closeReplay = useTwinStore((s) => s.closeReplay);
  if (!payload && !loading && !error) return null;

  return (
    <div className="panel rounded-lg px-3 py-2 flex items-center gap-3 border-amber-700/80"
         data-testid="replay-banner">
      <span className="chip !py-0 !px-1.5 border-amber-600 bg-amber-950/80 text-amber-300 animate-pulse">
        REPLAY
      </span>
      {payload ? (
        <>
          <div>
            <div className="label-cap">Historical run</div>
            <div className="text-[12.5px] font-semibold">
              {payload.simulation.code} · {scenarioLabel(payload.simulation.scenario)}
            </div>
          </div>
          <div className="w-px h-8 bg-line" />
          <div className="num text-[12.5px]">
            T+{t.toFixed(1)}s <span className="text-mist-500">/ {payload.duration_s.toFixed(0)}s</span>
          </div>
          <button
            className="btn !py-0.5 !text-[11px]"
            onClick={() => { onExit?.(); closeReplay(); }}
            title="Exit replay and return to live"
          >
            <IconX width={12} height={12} /> LIVE
          </button>
        </>
      ) : (
        <div className="text-[12px] text-mist-400">{error ?? 'Loading replay…'}</div>
      )}
    </div>
  );
}

/**
 * Replay transport (§63): PLAY/PAUSE/RESET/frame-step,0.5–10x speeds,
 * scrubber and the persisted event timeline. Drives the store's replay
 * slice — live state is never touched.
 */
export default function ReplayControls({ onExit }: { onExit?: () => void }) {
  const payload = useTwinStore((s) => s.replay);
  const t = useTwinStore((s) => s.replayT);
  const playing = useTwinStore((s) => s.replayPlaying);
  const speed = useTwinStore((s) => s.replaySpeed);
  const snapshot = useTwinStore((s) => s.replaySnapshot);
  const setReplayT = useTwinStore((s) => s.setReplayT);
  const setReplaySpeed = useTwinStore((s) => s.setReplaySpeed);
  const setReplayPlaying = useTwinStore((s) => s.setReplayPlaying);
  const stepReplay = useTwinStore((s) => s.stepReplay);
  const tickReplay = useTwinStore((s) => s.tickReplay);
  const closeReplay = useTwinStore((s) => s.closeReplay);

  // client-side ticking while playing (frame-rate independent)
  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    let last = performance.now();
    const loop = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      tickReplay(dt);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [playing, tickReplay]);

  const frame = useMemo(
    () => (payload ? frameAt(payload.frames, t) : null),
    [payload, t],
  );
  const currentEvent = useMemo(() => {
    if (!payload) return null;
    let best = null as (typeof payload.events)[number] | null;
    for (const ev of payload.events) {
      if (ev.t <= t + 1e-6) best = ev;
      else break;
    }
    return best;
  }, [payload, t]);

  if (!payload) return null;
  const duration = payload.duration_s;
  const frameStep = Math.max(payload.frame_step_s, 1);

  return (
    <div className="absolute bottom-3 left-1/2 -translate-x-1/2 z-20 w-[min(760px,calc(100%-24px))] panel rounded-xl px-3 py-2.5 space-y-2"
         data-testid="replay-controls">
      {/* transport */}
      <div className="flex items-center gap-2">
        <button className="btn !px-2 !py-1" title="Restart replay"
                onClick={() => setReplayT(0)}>
          <IconRefresh width={13} height={13} />
        </button>
        <button className="btn !px-2 !py-1" title="Step back one frame"
                onClick={() => stepReplay(-1)}>
          ‹
        </button>
        <button
          className="btn btn-primary !px-3 !py-1"
          title={playing ? 'Pause replay' : 'Play replay'}
          onClick={() => setReplayPlaying(!playing)}
        >
          {playing ? <IconPause width={14} height={14} /> : <IconPlay width={14} height={14} />}
          <span className="!text-[11.5px]">{playing ? 'Pause' : 'Play'}</span>
        </button>
        <button className="btn !px-2 !py-1" title="Step forward one frame"
                onClick={() => stepReplay(1)}>
          ›
        </button>

        <div className="flex gap-1 ml-1">
          {payload.speeds.map((sp) => (
            <button
              key={sp}
              className={`chip !text-[10.5px] ${speed === sp ? 'border-brand-400 bg-brand-950/70 text-brand-200' : ''}`}
              onClick={() => setReplaySpeed(sp)}
              title={`${sp}x speed`}
            >
              {sp}x
            </button>
          ))}
        </div>

        <div className="flex-1" />
        <span className="num text-[12px] font-bold">
          T+{t.toFixed(1)}s<span className="text-mist-500 font-normal"> / {duration.toFixed(0)}s</span>
        </span>
        <button className="btn !px-2 !py-1" title="Exit replay and return to live"
                onClick={() => { onExit?.(); closeReplay(); }}>
          <IconX width={13} height={13} />
        </button>
      </div>

      {/* scrubber */}
      <input
        type="range"
        min={0}
        max={duration}
        step={frameStep}
        value={Math.min(t, duration)}
        onChange={(e) => setReplayT(Number(e.target.value))}
        className="w-full accent-brand-400 h-1"
        aria-label="Replay position"
      />

      {/* frame stats */}
      <div className="flex items-center gap-3 flex-wrap text-[11px]" data-testid="replay-frame-stats">
        <span className={`chip !text-[9.5px] ${CATEGORY_COLOR.SIMULATION}`}>
          {snapshot?.status ?? frame?.status ?? '—'}
        </span>
        <span className="text-mist-400">
          last event <span className="text-mist-200">{frame?.last_kind ?? '—'}</span>
        </span>
        <span className="text-mist-400">
          risk <span className="num text-mist-200">{fmtNum(snapshot?.metrics.risk ?? 0, 0)}</span>
        </span>
        <span className="text-mist-400">
          people at risk <span className={`num ${snapshot?.metrics.people_at_risk ? 'text-red-300' : 'text-mist-200'}`}>{fmtNum(snapshot?.metrics.people_at_risk ?? 0)}</span>
        </span>
        {frame?.wall && (
          <span className="num text-mist-500 ml-auto">
            {new Date(frame.wall).toLocaleString()}
          </span>
        )}
      </div>

      {/* persisted event timeline */}
      <div className="max-h-[110px] overflow-y-auto scroll-y pr-1 space-y-0.5">
        {payload.events.map((ev, i) => {
          const active = currentEvent?.id === ev.id;
          const past = ev.t <= t + 1e-6;
          return (
            <button
              key={ev.id ?? i}
              onClick={() => setReplayT(ev.t)}
              className={`w-full text-left flex gap-2 items-center px-1.5 py-0.5 rounded text-[11px] transition-colors ${
                active ? 'bg-ink-800' : past ? 'opacity-90 hover:bg-ink-850' : 'opacity-45 hover:opacity-80'
              }`}
            >
              <span className="num text-mist-500 w-[52px] shrink-0">T+{ev.t.toFixed(0)}s</span>
              <span className={`chip !text-[9px] !py-0 !px-1 shrink-0 border ${CATEGORY_COLOR[ev.category] ?? 'border-line-strong text-mist-400'}`}>
                {ev.category}
              </span>
              <span className="text-mist-300 truncate">
                <span className="text-mist-500">{ev.kind}</span> — {ev.message}
              </span>
            </button>
          );
        })}
        {payload.events.length === 0 && (
          <div className="text-[11.5px] text-mist-500 py-2 text-center">
            No persisted events for this run — frames still replay lifecycle state.
          </div>
        )}
      </div>

      <div className="flex items-center justify-between text-[10px] text-mist-500 num">
        <span>source: {payload.source}</span>
        <span><IconTarget width={9} height={9} className="inline -mt-0.5" /> frame step {payload.frame_step_s}s · {payload.frames.length} frames</span>
      </div>
    </div>
  );
}
