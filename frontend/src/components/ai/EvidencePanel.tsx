import { useState } from 'react';
import { api } from '../../services/api';
import type { AnalystEvidenceItem } from '../../types';
import { IconTarget } from '../Icons';

const sourceTone = (source: string): string => {
  const s = source.toLowerCase();
  if (s.includes('risk')) return 'border-red-700 text-red-300';
  if (s.includes('route') || s.includes('evac')) return 'border-sky-700 text-sky-300';
  if (s.includes('predict')) return 'border-violet-700 text-violet-300';
  if (s.includes('sim')) return 'border-amber-700 text-amber-300';
  if (s.includes('congestion')) return 'border-orange-700 text-orange-300';
  return 'border-line-strong text-mist-300';
};

const ageLabel = (age?: number | null): string => {
  if (age == null) return '';
  if (age < 90) return `${Math.max(0, Math.round(age))}s old`;
  if (age < 5400) return `${Math.round(age / 60)}m old`;
  return `${Math.round(age / 3600)}h old`;
};

/**
 * Phase 8 §9 — grounding evidence behind an analyst result. Every claim the
 * Analyst makes resolves to one of these rows; clicking a row re-fetches the
 * persisted item (GET /api/ai/evidence/{id}) so the panel proves the round-trip.
 */
export default function EvidencePanel({ evidence }: { evidence: AnalystEvidenceItem[] }) {
  const [openId, setOpenId] = useState<string | null>(null);
  const [detail, setDetail] = useState<AnalystEvidenceItem | null>(null);
  const [loading, setLoading] = useState(false);

  const toggle = async (item: AnalystEvidenceItem) => {
    if (openId === item.id) {
      setOpenId(null);
      setDetail(null);
      return;
    }
    setOpenId(item.id);
    setDetail(item);
    setLoading(true);
    try {
      setDetail(await api.analystEvidence(item.id));
    } catch {
      /* keep the inline copy — the id still proves the reference exists */
    } finally {
      setLoading(false);
    }
  };

  if (evidence.length === 0) {
    return (
      <div className="text-[11.5px] text-mist-500 border border-dashed border-line rounded-md p-3 text-center">
        No evidence collected for this analysis.
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center gap-1.5 mb-1.5">
        <IconTarget width={13} height={13} className="text-sky-300" />
        <span className="label-cap">Evidence ({evidence.length})</span>
        <span className="num text-[9.5px] text-mist-600 ml-auto">every claim grounded</span>
      </div>
      <div className="space-y-1.5">
        {evidence.map((ev) => (
          <div key={ev.id} className="rounded border border-line bg-ink-850">
            <button
              type="button"
              className="w-full text-left px-2 py-1.5 hover:bg-ink-800 transition-colors"
              onClick={() => void toggle(ev)}
              aria-expanded={openId === ev.id}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-[11.5px] font-semibold text-mist-100 truncate">{ev.label}</span>
                <span className={`chip shrink-0 !text-[9px] ${sourceTone(ev.source_type)}`}>
                  {ev.source_type}
                </span>
              </div>
              <div className="num text-[10px] text-mist-500 mt-0.5 truncate">
                {ev.metric && <>{ev.metric}</>}
                {ev.value != null && <> · {String(ev.value)}{ev.unit ? ` ${ev.unit}` : ''}</>}
                {ageLabel(ev.age_seconds) && <> · {ageLabel(ev.age_seconds)}</>}
                {ev.confidence != null && <> · conf {Math.round(ev.confidence * 100)}%</>}
              </div>
            </button>
            {openId === ev.id && (
              <div className="px-2 pb-2 border-t border-line/60 pt-1.5">
                {loading ? (
                  <div className="text-[10.5px] text-mist-500">Loading persisted evidence…</div>
                ) : (
                  <>
                    {detail?.detail && (
                      <p className="text-[11px] text-mist-300 leading-snug">{detail.detail}</p>
                    )}
                    <div className="num text-[9.5px] text-mist-600 mt-1 break-all">
                      {ev.id}
                      {detail?.source_id && <> · source: {detail.source_id}</>}
                      {detail?.timestamp && <> · {detail.timestamp.slice(11, 19)}</>}
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
