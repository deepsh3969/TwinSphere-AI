import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import {
  IconActivity, IconAlert, IconBrain, IconCheck, IconRefresh, IconSpark, IconTarget,
} from '../components/Icons';
import { api, ApiError } from '../services/api';
import { useTwinStore } from '../store/useTwinStore';
import AnalystBrief from '../components/ai/AnalystBrief';
import EvidencePanel from '../components/ai/EvidencePanel';
import type {
  AIEvent, Anomaly, AnalystRecommendationRow, Prediction, Recommendation,
  RiskResponse, RiskResult,
} from '../types';
import { fmtNum, getRiskColor, levelChip, trendLabel } from '../utils/colors';

function ConfidenceBar({ value, label }: { value: number; label?: string }) {
  const tone = value >= 0.75 ? 'bg-emerald-500' : value >= 0.5 ? 'bg-amber-400' : 'bg-red-400';
  return (
    <div className="flex items-center gap-2 min-w-[120px]">
      <div className="flex-1 h-1.5 rounded-full bg-ink-700 overflow-hidden">
        <div className={`h-full ${tone}`} style={{ width: `${Math.round(value * 100)}%` }} />
      </div>
      <span className="num text-[10.5px] text-mist-400 w-12 text-right">
        {label ?? `${Math.round(value * 100)}%`}
      </span>
    </div>
  );
}

const SEVERITIES = ['ALL', 'CRITICAL', 'HIGH', 'MODERATE', 'LOW'] as const;
const HORIZONS = ['ALL', '15', '30', '60'] as const;

/** NORMAL band anomalies never render as alerts — they are quiet by design. */
function bandOf(a: Anomaly): string {
  const b = (a.band ?? a.severity ?? '').toUpperCase();
  return b === 'MEDIUM' ? 'MODERATE' : b;
}

function bandChip(band: string): string {
  switch (band) {
    case 'CRITICAL': return 'border-red-700 text-red-300';
    case 'HIGH': return 'border-orange-700 text-orange-300';
    case 'MODERATE': return 'border-amber-700 text-amber-300';
    case 'LOW': return 'border-sky-700 text-sky-300';
    default: return 'border-line-strong text-mist-400';
  }
}

function eventChip(kind: AIEvent['kind'], level?: string): string {
  if (level === 'critical') return 'border-red-700 text-red-300';
  if (level === 'warn') return 'border-amber-700 text-amber-300';
  switch (kind) {
    case 'ANOMALY': return 'border-orange-700 text-orange-300';
    case 'RISK': return 'border-red-700 text-red-300';
    case 'PREDICTION': return 'border-sky-700 text-sky-300';
    case 'DATA': return 'border-violet-700 text-violet-300';
    default: return 'border-line-strong text-mist-400';
  }
}

const DISCLAIMER =
  'AI limitations — predictions are statistical estimates from simulated sensor history, not guarantees. '
  + 'Anomaly scores and the risk index are weighted indicators for operators, not probabilities of harm. '
  + 'Verify against live sensors before acting.';

