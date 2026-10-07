import { useState } from 'react';
import { api } from '../../services/api';
import { useTwinStore } from '../../store/useTwinStore';
import AnalystBrief from '../ai/AnalystBrief';
import EvidencePanel from '../ai/EvidencePanel';
import { IconBrain, IconCheck, IconRefresh, IconSpark } from '../Icons';

export default function AIPanel({ onApplied }: { onApplied?: () => void }) {
  const analyst = useTwinStore((s) => s.analyst);
  const aiFallback = useTwinStore((s) => s.aiFallback);
  const snapshot = useTwinStore((s) => s.snapshot);
  const user = useTwinStore((s) => s.user);
  const refreshAnalyst = useTwinStore((s) => s.refreshAnalyst);
  const handleApiError = useTwinStore((s) => s.handleApiError);
  const pushToast = useTwinStore((s) => s.pushToast);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const canApply = user && ['ADMIN', 'OPERATOR'].includes(user.role);
  const pending = (snapshot?.recommendations ?? []).filter((r) => r.status === 'PENDING');
  const applied = (snapshot?.recommendations ?? []).filter((r) => r.status === 'APPLIED');
  // Phase 5 — live tracker output (snapshot.anomalies is the legacy record)
  const liveAnomalies = useTwinStore((s) => s.anomalies);
  const anomalyDataQuality = useTwinStore((s) => s.anomalyDataQuality);
  const anomalies = liveAnomalies.slice(0, 3);

  const bandOf = (a: { band?: string; severity?: string }) =>
    ((a.band ?? a.severity ?? '').toUpperCase() === 'MEDIUM' ? 'MODERATE' : (a.band ?? a.severity ?? '').toUpperCase());

  const bandTone = (band: string) =>
    band === 'CRITICAL' ? 'border-red-700 text-red-300'
      : band === 'HIGH' ? 'border-orange-700 text-orange-300'
        : band === 'MODERATE' ? 'border-amber-700 text-amber-300'
          : 'border-sky-700 text-sky-300';

  const apply = async (id: string) => {
    setBusyId(id);
    try {
      const rec = await api.applyRecommendation(id);
      pushToast('success', 'Recommendation applied', rec.applied_detail ?? rec.title);
      onApplied?.();
      await useTwinStore.getState().refreshAnalyst();
    } catch (err) {
      handleApiError(err);
    } finally {
      setBusyId(null);
    }
  };

  const refresh = async () => {
    setRefreshing(true);
    try {
      await api.analyze('');
      await refreshAnalyst();
    } catch (err) {
      handleApiError(err);
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex items-center gap-2 px-3 py-2.5 border-b border-line">
        <IconBrain width={15} height={15} className="text-brand-400" />
        <span className="text-[12px] font-bold tracking-wide">AI INTELLIGENCE</span>
        <span className={`chip ${aiFallback ? 'border-amber-700 bg-amber-950/70 text-amber-300' : 'border-sky-700 bg-sky-950/70 text-sky-300'}`}>
          {aiFallback ? 'LOCAL FALLBACK ACTIVE' : 'LLM ANALYST'}
        </span>
        <button
          className="ml-auto text-mist-500 hover:text-white disabled:opacity-40"
          onClick={() => void refresh()}
          disabled={refreshing}
          title="Re-run analysis"
        >
          <IconRefresh width={14} height={14} className={refreshing ? 'animate-spin' : ''} />
        </button>
      </div>

      <div className="flex-1 min-h-0 scroll-y px-3 py-3 space-y-3">
        {analyst ? (
          <>
            {/* Phase 8 §63 — AI-INSIGHT: structured evidence-grounded brief */}
            <div>
              <div className="flex items-center gap-1.5 mb-1.5">
                <span className="label-cap text-brand-300">AI insight</span>
                {analyst.situation && (
                  <span className={`chip !text-[9px] ${
                    analyst.situation.severity === 'CRITICAL' ? 'border-red-700 bg-red-950 text-red-300'
                      : analyst.situation.severity === 'HIGH' || analyst.situation.severity === 'ELEVATED'
                        ? 'border-orange-700 bg-orange-950 text-orange-300'
                        : analyst.situation.severity === 'MODERATE' ? 'border-amber-700 bg-amber-950 text-amber-300'
                          : 'border-sky-700 bg-sky-950 text-sky-300'}`}
                  >{analyst.situation.severity}</span>
                )}
                {analyst.confidence && (
                  <span className="num text-[9.5px] text-mist-600 ml-auto">
                    conf {Math.round(analyst.confidence.overall * 100)}% · {analyst.confidence.level}
                  </span>
                )}
              </div>
              <AnalystBrief report={analyst} compact />
            </div>
            {!!analyst.evidence?.length && (
              <EvidencePanel evidence={analyst.evidence} />
            )}
          </>
        ) : (
          <div className="rounded-md border border-line bg-ink-850 p-4 text-center">
            <div className="w-6 h-6 mx-auto mb-2 border-2 border-brand-400 border-t-transparent rounded-full animate-spin" />
            <div className="text-[12px] text-mist-300">Analyst warming up…</div>
          </div>
        )}

        <div>
          <div className="flex items-center gap-1.5 mb-1.5">
            <IconSpark width={13} height={13} className="text-amber-300" />
            <span className="label-cap">Recommendations ({pending.length})</span>
          </div>
          {pending.length === 0 && applied.length === 0 && (
            <div className="text-[11.5px] text-mist-500 border border-dashed border-line rounded-md p-3 text-center">
              No recommendations — operating normally.
            </div>
          )}
          <div className="space-y-2">
            {pending.map((rec) => (
              <div
                key={rec.id}
                className={`rounded-md border p-2.5 ${
                  rec.priority === 'CRITICAL' ? 'border-red-800 bg-red-950/40'
                    : rec.priority === 'HIGH' ? 'border-orange-800 bg-orange-950/30'
                      : 'border-line bg-ink-850'
                }`}
              >
                <div className="flex items-start gap-2">
                  <span className={`chip shrink-0 ${
                    rec.priority === 'CRITICAL' ? 'border-red-700 bg-red-950 text-red-300'
                      : rec.priority === 'HIGH' ? 'border-orange-700 bg-orange-950 text-orange-300'
                        : 'border-line-strong bg-ink-800 text-mist-300'
                  }`}>{rec.priority}</span>
                  <div className="min-w-0">
                    <div className="text-[12.5px] font-semibold leading-tight">{rec.title}</div>
                    <p className="text-[11.5px] text-mist-300 mt-1 leading-snug">{rec.rationale}</p>
                  </div>
                </div>
                <div className="flex gap-2 mt-2">
                  <button
                    className="btn btn-success !py-1 !text-[11px]"
                    disabled={!canApply || busyId === rec.id}
                    onClick={() => void apply(rec.id)}
                    title={canApply ? 'Apply to digital twin' : 'Requires OPERATOR/ADMIN role'}
                  >
                    <IconCheck width={12} height={12} />
                    {busyId === rec.id ? 'Applying…' : 'APPLY RECOMMENDATION'}
                  </button>
                </div>
              </div>
            ))}
            {applied.map((rec) => (
              <div key={rec.id} className="rounded-md border border-emerald-800 bg-emerald-950/30 p-2.5">
                <div className="text-[12px] font-semibold text-emerald-200 flex items-center gap-1.5">
                  <IconCheck width={13} height={13} /> {rec.title}
                </div>
                {rec.applied_detail && (
                  <p className="text-[11px] text-emerald-300/80 mt-1">{rec.applied_detail}</p>
                )}
              </div>
            ))}
          </div>
        </div>

        <div>
          <div className="flex items-center gap-2">
            <span className="label-cap">Anomaly Watch</span>
            <span className="num text-[9.5px] text-mist-600 ml-auto">data {anomalyDataQuality}</span>
          </div>
          <div className="space-y-1.5 mt-1.5">
            {anomalies.length === 0 && (
              <div className="text-[11.5px] text-mist-500">All telemetry within expected bounds.</div>
            )}
            {anomalies.map((a) => {
              const band = bandOf(a);
              return (
                <div key={a.id ?? `${a.sensor_id}-${a.metric}`} className="rounded border border-line bg-ink-850 px-2 py-1.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[11.5px] font-semibold truncate">{a.location} · {a.metric}</span>
                    <span className={`chip shrink-0 ${bandTone(band)}`}>
                      {a.score}{a.band ? '/100 ' : ' '}{band}
                    </span>
                  </div>
                  <p className="text-[11px] text-mist-300 leading-snug mt-0.5">{a.explanation}</p>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
