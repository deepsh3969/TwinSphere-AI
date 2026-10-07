import { useTwinStore } from '../../store/useTwinStore';
import type { MetricSample } from '../../types';
import { fmtNum, levelChip } from '../../utils/colors';

function Tile({ label, value, sub, tone }: {
  label: string;
  value: string | number;
  sub?: string;
  tone?: string;
}) {
  return (
    <div className="rounded-md border border-line bg-ink-850 px-2.5 py-2">
      <div className="label-cap">{label}</div>
      <div className={`num text-lg font-bold ${tone ?? 'text-white'}`}>{value}</div>
      {sub && <div className="text-[10px] text-mist-500 mt-0.5">{sub}</div>}
    </div>
  );
}

/** Honest trend arrow: needs ≥5 samples, else "—" (never invents a direction). */
function Trend({ values, digits = 1, unit = '' }: { values: number[]; digits?: number; unit?: string }) {
  if (values.length < 5) return <span className="num text-[10px] text-mist-600" title="Needs at least 5 live samples">—</span>;
  const delta = values[values.length - 1] - values[0];
  const eps = Math.max(Math.abs(values[0]), 1) * 0.01;
  if (Math.abs(delta) < eps) {
    return <span className="num text-[10px] text-mist-500" title="Stable over the window">→ {values[values.length - 1].toFixed(digits)}{unit}</span>;
  }
  const cls = delta > 0 ? 'text-amber-300' : 'text-emerald-300';
  const arrow = delta > 0 ? '↑' : '↓';
  return (
    <span className={`num text-[10px] ${cls}`} title={`First vs last of ${values.length} samples`}>
      {arrow} {Math.abs(delta).toFixed(digits)}{unit} · {values[values.length - 1].toFixed(digits)}{unit}
    </span>
  );
}

/**
 * Campus overview panel (spec §24/§25): shown when nothing is selected.
 * Every value derives from real Phase 2 API data; unavailable → "—".
 */
