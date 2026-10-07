import { useEffect, useMemo, useState } from 'react';
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Line, LineChart,
  Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { IconRefresh } from '../components/Icons';
import { api } from '../services/api';
import { useTwinStore } from '../store/useTwinStore';
import { fmtNum } from '../utils/colors';

const RANGES = ['1H', '6H', '24H', '7D', '30D'] as const;
type Range = (typeof RANGES)[number];

interface Series { t: string; value: number; pct?: number }
interface PredPoint { t: string; actual: number; predicted: number }
interface RecoveryPoint { name: string; scenario: string; recovery: number; peak_risk: number; people: number }
interface SeverityPoint { name: string; value: number }

interface Payload {
  range: string;
  occupancy: Series[];
  energy: Series[];
  temperature: Series[];
  risk: Series[];
  incidents: Series[];
  predictions: PredPoint[];
  recovery: RecoveryPoint[];
  severity: SeverityPoint[];
  source: string;
}

const SEV_COLORS: Record<string, string> = {
  CRITICAL: '#ef4444', HIGH: '#f97316', MEDIUM: '#f59e0b', LOW: '#22c55e',
};

function label(t: string, range: Range) {
  const d = new Date(t);
  if (Number.isNaN(d.getTime())) return '';
  if (range === '7D' || range === '30D') return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
}

function ChartCard({ title, sub, children, tall = false }: { title: string; sub?: string; children: React.ReactNode; tall?: boolean }) {
  return (
    <div className="panel rounded-xl p-4">
      <div className="flex items-baseline justify-between mb-2 gap-2">
        <span className="label-cap">{title}</span>
        {sub && <span className="text-[10.5px] text-mist-500 num truncate">{sub}</span>}
      </div>
      <div className={tall ? 'h-[240px]' : 'h-[190px]'}>
        <ResponsiveContainer width="100%" height="100%">
          {children as React.ReactElement}
        </ResponsiveContainer>
      </div>
    </div>
  );
}

const AXIS = { stroke: '#47577d', fontSize: 10, fontFamily: 'monospace' };
const GRID = '#1c2b47';
const TOOLTIP_STYLE = {
  contentStyle: { background: '#0d1626', border: '1px solid #2a3c5f', borderRadius: 8, fontSize: 12 },
  labelStyle: { color: '#94a3b8' },
};

