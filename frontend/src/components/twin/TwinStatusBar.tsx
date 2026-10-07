import { useTwinStore } from '../../store/useTwinStore';
import { fmtSimHour } from './SimControlPanel';

function fmtClockMs(epochMs: number): string {
  if (!epochMs) return '—';
  return new Date(epochMs).toLocaleTimeString(undefined, { hour12: false });
}

/**
 * Digital twin status bar (spec §29): connection truth, data source label,
 * entity counts and last update time. Never claims connectivity it lacks.
 * Phase 4 adds an honest LIVE badge (WS streaming) + simulator status/clock.
 */
export default function TwinStatusBar() {
  const snapshot = useTwinStore((s) => s.snapshot);
  const connection = useTwinStore((s) => s.connection);
  const backendOffline = useTwinStore((s) => s.backendOffline);
  const lastUpdate = useTwinStore((s) => s.lastUpdate);
  const realtime = useTwinStore((s) => s.realtime);

  const source = snapshot?.data_source ?? snapshot?.metadata?.data_source ?? '—';
  const buildings = snapshot ? (snapshot.summary?.buildings ?? snapshot.buildings.length) : null;
  const zones = snapshot ? (snapshot.summary?.zones ?? (snapshot.zones ? snapshot.zones.length : null)) : null;
  const sensors = snapshot ? (snapshot.summary?.sensors ?? (snapshot.sensors ? snapshot.sensors.length : null)) : null;
  const incidents = snapshot
    ? snapshot.incidents.filter((i) => i.status === 'ACTIVE').length
    : null;

  const connLabel = backendOffline ? 'BACKEND OFFLINE' : connection;
  const dot = backendOffline || connection === 'OFFLINE'
    ? 'bg-red-500'
    : connection === 'DEGRADED' ? 'bg-amber-400' : 'bg-emerald-400';
  const connText = backendOffline || connection === 'OFFLINE'
    ? 'text-red-300'
    : connection === 'DEGRADED' ? 'text-amber-300' : 'text-emerald-300';

  const item = (label: string, value: number | string | null) => (
    <span className="flex items-center gap-1.5" title={label}>
      <span className="label-cap">{label}</span>
      <b className="num text-mist-100">{value ?? '—'}</b>
    </span>
  );

  return (
    <div className="absolute bottom-0 inset-x-0 h-8 z-10 border-t border-line bg-ink-900/92 backdrop-blur-sm px-3 flex items-center gap-4 text-[11px] overflow-hidden">
      <span className="flex items-center gap-2 shrink-0">
        <span className={`w-2 h-2 rounded-full ${dot}`} aria-hidden="true" />
        <b className="tracking-[0.14em] text-[10px] text-white">DIGITAL TWIN</b>
        <span className={`font-bold text-[10px] tracking-wider ${connText}`}>{connLabel}</span>
      </span>

      <span className="flex items-center gap-1.5 shrink-0" title="Data source for all telemetry">
        <span className="label-cap">Data Source</span>
        <b className="text-amber-300">{source}</b>
      </span>

      {connection === 'CONNECTED' && (
        <span
          className="flex items-center gap-1.5 shrink-0 chip !py-0 !px-1.5 !text-[9px] border-emerald-700 bg-emerald-950/60 text-emerald-300"
          title="WebSocket streaming is active — values update live"
          data-testid="live-badge"
        >
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 pulse-soft" aria-hidden="true" />
          LIVE
        </span>
      )}

      {realtime && (
        <span className="flex items-center gap-1.5 shrink-0" title="Simulator status (Phase 4)">
          <span className="label-cap">Sim</span>
          <b className={realtime.status === 'RUNNING' ? 'text-emerald-300'
            : realtime.status === 'PAUSED' ? 'text-amber-300' : 'text-red-300'}>
            {realtime.status}
          </b>
          <span className="num text-mist-100">{fmtSimHour(realtime.clock_hour)}</span>
          <span className="num text-mist-400">{realtime.speed}x</span>
        </span>
      )}

      <span className="hidden sm:flex items-center gap-4 min-w-0 overflow-hidden">
        {item('Buildings', buildings)}
        {item('Zones', zones)}
        {item('Sensors', sensors)}
        {item('Active Incidents', incidents)}
      </span>

      <span className="ml-auto flex items-center gap-1.5 shrink-0" title="Last snapshot refresh">
        <span className="label-cap">Last Update</span>
        <b className="num text-mist-100">{fmtClockMs(lastUpdate)}</b>
      </span>
    </div>
  );
}
