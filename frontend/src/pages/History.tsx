import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import {
  IconDownload, IconHistory, IconPlay, IconRefresh, IconSearch, IconTarget,
} from '../components/Icons';
import { api } from '../services/api';
import { useTwinStore } from '../store/useTwinStore';
import type {
  IncidentDetailResponse, IncidentListResponse, IncidentReportResponse,
  SimulationCompareResponse, SimulationDetailResponse, SimulationListResponse,
} from '../types';
import { fmtNum, scenarioIcon, scenarioLabel } from '../utils/colors';
import { downloadCsv } from '../utils/download';

const PAGE_SIZE = 10;
const INC_STATUSES = ['ACTIVE', 'RESOLVED', 'CLOSED', 'DISMISSED'];
const SEVERITIES = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'];
const KINDS = ['FIRE', 'FLOOD', 'MEDICAL', 'SECURITY', 'POWER', 'WEATHER',
               'INFRASTRUCTURE', 'ENVIRONMENTAL', 'OTHER', 'DRILL'];
const SCENARIOS = ['all', 'fire', 'crowd', 'power', 'road', 'temperature'];
const SIM_STATUSES = ['CREATED', 'RUNNING', 'PAUSED', 'AWAITING_RECOVERY',
                      'RECOVERING', 'COMPLETED', 'RESET'];

const sevClass = (sev: string) => (
  sev === 'CRITICAL' || sev === 'HIGH' ? 'border-red-700 text-red-300'
    : sev === 'MEDIUM' ? 'border-amber-700 text-amber-300'
      : 'border-emerald-700 text-emerald-300'
);

const statusClass = (s: string) => (
  ['COMPLETED', 'RESOLVED', 'CLOSED'].includes(s) ? 'border-emerald-700 text-emerald-300'
    : ['RUNNING', 'ACTIVE'].includes(s) ? 'border-red-700 text-red-300'
      : 'border-line-strong text-mist-300'
);

function Paginate({ page, pages, total, onPage, loading }: {
  page: number; pages: number; total: number;
  onPage: (p: number) => void; loading: boolean;
}) {
  if (pages <= 1) {
    return <div className="px-3 py-2 text-[11px] text-mist-500 num">{total} records</div>;
  }
  return (
    <div className="flex items-center gap-2 px-3 py-2 border-t border-line/60">
      <span className="text-[11px] text-mist-500 num">
        page {page} / {pages} · {total} records
      </span>
      <div className="flex-1" />
      <button
        className="btn !py-0.5 !text-[11px]"
        data-testid="paginate-prev"
        disabled={loading || page <= 1}
        onClick={() => onPage(page - 1)}
      >
        ‹ Prev
      </button>
      <button
        className="btn !py-0.5 !text-[11px]"
        data-testid="paginate-next"
        disabled={loading || page >= pages}
        onClick={() => onPage(page + 1)}
      >
        Next ›
      </button>
    </div>
  );
}

function MetricGrid({ items }: { items: Array<[string, string]> }) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
      {items.map(([label, value]) => (
        <div key={label} className="rounded-lg border border-line bg-ink-850 px-2.5 py-2">
          <div className="label-cap">{label}</div>
          <div className="num text-[13px] font-semibold mt-0.5">{value}</div>
        </div>
      ))}
    </div>
  );
}

/**
 * Phase 9 §62 — historical intelligence: incidents + simulations tabs with
 * server-side pagination/filters (URL-persisted), incident detail + report +
 * CSV export, simulation detail/events, two-run compare and replay hand-off.
 */