export default function Analytics() {
  const snapshot = useTwinStore((s) => s.snapshot);
  const [range, setRange] = useState<Range>('24H');
  const [data, setData] = useState<Payload | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    api.analytics(range)
      .then((res) => { if (alive) setData(res as unknown as Payload); })
      .catch(() => { if (alive) setData(null); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [range]);

  const occData = useMemo(
    () => (data?.occupancy ?? []).map((p) => ({
      t: label(p.t, range), value: p.value, pct: p.pct ?? 0,
    })),
    [data, range],
  );
  const predData = useMemo(
    () => (data?.predictions ?? []).map((p) => ({
      t: label(p.t, range), actual: p.actual, predicted: p.predicted,
    })),
    [data, range],
  );
  const energyData = useMemo(
    () => (data?.energy ?? []).map((p) => ({ t: label(p.t, range), value: p.value })),
    [data, range],
  );
  const riskData = useMemo(
    () => (data?.risk ?? []).map((p) => ({ t: label(p.t, range), value: p.value })),
    [data, range],
  );
  const tempData = useMemo(
    () => (data?.temperature ?? []).map((p) => ({ t: label(p.t, range), value: p.value })),
    [data, range],
  );
  const incData = useMemo(
    () => (data?.incidents ?? []).map((p) => ({ t: label(p.t, range), value: p.value })),
    [data, range],
  );

  const avg = (arr: Array<{ value: number }>) =>
    arr.length ? arr.reduce((s, x) => s + x.value, 0) / arr.length : 0;

  return (
    <div className="h-full overflow-y-auto scroll-y p-4 space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-lg font-bold">Analytics</h1>
        <span className="chip border-line-strong bg-ink-800 text-mist-300">SIMULATED DATA</span>
        <div className="flex gap-1.5">
          {RANGES.map((r) => (
            <button
              key={r}
              onClick={() => setRange(r)}
              className={`chip ${range === r ? 'border-brand-400 bg-brand-950/70 text-brand-200' : ''}`}
            >
              {r}
            </button>
          ))}
        </div>
        <div className="flex-1" />
        <button className="btn" onClick={() => setRange((r) => r)} disabled={loading}>
          <IconRefresh width={13} height={13} className={loading ? 'animate-spin' : ''} /> Reload
        </button>
      </div>

      {/* KPI strip */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-2">
        <div className="panel rounded-lg p-3">
          <div className="label-cap">Avg occupancy</div>
          <div className="num text-xl font-bold">{fmtNum(avg(occData))}</div>
          <div className="text-[10.5px] text-mist-500">people on campus</div>
        </div>
        <div className="panel rounded-lg p-3">
          <div className="label-cap">Avg energy</div>
          <div className="num text-xl font-bold text-amber-300">{avg(energyData).toFixed(0)} <span className="text-[11px] text-mist-500">kW</span></div>
          <div className="text-[10.5px] text-mist-500">campus load</div>
        </div>
        <div className="panel rounded-lg p-3">
          <div className="label-cap">Avg temperature</div>
          <div className="num text-xl font-bold">{avg(tempData).toFixed(1)}<span className="text-[11px] text-mist-500"> °C</span></div>
          <div className="text-[10.5px] text-mist-500">ambient model</div>
        </div>
        <div className="panel rounded-lg p-3">
          <div className="label-cap">Peak risk ({range})</div>
          <div className="num text-xl font-bold text-red-400">{Math.max(0, ...riskData.map((p) => p.value)).toFixed(0)}</div>
          <div className="text-[10.5px] text-mist-500">risk index max</div>
        </div>
        <div className="panel rounded-lg p-3">
          <div className="label-cap">Live risk now</div>
          <div className={`num text-xl font-bold ${snapshot && snapshot.risk.score > 60 ? 'text-red-400' : 'text-emerald-400'}`}>
            {snapshot?.risk.score.toFixed(0) ?? '—'}
          </div>
          <div className="text-[10.5px] text-mist-500">{snapshot?.risk.level ?? ''}</div>
        </div>
      </div>

      <div className="grid lg:grid-cols-2 gap-4">
        <ChartCard title="Occupancy — actual vs predicted" sub={`${range} · people`} tall>
          <AreaChart data={occData} margin={{ left: -18, right: 8, top: 6 }}>
            <defs>
              <linearGradient id="gOcc" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#38bdf8" stopOpacity={0.55} />
                <stop offset="100%" stopColor="#38bdf8" stopOpacity={0.03} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="t" tick={AXIS} interval="preserveStartEnd" minTickGap={30} />
            <YAxis tick={AXIS} width={46} />
            <Tooltip {...TOOLTIP_STYLE} />
            <Area type="monotone" dataKey="value" stroke="#38bdf8" fill="url(#gOcc)" strokeWidth={2} name="actual" />
          </AreaChart>
        </ChartCard>

        <ChartCard title="Occupancy forecast" sub="model vs actual" tall>
          <LineChart data={predData} margin={{ left: -18, right: 8, top: 6 }}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="t" tick={AXIS} interval="preserveStartEnd" minTickGap={30} />
            <YAxis tick={AXIS} width={46} />
            <Tooltip {...TOOLTIP_STYLE} />
            <Line type="monotone" dataKey="actual" stroke="#38bdf8" strokeWidth={2} dot={false} name="actual" />
            <Line type="monotone" dataKey="predicted" stroke="#a78bfa" strokeWidth={2} strokeDasharray="5 4" dot={false} name="predicted" />
          </LineChart>
        </ChartCard>

        <ChartCard title="Energy demand" sub="kW">
          <AreaChart data={energyData} margin={{ left: -18, right: 8, top: 6 }}>
            <defs>
              <linearGradient id="gEnergy" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#f59e0b" stopOpacity={0.55} />
                <stop offset="100%" stopColor="#f59e0b" stopOpacity={0.03} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="t" tick={AXIS} interval="preserveStartEnd" minTickGap={36} />
            <YAxis tick={AXIS} width={46} />
            <Tooltip {...TOOLTIP_STYLE} />
            <Area type="monotone" dataKey="value" stroke="#f59e0b" fill="url(#gEnergy)" strokeWidth={2} name="kW" />
          </AreaChart>
        </ChartCard>

        <ChartCard title="Campus risk index" sub="0–100">
          <LineChart data={riskData} margin={{ left: -18, right: 8, top: 6 }}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="t" tick={AXIS} interval="preserveStartEnd" minTickGap={36} />
            <YAxis tick={AXIS} width={46} domain={[0, 100]} />
            <Tooltip {...TOOLTIP_STYLE} />
            <Line type="monotone" dataKey="value" stroke="#ef4444" strokeWidth={2} dot={false} name="risk" />
          </LineChart>
        </ChartCard>

        <ChartCard title="Outdoor temperature" sub="°C">
          <AreaChart data={tempData} margin={{ left: -18, right: 8, top: 6 }}>
            <defs>
              <linearGradient id="gTemp" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#f87171" stopOpacity={0.5} />
                <stop offset="100%" stopColor="#f87171" stopOpacity={0.03} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="t" tick={AXIS} interval="preserveStartEnd" minTickGap={36} />
            <YAxis tick={AXIS} width={46} />
            <Tooltip {...TOOLTIP_STYLE} />
            <Area type="monotone" dataKey="value" stroke="#f87171" fill="url(#gTemp)" strokeWidth={2} name="°C" />
          </AreaChart>
        </ChartCard>

        <ChartCard title="Active incidents" sub="count over window">
          <BarChart data={incData} margin={{ left: -24, right: 8, top: 6 }}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="t" tick={AXIS} interval="preserveStartEnd" minTickGap={36} />
            <YAxis tick={AXIS} width={40} allowDecimals={false} />
            <Tooltip {...TOOLTIP_STYLE} />
            <Bar dataKey="value" fill="#ef4444" radius={[3, 3, 0, 0]} name="incidents" />
          </BarChart>
        </ChartCard>

        <ChartCard title="Recovery time by simulation" sub="minutes">
          <BarChart data={data?.recovery ?? []} margin={{ left: -18, right: 8, top: 6 }}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="name" tick={AXIS} interval={0} angle={-25} height={46} textAnchor="end" />
            <YAxis tick={AXIS} width={40} />
            <Tooltip {...TOOLTIP_STYLE} />
            <Bar dataKey="recovery" fill="#38bdf8" radius={[3, 3, 0, 0]} name="recovery (min)" />
          </BarChart>
        </ChartCard>

        <ChartCard title="Incidents by severity" sub="all time">
          <PieChart>
            <Pie
              data={data?.severity ?? []}
              dataKey="value"
              nameKey="name"
              innerRadius={52}
              outerRadius={80}
              paddingAngle={3}
            >
              {(data?.severity ?? []).map((s) => (
                <Cell key={s.name} fill={SEV_COLORS[s.name] ?? '#64748b'} />
              ))}
            </Pie>
            <Tooltip {...TOOLTIP_STYLE} />
          </PieChart>
        </ChartCard>
      </div>

      <div className="panel rounded-xl px-4 py-3 text-[11.5px] text-mist-500">
        Source: {data?.source ?? 'loading…'} — charts are generated by the backend analytics engine.
      </div>
    </div>
  );
}
