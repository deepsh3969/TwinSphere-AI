import { useTwinStore } from '../../store/useTwinStore';
import type { SimStatus } from '../../types';

const SPEEDS = [1, 2, 5, 10] as const;

const STATUS_CHIP: Record<SimStatus, { cls: string; label: string }> = {
  RUNNING: { cls: 'border-emerald-700 bg-emerald-950/60 text-emerald-300', label: 'RUNNING' },
  PAUSED: { cls: 'border-amber-700 bg-amber-950/60 text-amber-300', label: 'PAUSED' },
  STOPPED: { cls: 'border-red-700 bg-red-950/60 text-red-300', label: 'STOPPED' },
};

export function fmtSimHour(hour: number | undefined | null): string {
  if (hour == null) return '—';
  const h = Math.floor(((hour % 24) + 24) % 24);
  const m = Math.floor((hour - Math.floor(hour)) * 60);
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
}

/**
 * Realtime simulation control panel (spec §36/§44): backend-authoritative
 * start/pause/resume/reset + speed (1x/2x/5x/10x). Controls are read-only for
 * roles without the `simulate` permission (ANALYST/VIEWER) and disabled when
 * the simulator is disabled server-side.
 */
export default function SimControlPanel() {
  const realtime = useTwinStore((s) => s.realtime);
  const busy = useTwinStore((s) => s.realtimeBusy);
  const role = useTwinStore((s) => s.user?.role ?? null);
  const action = useTwinStore((s) => s.realtimeAction);
  const setSpeed = useTwinStore((s) => s.setRealtimeSpeed);

  const status: SimStatus = realtime?.status ?? 'STOPPED';
  const chip = STATUS_CHIP[status];
  const canControl = role === 'ADMIN' || role === 'OPERATOR';
  const enabled = realtime?.enabled ?? true;
  const speed = realtime?.speed ?? 1;

  const disabled = busy || !canControl || !enabled;
  const showStart = status === 'STOPPED';

  return (
    <div className="panel rounded-lg shadow-lg shadow-black/40 w-[240px] overflow-hidden" data-testid="sim-control-panel">
      <div className="flex items-center justify-between px-3 py-2 border-b border-line">
        <span className="label-cap">Simulation</span>
        <span className={`chip !py-0 !px-1.5 !text-[9px] ${chip.cls}`} data-testid="sim-status-chip">
          {chip.label}
        </span>
      </div>

      <div className="px-3 py-2 space-y-2 border-b border-line">
        <div className="flex items-center justify-between text-[11.5px]">
          <span className="text-mist-500">Sim clock</span>
          <b className="num text-white" data-testid="sim-clock">{fmtSimHour(realtime?.clock_hour)}</b>
        </div>
        <div className="flex items-center justify-between text-[11.5px]">
          <span className="text-mist-500">Speed</span>
          <b className="num text-white">{speed}x</b>
        </div>
        <div className="flex items-center justify-between text-[11.5px]">
          <span className="text-mist-500">Data source</span>
          <b className="text-amber-300">{realtime?.data_source ?? 'SIMULATED'}</b>
        </div>
      </div>

      <div className="px-3 py-2.5 space-y-2">
        <div className="grid grid-cols-2 gap-1.5">
          {showStart ? (
            <button
              className="btn btn-primary !text-[11px] !py-1.5 col-span-2"
              disabled={disabled}
              onClick={() => void action('start')}
              aria-label="Start simulation"
            >
              Start
            </button>
          ) : (
            <button
              className="btn !text-[11px] !py-1.5"
              disabled={disabled || status === 'PAUSED'}
              onClick={() => void action('pause')}
              aria-label="Pause simulation"
            >
              Pause
            </button>
          )}
          {!showStart && (
            <button
              className="btn !text-[11px] !py-1.5"
              disabled={disabled || status === 'RUNNING'}
              onClick={() => void action('resume')}
              aria-label="Resume simulation"
            >
              Resume
            </button>
          )}
          <button
            className="btn !text-[11px] !py-1.5 col-span-2"
            disabled={disabled}
            onClick={() => void action('reset')}
            title="Reset the simulated clock and telemetry baseline to 10:00"
            aria-label="Reset simulation"
          >
            Reset
          </button>
        </div>

        <div className="pt-1.5 border-t border-line">
          <div className="label-cap mb-1">Speed</div>
          <div className="flex gap-1">
            {SPEEDS.map((s) => (
              <button
                key={s}
                onClick={() => void setSpeed(s)}
                disabled={disabled || speed === s}
                aria-pressed={speed === s}
                className={`chip flex-1 justify-center !text-[10px] ${
                  speed === s ? 'border-brand-400 bg-brand-950/70 text-brand-200' : 'border-line-strong text-mist-500'
                } ${disabled || speed === s ? 'opacity-60' : 'hover:border-line'}`}
              >
                {s}x
              </button>
            ))}
          </div>
        </div>

        {!canControl && (
          <p className="text-[10px] text-mist-600 leading-snug">
            Your role has read-only access — simulation controls are disabled.
          </p>
        )}
        {!enabled && (
          <p className="text-[10px] text-amber-400/90 leading-snug">
            Simulator is disabled on the server (SIMULATION_ENABLED=false).
          </p>
        )}
      </div>
    </div>
  );
}