export default function CampusOverview() {
  const snapshot = useTwinStore((s) => s.snapshot);
  const metricHistory = useTwinStore((s) => s.metricHistory);
  if (!snapshot) return null;

  const summary = snapshot.summary;
  const metrics = snapshot.metrics;

  const capacity = snapshot.buildings.reduce((sum, b) => sum + (b.capacity || 0), 0);
  const occupancy = summary?.occupancy ?? metrics?.occupancy ?? null;
  const occupancyPct = summary?.occupancy_pct ?? metrics?.occupancy_pct ?? null;

  const totalSensors = snapshot.sensors ? snapshot.sensors.length : (summary?.sensors ?? null);
  const onlineSensors = snapshot.sensors
    ? snapshot.sensors.filter((s) => s.status === 'ONLINE').length
    : null;
  const onlinePct = totalSensors && onlineSensors !== null
    ? Math.round((onlineSensors / totalSensors) * 100)
    : null;

  const activeIncidents = snapshot.incidents.filter((i) => i.status === 'ACTIVE').length;
  const riskLevel = summary?.risk_level ?? metrics?.risk_level ?? null;

  return (
    <div className="flex flex-col min-h-0 h-full">
      <div className="px-3.5 py-3 border-b border-line">
        <h2 className="text-[13px] font-bold tracking-wide">CAMPUS OVERVIEW</h2>
        <p className="text-[11px] text-mist-500 mt-0.5">
          Select a building or sensor to inspect details.
        </p>
      </div>

      <div className="flex-1 min-h-0 scroll-y px-3.5 py-3 space-y-3">
        <div className="grid grid-cols-2 gap-2">
          <Tile label="Buildings" value={summary?.buildings ?? snapshot.buildings.length} />
          <Tile label="Zones" value={summary?.zones ?? (snapshot.zones ? snapshot.zones.length : '—')} />
          <Tile label="Sensors" value={totalSensors ?? '—'} />
          <Tile label="Floors" value={summary?.floors ?? '—'} />
          <Tile label="Campus Capacity" value={capacity > 0 ? fmtNum(capacity) : '—'} />
          <Tile
            label="Current Occupancy"
            value={occupancy !== null ? fmtNum(occupancy) : '—'}
            sub={occupancyPct !== null ? `${occupancyPct.toFixed(0)}% of capacity` : undefined}
          />
        </div>

        <div className="rounded-md border border-line bg-ink-850 p-2.5">
          <div className="flex items-center justify-between">
            <span className="label-cap">Sensors Online</span>
            <span className={`num text-[13px] font-bold ${(onlinePct ?? 100) < 90 ? 'text-amber-300' : 'text-emerald-400'}`}>
              {onlinePct !== null ? `${onlinePct}%` : '—'}
            </span>
          </div>
          <div className="flex items-center justify-between mt-1 text-[11px] text-mist-400">
            <span className="num">{onlineSensors !== null ? `${onlineSensors} / ${totalSensors}` : '—'} reporting</span>
            <span className="num">{snapshot.roads.length} roads · {summary?.gates ?? '—'} gates</span>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <div className="rounded-md border border-line bg-ink-850 p-2.5">
            <div className="label-cap">Active Incidents</div>
            <div className={`num text-lg font-bold ${activeIncidents > 0 ? 'text-red-400' : 'text-emerald-400'}`}>
              {activeIncidents}
            </div>
          </div>
          <div className="rounded-md border border-line bg-ink-850 p-2.5">
            <div className="label-cap">Campus Risk</div>
            <div className="mt-1">
              {riskLevel
                ? <span className={`chip ${levelChip(riskLevel)}`}>{riskLevel}</span>
                : <span className="num text-lg font-bold text-mist-500">—</span>}
            </div>
          </div>
        </div>

        {/* live metric trends (Phase 4 §45) — bounded window, honest dash when unknown */}
        <div className="rounded-md border border-line bg-ink-850 p-2.5" data-testid="live-trends">
          <div className="flex items-center justify-between mb-1.5">
            <span className="label-cap">Live Trends</span>
            <span className="num text-[10px] text-mist-600">{metricHistory.length} samples</span>
          </div>
          <div className="space-y-1 text-[11.5px]">
            <div className="flex items-center justify-between gap-2">
              <span className="text-mist-400">Occupancy</span>
              <Trend values={metricHistory.map((m: MetricSample) => m.occupancy_pct)} digits={0} unit="%" />
            </div>
            <div className="flex items-center justify-between gap-2">
              <span className="text-mist-400">Energy</span>
              <Trend values={metricHistory.map((m: MetricSample) => m.energy)} digits={1} unit=" kW" />
            </div>
            <div className="flex items-center justify-between gap-2">
              <span className="text-mist-400">Temperature</span>
              <Trend values={metricHistory.map((m: MetricSample) => m.temperature)} digits={1} unit="°" />
            </div>
            <div className="flex items-center justify-between gap-2">
              <span className="text-mist-400">Risk score</span>
              <Trend values={metricHistory.map((m: MetricSample) => m.risk)} digits={1} />
            </div>
            <div className="flex items-center justify-between gap-2">
              <span className="text-mist-400">Water</span>
              <Trend values={metricHistory.map((m: MetricSample) => m.water)} digits={0} unit="%" />
            </div>
          </div>
          <p className="text-[10px] text-mist-600 mt-1.5 leading-snug">
            First vs last of up to 30 live samples. Shows "—" until at least 5 samples arrive.
          </p>
        </div>

        <div className="rounded-md border border-line bg-ink-850 p-2.5 text-[11px] text-mist-400 space-y-1">
          <div className="flex justify-between">
            <span>Active simulation</span>
            <b>{snapshot.active_sim ? snapshot.active_sim.scenario : 'None'}</b>
          </div>
          <div className="flex justify-between">
            <span>Connected clients</span>
            <b className="num">{snapshot.connected_clients ?? '—'}</b>
          </div>
          <div className="flex justify-between">
            <span>Data source</span>
            <b className="text-amber-300">{snapshot.data_source ?? '—'}</b>
          </div>
        </div>
      </div>
    </div>
  );
}
