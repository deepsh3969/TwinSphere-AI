import { useCallback, useEffect, useState } from 'react';
import { IconRefresh } from '../Icons';
import { api } from '../../services/api';
import type { SystemStatusResponse } from '../../types';

const STATUS_CLS: Record<string, string> = {
  ONLINE: 'border-emerald-700 text-emerald-300',
  DEGRADED: 'border-amber-700 text-amber-300',
  OFFLINE: 'border-red-700 text-red-300',
};

const DOT_CLS: Record<string, string> = {
  ONLINE: 'bg-emerald-400',
  DEGRADED: 'bg-amber-400',
  OFFLINE: 'bg-red-500',
};

/**
 * Phase 9 §60 — system-health bottom bar: all nine components with live
 * status, refreshed every 30s.
 */
export default function SystemHealthBar() {
  const [status, setStatus] = useState<SystemStatusResponse | null>(null);
  const [failed, setFailed] = useState(false);

  const load = useCallback(() => {
    api.analyticsSystem()
      .then((res) => { setStatus(res); setFailed(false); })
      .catch(() => setFailed(true));
  }, []);

  useEffect(() => {
    load();
    const id = window.setInterval(load, 30_000);
    return () => window.clearInterval(id);
  }, [load]);

  if (failed && !status) {
    return (
      <div className="px-3 py-1.5 text-[11px] text-amber-300 border-t border-line">
        System health unavailable — cannot reach analytics endpoint.
      </div>
    );
  }
  if (!status) {
    return (
      <div className="px-3 py-1.5 text-[11px] text-mist-500 border-t border-line">
        Checking system health…
      </div>
    );
  }

  const s = status.summary;
  return (
    <div className="flex items-center gap-2 px-3 py-1.5 border-t border-line bg-ink-950/60 overflow-x-auto scroll-y"
         data-testid="system-health-bar">
      <span className="label-cap shrink-0">System health</span>
      <span className={`chip !text-[9.5px] !py-0 !px-1.5 shrink-0 ${
        s.offline > 0 ? 'border-red-700 text-red-300'
          : s.degraded > 0 ? 'border-amber-700 text-amber-300'
            : 'border-emerald-700 text-emerald-300'
      }`}>
        {s.online}/{s.total} online
      </span>
      <div className="flex items-center gap-1.5 flex-1 min-w-0">
        {status.components.map((c) => (
          <span key={c.id}
                title={`${c.name}: ${c.message}`}
                className={`chip !text-[9.5px] !py-0 !px-1.5 shrink-0 ${STATUS_CLS[c.status] ?? ''}`}>
            <span className={`w-1.5 h-1.5 rounded-full ${DOT_CLS[c.status] ?? 'bg-mist-500'}`} />
            {c.name}
          </span>
        ))}
      </div>
      <span className="num text-[10px] text-mist-500 shrink-0">
        {new Date(status.computed_at).toLocaleTimeString()}
      </span>
      <button className="btn !py-0 !px-1.5 shrink-0" title="Refresh system health" onClick={load}>
        <IconRefresh width={11} height={11} />
      </button>
    </div>
  );
}