export default function History() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const handleApiError = useTwinStore((s) => s.handleApiError);
  const focusCamera = useTwinStore((s) => s.focusCamera);
  const selectBuilding = useTwinStore((s) => s.selectBuilding);
  const snapshot = useTwinStore((s) => s.snapshot);

  const tab = params.get('tab') === 'incidents' ? 'incidents' as const : 'simulations' as const;
  const page = Math.max(1, Number(params.get('page') ?? '1') || 1);
  const incStatus = params.get('status') ?? '';
  const incSeverity = params.get('severity') ?? '';
  const incKind = params.get('kind') ?? '';
  const incQ = params.get('q') ?? '';
  const scenario = params.get('scenario') ?? '';
  const simStatus = params.get('simstatus') ?? '';
  const simQ = params.get('simq') ?? '';
  const incId = params.get('inc') ?? '';
  const simId = params.get('sim') ?? '';
  const cmpParam = params.get('cmp') ?? '';

  const setParam = useCallback((key: string, value: string, keepPage = false) => {
    setParams((prev) => {
      const p = new URLSearchParams(prev);
      if (value) p.set(key, value);
      else p.delete(key);
      if (!keepPage && key !== 'page') p.delete('page');
      return p;
    });
  }, [setParams]);

  const setTab = useCallback((next: 'incidents' | 'simulations') => {
    setParams((prev) => {
      const p = new URLSearchParams(prev);
      p.set('tab', next);
      p.delete('page');
      p.delete('inc');
      p.delete('sim');
      p.delete('cmp');
      return p;
    });
  }, [setParams]);

  const locate = (targetId: string | null) => {
    navigate('/twin');
    if (!targetId) return;
    void selectBuilding(targetId);
    const b = snapshot?.buildings.find((x) => x.id === targetId);
    if (b) focusCamera(b.position.x, b.position.z);
  };

  // ---- lists (server-side pagination + filters) ----
  const [incidents, setIncidents] = useState<IncidentListResponse | null>(null);
  const [sims, setSims] = useState<SimulationListResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshTick, setRefreshTick] = useState(0);

  useEffect(() => {
    if (tab !== 'incidents') return undefined;
    let alive = true;
    setLoading(true);
    api.historyIncidents({
      page, page_size: PAGE_SIZE,
      status: incStatus || undefined,
      severity: incSeverity || undefined,
      kind: incKind || undefined,
      q: incQ || undefined,
    })
      .then((res) => { if (alive) setIncidents(res); })
      .catch((err) => { if (alive) handleApiError(err); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [tab, page, incStatus, incSeverity, incKind, incQ, handleApiError, refreshTick]);

  useEffect(() => {
    if (tab !== 'simulations') return undefined;
    let alive = true;
    setLoading(true);
    api.historySimulations({
      page, page_size: PAGE_SIZE,
      scenario: scenario || undefined,
      status: simStatus || undefined,
      q: simQ || undefined,
    })
      .then((res) => { if (alive) setSims(res); })
      .catch((err) => { if (alive) handleApiError(err); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [tab, page, scenario, simStatus, simQ, handleApiError, refreshTick]);

  /** Single URL write so back-to-back navigation never drops a param. */
  const openIncident = useCallback((id: string) => {
    setParams((prev) => {
      const p = new URLSearchParams(prev);
      p.set('tab', 'incidents');
      p.set('inc', id);
      p.delete('sim');
      p.delete('cmp');
      p.delete('page');
      return p;
    });
  }, [setParams]);

  // ---- incident detail + report ----
  const [incDetail, setIncDetail] = useState<IncidentDetailResponse | null>(null);
  const [incDetailLoading, setIncDetailLoading] = useState(false);
  const [report, setReport] = useState<IncidentReportResponse | null>(null);
  const [reportLoading, setReportLoading] = useState(false);

  useEffect(() => {
    if (!incId) {
      setIncDetail(null);
      setReport(null);
      return undefined;
    }
    let alive = true;
    setIncDetailLoading(true);
    setReport(null);
    api.historyIncident(incId)
      .then((res) => { if (alive) setIncDetail(res); })
      .catch((err) => { if (alive) handleApiError(err); })
      .finally(() => { if (alive) setIncDetailLoading(false); });
    return () => { alive = false; };
  }, [incId, handleApiError]);

  const loadReport = useCallback(async (id: string) => {
    setReportLoading(true);
    try {
      setReport(await api.incidentReport(id));
    } catch (err) {
      handleApiError(err);
    } finally {
      setReportLoading(false);
    }
  }, [handleApiError]);

  const exportIncident = useCallback(async (id: string) => {
    try {
      const text = await api.incidentExport(id, 'csv');
      downloadCsv(`twinsphere_incident_${id}`, text);
    } catch (err) {
      handleApiError(err);
    }
  }, [handleApiError]);

  // ---- simulation detail + compare ----
  const [simDetail, setSimDetail] = useState<SimulationDetailResponse | null>(null);
  const [simDetailLoading, setSimDetailLoading] = useState(false);
  const [compare, setCompare] = useState<SimulationCompareResponse | null>(null);
  const [compareLoading, setCompareLoading] = useState(false);

  useEffect(() => {
    if (!simId) {
      setSimDetail(null);
      return undefined;
    }
    let alive = true;
    setSimDetailLoading(true);
    api.historySimulation(simId)
      .then((res) => { if (alive) setSimDetail(res); })
      .catch((err) => { if (alive) handleApiError(err); })
      .finally(() => { if (alive) setSimDetailLoading(false); });
    return () => { alive = false; };
  }, [simId, handleApiError]);

  const cmpIds = cmpParam.split(',').filter(Boolean);
  const loadCompare = useCallback(async (ids: string[]) => {
    if (ids.length !== 2) {
      setCompare(null);
      return;
    }
    setCompareLoading(true);
    try {
      setCompare(await api.compareSimulations(ids[0], ids[1]));
    } catch (err) {
      handleApiError(err);
      setCompare(null);
    } finally {
      setCompareLoading(false);
    }
  }, [handleApiError]);

  useEffect(() => {
    void loadCompare(cmpParam.split(',').filter(Boolean));
  }, [cmpParam, loadCompare]);

  const toggleCompare = (id: string) => {
    const ids = new Set(cmpIds);
    if (ids.has(id)) ids.delete(id);
    else if (ids.size < 2) ids.add(id);
    setParam('cmp', [...ids].join(','));
  };

  // ---- exports ----
  const [exporting, setExporting] = useState(false);
  const exportList = useCallback(async () => {
    setExporting(true);
    try {
      const csv = await api.historyExport(tab, { page_size: 1000 });
      downloadCsv(`twinsphere_${tab}`, csv);
    } catch (err) {
      handleApiError(err);
    } finally {
      setExporting(false);
    }
  }, [tab, handleApiError]);

  const inc = incDetail?.incident ?? null;

  return (
    <div className="h-full overflow-y-auto scroll-y p-4 space-y-4">
      {/* header + tabs */}
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-lg font-bold flex items-center gap-2">
          <IconHistory width={17} height={17} className="text-brand-400" /> History
        </h1>
        <div className="flex gap-1.5">
          <button
            data-testid="tab-simulations"
            onClick={() => setTab('simulations')}
            className={`chip ${tab === 'simulations' ? 'border-brand-400 bg-brand-950/70 text-brand-200' : ''}`}
          >
            Simulations{sims ? ` · ${sims.total}` : ''}
          </button>
          <button
            data-testid="tab-incidents"
            onClick={() => setTab('incidents')}
            className={`chip ${tab === 'incidents' ? 'border-brand-400 bg-brand-950/70 text-brand-200' : ''}`}
          >
            Incidents{incidents ? ` · ${incidents.total}` : ''}
          </button>
        </div>
        <div className="flex-1" />
        <button
          className="btn"
          data-testid="history-export"
          onClick={() => void exportList()}
          disabled={exporting}
        >
          <IconDownload width={13} height={13} /> {exporting ? 'Exporting…' : 'Export CSV'}
        </button>
        <button className="btn" data-testid="history-refresh"
          onClick={() => setRefreshTick((t) => t + 1)}>
          <IconRefresh width={13} height={13} className={loading ? 'animate-spin' : ''} /> Refresh
        </button>
      </div>

      {/* filters */}
      {tab === 'incidents' ? (
        <div className="flex items-center gap-1.5 flex-wrap">
          <div className="relative">
            <IconSearch width={12} height={12}
              className="absolute left-2 top-1/2 -translate-y-1/2 text-mist-500" />
            <input
              data-testid="search-incidents"
              aria-label="Search incidents"
              placeholder="code, title…"
              defaultValue={incQ}
              onKeyDown={(e) => {
                if (e.key === 'Enter') setParam('q', (e.target as HTMLInputElement).value);
              }}
              className="bg-ink-800 border border-line-strong rounded pl-7 pr-2 py-1 text-[11.5px] w-44"
            />
          </div>
          <select
            data-testid="filter-inc-status"
            aria-label="Incident status filter"
            value={incStatus}
            onChange={(e) => setParam('status', e.target.value)}
            className="bg-ink-800 border border-line-strong rounded px-2 py-1 text-[11.5px]"
          >
            <option value="">All statuses</option>
            {INC_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <select
            data-testid="filter-inc-severity"
            aria-label="Incident severity filter"
            value={incSeverity}
            onChange={(e) => setParam('severity', e.target.value)}
            className="bg-ink-800 border border-line-strong rounded px-2 py-1 text-[11.5px]"
          >
            <option value="">All severities</option>
            {SEVERITIES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <select
            data-testid="filter-inc-kind"
            aria-label="Incident kind filter"
            value={incKind}
            onChange={(e) => setParam('kind', e.target.value)}
            className="bg-ink-800 border border-line-strong rounded px-2 py-1 text-[11.5px]"
          >
            <option value="">All kinds</option>
            {KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
          </select>
          {(incStatus || incSeverity || incKind || incQ) && (
            <button
              className="chip"
              data-testid="clear-inc-filters"
              onClick={() => setParams((prev) => {
                const p = new URLSearchParams(prev);
                ['status', 'severity', 'kind', 'q', 'page'].forEach((k) => p.delete(k));
                return p;
              })}
            >
              Clear
            </button>
          )}
        </div>
      ) : (
        <div className="flex items-center gap-1.5 flex-wrap">
          <div className="relative">
            <IconSearch width={12} height={12}
              className="absolute left-2 top-1/2 -translate-y-1/2 text-mist-500" />
            <input
              data-testid="search-simulations"
              aria-label="Search simulations"
              placeholder="code…"
              defaultValue={simQ}
              onKeyDown={(e) => {
                if (e.key === 'Enter') setParam('simq', (e.target as HTMLInputElement).value);
              }}
              className="bg-ink-800 border border-line-strong rounded pl-7 pr-2 py-1 text-[11.5px] w-40"
            />
          </div>
          {SCENARIOS.map((f) => (
            <button
              key={f}
              data-testid={`scenario-${f}`}
              onClick={() => setParam('scenario', f === 'all' ? '' : f)}
              className={`chip ${(scenario || 'all') === f ? 'border-brand-400 bg-brand-950/70 text-brand-200' : ''}`}
            >
              {f === 'all' ? 'All scenarios' : scenarioLabel(f)}
            </button>
          ))}
          <select
            data-testid="filter-sim-status"
            aria-label="Simulation status filter"
            value={simStatus}
            onChange={(e) => setParam('simstatus', e.target.value)}
            className="bg-ink-800 border border-line-strong rounded px-2 py-1 text-[11.5px]"
          >
            <option value="">All statuses</option>
            {SIM_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <div className="flex-1" />
          <button
            className="btn !py-0.5 !text-[11px]"
            data-testid="compare-btn"
            disabled={cmpIds.length !== 2 || compareLoading}
            onClick={() => void loadCompare(cmpIds)}
          >
            Compare ({cmpIds.length}/2)
          </button>
          {cmpIds.length > 0 && (
            <button className="chip" data-testid="compare-clear"
              onClick={() => setParam('cmp', '')}>
              Clear compare
            </button>
          )}
        </div>
      )}

      {/* compare result */}
      {compare && (
        <section className="panel rounded-xl p-4" data-testid="compare-panel">
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-[13px] font-bold">
              Compare · <span className="num">{compare.a.code}</span> vs{' '}
              <span className="num">{compare.b.code}</span>
            </h2>
            <button className="btn !py-0.5 !text-[11px]" onClick={() => setParam('cmp', '')}>
              Close
            </button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[12px]">
              <thead>
                <tr className="border-b border-line text-left">
                  <th className="label-cap px-2 py-1.5">Metric</th>
                  <th className="label-cap px-2 py-1.5 num">{compare.a.code}</th>
                  <th className="label-cap px-2 py-1.5 num">{compare.b.code}</th>
                </tr>
              </thead>
              <tbody>
                {compare.rows.map((r) => (
                  <tr key={r.metric} className="border-b border-line/50">
                    <td className="px-2 py-1.5 text-mist-300">{r.label}</td>
                    <td className="px-2 py-1.5 num">{r.a ?? '—'}</td>
                    <td className="px-2 py-1.5 num">{r.b ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* tables */}
      <div className="panel rounded-xl overflow-hidden">
        {tab === 'simulations' ? (
          <div className="overflow-x-auto">
            <table className="w-full text-[12.5px]">
              <thead>
                <tr className="border-b border-line bg-ink-850/80 text-left">
                  <th className="label-cap px-3 py-2.5 w-8" />
                  {['Code', 'Scenario', 'Target', 'Status', 'Created', 'Peak risk',
                    'People', 'Recovery', 'Severity', 'Events', ''].map((h) => (
                    <th key={h} className="label-cap px-3 py-2.5 whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(sims?.items ?? []).map((s) => (
                  <tr
                    key={s.id}
                    data-testid={`sim-row-${s.id}`}
                    className="border-b border-line/60 hover:bg-ink-850/60 cursor-pointer"
                    onClick={() => setParam('sim', s.id, true)}
                  >
                    <td className="px-3 py-2.5" onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        aria-label={`Compare select ${s.code}`}
                        data-testid={`sim-cmp-${s.id}`}
                        checked={cmpIds.includes(s.id)}
                        onChange={() => toggleCompare(s.id)}
                      />
                    </td>
                    <td className="px-3 py-2.5 num font-semibold whitespace-nowrap">{s.code}</td>
                    <td className="px-3 py-2.5 whitespace-nowrap">
                      <span className="flex items-center gap-2">
                        <span>{scenarioIcon(s.scenario)}</span>
                        <span>{scenarioLabel(s.scenario)}</span>
                      </span>
                    </td>
                    <td className="px-3 py-2.5 text-mist-300">{s.target_id ?? 'campus-wide'}</td>
                    <td className="px-3 py-2.5">
                      <span className={`chip !text-[9.5px] ${statusClass(s.status)}`}>{s.status}</span>
                    </td>
                    <td className="px-3 py-2.5 num text-mist-400 whitespace-nowrap">
                      {new Date(s.created_at).toLocaleString()}
                    </td>
                    <td className="px-3 py-2.5 num">
                      <span className={s.peak_risk > 60 ? 'text-red-400 font-bold'
                        : s.peak_risk > 35 ? 'text-amber-300' : 'text-emerald-400'}>
                        {s.peak_risk.toFixed(0)}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 num">{fmtNum(s.people_affected)}</td>
                    <td className="px-3 py-2.5 num text-mist-300">
                      {s.recovery_time_s > 0 ? `${s.recovery_time_s.toFixed(0)}s` : '—'}
                    </td>
                    <td className="px-3 py-2.5">
                      <span className={`chip !text-[9.5px] ${sevClass(s.severity)}`}>{s.severity}</span>
                    </td>
                    <td className="px-3 py-2.5 num text-mist-400">{s.events}</td>
                    <td className="px-3 py-2.5 text-right whitespace-nowrap"
                      onClick={(e) => e.stopPropagation()}>
                      <button
                        className="btn !py-0.5 !text-[11px] mr-1.5"
                        data-testid={`replay-${s.id}`}
                        onClick={() => navigate(`/dashboard?replay=${encodeURIComponent(s.id)}`)}
                      >
                        <IconPlay width={11} height={11} /> Replay
                      </button>
                      <button
                        className="btn !py-0.5 !text-[11px]"
                        onClick={() => locate(s.target_id)}
                      >
                        <IconTarget width={11} height={11} /> Locate
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {loading && (sims?.items ?? []).length === 0 && (
              <div className="px-4 py-8 text-center text-[12.5px] text-mist-500">Loading…</div>
            )}
            {!loading && (sims?.items ?? []).length === 0 && (
              <div className="px-4 py-10 text-center" data-testid="empty-simulations">
                <div className="text-[13px] text-mist-300 mb-1">No simulations match these filters.</div>
                <div className="text-[12px] text-mist-500">
                  Run a drill in the <Link className="text-brand-400 underline" to="/simulation">Simulation Center</Link> to build history.
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-[12.5px]">
              <thead>
                <tr className="border-b border-line bg-ink-850/80 text-left">
                  {['Code', 'Title', 'Kind', 'Severity', 'Status', 'Started',
                    'Duration', 'Risk', 'Building', ''].map((h) => (
                    <th key={h} className="label-cap px-3 py-2.5 whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(incidents?.items ?? []).map((i) => (
                  <tr
                    key={i.id}
                    data-testid={`inc-row-${i.id}`}
                    className="border-b border-line/60 hover:bg-ink-850/60 cursor-pointer"
                    onClick={() => setParam('inc', i.id, true)}
                  >
                    <td className="px-3 py-2.5 num font-semibold whitespace-nowrap">{i.code}</td>
                    <td className="px-3 py-2.5 max-w-[260px] truncate">{i.title}</td>
                    <td className="px-3 py-2.5 text-mist-300">{i.kind}</td>
                    <td className="px-3 py-2.5">
                      <span className={`chip !text-[9.5px] ${sevClass(i.severity)}`}>{i.severity}</span>
                    </td>
                    <td className="px-3 py-2.5">
                      <span className={`chip !text-[9.5px] ${statusClass(i.status)}`}>{i.status}</span>
                    </td>
                    <td className="px-3 py-2.5 num text-mist-400 whitespace-nowrap">
                      {new Date(i.started_at).toLocaleString()}
                    </td>
                    <td className="px-3 py-2.5 num text-mist-300">
                      {i.duration_s != null ? `${i.duration_s.toFixed(0)}s` : '—'}
                    </td>
                    <td className="px-3 py-2.5 num">
                      {i.risk_score != null ? i.risk_score.toFixed(0) : '—'}
                    </td>
                    <td className="px-3 py-2.5 text-mist-300 num">{i.building_id ?? '—'}</td>
                    <td className="px-3 py-2.5 text-right whitespace-nowrap"
                      onClick={(e) => e.stopPropagation()}>
                      <button
                        className="btn !py-0.5 !text-[11px]"
                        data-testid={`inc-export-${i.id}`}
                        onClick={() => void exportIncident(i.id)}
                      >
                        <IconDownload width={11} height={11} /> CSV
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {loading && (incidents?.items ?? []).length === 0 && (
              <div className="px-4 py-8 text-center text-[12.5px] text-mist-500">Loading…</div>
            )}
            {!loading && (incidents?.items ?? []).length === 0 && (
              <div className="px-4 py-10 text-center" data-testid="empty-incidents">
                <div className="text-[13px] text-mist-300 mb-1">No incidents match these filters.</div>
                <div className="text-[12px] text-mist-500">Widen the filters, or run a simulation to generate incidents.</div>
              </div>
            )}
          </div>
        )}
        <Paginate
          page={page}
          pages={tab === 'incidents' ? (incidents?.pages ?? 1) : (sims?.pages ?? 1)}
          total={tab === 'incidents' ? (incidents?.total ?? 0) : (sims?.total ?? 0)}
          onPage={(p) => setParam('page', String(p), true)}
          loading={loading}
        />
      </div>

      {/* incident detail drawer */}
      {tab === 'incidents' && incId && (
        <section className="panel rounded-xl p-4" data-testid="incident-drawer">
          <div className="flex items-center justify-between gap-2 mb-3 flex-wrap">
            <div className="flex items-baseline gap-2 min-w-0">
              <h2 className="text-[13px] font-bold">
                {incDetailLoading ? 'Loading incident…' : (inc ? `${inc.code} · ${inc.title}` : 'Incident')}
              </h2>
              {inc && <span className={`chip !text-[9.5px] ${sevClass(inc.severity)}`}>{inc.severity}</span>}
              {inc && <span className={`chip !text-[9.5px] ${statusClass(inc.status)}`}>{inc.status}</span>}
            </div>
            <div className="flex gap-1.5">
              {inc && (
                <>
                  <button
                    className="btn !py-0.5 !text-[11px]"
                    data-testid="report-toggle"
                    onClick={() => (report ? setReport(null) : void loadReport(inc.id))}
                    disabled={reportLoading}
                  >
                    {reportLoading ? 'Building…' : report ? 'Hide report' : 'Generate report'}
                  </button>
                  <button
                    className="btn !py-0.5 !text-[11px]"
                    data-testid="incident-export"
                    onClick={() => void exportIncident(inc.id)}
                  >
                    <IconDownload width={11} height={11} /> Export CSV
                  </button>
                  <button
                    className="btn !py-0.5 !text-[11px]"
                    onClick={() => locate(inc.building_id)}
                  >
                    <IconTarget width={11} height={11} /> Locate
                  </button>
                </>
              )}
              <button className="btn !py-0.5 !text-[11px]" data-testid="incident-close"
                onClick={() => setParam('inc', '')}>
                Close
              </button>
            </div>
          </div>

          {incDetail && (
            <div className="space-y-3">
              <MetricGrid items={[
                ['Duration', incDetail.metrics.duration_s != null ? `${incDetail.metrics.duration_s.toFixed(0)}s` : '—'],
                ['Peak risk', incDetail.metrics.peak_risk != null ? incDetail.metrics.peak_risk.toFixed(0) : '—'],
                ['Avg risk', incDetail.metrics.avg_risk != null ? incDetail.metrics.avg_risk.toFixed(1) : '—'],
                ['People affected', fmtNum(incDetail.metrics.people_affected ?? 0)],
                ['Timeline items', String(incDetail.metrics.timeline_items)],
                ['Recommendations', String(incDetail.metrics.recommendations)],
                ['Risk entity', incDetail.metrics.risk_entity ?? '—'],
                ['Source', incDetail.source],
              ]} />
              <div className="text-[11.5px] text-mist-300">{inc?.description}</div>

              <div>
                <div className="label-cap mb-1">Timeline</div>
                <div className="space-y-1 max-h-56 scroll-y pr-1">
                  {incDetail.timeline.length === 0 && (
                    <div className="text-[12px] text-mist-500">No timeline items persisted for this incident.</div>
                  )}
                  {incDetail.timeline.map((ev) => (
                    <div key={ev.id} className="flex gap-2 text-[11.5px]">
                      <span className="num text-mist-500 w-[150px] shrink-0 truncate">{ev.t}</span>
                      <span className="chip !text-[9px] shrink-0">{String(ev.category)}</span>
                      <span className="text-mist-300 w-[140px] shrink-0 truncate">{ev.kind}</span>
                      <span className="text-mist-100 truncate">{ev.title}</span>
                    </div>
                  ))}
                </div>
              </div>

              {report && (
                <div className="rounded-lg border border-line bg-ink-850 p-3 space-y-2"
                  data-testid="report-block">
                  <div className="flex items-center gap-2">
                    <span className="label-cap">Incident report</span>
                    <span className="chip !text-[9px]">{report.report_type}</span>
                    <span className="num text-[10.5px] text-mist-500">
                      {report.window.started_at ?? '—'} → {report.window.resolved_at ?? 'ongoing'}
                    </span>
                  </div>
                  <p className="text-[12px] text-mist-200 leading-relaxed">
                    {report.executive_summary}
                  </p>
                  <div className="grid sm:grid-cols-2 gap-3">
                    <div>
                      <div className="label-cap mb-1">Timeline categories</div>
                      <div className="flex flex-wrap gap-1.5">
                        {Object.entries(report.timeline_categories).map(([k, v]) => (
                          <span key={k} className="chip !text-[9.5px] num">{k}: {v}</span>
                        ))}
                        {Object.keys(report.timeline_categories).length === 0 && (
                          <span className="text-[11.5px] text-mist-500">none</span>
                        )}
                      </div>
                    </div>
                    <div>
                      <div className="label-cap mb-1">Response actions</div>
                      <div className="space-y-0.5">
                        {report.response_actions.map((a, i) => (
                          <div key={i} className="text-[11.5px] text-mist-300">
                            <span className="chip !text-[9px] mr-1.5">{a.category}</span>
                            {a.title}
                          </div>
                        ))}
                        {report.response_actions.length === 0 && (
                          <span className="text-[11.5px] text-mist-500">none recorded</span>
                        )}
                      </div>
                    </div>
                  </div>
                  {report.contributing_factors.length > 0 && (
                    <div>
                      <div className="label-cap mb-1">Contributing factors</div>
                      <div className="space-y-0.5">
                        {report.contributing_factors.map((f, i) => (
                          <div key={i} className="text-[11.5px] text-mist-300 num">
                            {Object.entries(f).map(([k, v]) => `${k}=${String(v)}`).join(' · ')}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </section>
      )}

      {/* simulation detail drawer */}
      {tab === 'simulations' && simId && (
        <section className="panel rounded-xl p-4" data-testid="simulation-drawer">
          <div className="flex items-center justify-between gap-2 mb-3 flex-wrap">
            <div className="flex items-baseline gap-2 min-w-0">
              <h2 className="text-[13px] font-bold">
                {simDetailLoading ? 'Loading simulation…'
                  : (simDetail ? `${simDetail.simulation.code} · ${scenarioLabel(simDetail.simulation.scenario)}` : 'Simulation')}
              </h2>
              {simDetail && (
                <span className={`chip !text-[9.5px] ${statusClass(simDetail.simulation.status)}`}>
                  {simDetail.simulation.status}
                </span>
              )}
            </div>
            <div className="flex gap-1.5">
              <button
                className="btn !py-0.5 !text-[11px]"
                data-testid="drawer-replay-btn"
                onClick={() => navigate(`/dashboard?replay=${encodeURIComponent(simId)}`)}
              >
                <IconPlay width={11} height={11} /> Replay
              </button>
              <button className="btn !py-0.5 !text-[11px]" data-testid="simulation-close"
                onClick={() => setParam('sim', '')}>
                Close
              </button>
            </div>
          </div>

          {simDetail && (
            <div className="space-y-3">
              <MetricGrid items={[
                ['Events', String(simDetail.metrics.events)],
                ['Incidents', String(simDetail.metrics.incidents)],
                ['Route events', String(simDetail.metrics.route_events)],
                ['AI analyses', String(simDetail.metrics.ai_analyses_in_window)],
                ['Peak risk (persisted)', simDetail.metrics.peak_risk_persisted != null
                  ? simDetail.metrics.peak_risk_persisted.toFixed(0) : '—'],
                ['Avg risk (persisted)', simDetail.metrics.avg_risk_persisted != null
                  ? simDetail.metrics.avg_risk_persisted.toFixed(1) : '—'],
                ['Wall start', simDetail.metrics.wall_start
                  ? new Date(simDetail.metrics.wall_start).toLocaleString() : '—'],
                ['Wall end', simDetail.metrics.wall_end
                  ? new Date(simDetail.metrics.wall_end).toLocaleString() : '—'],
              ]} />

              <div>
                <div className="label-cap mb-1">
                  Events by category ({simDetail.metrics.events})
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {Object.entries(simDetail.metrics.events_by_category).map(([k, v]) => (
                    <span key={k} className="chip !text-[9.5px] num">{k}: {v}</span>
                  ))}
                  {Object.keys(simDetail.metrics.events_by_category).length === 0 && (
                    <span className="text-[11.5px] text-mist-500">No persisted events.</span>
                  )}
                </div>
              </div>

              {simDetail.incidents.length > 0 && (
                <div>
                  <div className="label-cap mb-1">Incidents from this run</div>
                  <div className="flex flex-wrap gap-1.5">
                    {simDetail.incidents.map((i) => (
                      <button
                        key={i.id}
                        className="chip !text-[9.5px]"
                        data-testid={`sim-inc-${i.id}`}
                        onClick={() => openIncident(i.id)}
                      >
                        {i.code} · {i.kind} · {i.severity}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              <div>
                <div className="label-cap mb-1">Event log</div>
                <div className="space-y-1 max-h-64 scroll-y pr-1">
                  {simDetail.events.length === 0 && (
                    <div className="text-[12px] text-mist-500">No persisted events for this run.</div>
                  )}
                  {simDetail.events.map((ev) => (
                    <div key={ev.id} className="flex gap-2 text-[11.5px]">
                      <span className="num text-mist-500 w-[54px] shrink-0">T+{ev.t.toFixed(0)}s</span>
                      <span className="chip !text-[9px] shrink-0">{String(ev.category)}</span>
                      <span className="text-mist-300 w-[130px] shrink-0 truncate">
                        {ev.kind.replace(/_/g, ' ')}
                      </span>
                      <span className="text-mist-100">{ev.message}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
