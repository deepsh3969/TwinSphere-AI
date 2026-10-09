import { useCallback, useEffect, useState } from 'react';
import { IconRefresh } from '../Icons';
import { api } from '../../services/api';
import type { CampusHealthResponse, WhatChangedResponse } from '../../types';
import { fmtNum } from '../../utils/colors';

const IMPACT_CLS: Record<string, string> = {
  better: 'text-emerald-300',
  worse: 'text-red-300',
  info: 'text-mist-300',
};

const GLYPH: Record<string, string> = { up: '▲', down: '▼', same: '=' };

function levelChip(level: string): string {
  if (level === 'GOOD') return 'border-emerald-700 text-emerald-300';
  if (level === 'FAIR') return 'border-amber-700 text-amber-300';
  return 'border-red-700 text-red-300';
}

/**
 * Phase 9 §60 — campus health score (weighted components) + "What Changed?"
 * delta panel comparing the last 60 minutes with the 60 before.
 */
export default function HealthChangesPanel() {
  const [health, setHealth] = useState<CampusHealthResponse | null>(null);
  const [changes, setChanges] = useState<WhatChangedResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setBusy(true);
    Promise.all([
      api.campusHealth({ range: '24H' }),
      api.whatChanged(60),
    ]).then(([h, w]) => {
      setHealth(h);
      setChanges(w);
      setError(null);
    }).catch((err: unknown) => {
      setError(err instanceof Error ? err.message : 'Failed to load');
    }).finally(() => setBusy(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  if (error && !health) {
    return <div className="p-3 text-[12px] text-amber-300">Health panel unavailable — {error}</div>;
  }
  if (!health || !changes) {
    return <div className="p-3 text-[12px] text-mist-500">Computing campus health…</div>;
  }

  return (
    <div className="h-full overflow-y-auto scroll-y" data-testid="health-changes">
      {/* campus health score */}
      <div className="px-3 py-2.5 border-b border-line">
        <div className="flex items-center justify-between mb-2">
          <span className="label-cap">Campus health score</span>
          <span className={`chip !text-[9.5px] !py-0 !px-1.5 ${levelChip(health.level)}`}>
            {health.level}
          </span>
        </div>
        <div className="flex items-end gap-2">
          <span className="num text-3xl font-bold leading-none">{health.score.toFixed(0)}</span>
          <span className="text-[11px] text-mist-500 mb-0.5">/ 100 · weighted {health.weights_total}</span>
        </div>
        <div className="space-y-1 mt-2">
          {health.components.map((c) => (
            <div key={c.id} className="flex items-center gap-2 text-[10.5px]" title={c.note ?? c.detail}>
              <span className="w-[76px] shrink-0 text-mist-400 truncate">{c.label}</span>
              <div className="flex-1 h-1.5 rounded-full bg-ink-700 overflow-hidden">
                <div
                  className={`h-full rounded-full ${c.score >= 80 ? 'bg-emerald-500' : c.score >= 50 ? 'bg-amber-500' : 'bg-red-500'}`}
                  style={{ width: `${Math.max(2, Math.min(100, c.score))}%` }}
                />
              </div>
              <span className="num w-8 text-right text-mist-300">{c.score.toFixed(0)}</span>
              <span className="num w-8 text-right text-mist-500">w{c.weight}</span>
            </div>
          ))}
        </div>
      </div>

      {/* what changed */}
      <div className="px-3 py-2.5">
        <div className="flex items-center justify-between mb-1.5">
          <span className="label-cap">What changed? · last {changes.ago_minutes}m</span>
          <button className="btn !py-0 !px-1.5" title="Refresh" onClick={load} disabled={busy}>
            <IconRefresh width={11} height={11} className={busy ? 'animate-spin' : ''} />
          </button>
        </div>
        <div className="text-[11.5px] text-mist-200 mb-2">{changes.summary.headline}</div>
        <div className="space-y-1.5">
          {changes.rows.map((row) => (
            <div key={row.metric} className="flex items-center gap-2 text-[11.5px]">
              <span className="text-mist-400 w-[110px] shrink-0 truncate">{row.label}</span>
              <span className="num text-mist-300">
                {row.available && row.previous !== null ? fmtNum(row.previous, 1) : '—'}
              </span>
              <span className="text-mist-600 text-[10px]">→</span>
              <span className="num text-mist-100">
                {row.current !== null ? fmtNum(row.current, 1) : '—'}
              </span>
              <span className={`num text-[10.5px] ml-auto ${IMPACT_CLS[row.impact] ?? 'text-mist-400'}`}>
                {row.available && row.change !== 'same'
                  ? `${GLYPH[row.direction] ?? ''} ${row.delta !== null ? (row.delta > 0 ? '+' : '') + fmtNum(row.delta, 1) : ''} ${row.unit}`
                  : 'no change'}
              </span>
            </div>
          ))}
        </div>
        <div className="text-[10px] text-mist-500 mt-2 num">{changes.note}</div>
      </div>
    </div>
  );
}
