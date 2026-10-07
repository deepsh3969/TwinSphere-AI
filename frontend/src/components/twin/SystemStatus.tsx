import { useTwinStore } from '../../store/useTwinStore';
import type { SimStatus } from '../../types';
import { fmtSimHour } from './SimControlPanel';

function Row({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="flex items-center justify-between gap-2 text-[11.5px]">
      <span className="text-mist-500">{label}</span>
      <b className={`num ${tone ?? 'text-mist-100'}`}>{value}</b>
    </div>
  );
}

function serviceTone(ok: boolean | undefined): string {
  return ok ? 'text-emerald-400' : 'text-red-400';
}

/**
 * System status panel (spec §14/§48): backend/database/websocket/simulator/AI
 * health from the `system.status` WS event (falls back to snapshot data when
 * no event has arrived yet). Never claims a service is up without evidence.
 */
export default function SystemStatus() {
  const sys = useTwinStore((s) => s.systemStatus);
  const realtime = useTwinStore((s) => s.realtime);
  const connection = useTwinStore((s) => s.connection);
  const snapshot = useTwinStore((s) => s.snapshot);

  const backend = sys?.backend ?? snapshot?.system_health?.backend === true;
  const database = sys?.database ?? snapshot?.system_health?.database === true;
  const websocket = sys?.websocket ?? connection === 'CONNECTED';
  const sim: SimStatus = sys?.simulator ?? realtime?.status ?? snapshot?.sim_status ?? 'STOPPED';
  const ai = sys?.ai ?? snapshot?.system_health?.ai === true;
  const risk = sys?.risk_level ?? snapshot?.metrics?.risk_level ?? null;
  const incidents = sys?.incidents ?? snapshot?.incidents.filter((i) => i.status === 'ACTIVE').length ?? 0;
  const speed = sys?.speed ?? realtime?.speed ?? 1;
  const clockHour = sys?.clock_hour ?? realtime?.clock_hour ?? snapshot?.clock_hour;

  return (
    <div className="rounded-md border border-line bg-ink-850 p-2.5 space-y-1" data-testid="system-status">
      <div className="flex items-center justify-between mb-1.5">
        <span className="label-cap">System Status</span>
        <span className={`chip !py-0 !px-1.5 !text-[9px] ${
          connection === 'CONNECTED'
            ? 'border-emerald-700 bg-emerald-950/60 text-emerald-300'
            : connection === 'DEGRADED'
              ? 'border-amber-700 bg-amber-950/60 text-amber-300'
              : 'border-red-700 bg-red-950/60 text-red-300'
        }`}>
          {connection}
        </span>
      </div>
      <Row label="Backend" value={backend ? 'UP' : 'DOWN'} tone={serviceTone(backend)} />
      <Row label="Database" value={database ? 'UP' : 'DOWN'} tone={serviceTone(database)} />
      <Row label="WebSocket" value={websocket ? 'STREAMING' : 'OFFLINE'} tone={serviceTone(websocket)} />
      <Row label="Simulator" value={`${sim} · ${speed}x`} tone={sim === 'RUNNING' ? 'text-emerald-400' : sim === 'PAUSED' ? 'text-amber-300' : 'text-red-300'} />
      <Row label="Sim clock" value={fmtSimHour(clockHour)} />
      <Row label="AI Analyst" value={ai ? 'READY' : 'UNAVAILABLE'} tone={ai ? 'text-emerald-400' : 'text-amber-300'} />
      <Row label="Connected clients" value={String(sys?.connected_clients ?? snapshot?.connected_clients ?? '—')} />
      <Row
        label="Campus risk"
        value={risk ?? '—'}
        tone={risk === 'LOW' ? 'text-emerald-400' : risk === 'CRITICAL' || risk === 'HIGH' ? 'text-red-300' : 'text-amber-300'}
      />
      <Row label="Active incidents" value={String(incidents)} tone={incidents > 0 ? 'text-red-300' : 'text-emerald-400'} />
      <div className="pt-1.5 mt-1 border-t border-line text-[10px] text-mist-600">
        Source: live WebSocket status events ({sys ? 'realtime' : 'last snapshot'}).
      </div>
    </div>
  );
}
