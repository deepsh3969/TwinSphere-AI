import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Line, LineChart,
  Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { useSearchParams } from 'react-router-dom';
import { IconDownload, IconRefresh, IconSearch } from '../components/Icons';
import { api, ApiError } from '../services/api';
import { useTwinStore } from '../store/useTwinStore';
import type {
  AiAnalyticsResponse, AnalyticsRange, BuildingsAnalyticsResponse,
  BuildingsCompareResponse, CampusHealthResponse, EnergyAnalyticsResponse,
  EnvironmentAnalyticsResponse, HistoryIncident, HistorySimulation,
  IncidentListResponse, OccupancyAnalyticsResponse, OverviewResponse,
  RiskAnalyticsResponse, RoutesAnalyticsResponse, SensorHealthDetailResponse,
  SensorHealthResponse, SeriesPoint,
} from '../types';
import { fmtNum } from '../utils/colors';
import { downloadCsv } from '../utils/download';

const RANGES: AnalyticsRange[] = ['15M', '1H', '6H', '24H', '7D', '30D', 'CUSTOM'];
const EXPORT_KINDS = [
  'summary', 'risk', 'occupancy', 'energy', 'sensor_health', 'buildings',
  'routes', 'incidents', 'simulations',
] as const;
const ENV_METRIC_OPTIONS = ['temperature', 'humidity', 'air_quality', 'smoke', 'water'] as const;
const SEVERITIES = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'] as const;
const INCIDENT_STATUSES = ['ACTIVE', 'RESOLVED', 'CLOSED', 'DISMISSED'] as const;
const INCIDENT_KINDS = ['FIRE', 'FLOOD', 'MEDICAL', 'SECURITY', 'POWER', 'WEATHER',
                        'INFRASTRUCTURE', 'ENVIRONMENTAL', 'OTHER', 'DRILL'] as const;
const SCENARIOS = ['fire', 'crowd', 'power', 'road', 'temperature'] as const;
const SEV_COLORS: Record<string, string> = {
  CRITICAL: '#ef4444', HIGH: '#f97316', MEDIUM: '#f59e0b', LOW: '#22c55e',
};

const AXIS = { stroke: '#47577d', fontSize: 10, fontFamily: 'monospace' };
const GRID = '#1c2b47';
const TOOLTIP_STYLE = {
  contentStyle: { background: '#0d1626', border: '1px solid #2a3c5f', borderRadius: 8, fontSize: 12 },
  labelStyle: { color: '#94a3b8' },
};

function label(t: string, range: AnalyticsRange) {
  const d = new Date(t);
  if (Number.isNaN(d.getTime())) return '';
  if (range === '7D' || range === '30D' || range === 'CUSTOM') {
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  }
  return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
}

function Section({ title, sub, right, children }: {
  title: string; sub?: string; right?: React.ReactNode; children: React.ReactNode;
}) {
  return (
    <section className="panel rounded-xl p-4" data-testid={`section-${title.toLowerCase().replace(/[^a-z]+/g, '-')}`}>
      <div className="flex items-center justify-between gap-2 mb-3 flex-wrap">
        <div className="flex items-baseline gap-2 min-w-0">
          <h2 className="text-[13px] font-bold">{title}</h2>
          {sub && <span className="text-[10.5px] text-mist-500 num truncate">{sub}</span>}
        </div>
        {right}
      </div>
      {children}
    </section>
  );
}

function ChartCard({ title, sub, children, tall = false }: {
  title: string; sub?: string; children: React.ReactNode; tall?: boolean;
}) {
  return (
    <div className="panel rounded-lg p-3">
      <div className="flex items-baseline justify-between mb-2 gap-2">
        <span className="label-cap">{title}</span>
        {sub && <span className="text-[10.5px] text-mist-500 num truncate">{sub}</span>}
      </div>
      <div className={tall ? 'h-[220px]' : 'h-[170px]'}>
        <ResponsiveContainer width="100%" height="100%">
          {children as React.ReactElement}
        </ResponsiveContainer>
      </div>
    </div>
  );
}

/** Honest empty state — never draws a fabricated series. */
function EmptyWindow({ reason }: { reason?: string }) {
  return (
    <div className="h-[120px] flex flex-col items-center justify-center text-center px-4 rounded-lg border border-dashed border-line-strong">
      <div className="text-[12px] text-mist-300">No persisted data in this window</div>
      <div className="text-[10.5px] text-mist-500 mt-0.5">{reason ?? 'try a wider time range'}</div>
    </div>
  );
}

