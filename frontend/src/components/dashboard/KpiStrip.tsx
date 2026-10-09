import { useEffect, useMemo, useState } from 'react';
import { Area, AreaChart, ResponsiveContainer } from 'recharts';
import { api } from '../../services/api';
import type { OverviewResponse, SeriesPoint } from '../../types';
import { fmtNum } from '../../utils/colors';

const STATUS_DOT: Record<string, string> = {
  GOOD: 'bg-emerald-400',
  WARN: 'bg-amber-400',
  CRITICAL: 'bg-red-500',
  LOW: 'bg-sky-400',
  UNKNOWN: 'bg-mist-500',
};

const TREND_CLS: Record<string, string> = {
  up: 'text-amber-300',
  down: 'text-sky-300',
  flat: 'text-mist-500',
};

const TREND_GLYPH: Record<string, string> = { up: '▲', down: '▼', flat: '–' };

function Spark({ points }: { points: SeriesPoint[] }) {
  const data = useMemo(
    () => points.filter((p) => typeof p.value === 'number').map((p) => ({ v: p.value })),
    [points],
  );
  if (data.length < 2) return <div className="h-6" />;
  return (
    <div className="h-6 mt-0.5" data-testid="kpi-spark">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data}>
          <Area type="monotone" dataKey="v" stroke="#38bdf8" fill="#38bdf818" strokeWidth={1.5} dot={false} isAnimationActive={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

/**
 * Phase 9 §60 — command-center KPI strip: server-computed KPIs with
 * quarter-over-quarter trend, status band and sparklines for the
 * series-backed metrics.
 */
export default function KpiStrip() {
  const [overview, setOverview] = useState<OverviewResponse | null>(null);
  const [series, setSeries] = useState<Record<string, SeriesPoint[]>>({});
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    Promise.all([
      api.analyticsOverview({ range: '24H' }),
      api.occupancyAnalytics({ range: '6H' }).catch(() => null),
      api.energyAnalytics({ range: '6H' }).catch(() => null),
      api.riskAnalytics({ range: '6H' }).catch(() => null),
    ]).then(([ov, occ, en, risk]) => {
      if (!alive) return;
      setOverview(ov);
      setSeries({
        occupancy: occ?.series ?? [],
        energy: en?.series ?? [],
        risk: risk?.series ?? [],
      });
      setError(null);
    }).catch((err: unknown) => {
      if (alive) setError(err instanceof Error ? err.message : 'Failed to load KPIs');
    }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, []);

  if (loading) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-2">
        {Array.from({ length: 6 }, (_, i) => (
          <div key={i} className="panel rounded-lg p-2.5 animate-pulse h-[74px]" />
        ))}
      </div>
    );
  }
  if (error || !overview) {
    return (
      <div className="panel rounded-lg px-3 py-2 text-[12px] text-amber-300">
        Command-center KPIs unavailable — {error ?? 'no data'}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-2" data-testid="kpi-strip">
      {overview.kpis.map((kpi) => (
        <div key={kpi.id} className="panel rounded-lg px-2.5 py-2 min-w-0">
          <div className="flex items-center gap-1.5">
            <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${STATUS_DOT[kpi.status] ?? STATUS_DOT.UNKNOWN}`} />
            <span className="label-cap truncate">{kpi.label}</span>
          </div>
          <div className="flex items-baseline gap-1.5 mt-0.5">
            <span className="num text-lg font-bold leading-none truncate">
              {kpi.value === null ? '—' : fmtNum(kpi.value, Number.isInteger(kpi.value) ? 0 : 1)}
            </span>
            <span className="text-[10px] text-mist-500 shrink-0">{kpi.unit}</span>
            {kpi.secondary && (
              <span className="text-[10px] text-mist-400 truncate">{kpi.secondary}</span>
            )}
          </div>
          <div className={`flex items-center gap-1 text-[10px] num ${TREND_CLS[kpi.trend.direction] ?? 'text-mist-500'}`}>
            <span>{TREND_GLYPH[kpi.trend.direction] ?? '–'}</span>
            <span className="truncate">
              {kpi.trend.available
                ? `${kpi.trend.delta_pct > 0 ? '+' : ''}${kpi.trend.delta_pct.toFixed(1)}%`
                : kpi.trend.label}
            </span>
          </div>
          <Spark points={series[kpi.id] ?? []} />
        </div>
      ))}
      <div className="col-span-full text-[10px] text-mist-500 num flex justify-between">
        <span>window {overview.window.preset} · {new Date(overview.window.from).toLocaleString()} → {new Date(overview.window.to).toLocaleString()}</span>
        <span>{overview.source} · computed {new Date(overview.computed_at).toLocaleTimeString()}</span>
      </div>
    </div>
  );
}
