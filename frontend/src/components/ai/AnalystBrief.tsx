import { useState } from 'react';
import { api } from '../../services/api';
import { useTwinStore } from '../../store/useTwinStore';
import type {
  AnalystDecision, AnalystRecommendationRow, AnalystReport,
} from '../../types';
import { IconCheck, IconSpark, IconX } from '../Icons';

const SEV_TONE: Record<string, string> = {
  LOW: 'border-sky-700 bg-sky-950/60 text-sky-300',
  MODERATE: 'border-amber-700 bg-amber-950/60 text-amber-300',
  ELEVATED: 'border-orange-700 bg-orange-950/60 text-orange-300',
  HIGH: 'border-orange-700 bg-orange-950/60 text-orange-300',
  CRITICAL: 'border-red-700 bg-red-950/60 text-red-300',
};

const PRI_TONE: Record<string, string> = {
  LOW: 'border-line-strong bg-ink-800 text-mist-300',
  MEDIUM: 'border-amber-700 bg-amber-950/60 text-amber-300',
  HIGH: 'border-orange-700 bg-orange-950/60 text-orange-300',
  IMMEDIATE: 'border-red-700 bg-red-950/60 text-red-300',
};

const CONF_TONE: Record<string, string> = {
  HIGH: 'border-emerald-700 text-emerald-300',
  MEDIUM: 'border-amber-700 text-amber-300',
  LOW: 'border-red-700 text-red-300',
};

function Block({ title, text, tone }: { title: string; text: string; tone: string }) {
  return (
    <div className="rounded-md border border-line bg-ink-850 p-3">
      <div className={`label-cap mb-1 ${tone}`}>{title}</div>
      <p className="text-[13px] leading-relaxed text-mist-100">{text}</p>
    </div>
  );
}

function ConfidenceMeter({ report, compact }: { report: AnalystReport; compact?: boolean }) {
  const conf = report.confidence;
  if (!conf) return null;
  const tone = conf.overall >= 0.75 ? 'bg-emerald-500' : conf.overall >= 0.5 ? 'bg-amber-400' : 'bg-red-400';
  return (
    <div className="rounded-md border border-line bg-ink-850 p-3">
      <div className="flex items-center gap-2">
        <span className="label-cap">Confidence</span>
        <span className={`chip !text-[9px] ${CONF_TONE[conf.level] ?? 'border-line-strong text-mist-300'}`}>
          {conf.level}
        </span>
        <span className="num text-[12px] font-bold ml-auto">{Math.round(conf.overall * 100)}%</span>
      </div>
      <div className="h-1.5 rounded-full bg-ink-700 overflow-hidden mt-2">
        <div className={`h-full ${tone}`} style={{ width: `${Math.round(conf.overall * 100)}%` }} />
      </div>
      {!compact && conf.components.length > 0 && (
        <div className="grid grid-cols-2 gap-x-3 gap-y-1 mt-2">
          {conf.components.map((c) => (
            <div key={c.name} className="flex items-center gap-1.5 min-w-0">
              <span className="text-[10px] text-mist-400 truncate flex-1" title={c.name}>{c.name}</span>
              <div className="w-10 h-1 rounded-full bg-ink-700 overflow-hidden shrink-0">
                <div className="h-full bg-sky-500" style={{ width: `${Math.round(c.value * 100)}%` }} />
              </div>
              <span className="num text-[9.5px] text-mist-500 w-7 text-right shrink-0">
                {Math.round(c.value * 100)}
              </span>
            </div>
          ))}
        </div>
      )}
      {conf.notes.length > 0 && (
        <p className="text-[10.5px] text-mist-500 italic mt-1.5 leading-snug">{conf.notes.join(' ')}</p>
      )}
    </div>
  );
}

interface AnalystBriefProps {
  report: AnalystReport;
  /** Full = AI page sections; compact = dashboard AI-INSIGHT block. */
  compact?: boolean;
  /** Persisted rows (with decision state) — when given, ACCEPT/DISMISS render. */
  decisions?: AnalystRecommendationRow[];
  canDecide?: boolean;
  onDecided?: () => void;
}