function Spark({ points, color = '#38bdf8' }: { points: SeriesPoint[]; color?: string }) {
  const data = points.filter((p) => typeof p.value === 'number').map((p) => ({ v: p.value }));
  if (data.length < 2) return <div className="h-[170px]"><EmptyWindow /></div>;
  return (
    <div className="h-[170px]">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <Area type="monotone" dataKey="v" stroke={color} fill={`${color}18`} strokeWidth={2} dot={false} isAnimationActive={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

function heatColor(v: number | null): string {
  if (v === null || Number.isNaN(v)) return 'transparent';
  const alpha = 0.12 + (Math.max(0, Math.min(100, v)) / 100) * 0.75;
  return `rgba(239, 68, 68, ${alpha.toFixed(2)})`;
}

interface Bundle {
  overview: OverviewResponse;
  risk: RiskAnalyticsResponse;
  occupancy: OccupancyAnalyticsResponse;
  energy: EnergyAnalyticsResponse;
  environment: EnvironmentAnalyticsResponse;
  sensors: SensorHealthResponse;
  buildings: BuildingsAnalyticsResponse;
  routes: RoutesAnalyticsResponse;
  ai: AiAnalyticsResponse;
  health: CampusHealthResponse;
}

/**
 * Phase 9 §62 — full analytics workspace: window ranges (incl. custom),
 * building/zone/metric/incident/simulation filters, URL-persisted state,
 * server-side aggregation and CSV export.
 */
export default function Analytics() {
  const snapshot = useTwinStore((s) => s.snapshot);
  const [params, setParams] = useSearchParams();

  const range = (params.get('range') as AnalyticsRange | null) ?? '24H';
  const start = params.get('start') ?? '';
  const end = params.get('end') ?? '';
  const building = params.get('building') ?? '';
  const zone = params.get('zone') ?? '';
  const metric = params.get('metric') ?? 'temperature';
  const kind = params.get('kind') ?? '';
  const status = params.get('status') ?? '';
  const severity = params.get('severity') ?? '';
  const q = params.get('q') ?? '';
  const scenario = params.get('scenario') ?? '';
  const compare = params.get('compare') ?? '';

  const setParam = useCallback((key: string, value: string) => {
    setParams((prev) => {
      const p = new URLSearchParams(prev);
      if (value) p.set(key, value);
      else p.delete(key);
      return p;
    }, { replace: true });
  }, [setParams]);

  const windowParams = useMemo(
    () => (range === 'CUSTOM' ? { range, start, end } : { range }),
    [range, start, end],
  );

  // ---- main bundle (window + building scoped) ----
  const [bundle, setBundle] = useState<Bundle | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const buildingParam = useMemo(
    () => (building ? { building_id: building } : {}),
    [building],
  );

  useEffect(() => {
    let alive = true;
    setLoading(true);
    Promise.all([
      api.analyticsOverview(windowParams),
      api.riskAnalytics({ ...windowParams, ...buildingParam }),
      api.occupancyAnalytics({ ...windowParams, ...buildingParam }),
      api.energyAnalytics({ ...windowParams, ...buildingParam }),
      api.environmentAnalytics({ ...windowParams, ...buildingParam }),
      api.sensorHealth(windowParams),
      api.buildingsAnalytics(windowParams),
      api.routesAnalytics(windowParams),
      api.aiAnalytics(windowParams),
      api.campusHealth(windowParams),
    ]).then(([overview, risk, occupancy, energy, environment, sensors, buildings, routes, ai, health]) => {
      if (!alive) return;
      setBundle({ overview, risk, occupancy, energy, environment, sensors, buildings, routes, ai, health });
      setError(null);
    }).catch((err: unknown) => {
      if (alive) setError(err instanceof ApiError ? err.message : 'Failed to load analytics');
    }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [windowParams, buildingParam]);

  // ---- incidents (kind/status/severity/search/building filters) ----
  const [incidents, setIncidents] = useState<IncidentListResponse | null>(null);
  useEffect(() => {
    let alive = true;
    api.historyIncidents({
      page_size: 50, kind, status, severity, q,
      building_id: building || undefined,
      sort: 'started_at', order: 'desc',
    }).then((res) => { if (alive) setIncidents(res); })
      .catch(() => { if (alive) setIncidents(null); });
    return () => { alive = false; };
  }, [kind, status, severity, q, building]);

  // ---- simulations (scenario filter) ----
  const [sims, setSims] = useState<HistorySimulation[] | null>(null);
  useEffect(() => {
    let alive = true;
    api.historySimulations({
      page_size: 50, scenario, sort: 'created_at', order: 'desc',
    }).then((res) => { if (alive) setSims(res.items); })
      .catch(() => { if (alive) setSims(null); });
    return () => { alive = false; };
  }, [scenario]);

  // ---- building compare (2-3 ids) ----
  const [compareData, setCompareData] = useState<BuildingsCompareResponse | null>(null);
  const compareIds = compare.split(',').filter(Boolean);
  useEffect(() => {
    if (compareIds.length < 2) { setCompareData(null); return; }
    let alive = true;
    api.compareBuildings(compareIds.join(','), windowParams)
      .then((res) => { if (alive) setCompareData(res); })
      .catch(() => { if (alive) setCompareData(null); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [compare, windowParams]);

  // ---- sensor detail on click ----
  const [sensorDetail, setSensorDetail] = useState<SensorHealthDetailResponse | null>(null);
  const [sensorDetailId, setSensorDetailId] = useState<string | null>(null);
  useEffect(() => {
    if (!sensorDetailId) { setSensorDetail(null); return; }
    let alive = true;
    api.sensorHealthDetail(sensorDetailId, windowParams)
      .then((res) => { if (alive) setSensorDetail(res); })
      .catch(() => { if (alive) setSensorDetail(null); });
    return () => { alive = false; };
  }, [sensorDetailId, windowParams]);

  // ---- CSV export ----
  const [exportKind, setExportKind] = useState<string>('summary');
  const [exporting, setExporting] = useState(false);
  const runExport = useCallback(async () => {
    setExporting(true);
    try {
      const csv = await api.exportAnalytics(exportKind, windowParams);
      downloadCsv(`twinsphere_${exportKind}`, csv);
    } catch (err) {
      useTwinStore.getState().handleApiError(err);
    } finally {
      setExporting(false);
    }
  }, [exportKind, windowParams]);

  const buildingOptions = useMemo(
    () => Object.values(snapshot?.buildings ?? {}),
    [snapshot],
  );
  const zoneOptions = useMemo(() => {
    const zones = snapshot?.zones ?? [];
    return building ? zones.filter((z) => z.building_id === building) : zones;
  }, [snapshot, building]);

  const sensorInventory = useMemo(() => {
    const all = snapshot?.sensors ?? [];
    return all.filter((s) => (!building || s.building_id === building)
      && (!zone || s.zone_id === zone));
  }, [snapshot, building, zone]);

  const severityMix = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const i of incidents?.items ?? []) counts[i.severity] = (counts[i.severity] ?? 0) + 1;
    return Object.entries(counts).map(([name, value]) => ({ name, value }));
  }, [incidents]);

  const recoveryData = useMemo(() => (
    (sims ?? []).filter((s) => s.recovery_time_s > 0)
      .map((s) => ({
        name: s.code, scenario: s.scenario,
        recovery: Math.round(s.recovery_time_s), peak_risk: s.peak_risk,
        people: s.people_affected,
      }))
  ), [sims]);

  const envBlock = bundle?.environment.metrics.find((m) => m.metric === metric)
    ?? bundle?.environment.metrics[0];

  const riskSeries = useMemo(
    () => (bundle?.risk.series ?? []).map((p) => ({ t: label(p.t, range), value: p.value })),
    [bundle, range],
  );
  const occSeries = useMemo(
    () => (bundle?.occupancy.series ?? []).map((p) => ({
      t: label(p.t, range), value: p.value, pct: p.pct,
    })),
    [bundle, range],
  );
  const energySeries = useMemo(
    () => (bundle?.energy.series ?? []).map((p) => ({ t: label(p.t, range), value: p.value })),
    [bundle, range],
  );
  const envSeries = useMemo(
    () => (envBlock?.series ?? []).map((p) => ({ t: label(p.t, range), value: p.value })),
    [envBlock, range],
  );

  const toggleCompare = (id: string) => {
    const ids = new Set(compareIds);
    if (ids.has(id)) ids.delete(id);
    else if (ids.size < 3) ids.add(id);
    setParam('compare', [...ids].join(','));
  };

  return (
    <div className="h-full overflow-y-auto scroll-y p-4 space-y-4">
      {/* header + filters */}
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-lg font-bold">Analytics</h1>
        <span className="chip border-line-strong bg-ink-800 text-mist-300">SERVER-SIDE AGGREGATION</span>
        <div className="flex gap-1.5">
          {RANGES.map((r) => (
            <button
              key={r}
              onClick={() => setParam('range', r)}
              data-testid={`range-${r}`}
              className={`chip ${range === r ? 'border-brand-400 bg-brand-950/70 text-brand-200' : ''}`}
            >
              {r}
            </button>
          ))}
        </div>
        {range === 'CUSTOM' && (
          <div className="flex items-center gap-1.5 text-[11px]">
            <input
              type="datetime-local"
              value={start.slice(0, 16)}
              onChange={(e) => setParam('start', e.target.value ? `${e.target.value}:00Z` : '')}
              className="bg-ink-800 border border-line-strong rounded px-2 py-1 num text-[11px]"
              aria-label="Window start"
            />
            <span className="text-mist-500">→</span>
            <input
              type="datetime-local"
              value={end.slice(0, 16)}
              onChange={(e) => setParam('end', e.target.value ? `${e.target.value}:00Z` : '')}
              className="bg-ink-800 border border-line-strong rounded px-2 py-1 num text-[11px]"
              aria-label="Window end"
            />
          </div>
        )}
        <select
          value={building}
          onChange={(e) => setParams((prev) => {
            // single URL write: two sequential setParams calls would clobber
            const p = new URLSearchParams(prev);
            if (e.target.value) p.set('building', e.target.value);
            else p.delete('building');
            p.delete('zone');
            return p;
          }, { replace: true })}
          className="bg-ink-800 border border-line-strong rounded px-2 py-1 text-[11.5px]"
          data-testid="filter-building"
          aria-label="Building filter"
        >
          <option value="">All buildings</option>
          {buildingOptions.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
        </select>
        <select
          value={metric}
          onChange={(e) => setParam('metric', e.target.value)}
          className="bg-ink-800 border border-line-strong rounded px-2 py-1 text-[11.5px]"
          data-testid="filter-metric"
          aria-label="Metric filter"
        >
          {ENV_METRIC_OPTIONS.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
        <select
          value={zone}
          onChange={(e) => setParam('zone', e.target.value)}
          className="bg-ink-800 border border-line-strong rounded px-2 py-1 text-[11.5px]"
          data-testid="filter-zone"
          aria-label="Zone filter"
          disabled={zoneOptions.length === 0}
        >
          <option value="">All zones</option>
          {zoneOptions.map((z) => <option key={z.id} value={z.id}>{z.name}</option>)}
        </select>
        <div className="flex-1" />
        <div className="flex items-center gap-1.5">
          <select
            value={exportKind}
            onChange={(e) => setExportKind(e.target.value)}
            className="bg-ink-800 border border-line-strong rounded px-2 py-1 text-[11.5px]"
            aria-label="Export dataset"
          >
            {EXPORT_KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
          </select>
          <button className="btn" onClick={() => void runExport()} disabled={exporting}
                  data-testid="export-csv">
            <IconDownload width={13} height={13} className={exporting ? 'animate-pulse' : ''} />
            Export CSV
          </button>
          <button className="btn" onClick={() => setParams(new URLSearchParams({ range }), { replace: true })}>
            <IconRefresh width={13} height={13} /> Reset filters
          </button>
        </div>
      </div>

      {/* incident + simulation filters (URL state) */}
      <div className="flex items-center gap-2 flex-wrap panel rounded-lg px-3 py-2">
        <span className="label-cap">Incident filters</span>
        <select value={kind} onChange={(e) => setParam('kind', e.target.value)}
                className="bg-ink-800 border border-line-strong rounded px-2 py-1 text-[11.5px]"
                data-testid="filter-kind" aria-label="Incident kind">
          <option value="">Any kind</option>
          {INCIDENT_KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
        </select>
        <select value={status} onChange={(e) => setParam('status', e.target.value)}
                className="bg-ink-800 border border-line-strong rounded px-2 py-1 text-[11.5px]"
                data-testid="filter-status" aria-label="Incident status">
          <option value="">Any status</option>
          {INCIDENT_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <select value={severity} onChange={(e) => setParam('severity', e.target.value)}
                className="bg-ink-800 border border-line-strong rounded px-2 py-1 text-[11.5px]"
                aria-label="Incident severity">
          <option value="">Any severity</option>
          {SEVERITIES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <div className="relative">
          <IconSearch width={12} height={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-mist-500" />
          <input
            value={q}
            onChange={(e) => setParam('q', e.target.value)}
            placeholder="search incidents…"
            data-testid="filter-q"
            className="bg-ink-800 border border-line-strong rounded pl-7 pr-2 py-1 text-[11.5px] w-[170px]"
            aria-label="Incident search"
          />
        </div>
        <span className="label-cap ml-3">Simulation</span>
        <select value={scenario} onChange={(e) => setParam('scenario', e.target.value)}
                className="bg-ink-800 border border-line-strong rounded px-2 py-1 text-[11.5px]"
                data-testid="filter-scenario" aria-label="Simulation scenario filter">
          <option value="">All scenarios</option>
          {SCENARIOS.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <span className="num text-[10.5px] text-mist-500 ml-auto">
          {incidents ? `${incidents.total} incidents` : '…'} · {sims ? `${sims.length} sims` : '…'}
        </span>
      </div>

      {error && (
        <div className="panel rounded-lg px-3 py-2 text-[12px] text-amber-300 flex items-center gap-2">
          {error}
          <button className="btn !py-0 !text-[11px] ml-auto" onClick={() => setParams(new URLSearchParams({ ...Object.fromEntries(params), _r: String(Date.now()) }), { replace: true })}>
            Retry
          </button>
        </div>
      )}
      {loading && !bundle && (
        <div className="panel rounded-xl p-4 animate-pulse h-[180px]" data-testid="analytics-loading" />
      )}

      {bundle && (
        <>
          {/* overview KPIs */}
          <Section title="Window overview" sub={`${bundle.overview.window.preset} · ${bundle.overview.source}`}>
            <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-2">
              {bundle.overview.kpis.map((kpi) => (
                <div key={kpi.id} className="rounded-lg border border-line bg-ink-850/70 px-2.5 py-2">
                  <div className="label-cap truncate">{kpi.label}</div>
                  <div className="num text-lg font-bold leading-tight">
                    {kpi.value === null ? '—' : fmtNum(kpi.value, 1)}
                    <span className="text-[10px] text-mist-500 ml-1">{kpi.unit}</span>
                  </div>
                  <div className={`text-[10px] num ${
                    kpi.status === 'GOOD' ? 'text-emerald-300'
                      : kpi.status === 'WARN' ? 'text-amber-300'
                        : kpi.status === 'CRITICAL' ? 'text-red-300' : 'text-mist-400'
                  }`}>
                    {kpi.status}{kpi.secondary ? ` · ${kpi.secondary}` : ''}
                    <span className="text-mist-500"> · {kpi.trend.direction}</span>
                  </div>
                </div>
              ))}
            </div>
            <div className="text-[10.5px] text-mist-500 num mt-2">
              prediction accuracy:{' '}
              {bundle.overview.confidence.available && bundle.overview.confidence.prediction_accuracy !== null
                ? `${bundle.overview.confidence.prediction_accuracy.toFixed(1)}% (vs persisted actuals)`
                : 'insufficient matched predictions in window'}
            </div>
          </Section>

          {/* risk */}
          <Section
            title="Risk"
            sub={`${bundle.risk.entity} · ${bundle.risk.stats.samples} samples`}
            right={building ? <span className="chip !text-[10px]">building: {building}</span> : undefined}
          >
            {!bundle.risk.available ? (
              <EmptyWindow reason={bundle.risk.reason} />
            ) : (
              <div className="grid lg:grid-cols-3 gap-3">
                <ChartCard title="Risk score" sub="0–100" tall>
                  <LineChart data={riskSeries} margin={{ left: -18, right: 8, top: 6 }}>
                    <CartesianGrid stroke={GRID} vertical={false} />
                    <XAxis dataKey="t" tick={AXIS} interval="preserveStartEnd" minTickGap={30} />
                    <YAxis tick={AXIS} width={44} domain={[0, 100]} />
                    <Tooltip {...TOOLTIP_STYLE} />
                    <Line type="monotone" dataKey="value" stroke="#ef4444" strokeWidth={2} dot={false} name="risk" />
                  </LineChart>
                </ChartCard>
                <div className="panel rounded-lg p-3">
                  <div className="label-cap mb-2">Time in risk band</div>
                  <div className="flex h-3 rounded-full overflow-hidden">
                    {bundle.risk.time_in_category.map((c) => (
                      <div key={c.category}
                           title={`${c.category}: ${c.pct}%`}
                           style={{
                             width: `${c.pct}%`,
                             background: c.category === 'CRITICAL' ? '#ef4444'
                               : c.category === 'HIGH' ? '#f97316'
                                 : c.category === 'ELEVATED' ? '#f59e0b'
                                   : c.category === 'MODERATE' ? '#eab308' : '#22c55e',
                           }} />
                    ))}
                  </div>
                  <div className="grid grid-cols-2 gap-x-3 gap-y-1 mt-2">
                    {bundle.risk.time_in_category.map((c) => (
                      <div key={c.category} className="flex justify-between text-[10.5px] num">
                        <span className="text-mist-400">{c.category}</span>
                        <span className="text-mist-200">{c.pct.toFixed(1)}%</span>
                      </div>
                    ))}
                  </div>
                  <div className="label-cap mt-3 mb-1">Peak / average</div>
                  <div className="num text-[12.5px]">
                    max {bundle.risk.stats.max.toFixed(0)} · avg {bundle.risk.stats.avg.toFixed(0)} · min {bundle.risk.stats.min.toFixed(0)}
                  </div>
                  <div className="text-[11px] text-mist-400 mt-1.5 leading-snug">{bundle.risk.explanation}</div>
                  {bundle.risk.factors.length > 0 && (
                    <div className="mt-2 space-y-1">
                      {bundle.risk.factors.slice(0, 4).map((f) => (
                        <div key={f.label} className="flex items-center gap-2 text-[10.5px]">
                          <span className="text-mist-400 w-[110px] truncate">{f.label}</span>
                          <div className="flex-1 h-1.5 rounded bg-ink-700 overflow-hidden">
                            <div className="h-full bg-brand-500" style={{ width: `${Math.min(100, Math.abs(f.contribution) * 8)}%` }} />
                          </div>
                          <span className="num text-mist-300">{f.contribution.toFixed(2)}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                <div className="panel rounded-lg p-3 overflow-x-auto">
                  <div className="label-cap mb-2">Building heatmap (persisted scores)</div>
                  <table className="w-full text-[10.5px] num">
                    <thead>
                      <tr>
                        <th className="text-left label-cap pr-2">Building</th>
                        {bundle.risk.heatmap.buckets.slice(-8).map((b, i) => (
                          <th key={i} className="label-cap px-0.5">{new Date(b).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {bundle.risk.heatmap.rows.map((row) => (
                        <tr key={row.entity}>
                          <td className="pr-2 text-mist-300 whitespace-nowrap">{row.name}</td>
                          {row.cells.slice(-8).map((cell, i) => (
                            <td key={i} className="px-0.5 py-1 text-center rounded"
                                title={cell.value === null ? 'no sample' : `${row.name}: ${cell.value}`}
                                style={{ background: heatColor(cell.value) }}>
                              {cell.value === null ? '·' : cell.value.toFixed(0)}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
            {bundle.risk.critical_events.length > 0 && (
              <div className="mt-3 space-y-1">
                <div className="label-cap">Critical incidents in window</div>
                {bundle.risk.critical_events.slice(0, 5).map((e) => (
                  <div key={e.id} className="text-[11.5px] flex gap-2">
                    <span className="chip !text-[9px] border-red-700 text-red-300">{e.severity}</span>
                    <span className="text-mist-200">{e.title}</span>
                    <span className="num text-mist-500 ml-auto">{new Date(e.started_at).toLocaleString()}</span>
                  </div>
                ))}
              </div>
            )}
          </Section>

          {/* occupancy + energy */}
          <div className="grid lg:grid-cols-2 gap-4">
            <Section title="Occupancy" sub={`current ${fmtNum(bundle.occupancy.current ?? 0)} / ${fmtNum(bundle.occupancy.capacity ?? 0)}`}>
              {!bundle.occupancy.available ? (
                <EmptyWindow reason={bundle.occupancy.reason} />
              ) : (
                <>
                  <ChartCard title="People on campus" sub={`${range} · avg ${fmtNum(bundle.occupancy.stats.avg)} · peak ${fmtNum(bundle.occupancy.stats.peak)}`} tall>
                    <AreaChart data={occSeries} margin={{ left: -18, right: 8, top: 6 }}>
                      <defs>
                        <linearGradient id="gOcc9" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="#38bdf8" stopOpacity={0.55} />
                          <stop offset="100%" stopColor="#38bdf8" stopOpacity={0.03} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid stroke={GRID} vertical={false} />
                      <XAxis dataKey="t" tick={AXIS} interval="preserveStartEnd" minTickGap={30} />
                      <YAxis tick={AXIS} width={46} />
                      <Tooltip {...TOOLTIP_STYLE} />
                      <Area type="monotone" dataKey="value" stroke="#38bdf8" fill="url(#gOcc9)" strokeWidth={2} name="people" />
                    </AreaChart>
                  </ChartCard>
                  <div className="grid grid-cols-2 gap-2 mt-2">
                    {bundle.occupancy.by_building.map((b) => (
                      <div key={b.id} className="text-[10.5px] flex items-center gap-2">
                        <span className="text-mist-400 w-[84px] truncate">{b.name}</span>
                        <div className="flex-1 h-1.5 rounded bg-ink-700 overflow-hidden">
                          <div className={`h-full ${b.pct > 85 ? 'bg-red-500' : b.pct > 65 ? 'bg-amber-500' : 'bg-emerald-500'}`}
                               style={{ width: `${Math.min(100, b.pct)}%` }} />
                        </div>
                        <span className="num w-9 text-right text-mist-300">{b.pct.toFixed(0)}%</span>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </Section>

            <Section title="Energy" sub={`current ${bundle.energy.current !== null ? `${bundle.energy.current.toFixed(1)} kW` : '—'}`}>
              {!bundle.energy.available ? (
                <EmptyWindow reason={bundle.energy.reason} />
              ) : (
                <>
                  <ChartCard title="Campus load" sub={`${range} · avg ${bundle.energy.stats.avg.toFixed(1)} kW · ${bundle.energy.stats.samples} samples`} tall>
                    <AreaChart data={energySeries} margin={{ left: -18, right: 8, top: 6 }}>
                      <defs>
                        <linearGradient id="gEn9" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="#f59e0b" stopOpacity={0.55} />
                          <stop offset="100%" stopColor="#f59e0b" stopOpacity={0.03} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid stroke={GRID} vertical={false} />
                      <XAxis dataKey="t" tick={AXIS} interval="preserveStartEnd" minTickGap={30} />
                      <YAxis tick={AXIS} width={46} />
                      <Tooltip {...TOOLTIP_STYLE} />
                      <Area type="monotone" dataKey="value" stroke="#f59e0b" fill="url(#gEn9)" strokeWidth={2} name="kW" />
                    </AreaChart>
                  </ChartCard>
                  <div className="flex items-center gap-3 mt-2 text-[11px]">
                    <span className={bundle.energy.abnormal.count > 0 ? 'text-amber-300' : 'text-emerald-300'}>
                      {bundle.energy.abnormal.count} readings outside sensor normal range
                    </span>
                    <span className="text-mist-500">{bundle.energy.abnormal.definition}</span>
                  </div>
                </>
              )}
            </Section>
          </div>

          {/* environment */}
          <Section title="Environment" sub={`focused metric: ${metric} · live ${bundle.environment.live_temperature.toFixed(1)} °C`}>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-2 mb-3">
              {bundle.environment.metrics.map((m) => (
                <button key={m.metric}
                        onClick={() => setParam('metric', m.metric)}
                        className={`rounded-lg border px-2.5 py-2 text-left transition-colors ${
                          m.metric === metric ? 'border-brand-400 bg-brand-950/50' : 'border-line bg-ink-850/70 hover:border-line-strong'
                        }`}>
                  <div className="label-cap truncate">{m.metric}</div>
                  <div className="num text-[15px] font-bold">
                    {m.available ? m.stats.avg.toFixed(1) : '—'}
                    <span className="text-[10px] text-mist-500 ml-1">{m.unit}</span>
                  </div>
                  <div className="text-[10px] text-mist-500 num">
                    {m.available ? `min ${m.stats.min.toFixed(0)} · max ${m.stats.max.toFixed(0)}` : 'no samples'}
                    {m.abnormal_readings > 0 && <span className="text-amber-300"> · {m.abnormal_readings} abnormal</span>}
                  </div>
                </button>
              ))}
            </div>
            {!envBlock?.available ? (
              <EmptyWindow reason={envBlock?.reason ?? undefined} />
            ) : (
              <ChartCard title={`${metric} trend`} sub={`${range} · ${envBlock.unit} · ${envBlock.stats.samples} samples`}>
                <LineChart data={envSeries} margin={{ left: -18, right: 8, top: 6 }}>
                  <CartesianGrid stroke={GRID} vertical={false} />
                  <XAxis dataKey="t" tick={AXIS} interval="preserveStartEnd" minTickGap={36} />
                  <YAxis tick={AXIS} width={46} />
                  <Tooltip {...TOOLTIP_STYLE} />
                  <Line type="monotone" dataKey="value" stroke="#a78bfa" strokeWidth={2} dot={false} name={metric} />
                </LineChart>
              </ChartCard>
            )}
          </Section>

          {/* sensors */}
          <Section
            title="Sensor health"
            sub={`${bundle.sensors.totals.total} sensors · ${bundle.sensors.status} · ${bundle.sensors.totals.out_of_range_readings} out-of-range readings`}
            right={
              <span className="chip !text-[10px]">
                {sensorInventory.length} in view{zone ? ` · zone ${zone}` : building ? ` · ${building}` : ''}
              </span>
            }
          >
            <div className="grid lg:grid-cols-3 gap-3">
              <div className="panel rounded-lg p-3">
                <div className="label-cap mb-2">By type</div>
                <div className="space-y-1.5">
                  {bundle.sensors.by_type.map((t) => (
                    <div key={t.type} className="flex items-center gap-2 text-[10.5px]">
                      <span className="text-mist-400 w-[86px] truncate">{t.type}</span>
                      <div className="flex-1 h-1.5 rounded bg-ink-700 overflow-hidden">
                        <div className={`h-full ${t.health_pct >= 95 ? 'bg-emerald-500' : t.health_pct >= 80 ? 'bg-amber-500' : 'bg-red-500'}`}
                             style={{ width: `${Math.max(2, t.health_pct)}%` }} />
                      </div>
                      <span className="num w-16 text-right text-mist-300">{t.healthy}/{t.total}</span>
                    </div>
                  ))}
                </div>
              </div>
              <div className="panel rounded-lg p-3 lg:col-span-2">
                <div className="label-cap mb-2">Inventory (click a sensor for its persisted series)</div>
                <div className="max-h-[220px] overflow-y-auto scroll-y">
                  <table className="w-full text-[11px]">
                    <thead><tr className="text-left border-b border-line">
                      {['Sensor', 'Type', 'Zone', 'Status', ''].map((h) => (
                        <th key={h} className="label-cap py-1 pr-2">{h}</th>
                      ))}
                    </tr></thead>
                    <tbody>
                      {sensorInventory.slice(0, 60).map((s) => (
                        <tr key={s.id} className="border-b border-line/50 hover:bg-ink-850/60 cursor-pointer"
                            onClick={() => setSensorDetailId(s.id)}>
                          <td className="py-1 pr-2 truncate">{s.name}</td>
                          <td className="py-1 pr-2 text-mist-400">{s.type}</td>
                          <td className="py-1 pr-2 text-mist-500 truncate max-w-[110px]">{s.zone_id ?? '—'}</td>
                          <td className="py-1 pr-2">
                            <span className={`chip !text-[9px] ${s.status === 'ONLINE' ? 'border-emerald-700 text-emerald-300' : 'border-red-700 text-red-300'}`}>
                              {s.status}
                            </span>
                          </td>
                          <td className="py-1 text-mist-600 text-right">▸</td>
                        </tr>
                      ))}
                      {sensorInventory.length === 0 && (
                        <tr><td colSpan={5} className="py-3 text-center text-mist-500">No sensors match this building/zone filter.</td></tr>
                      )}
                    </tbody>
                  </table>
                </div>
                {sensorDetail && (
                  <div className="mt-2 border-t border-line pt-2" data-testid="sensor-detail">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-[12px] font-semibold">{sensorDetail.sensor.name}</span>
                      <span className="chip !text-[9px]">{sensorDetail.status}</span>
                      <span className="num text-[10.5px] text-mist-500">
                        {sensorDetail.current !== null ? `${sensorDetail.current} ${sensorDetail.sensor.unit}` : 'no current value'}
                      </span>
                      <button className="btn !py-0 !px-1.5 ml-auto" onClick={() => setSensorDetailId(null)}>✕</button>
                    </div>
                    <Spark points={sensorDetail.series} color="#34d399" />
                    <div className="text-[10px] text-mist-500 num">
                      avg {sensorDetail.stats.avg.toFixed(1)} · min {sensorDetail.stats.min} · max {sensorDetail.stats.max} · {sensorDetail.stats.samples} samples · {sensorDetail.source}
                    </div>
                  </div>
                )}
              </div>
            </div>
            {bundle.sensors.diagnostics.length > 0 && (
              <div className="mt-3">
                <div className="label-cap mb-1">Diagnostics ({bundle.sensors.diagnostics.length})</div>
                <div className="space-y-1">
                  {bundle.sensors.diagnostics.slice(0, 8).map((d) => (
                    <div key={d.sensor_id} className="text-[11px] flex gap-2 items-center flex-wrap">
                      <span className="font-semibold text-mist-200">{d.name}</span>
                      <span className="num text-mist-500">{d.sensor_code}</span>
                      <span className="num text-mist-300">{d.value} {d.unit}</span>
                      <span className="num text-mist-500">age {Math.round(d.age_seconds)}s</span>
                      {d.issues.map((issue) => (
                        <span key={issue} className="chip !text-[9px] border-amber-700 text-amber-300">{issue}</span>
                      ))}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </Section>

          {/* buildings + compare */}
          <Section
            title="Buildings"
            sub={`${bundle.buildings.count} buildings · click chips to compare (2–3)`}
          >
            <div className="flex gap-1.5 flex-wrap mb-3">
              {bundle.buildings.buildings.map((b) => (
                <button
                  key={b.id}
                  onClick={() => toggleCompare(b.id)}
                  className={`chip !text-[10.5px] ${compareIds.includes(b.id) ? 'border-brand-400 bg-brand-950/70 text-brand-200' : ''}`}
                  data-testid={`compare-${b.id}`}
                >
                  {b.name}
                </button>
              ))}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-[12px]">
                <thead>
                  <tr className="border-b border-line text-left">
                    {['Building', 'Risk', 'Occupancy', 'Energy', 'Temp', 'Incidents', 'Sensors', 'Health'].map((h) => (
                      <th key={h} className="label-cap px-2 py-1.5">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {bundle.buildings.buildings.map((b) => (
                    <tr key={b.id} className="border-b border-line/50 hover:bg-ink-850/60">
                      <td className="px-2 py-1.5 font-semibold">{b.name}</td>
                      <td className={`px-2 py-1.5 num ${b.risk > 60 ? 'text-red-400' : b.risk > 35 ? 'text-amber-300' : 'text-emerald-400'}`}>
                        {b.risk.toFixed(0)} <span className="text-mist-500 text-[10px]">{b.risk_level}</span>
                      </td>
                      <td className="px-2 py-1.5 num">{fmtNum(b.occupancy)} / {fmtNum(b.capacity)} ({b.occupancy_pct.toFixed(0)}%)</td>
                      <td className="px-2 py-1.5 num">{b.energy !== null ? `${b.energy.toFixed(1)} kW` : '—'}</td>
                      <td className="px-2 py-1.5 num">{b.temperature !== null ? `${b.temperature.toFixed(1)} °C` : '—'}</td>
                      <td className="px-2 py-1.5 num">{b.incidents}</td>
                      <td className="px-2 py-1.5 num">{b.sensors}</td>
                      <td className={`px-2 py-1.5 num ${b.sensor_health >= 95 ? 'text-emerald-400' : b.sensor_health >= 80 ? 'text-amber-300' : 'text-red-400'}`}>
                        {b.sensor_health.toFixed(0)}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {compareData && compareData.available && (
              <div className="mt-3 overflow-x-auto" data-testid="compare-table">
                <div className="label-cap mb-1">
                  Compare · {compareData.buildings.map((b) => b.name).join(' vs ')}
                </div>
                <table className="w-full text-[11.5px]">
                  <thead>
                    <tr className="border-b border-line text-left">
                      <th className="label-cap px-2 py-1">Metric</th>
                      {compareData.buildings.map((b) => (
                        <th key={b.id} className="label-cap px-2 py-1">{b.name}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {compareData.rows.map((row) => (
                      <tr key={row.metric} className="border-b border-line/50">
                        <td className="px-2 py-1 text-mist-400">{row.label}{row.unit ? ` (${row.unit})` : ''}</td>
                        {compareData.buildings.map((b) => {
                          const cell = row.values[b.id];
                          return (
                            <td key={b.id} className="px-2 py-1">
                              {cell?.raw === null || cell?.raw === undefined ? '—' : (
                                <div className="flex items-center gap-2">
                                  <span className="num">{typeof cell.raw === 'number' ? cell.raw.toFixed(1) : cell.raw}</span>
                                  <div className="w-14 h-1.5 rounded bg-ink-700 overflow-hidden">
                                    <div className="h-full bg-brand-500" style={{ width: `${cell.norm ?? 0}%` }} />
                                  </div>
                                </div>
                              )}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div className="text-[10px] text-mist-500 mt-1">{compareData.note}</div>
              </div>
            )}
            {compareIds.length === 1 && (
              <div className="text-[11px] text-mist-500 mt-2">Select one more building to compare.</div>
            )}
          </Section>

          {/* routes + AI */}
          <div className="grid lg:grid-cols-2 gap-4">
            <Section title="Routes" sub={`${bundle.routes.stats.events} events in window`}>
              <div className="grid grid-cols-2 gap-2 text-[12px]">
                <div className="rounded border border-line bg-ink-850/60 px-2.5 py-2">
                  <div className="label-cap">Recalculations</div>
                  <div className="num text-lg font-bold">{bundle.routes.stats.recalculations}</div>
                </div>
                <div className="rounded border border-line bg-ink-850/60 px-2.5 py-2">
                  <div className="label-cap">Active now</div>
                  <div className="num text-lg font-bold">{bundle.routes.current.active_routes}</div>
                </div>
                <div className="rounded border border-line bg-ink-850/60 px-2.5 py-2">
                  <div className="label-cap">Avg distance</div>
                  <div className="num text-lg font-bold">{bundle.routes.stats.avg_distance.toFixed(0)} m</div>
                </div>
                <div className="rounded border border-line bg-ink-850/60 px-2.5 py-2">
                  <div className="label-cap">Avg ETA</div>
                  <div className="num text-lg font-bold">{bundle.routes.stats.avg_eta_s.toFixed(0)} s</div>
                </div>
              </div>
              <div className="text-[11px] text-mist-400 mt-2">
                mode <span className="num text-mist-200">{bundle.routes.current.mode}</span> ·
                v<span className="num text-mist-200">{bundle.routes.current.route_version}</span> ·
                evacuation <span className="num text-mist-200">{bundle.routes.current.evacuation_status}</span>
                {Object.keys(bundle.routes.stats.by_mode).length > 0 && (
                  <> · by mode: {Object.entries(bundle.routes.stats.by_mode).map(([m, n]) => `${m}=${n}`).join(', ')}</>
                )}
              </div>
            </Section>

            <Section title="AI" sub={`${bundle.ai.stats.analyses} analyses · ${bundle.ai.stats.recommendations} recommendations`}>
              <div className="grid grid-cols-2 gap-2 text-[12px]">
                <div className="rounded border border-line bg-ink-850/60 px-2.5 py-2">
                  <div className="label-cap">Avg confidence</div>
                  <div className="num text-lg font-bold">
                    {bundle.ai.stats.avg_confidence !== null ? `${(bundle.ai.stats.avg_confidence * 100).toFixed(0)}%` : '—'}
                  </div>
                </div>
                <div className="rounded border border-line bg-ink-850/60 px-2.5 py-2">
                  <div className="label-cap">Acceptance rate</div>
                  <div className="num text-lg font-bold">
                    {bundle.ai.stats.acceptance_rate !== null ? `${bundle.ai.stats.acceptance_rate.toFixed(0)}%` : '—'}
                  </div>
                </div>
                <div className="rounded border border-line bg-ink-850/60 px-2.5 py-2">
                  <div className="label-cap">Anomalies</div>
                  <div className="num text-lg font-bold">{bundle.ai.engine.anomalies}</div>
                </div>
                <div className="rounded border border-line bg-ink-850/60 px-2.5 py-2">
                  <div className="label-cap">Predictions</div>
                  <div className="num text-lg font-bold">{bundle.ai.engine.predictions}</div>
                </div>
              </div>
              <div className="text-[11px] text-mist-400 mt-2">
                sources: {Object.entries(bundle.ai.stats.by_source).map(([s, n]) => `${s}=${n}`).join(', ') || '—'}
                {' · '}decisions {bundle.ai.stats.decisions}
              </div>
            </Section>
          </div>

          {/* campus health */}
          <Section title="Campus health" sub={`${bundle.health.score.toFixed(0)}/100 · ${bundle.health.level} · weights ${bundle.health.weights_total}`}>
            <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-2">
              {bundle.health.components.map((c) => (
                <div key={c.id} className="rounded border border-line bg-ink-850/60 px-2.5 py-2" title={c.note ?? c.detail}>
                  <div className="flex justify-between items-baseline">
                    <span className="label-cap truncate">{c.label}</span>
                    <span className="num text-[10px] text-mist-500">w{c.weight}</span>
                  </div>
                  <div className={`num text-lg font-bold ${c.score >= 80 ? 'text-emerald-300' : c.score >= 50 ? 'text-amber-300' : 'text-red-300'}`}>
                    {c.score.toFixed(0)}
                  </div>
                  <div className="text-[10px] text-mist-500 truncate">{c.detail}</div>
                </div>
              ))}
            </div>
          </Section>

          {/* incidents */}
          <Section
            title="Incidents"
            sub={incidents ? `${incidents.total} matching · page ${incidents.page}/${incidents.pages}` : 'loading…'}
          >
            <div className="grid lg:grid-cols-3 gap-3">
              <div className="panel rounded-lg p-3">
                <div className="label-cap mb-2">Severity mix (latest 50)</div>
                {severityMix.length === 0 ? (
                  <div className="text-[11.5px] text-mist-500 py-6 text-center">No incidents match these filters.</div>
                ) : (
                  <div className="h-[170px]">
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart>
                        <Pie data={severityMix} dataKey="value" nameKey="name" innerRadius={44} outerRadius={70} paddingAngle={3}>
                          {severityMix.map((s) => <Cell key={s.name} fill={SEV_COLORS[s.name] ?? '#64748b'} />)}
                        </Pie>
                        <Tooltip {...TOOLTIP_STYLE} />
                      </PieChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </div>
              <div className="panel rounded-lg p-3 lg:col-span-2 overflow-x-auto">
                <table className="w-full text-[11.5px]">
                  <thead>
                    <tr className="border-b border-line text-left">
                      {['Code', 'Title', 'Kind', 'Severity', 'Status', 'Building', 'Started'].map((h) => (
                        <th key={h} className="label-cap py-1 pr-2">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {(incidents?.items ?? []).slice(0, 12).map((i: HistoryIncident) => (
                      <tr key={i.id} className="border-b border-line/50">
                        <td className="py-1 pr-2 num">{i.code}</td>
                        <td className="py-1 pr-2 truncate max-w-[190px]">{i.title}</td>
                        <td className="py-1 pr-2 text-mist-400">{i.kind}</td>
                        <td className="py-1 pr-2">
                          <span className={`chip !text-[9px] ${i.severity === 'CRITICAL' || i.severity === 'HIGH' ? 'border-red-700 text-red-300' : i.severity === 'MEDIUM' ? 'border-amber-700 text-amber-300' : 'border-emerald-700 text-emerald-300'}`}>
                            {i.severity}
                          </span>
                        </td>
                        <td className="py-1 pr-2 text-mist-300">{i.status}</td>
                        <td className="py-1 pr-2 text-mist-400">{i.building_id ?? '—'}</td>
                        <td className="py-1 num text-mist-500 whitespace-nowrap">{new Date(i.started_at).toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {(incidents?.items.length ?? 0) === 0 && !loading && (
                  <div className="text-[11.5px] text-mist-500 py-4 text-center">
                    No incidents match — clear kind/status/search filters or widen the campus.
                  </div>
                )}
              </div>
            </div>
          </Section>

          {/* simulations */}
          <Section
            title="Simulations"
            sub={scenario ? `scenario: ${scenario}` : 'all scenarios'}
            right={<span className="text-[10.5px] text-mist-500">recovery chart needs completed runs with recovery time</span>}
          >
            <div className="grid lg:grid-cols-2 gap-3">
              <ChartCard title="Recovery time by simulation" sub="seconds">
                {recoveryData.length === 0 ? (
                  <div className="h-full flex items-center justify-center text-[11.5px] text-mist-500">
                    No completed simulations with recovery time in this filter.
                  </div>
                ) : (
                  <BarChart data={recoveryData} margin={{ left: -18, right: 8, top: 6 }}>
                    <CartesianGrid stroke={GRID} vertical={false} />
                    <XAxis dataKey="name" tick={AXIS} interval={0} angle={-25} height={46} textAnchor="end" />
                    <YAxis tick={AXIS} width={40} />
                    <Tooltip {...TOOLTIP_STYLE} />
                    <Bar dataKey="recovery" fill="#38bdf8" radius={[3, 3, 0, 0]} name="recovery (s)" />
                  </BarChart>
                )}
              </ChartCard>
              <div className="panel rounded-lg p-3 overflow-x-auto">
                <div className="label-cap mb-2">Runs (latest 50)</div>
                <table className="w-full text-[11.5px]">
                  <thead>
                    <tr className="border-b border-line text-left">
                      {['Code', 'Scenario', 'Status', 'Peak', 'People', 'Recovery', 'Created'].map((h) => (
                        <th key={h} className="label-cap py-1 pr-2">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {(sims ?? []).slice(0, 12).map((s) => (
                      <tr key={s.id} className="border-b border-line/50">
                        <td className="py-1 pr-2 num">{s.code}</td>
                        <td className="py-1 pr-2">{s.scenario}</td>
                        <td className="py-1 pr-2 text-mist-300">{s.status}</td>
                        <td className="py-1 pr-2 num">{s.peak_risk.toFixed(0)}</td>
                        <td className="py-1 pr-2 num">{fmtNum(s.people_affected)}</td>
                        <td className="py-1 pr-2 num">{s.recovery_time_s > 0 ? `${s.recovery_time_s.toFixed(0)}s` : '—'}</td>
                        <td className="py-1 num text-mist-500 whitespace-nowrap">{new Date(s.created_at).toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {(sims?.length ?? 0) === 0 && (
                  <div className="text-[11.5px] text-mist-500 py-4 text-center">No simulations match this scenario filter.</div>
                )}
              </div>
            </div>
          </Section>

          <div className="panel rounded-xl px-4 py-3 text-[11.5px] text-mist-500">
            Sources — window bundle: {bundle.overview.source}; risk: {bundle.risk.source};
            incidents: {incidents?.source ?? '—'}; simulations: {sims ? 'simulation rows' : '—'}.
            Empty windows report <span className="text-mist-300">available: false</span> with a reason instead of fabricated series.
          </div>
        </>
      )}
    </div>
  );
}