export default function AIIntelligence() {
  const snapshot = useTwinStore((s) => s.snapshot);
  const analyst = useTwinStore((s) => s.analyst);
  const analystStatus = useTwinStore((s) => s.analystStatus);
  const aiFallback = useTwinStore((s) => s.aiFallback);
  const refreshAnalyst = useTwinStore((s) => s.refreshAnalyst);
  const user = useTwinStore((s) => s.user);
  const pushToast = useTwinStore((s) => s.pushToast);
  const handleApiError = useTwinStore((s) => s.handleApiError);

  // Phase 5 AI slice (WS-fed + refreshAi)
  const anomalies = useTwinStore((s) => s.anomalies);
  const sensorAiStatus = useTwinStore((s) => s.sensorAiStatus);
  const anomalyDataQuality = useTwinStore((s) => s.anomalyDataQuality);
  const aiPredictions = useTwinStore((s) => s.aiPredictions);
  const aiEvents = useTwinStore((s) => s.aiEvents);
  const aiStatus = useTwinStore((s) => s.aiStatus);
  const aiDegraded = useTwinStore((s) => s.aiDegraded);
  const aiRefreshing = useTwinStore((s) => s.aiRefreshing);
  const refreshAi = useTwinStore((s) => s.refreshAi);

  const [riskRes, setRiskRes] = useState<RiskResponse | null>(null);
  const [recs, setRecs] = useState<Recommendation[]>([]);
  const [analystRecs, setAnalystRecs] = useState<AnalystRecommendationRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [question, setQuestion] = useState('');
  const [sevFilter, setSevFilter] = useState<string>('ALL');
  const [bldFilter, setBldFilter] = useState<string>('ALL');
  const [horizonTab, setHorizonTab] = useState<string>('ALL');

  // RBAC §10 — analysis requires the `analyze` permission (ADMIN/ANALYST)
  const canAnalyze = !!user && ['ADMIN', 'ANALYST'].includes(user.role);
  const canApply = !!user && ['ADMIN', 'OPERATOR'].includes(user.role);

  const loadAnalystRecs = useCallback(async () => {
    try {
      const res = await api.analystRecommendations();
      setAnalystRecs(res.recommendations ?? []);
    } catch {
      setAnalystRecs([]);
    }
  }, []);

  const load = useCallback(async () => {
    try {
      const [r, rec] = await Promise.all([
        api.risk().catch(() => null),
        api.recommendations().catch(() => []),
      ]);
      if (r) setRiskRes(r);
      setRecs(Array.isArray(rec) ? rec : []);
      void loadAnalystRecs();
      await refreshAi();
    } catch (err) {
      handleApiError(err);
    }
  }, [handleApiError, refreshAi, loadAnalystRecs]);

  useEffect(() => { void load(); }, [load]);

  // keep REST-only fields (events/status) warm even without WS traffic
  useEffect(() => {
    const t = window.setInterval(() => { void refreshAi(); }, 20000);
    return () => window.clearInterval(t);
  }, [refreshAi]);

  const ask = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const report = await api.analyze(question);
      useTwinStore.setState({ analyst: report, aiFallback: report.source === 'local_fallback' });
      pushToast('success', 'ANALYSIS COMPLETE', `Source: ${report.source === 'llm' ? 'LLM' : 'local fallback engine'}`);
      setQuestion('');
      void loadAnalystRecs();
      void refreshAnalyst();
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        pushToast('warn', 'ROLE RESTRICTED', 'Analysis requires the ANALYST or ADMIN role.');
      } else {
        handleApiError(err);
      }
    } finally {
      setBusy(false);
    }
  };

  const applyRec = async (id: string) => {
    setBusy(true);
    try {
      const rec = await api.applyRecommendation(id);
      pushToast('success', 'APPLIED', rec.applied_detail ?? rec.title);
      await Promise.all([load(), refreshAnalyst()]);
    } catch (err) {
      handleApiError(err);
    } finally {
      setBusy(false);
    }
  };

  const pending = recs.filter((r) => r.status === 'PENDING');
  const applied = recs.filter((r) => r.status === 'APPLIED');
  const risk: RiskResult | undefined = snapshot?.risk;

  const published = riskRes?.published?.campus ?? null;
  const rawCampus = riskRes?.campus ?? null;
  const riskHistory = useMemo(
    () => riskRes?.risk_history?.campus ?? [], [riskRes],
  );

  const buildingName = useCallback((id: string | null | undefined): string => {
    if (!id) return '—';
    const b = snapshot?.buildings.find((x) => x.id === id);
    return b?.name ?? id;
  }, [snapshot]);

  const filteredAnoms = useMemo(() => anomalies.filter((a) => {
    const band = bandOf(a);
    const sevOk = sevFilter === 'ALL' || band === sevFilter;
    const bldOk = bldFilter === 'ALL' || a.building_id === bldFilter;
    return sevOk && bldOk;
  }), [anomalies, sevFilter, bldFilter]);

  const filteredPreds = useMemo(() => aiPredictions.filter(
    (p) => horizonTab === 'ALL' || String(p.horizon_min) === horizonTab,
  ), [aiPredictions, horizonTab]);

  const aiStatusCounts = useMemo(() => {
    const vals = Object.values(sensorAiStatus);
    return {
      total: vals.length,
      flagged: vals.filter((v) => v.status !== 'NORMAL' && v.status !== 'INSUFFICIENT_DATA').length,
      insufficient: vals.filter((v) => v.status === 'INSUFFICIENT_DATA').length,
      normal: vals.filter((v) => v.status === 'NORMAL').length,
    };
  }, [sensorAiStatus]);

  const buildingRiskRows = useMemo(() => {
    const pub = riskRes?.published?.buildings ?? {};
    return (riskRes ? Object.keys(riskRes.buildings) : [])
      .map((id) => {
        const p = pub[id];
        const raw = riskRes?.buildings[id];
        const score = p?.score ?? raw?.score ?? 0;
        const level = p?.level ?? raw?.level ?? 'LOW';
        const factor = p?.factors?.[0] ?? raw?.factors?.[0];
        return { id, score, level, factor, rawScore: raw?.score ?? score };
      })
      .sort((a, b) => b.score - a.score);
  }, [riskRes]);

  return (
    <div className="h-full overflow-y-auto scroll-y p-4 space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-lg font-bold">AI Intelligence</h1>
        <span className={`chip ${aiDegraded ? 'border-red-700 bg-red-950/60 text-red-300' : 'border-sky-700 bg-sky-950/60 text-sky-300'}`}>
          {aiDegraded ? 'AI DEGRADED' : String((aiStatus?.anomaly_engine as string) ?? 'LAYERED ANOMALY ENGINE')}
        </span>
        <span className="chip border-line-strong bg-ink-800 text-mist-300">
          data: {anomalyDataQuality}
        </span>
        <span className={`chip ${aiFallback ? 'border-amber-700 bg-amber-950/60 text-amber-300' : 'border-emerald-700 bg-emerald-950/60 text-emerald-300'}`}>
          {aiFallback ? 'LOCAL FALLBACK ACTIVE' : 'LLM ANALYST'}
        </span>
        <div className="flex-1" />
        <button className="btn" onClick={() => void load()} disabled={busy || aiRefreshing}>
          <IconRefresh width={13} height={13} className={busy || aiRefreshing ? 'animate-spin' : ''} /> Refresh
        </button>
      </div>

      <div className="grid xl:grid-cols-[1.15fr_1fr] gap-4 items-start">
        {/* ---------------------------------------------------- left column */}
        <div className="space-y-4">
          {/* campus risk (published, stabilised) */}
          <div className="panel rounded-xl p-4">
            <div className="flex items-center justify-between mb-3">
              <span className="label-cap">Campus Risk — published (stabilised)</span>
              <span className={`chip ${levelChip(published?.level ?? risk?.level ?? 'LOW')}`}>
                {published?.level ?? risk?.level ?? 'LOW'}
              </span>
            </div>
            <div className="flex items-end gap-4">
              <div>
                <div className="num text-4xl font-bold" style={{ color: getRiskColor(published?.level) }}>
                  {fmtNum(published?.score ?? risk?.score ?? 0, 1)}
                </div>
                <div className="text-[11px] text-mist-500 mt-0.5">score / 100 · weighted index</div>
              </div>
              <div className="flex-1 text-[11.5px] text-mist-400 space-y-0.5 min-w-0">
                {rawCampus && (
                  <div className="num">raw {fmtNum(rawCampus.score, 1)} → published {fmtNum(published?.score ?? rawCampus.score, 1)}</div>
                )}
                {published?.trend != null && <div>trend: <b className="text-mist-200">{trendLabel(published.trend)}</b></div>}
                {rawCampus?.worst_building && <div>worst: <b className="text-mist-200">{buildingName(rawCampus.worst_building)}</b></div>}
              </div>
            </div>
            {riskHistory.length > 1 && (
              <div className="mt-3">
                <div className="label-cap mb-1">Published risk trend</div>
                <div className="flex items-end gap-px h-8" title="bounded stability history">
                  {riskHistory.slice(-48).map((h, i) => (
                    <div
                      key={i}
                      className="flex-1 rounded-sm min-w-[2px]"
                      style={{ height: `${Math.max(8, Math.min(100, h.score))}%`, background: getRiskColor(h.level) }}
                    />
                  ))}
                </div>
              </div>
            )}
            <div className="mt-3 pt-3 border-t border-line space-y-1.5">
              <div className="label-cap mb-1">Top contributing factors</div>
              {(published?.factors ?? risk?.factors ?? []).slice(0, 6).map((f) => (
                <div key={f.label} className="flex items-center gap-2 text-[12px]">
                  <span className="w-[160px] shrink-0 truncate text-mist-300">{f.label}</span>
                  <div className="flex-1 h-1.5 rounded-full bg-ink-700 overflow-hidden min-w-[60px]">
                    <div className="h-full bg-gradient-to-r from-amber-500 to-red-500" style={{ width: `${Math.min(100, f.contribution * 2)}%` }} />
                  </div>
                  <span className="num text-[11px] w-10 text-right">{f.contribution.toFixed(1)}</span>
                </div>
              ))}
              {(published?.factors ?? risk?.factors ?? []).length === 0 && (
                <div className="text-[12px] text-mist-500">No elevated factors — campus nominal.</div>
              )}
            </div>
          </div>

          {/* risk by building */}
          <div className="panel rounded-xl p-4">
            <div className="flex items-center justify-between mb-3">
              <span className="label-cap">Risk by building — published hierarchy</span>
              <span className="num text-[10.5px] text-mist-500">{buildingRiskRows.length} buildings</span>
            </div>
            <div className="space-y-2">
              {buildingRiskRows.map((b) => (
                <div key={b.id} className="rounded-md border border-line bg-ink-850 p-2.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[12.5px] font-semibold truncate">
                      {buildingName(b.id)}
                      {b.factor && (
                        <span className="text-mist-500 font-normal"> · {b.factor.label}</span>
                      )}
                    </span>
                    <span className="flex items-center gap-2 shrink-0">
                      <span className="num text-[12px]">{fmtNum(b.score, 1)}</span>
                      <span className={`chip !text-[9px] ${levelChip(b.level)}`}>{b.level}</span>
                    </span>
                  </div>
                  <div className="h-1.5 rounded-full bg-ink-700 overflow-hidden mt-1.5">
                    <div
                      className="h-full rounded-full transition-all"
                      style={{ width: `${Math.min(100, b.score)}%`, background: getRiskColor(b.level) }}
                    />
                  </div>
                </div>
              ))}
              {buildingRiskRows.length === 0 && (
                <div className="text-[12px] text-mist-500 border border-dashed border-line rounded-md p-4 text-center">
                  Risk hierarchy warming up — run a cycle or refresh.
                </div>
              )}
            </div>
          </div>

          {/* predictions */}
          <div className="panel rounded-xl p-4">
            <div className="flex items-center justify-between mb-3 gap-2 flex-wrap">
              <span className="label-cap">Predictions — occupancy & energy</span>
              <div className="flex gap-1">
                {HORIZONS.map((h) => (
                  <button
                    key={h}
                    className={`chip !text-[9px] cursor-pointer ${horizonTab === h
                      ? 'border-brand-500 bg-brand-950/60 text-brand-300'
                      : 'border-line-strong bg-ink-800 text-mist-400 hover:text-mist-200'}`}
                    onClick={() => setHorizonTab(h)}
                  >
                    {h === 'ALL' ? 'ALL' : `${h}m`}
                  </button>
                ))}
              </div>
            </div>
            <div className="space-y-2">
              {filteredPreds.slice(0, 12).map((p: Prediction) => (
                <div key={`${p.entity_id}-${p.metric}-${p.horizon_min}`} className="rounded-md border border-line bg-ink-850 p-2.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[12.5px] font-semibold truncate">
                      {buildingName(p.entity_id)}
                      <span className="text-mist-500 font-normal"> · {p.metric} · +{p.horizon_min}m</span>
                    </span>
                    <span className="flex items-center gap-1.5 shrink-0">
                      {p.status && (
                        <span className={`chip !text-[9px] ${
                          p.status === 'INSUFFICIENT_DATA' ? 'border-line-strong text-mist-400'
                            : p.status === 'LOW_CONFIDENCE' ? 'border-amber-700 text-amber-300'
                              : 'border-emerald-700 text-emerald-300'}`}
                        >{p.status}</span>
                      )}
                      <span className="chip !text-[9px] border-line-strong bg-ink-800 text-mist-300">{p.model_name}</span>
                    </span>
                  </div>
                  <div className="flex items-center justify-between mt-1.5 gap-3">
                    <span className="num text-[13px]">
                      {fmtNum(p.current_value, 1)} →{' '}
                      <b className={p.predicted_value > p.current_value ? 'text-amber-300' : 'text-sky-300'}>
                        {fmtNum(p.predicted_value, 1)}
                      </b>
                    </span>
                    <ConfidenceBar
                      value={p.confidence ?? 0}
                      label={p.confidence_label ?? `${Math.round((p.confidence ?? 0) * 100)}%`}
                    />
                  </div>
                  {(p.mae != null || p.r2 != null) && (
                    <div className="num text-[10.5px] text-mist-500 mt-1">
                      {p.mae != null && <>MAE {fmtNum(p.mae, 2)}</>}
                      {p.rmse != null && <> · RMSE {fmtNum(p.rmse, 2)}</>}
                      {p.r2 != null && <> · R² {p.r2.toFixed(2)}</>}
                      {p.samples != null && <> · n={p.samples}</>}
                    </div>
                  )}
                  <p className="text-[11px] text-mist-400 mt-1 leading-snug">{p.summary}</p>
                </div>
              ))}
              {filteredPreds.length === 0 && (
                <div className="text-[12px] text-mist-500 border border-dashed border-line rounded-md p-4 text-center">
                  No forecasts yet — the model needs ≥100 warm samples (cold start);
                  a deterministic baseline takes over until then.
                </div>
              )}
            </div>
          </div>

          {/* recent AI events */}
          <div className="panel rounded-xl p-4">
            <div className="flex items-center justify-between mb-3">
              <span className="label-cap">Recent AI events</span>
              <span className="num text-[10.5px] text-mist-500">{aiEvents.length} tracked</span>
            </div>
            <div className="space-y-1.5">
              {aiEvents.slice(0, 12).map((e, i) => (
                <div key={e.id ?? `${e.at}-${i}`} className="flex items-start gap-2 text-[12px]">
                  <span className={`chip !text-[9px] shrink-0 ${eventChip(e.kind, e.level)}`}>{e.kind}</span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-mist-200">{e.title}</div>
                    {e.detail && <div className="text-mist-500 text-[11px] truncate">{e.detail}</div>}
                  </div>
                  <span className="num text-[10px] text-mist-600 shrink-0">
                    {e.at ? e.at.slice(11, 19) : ''}
                  </span>
                </div>
              ))}
              {aiEvents.length === 0 && (
                <div className="text-[12px] text-mist-500 border border-dashed border-line rounded-md p-4 text-center">
                  No AI events yet — the first analysis cycle runs while the simulation is active.
                </div>
              )}
            </div>
          </div>

          {/* analyst */}
          <div className="panel rounded-xl p-4">
            <div className="flex items-center gap-2 mb-3 flex-wrap">
              <IconBrain width={16} height={16} className="text-brand-400" />
              <span className="label-cap">Operations Analyst</span>
              {/* Phase 8 §60 — analyst health pill (ONLINE/FALLBACK/DEGRADED/OFFLINE) */}
              {analystStatus && (
                <span
                  className={`chip !text-[9px] ${
                    analystStatus.status === 'ONLINE' ? 'border-emerald-700 bg-emerald-950/60 text-emerald-300'
                      : analystStatus.status === 'FALLBACK' ? 'border-amber-700 bg-amber-950/60 text-amber-300'
                        : analystStatus.status === 'DEGRADED' ? 'border-orange-700 bg-orange-950/60 text-orange-300'
                          : 'border-red-700 bg-red-950/60 text-red-300'}`}
                  title={analystStatus.llm_configured
                    ? `LLM configured · ${analystStatus.runs} runs · ${analystStatus.llm_errors} LLM errors`
                    : 'LLM_API_KEY not set — deterministic fallback analyst is in use'}
                >
                  {analystStatus.status}
                </span>
              )}
              {analyst?.model && <span className="num text-[10.5px] text-mist-500">model: {analyst.model}</span>}
              {analystStatus && (
                <span className="num text-[9.5px] text-mist-600 ml-auto">
                  {analystStatus.runs} runs · {analystStatus.cache_hits} cached · {analystStatus.last_latency_ms}ms
                </span>
              )}
            </div>

            <form onSubmit={ask} className="flex gap-2 mb-4">
              <input
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="Ask the campus analyst… (e.g. “Which building is most at risk right now?”)"
                className="flex-1 min-w-0 rounded-md bg-ink-900 border border-line px-3 py-2 text-[13px] outline-none focus:border-brand-500"
              />
              <button className="btn btn-primary" disabled={busy || !canAnalyze} title={canAnalyze ? 'Run analysis' : 'Requires ANALYST or ADMIN role'}>
                {busy ? 'Thinking…' : 'Analyze'}
              </button>
            </form>

            {analyst ? (
              <div className="space-y-3">
                <AnalystBrief
                  report={analyst}
                  decisions={analystRecs}
                  canDecide={canApply}
                  onDecided={() => { void loadAnalystRecs(); }}
                />
                {!!analyst.evidence?.length && <EvidencePanel evidence={analyst.evidence} />}
              </div>
            ) : (
              <div className="h-32 flex items-center justify-center border border-dashed border-line rounded-md">
                <div className="text-center">
                  <div className="w-6 h-6 mx-auto mb-2 border-2 border-brand-400 border-t-transparent rounded-full animate-spin" />
                  <div className="text-[12px] text-mist-400">Warming up analyst…</div>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* --------------------------------------------------- right column */}
        <div className="space-y-4">
          {/* active anomalies */}
          <div className="panel rounded-xl p-4">
            <div className="flex items-center justify-between mb-3 gap-2 flex-wrap">
              <span className="label-cap">Active anomalies</span>
              <div className="flex items-center gap-1.5 flex-wrap">
                <span className={`chip !text-[9px] ${
                  anomalyDataQuality === 'OK' ? 'border-emerald-700 text-emerald-300'
                    : anomalyDataQuality === 'LIMITED' ? 'border-amber-700 text-amber-300'
                      : 'border-line-strong text-mist-400'}`}
                >{anomalyDataQuality}</span>
                <span className="num text-[10px] text-mist-500">
                  {aiStatusCounts.flagged} flagged · {aiStatusCounts.insufficient} cold · {aiStatusCounts.total} sensors
                </span>
              </div>
            </div>

            {/* filters */}
            <div className="flex items-center gap-1.5 flex-wrap mb-3">
              {SEVERITIES.map((s) => (
                <button
                  key={s}
                  className={`chip !text-[9px] cursor-pointer ${sevFilter === s
                    ? 'border-brand-500 bg-brand-950/60 text-brand-300'
                    : 'border-line-strong bg-ink-800 text-mist-400 hover:text-mist-200'}`}
                  onClick={() => setSevFilter(s)}
                >
                  {s}
                </button>
              ))}
              <select
                value={bldFilter}
                onChange={(e) => setBldFilter(e.target.value)}
                className="rounded bg-ink-900 border border-line px-2 py-1 text-[11px] outline-none focus:border-brand-500"
              >
                <option value="ALL">All buildings</option>
                {(snapshot?.buildings ?? []).map((b) => (
                  <option key={b.id} value={b.id}>{b.name}</option>
                ))}
              </select>
              <span className="num text-[10px] text-mist-500 ml-auto">{filteredAnoms.length} shown</span>
            </div>

            <div className="space-y-1.5">
              {filteredAnoms.map((a) => (
                <div key={a.id ?? `${a.sensor_id}-${a.metric}`} className="rounded-md border border-line bg-ink-850 p-2.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[12.5px] font-semibold truncate">
                      {a.location} · {a.metric}
                    </span>
                    <span className="flex items-center gap-1.5 shrink-0">
                      <span className="num text-[11px] text-mist-300">{a.score}{a.band ? '/100' : ''}</span>
                      <span className={`chip !text-[9px] ${bandChip(bandOf(a))}`}>{bandOf(a)}</span>
                    </span>
                  </div>
                  <div className="num text-[11.5px] text-mist-300 mt-1">
                    value {fmtNum(a.value, 1)} · expected {fmtNum(a.expected, 1)} · z {a.z_score.toFixed(1)} · dev {a.deviation_pct.toFixed(0)}%
                  </div>
                  <div className="flex gap-1.5 mt-1.5 flex-wrap">
                    {a.detector && (
                      <span className="chip !py-0 !px-1.5 !text-[9px] border-line-strong text-mist-500">{a.detector}</span>
                    )}
                    {a.anomaly_type && (
                      <span className="chip !py-0 !px-1.5 !text-[9px] border-line-strong text-mist-500">{a.anomaly_type}</span>
                    )}
                    {a.status && (
                      <span className="chip !py-0 !px-1.5 !text-[9px] border-line-strong text-mist-500">
                        {a.status}{a.observations != null ? ` · ${a.observations} obs` : ''}
                      </span>
                    )}
                    {a.confidence == null && (
                      <span className="chip !py-0 !px-1.5 !text-[9px] border-violet-800 text-violet-300">
                        confidence withheld (n={a.available_samples ?? 0}&lt;{a.minimum_required ?? '—'})
                      </span>
                    )}
                  </div>
                  <p className="text-[11.5px] text-mist-400 mt-1 leading-snug">{a.explanation}</p>
                </div>
              ))}
              {filteredAnoms.length === 0 && (
                <div className="text-[12px] text-emerald-300/80 flex items-center gap-2 border border-dashed border-emerald-800/60 rounded-md p-3">
                  <IconCheck width={14} height={14} /> All telemetry within expected statistical bounds.
                </div>
              )}
            </div>
          </div>

          {/* recommendations */}
          <div className="panel rounded-xl p-4">
            <div className="flex items-center gap-2 mb-3">
              <IconSpark width={14} height={14} className="text-amber-300" />
              <span className="label-cap">Recommendations</span>
              <span className="num text-[10.5px] text-mist-500">{pending.length} pending · {applied.length} applied</span>
            </div>
            <div className="space-y-2">
              {pending.map((r) => (
                <div key={r.id} className={`rounded-md border p-2.5 ${
                  r.priority === 'CRITICAL' ? 'border-red-800 bg-red-950/40'
                    : r.priority === 'HIGH' ? 'border-orange-800 bg-orange-950/30'
                      : 'border-line bg-ink-850'
                }`}>
                  <div className="flex items-start gap-2">
                    <span className="chip shrink-0 border-line-strong bg-ink-800 text-mist-300">{r.priority}</span>
                    <div className="min-w-0">
                      <div className="text-[12.5px] font-semibold">{r.title}</div>
                      <p className="text-[11.5px] text-mist-300 mt-1 leading-snug">{r.rationale}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 mt-2">
                    <button
                      className="btn btn-success !py-1 !text-[11px]"
                      disabled={!canApply || busy}
                      onClick={() => void applyRec(r.id)}
                    >
                      <IconCheck width={12} height={12} /> APPLY RECOMMENDATION
                    </button>
                    {r.entity_id && snapshot?.buildings.some((b) => b.id === r.entity_id) && (
                      <Link className="btn !py-1 !text-[11px]" to={`/twin`}>
                        <IconTarget width={12} height={12} /> Inspect
                      </Link>
                    )}
                  </div>
                </div>
              ))}
              {applied.slice(0, 3).map((r) => (
                <div key={r.id} className="rounded-md border border-emerald-800 bg-emerald-950/30 p-2.5">
                  <div className="text-[12px] font-semibold text-emerald-200 flex items-center gap-1.5">
                    <IconCheck width={13} height={13} /> {r.title}
                  </div>
                  {r.applied_detail && <p className="text-[11px] text-emerald-300/75 mt-1">{r.applied_detail}</p>}
                </div>
              ))}
              {pending.length === 0 && applied.length === 0 && (
                <div className="text-[12px] text-mist-500 border border-dashed border-line rounded-md p-4 text-center">
                  No recommendations pending — run a simulation to generate decision support.
                </div>
              )}
            </div>
          </div>

          {/* system intelligence status */}
          <div className="panel rounded-xl p-4">
            <div className="flex items-center gap-2 mb-3">
              <IconActivity width={14} height={14} className="text-sky-300" />
              <span className="label-cap">System intelligence status</span>
            </div>
            <div className="grid grid-cols-2 gap-2 text-[12px]">
              <div className="rounded border border-line bg-ink-850 p-2">
                <div className="label-cap">Anomaly engine</div>
                <div className="font-semibold truncate">{String((aiStatus?.anomaly_engine as string) ?? '—')}</div>
                <div className="num text-[10px] text-mist-500">
                  threshold {String(aiStatus?.anomaly_score_threshold ?? '—')} · min n={String(aiStatus?.anomaly_min_samples ?? '—')}
                </div>
              </div>
              <div className="rounded border border-line bg-ink-850 p-2">
                <div className="label-cap">Prediction engine</div>
                <div className="font-semibold truncate">{String((aiStatus?.prediction_engine as string) ?? '—')}</div>
                <div className="num text-[10px] text-mist-500">
                  horizons {Array.isArray(aiStatus?.prediction_horizons)
                    ? (aiStatus?.prediction_horizons as number[]).join('/') : '—'}m
                </div>
              </div>
              <div className="rounded border border-line bg-ink-850 p-2">
                <div className="label-cap">Analyst source</div>
                <div className="font-semibold">{aiFallback ? 'Deterministic fallback' : 'LLM configured'}</div>
              </div>
              <div className="rounded border border-line bg-ink-850 p-2">
                <div className="label-cap">AI health</div>
                <div className="font-semibold flex items-center gap-1.5">
                  {aiDegraded ? 'Degraded' : 'Healthy'}
                  <span className={`chip !py-0 !px-1.5 !text-[9px] ${aiDegraded ? 'border-red-700 text-red-300' : 'border-emerald-700 text-emerald-300'}`}>
                    {aiDegraded ? 'ISOLATED' : 'OK'}
                  </span>
                </div>
                <div className="num text-[10px] text-mist-500">
                  cycle {String(aiStatus?.cycle_interval_s ?? '—')}s · tracked {String(aiStatus?.tracked_anomalies ?? anomalies.length)}
                </div>
              </div>
            </div>
            {anomalies.length > 0 && (
              <div className="mt-2.5 flex items-start gap-2 text-[11.5px] text-amber-200/85">
                <IconAlert width={13} height={13} className="mt-0.5" />
                {anomalies.length} anomalies currently tracked across {new Set(anomalies.map((a) => a.building_id)).size} buildings.
              </div>
            )}
            {snapshot?.anomalies && snapshot.anomalies.length > 0 && snapshot.anomalies.length !== anomalies.length && (
              <div className="mt-1.5 text-[11px] text-mist-500">
                Snapshot carries {snapshot.anomalies.length} legacy anomaly record(s).
              </div>
            )}
          </div>

          {/* AI limitations disclaimer — mandatory on this page */}
          <div className="rounded-xl border border-line bg-ink-900/70 p-3 flex items-start gap-2">
            <IconAlert width={14} height={14} className="text-mist-500 mt-0.5 shrink-0" />
            <p className="text-[11px] leading-relaxed text-mist-500">{DISCLAIMER}</p>
          </div>
        </div>
      </div>
    </div>
  );
}