/**
 * Phase 8 §26-§35 — the structured, evidence-grounded analyst brief.
 * Falls back to the Phase 5 narrative blocks when only legacy fields exist.
 */
export default function AnalystBrief({
  report, compact = false, decisions, canDecide = false, onDecided,
}: AnalystBriefProps) {
  const handleApiError = useTwinStore((s) => s.handleApiError);
  const pushToast = useTwinStore((s) => s.pushToast);
  const [busyId, setBusyId] = useState<string | null>(null);

  const decide = async (id: string, decision: AnalystDecision) => {
    setBusyId(id);
    try {
      await api.decideAnalystRecommendation(id, decision);
      pushToast('success', decision === 'ACCEPTED' ? 'RECOMMENDATION ACCEPTED' : 'RECOMMENDATION DISMISSED',
        decision === 'ACCEPTED'
          ? 'Queued for an operator to apply — the Analyst never acts alone.'
          : 'Marked as dismissed by a human decision-maker.');
      onDecided?.();
    } catch (err) {
      handleApiError(err);
    } finally {
      setBusyId(null);
    }
  };

  // legacy Phase 5 payload — narrative blocks only
  if (!report.situation) {
    return (
      <div className="space-y-2.5">
        {([
          ['What happened', report.what_happened, 'text-sky-300'],
          ['Why it matters', report.why_it_matters, 'text-amber-300'],
          ['Likely next', report.likely_next, 'text-violet-300'],
          ['Recommended action', report.recommended_action, 'text-emerald-300'],
        ] as const).map(([title, text, tone]) => (
          <Block key={title} title={title} text={text} tone={tone} />
        ))}
        {report.note && <p className="text-[11px] text-mist-500 italic">{report.note}</p>}
      </div>
    );
  }

  const sit = report.situation;
  const cards = decisions ?? [];

  return (
    <div className="space-y-2.5">
      {/* header: severity + title */}
      <div className="rounded-md border border-line bg-ink-850 p-3">
        <div className="flex items-center gap-2 flex-wrap">
          <span className={`chip ${SEV_TONE[sit.severity] ?? 'border-line-strong text-mist-300'}`}>
            {sit.severity}
          </span>
          <span className={`chip !text-[9px] ${PRI_TONE[sit.priority] ?? 'border-line-strong text-mist-300'}`}>
            {sit.priority} PRIORITY
          </span>
          <span className="chip !text-[9px] border-line-strong bg-ink-800 text-mist-400">{sit.mode}</span>
          <span className="num text-[9.5px] text-mist-600 ml-auto">
            {report.source === 'llm' ? 'LLM' : 'deterministic fallback'}
            {report.latency_ms != null && <> · {report.latency_ms}ms</>}
          </span>
        </div>
        <div className="text-[13.5px] font-bold mt-2 leading-tight">{sit.title}</div>
        <p className="text-[12.5px] text-mist-200 leading-relaxed mt-1">{sit.summary}</p>
      </div>

      <ConfidenceMeter report={report} compact={compact} />

      {/* query answer (§54 — answered from structured data only) */}
      {report.question && report.query_answer && (
        <div className="rounded-md border border-sky-800 bg-sky-950/30 p-3">
          <div className="label-cap text-sky-300 mb-1">Asked</div>
          <p className="text-[12px] text-mist-100 italic">{report.question}</p>
          <div className="label-cap text-sky-300 mt-2 mb-1">Answered from structured data</div>
          <p className="text-[12.5px] text-mist-100 leading-relaxed">{report.query_answer}</p>
        </div>
      )}

      {!compact && (
        <>
          {report.what_is_happening && report.what_is_happening.length > 0 && (
            <div className="rounded-md border border-line bg-ink-850 p-3">
              <div className="label-cap text-sky-300 mb-1.5">What is happening</div>
              <ul className="space-y-1">
                {report.what_is_happening.map((line, i) => (
                  <li key={i} className="text-[12.5px] text-mist-100 leading-snug flex gap-1.5">
                    <span className="text-sky-500 shrink-0">›</span>{line}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {!!report.why?.length && (
            <div className="rounded-md border border-line bg-ink-850 p-3">
              <div className="label-cap text-amber-300 mb-1.5">Why</div>
              <div className="space-y-1.5">
                {report.why.map((w, i) => (
                  <div key={i} className="flex items-start gap-2">
                    <span className={`chip !text-[9px] shrink-0 ${
                      w.impact === 'CRITICAL' ? 'border-red-700 text-red-300'
                        : w.impact === 'HIGH' ? 'border-orange-700 text-orange-300'
                          : w.impact === 'MEDIUM' ? 'border-amber-700 text-amber-300'
                            : 'border-line-strong text-mist-400'}`}
                    >{w.impact}</span>
                    <span className="text-[12px] text-mist-200 leading-snug">{w.factor}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {!!report.affected_areas?.length && (
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="label-cap">Affected</span>
              {report.affected_areas.map((a) => (
                <span key={a} className="chip !text-[9px] border-line-strong bg-ink-800 text-mist-300">{a}</span>
              ))}
            </div>
          )}

          {!!report.predicted_effects?.length && (
            <div className="rounded-md border border-line bg-ink-850 p-3">
              <div className="label-cap text-violet-300 mb-1.5">Predicted effects</div>
              <div className="space-y-1.5">
                {report.predicted_effects.map((p, i) => (
                  <div key={i} className="flex items-start gap-2">
                    <span className={`chip !text-[9px] shrink-0 ${
                      p.likelihood === 'HIGH' ? 'border-orange-700 text-orange-300'
                        : p.likelihood === 'MEDIUM' ? 'border-amber-700 text-amber-300'
                          : 'border-line-strong text-mist-400'}`}
                    >{p.likelihood}</span>
                    <span className="text-[12px] text-mist-200 leading-snug">
                      {p.effect}
                      {p.time_horizon && <span className="num text-mist-500"> · {p.time_horizon}</span>}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {!!report.what_changed?.length && (
            <div className="rounded-md border border-line bg-ink-850 p-3">
              <div className="label-cap text-amber-300 mb-1.5">What changed</div>
              <div className="space-y-1.5">
                {report.what_changed.map((c, i) => (
                  <div key={i} className="flex items-start gap-2">
                    <span className="chip !text-[9px] shrink-0 border-line-strong bg-ink-800 text-mist-400">
                      {c.kind.replace(/_/g, ' ')}
                    </span>
                    <span className="text-[12px] text-mist-200 leading-snug">{c.message}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {report.route_assessment?.recommended_route && (
            <div className="rounded-md border border-line bg-ink-850 p-3">
              <div className="label-cap text-emerald-300 mb-1.5">Route assessment</div>
              <div className="text-[12.5px] text-mist-100">
                <b>{report.route_assessment.recommended_route}</b>
                {report.route_assessment.status && (
                  <span className="chip !text-[9px] border-emerald-800 text-emerald-300 ml-2">
                    {report.route_assessment.status}
                  </span>
                )}
                {report.route_assessment.risk != null && (
                  <span className="num text-mist-400 ml-2">risk {Math.round(report.route_assessment.risk)}/100</span>
                )}
                {report.route_assessment.estimated_time != null && (
                  <span className="num text-mist-400 ml-2">~{Math.round(report.route_assessment.estimated_time)}s</span>
                )}
              </div>
              {report.route_assessment.reason && (
                <p className="text-[11.5px] text-mist-400 mt-1 leading-snug">{report.route_assessment.reason}</p>
              )}
            </div>
          )}
        </>
      )}

      {/* recommendations — persisted rows carry human decision state (§24) */}
      <div>
        <div className="flex items-center gap-1.5 mb-1.5">
          <IconSpark width={13} height={13} className="text-amber-300" />
          <span className="label-cap">
            Recommendations{decisions ? ` (${cards.length})` : report.recommendations?.length ? ` (${report.recommendations.length})` : ''}
          </span>
          {decisions && (
            <span className="num text-[9.5px] text-mist-600 ml-auto">human decision required</span>
          )}
        </div>
        <div className="space-y-2">
          {decisions
            ? cards.map((rec) => (
              <div
                key={rec.recommendation_id}
                className={`rounded-md border p-2.5 ${
                  rec.status === 'PENDING'
                    ? rec.priority >= 3 ? 'border-orange-800 bg-orange-950/30' : 'border-line bg-ink-850'
                    : rec.status === 'ACCEPTED' ? 'border-emerald-800 bg-emerald-950/30'
                      : 'border-line bg-ink-850 opacity-70'
                }`}
              >
                <div className="flex items-start gap-2">
                  <span className="chip shrink-0 border-line-strong bg-ink-800 text-mist-300">
                    #{rec.priority}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="chip !text-[9px] border-line-strong text-mist-400">{rec.category}</span>
                      <span className={`chip !text-[9px] ${
                        rec.status === 'PENDING' ? 'border-amber-700 text-amber-300'
                          : rec.status === 'ACCEPTED' ? 'border-emerald-700 text-emerald-300'
                            : 'border-line-strong text-mist-500'}`}
                      >{rec.status}</span>
                    </div>
                    <div className="text-[12.5px] font-semibold leading-tight mt-1">{rec.action}</div>
                    <p className="text-[11.5px] text-mist-300 mt-1 leading-snug">{rec.reason}</p>
                  </div>
                </div>
                {rec.status === 'PENDING' && (
                  <div className="flex gap-2 mt-2">
                    <button
                      className="btn btn-success !py-1 !text-[11px]"
                      disabled={!canDecide || busyId === rec.recommendation_id}
                      onClick={() => void decide(rec.recommendation_id, 'ACCEPTED')}
                      title={canDecide ? 'Accept — queued for an operator to apply' : 'Requires OPERATOR/ADMIN role'}
                    >
                      <IconCheck width={12} height={12} />
                      {busyId === rec.recommendation_id ? 'Saving…' : 'ACCEPT'}
                    </button>
                    <button
                      className="btn !py-1 !text-[11px]"
                      disabled={!canDecide || busyId === rec.recommendation_id}
                      onClick={() => void decide(rec.recommendation_id, 'DISMISSED')}
                      title={canDecide ? 'Dismiss with a human decision' : 'Requires OPERATOR/ADMIN role'}
                    >
                      <IconX width={12} height={12} /> DISMISS
                    </button>
                  </div>
                )}
                {rec.decided_by && (
                  <div className="num text-[9.5px] text-mist-600 mt-1.5">
                    decided by {rec.decided_by}{rec.decided_at ? ` · ${rec.decided_at.slice(11, 19)}` : ''}
                  </div>
                )}
              </div>
            ))
            : (report.recommendations ?? []).map((rec) => (
              <div key={rec.id} className="rounded-md border border-line bg-ink-850 p-2.5">
                <div className="flex items-center gap-2">
                  <span className="chip !text-[9px] border-line-strong bg-ink-800 text-mist-300">
                    {rec.category}
                  </span>
                  <span className="num text-[9.5px] text-mist-600 ml-auto">
                    {Math.round(rec.confidence * 100)}% conf
                  </span>
                </div>
                <div className="text-[12.5px] font-semibold leading-tight mt-1">{rec.action}</div>
                <p className="text-[11.5px] text-mist-300 mt-1 leading-snug">{rec.reason}</p>
              </div>
            ))}
          {!decisions && (report.recommendations ?? []).length === 0 && (
            <div className="text-[11.5px] text-mist-500 border border-dashed border-line rounded-md p-3 text-center">
              No recommendations — operating normally.
            </div>
          )}
        </div>
      </div>

      {report.note && <p className="text-[10.5px] text-mist-500 italic">{report.note}</p>}
    </div>
  );
}
