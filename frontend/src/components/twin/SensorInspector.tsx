import { useMemo } from 'react';
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { useTwinStore } from '../../store/useTwinStore';
import { sensorTypeColor, sensorTypeLabel } from '../../types/twin';
import { levelChip } from '../../utils/colors';
import { IconTarget, IconX } from '../Icons';

interface ChartPoint {
  label: string;
  full: string;
  v: number;
}

function fmtTime(iso: string): { label: string; full: string } | null {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return {
    label: d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false }),
    full: d.toLocaleString(),
  };
}

/**
 * Sensor inspector (spec §19/§20/§50): live value + metadata from the Phase 2
 * snapshot and a 24-hour history chart from `/api/sensors/{id}/history`.
 * Data source is always labelled — SIMULATED is never presented as real IoT.
 */
export default function SensorInspector({ onClose }: { onClose: () => void }) {
  const selectedId = useTwinStore((s) => s.selectedSensorId);
  const history = useTwinStore((s) => s.sensorHistory);
  const loading = useTwinStore((s) => s.sensorHistoryLoading);
  const error = useTwinStore((s) => s.sensorHistoryError);
  const snapshot = useTwinStore((s) => s.snapshot);
  const selectBuilding = useTwinStore((s) => s.selectBuilding);
  const selectSensor = useTwinStore((s) => s.selectSensor);
  const liveWindow = useTwinStore((s) => s.sensorLiveWindow);
  const sensorAiStatus = useTwinStore((s) => s.sensorAiStatus);

  const sensor = useMemo(
    () => snapshot?.sensors.find((s) => s.id === selectedId) ?? null,
    [snapshot, selectedId],
  );

  const liveChart = useMemo(() => (
    liveWindow.map((p) => ({
      label: new Date(p.t).toLocaleTimeString(undefined, { hour12: false }),
      full: new Date(p.t).toLocaleString(),
      v: p.value,
    }))
  ), [liveWindow]);

  const chart = useMemo<ChartPoint[]>(() => {
    if (!history || !sensor || history.sensor.id !== sensor.id) return [];
    const out: ChartPoint[] = [];
    for (const p of history.persisted) {
      const t = fmtTime(p.timestamp || p.at);
      if (!t) continue;
      out.push({ label: t.label, full: t.full, v: p.value });
    }
    return out;
  }, [history, sensor]);

  if (!sensor) return null;

  const building = sensor.building_id
    ? snapshot?.buildings.find((b) => b.id === sensor.building_id) ?? null
    : null;
  const zone = sensor.zone_id
    ? snapshot?.zones?.find((z) => z.id === sensor.zone_id) ?? null
    : null;
  const source = history?.data_source ?? snapshot?.data_source ?? snapshot?.metadata?.data_source ?? 'SIMULATED';
  const color = sensorTypeColor(sensor.type);
  const updated = sensor.updated_at
    ? new Date(sensor.updated_at * 1000).toLocaleTimeString(undefined, { hour12: false })
    : '—';
  const historyMatches = Boolean(history && history.sensor.id === sensor.id);
  const label = sensorTypeLabel(sensor.type);
  const ai = sensorAiStatus[sensor.id];
  const inRange = sensor.normal_min != null && sensor.normal_max != null
    ? sensor.value >= sensor.normal_min && sensor.value <= sensor.normal_max
    : null;

  return (
    <div className="absolute top-3 right-3 bottom-10 w-[335px] z-20 panel rounded-xl shadow-2xl shadow-black/60 flex flex-col overflow-hidden max-lg:w-[300px] max-sm:inset-x-2 max-sm:w-auto max-sm:bottom-14">
      {/* header */}
      <div className="px-3.5 py-3 border-b border-line flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: color }} />
            <h2 className="text-[14px] font-bold truncate num">{sensor.sensor_code || sensor.id}</h2>
          </div>
          <div className="flex items-center gap-1.5 mt-1.5 flex-wrap">
            <span className="chip !text-[9px] border-line-strong bg-ink-800 text-mist-300">{label}</span>
            <span className={`chip !text-[9px] ${
              sensor.status === 'ONLINE'
                ? 'border-emerald-700 bg-emerald-950/60 text-emerald-300'
                : 'border-red-700 bg-red-950/60 text-red-300'
            }`}>
              {sensor.status}
            </span>
            {liveChart.length > 0 && (
              <span
                className="chip !text-[9px] border-emerald-700 bg-emerald-950/60 text-emerald-300"
                title="Streaming live readings for this sensor"
              >
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 pulse-soft mr-1" aria-hidden="true" />
                LIVE
              </span>
            )}
            <span className="chip !text-[9px] border-amber-700 bg-amber-950/60 text-amber-300" title="Simulated telemetry — not real IoT">
              {source}
            </span>
          </div>
        </div>
        <button
          className="btn !px-2 !py-1"
          onClick={onClose}
          title="Close sensor inspector"
          aria-label="Close sensor inspector"
        >
          <IconX width={13} height={13} />
        </button>
      </div>

      <div className="flex-1 min-h-0 scroll-y px-3.5 py-3 space-y-3 pb-10">
        {/* live value */}
        <div className="rounded-md border border-line bg-ink-850 p-3">
          <div className="flex items-baseline justify-between">
            <span className="label-cap">Current Value</span>
            <span className="num text-[11px] text-mist-500">updated {updated}</span>
          </div>
          <div className="flex items-baseline gap-2 mt-1">
            <span className={`num text-3xl font-bold ${inRange === false ? 'text-amber-300' : 'text-white'}`}>
              {sensor.value.toFixed(sensor.type === 'energy' ? 1 : 2)}
            </span>
            <span className="text-[13px] text-mist-400">{sensor.unit}</span>
            {inRange !== null && (
              <span className={`chip !text-[9px] ml-auto ${
                inRange ? 'border-emerald-700 text-emerald-300' : 'border-amber-600 text-amber-300'
              }`}>
                {inRange ? 'IN RANGE' : 'OUTSIDE RANGE'}
              </span>
            )}
          </div>
          {sensor.normal_min != null && sensor.normal_max != null && (
            <div className="text-[10.5px] text-mist-500 mt-1 num">
              Normal range {sensor.normal_min}–{sensor.normal_max} {sensor.unit}
            </div>
          )}
        </div>

        {/* Phase 5 — AI status (server-derived; never inferred client-side) */}
        <div className="rounded-md border border-line bg-ink-850 p-3" data-testid="sensor-ai-status">
          <div className="flex items-center justify-between mb-1.5">
            <span className="label-cap">AI Status</span>
            <span className="num text-[10px] text-mist-500">anomaly engine</span>
          </div>
          {!ai && (
            <div className="text-[11.5px] text-mist-500">
              Not analysed yet — status appears after the first AI cycle.
            </div>
          )}
          {ai && (
            <>
              <div className="flex items-center gap-2 flex-wrap">
                <span className={`chip !text-[10px] font-bold border ${
                  ai.status === 'INSUFFICIENT_DATA'
                    ? 'border-line-strong bg-ink-800 text-mist-400'
                    : ai.status === 'NORMAL'
                      ? 'border-emerald-700 bg-emerald-950/70 text-emerald-300'
                      : levelChip(ai.status)
                }`}>
                  {ai.status}
                </span>
                <span className="num text-[11px] text-mist-400">
                  score {ai.score != null ? ai.score : '—'}
                </span>
                {ai.detector && (
                  <span className="chip !text-[9px] border-line-strong text-mist-500">{ai.detector}</span>
                )}
              </div>
              <div className="flex items-center justify-between text-[10.5px] mt-1.5">
                <span className="text-mist-500">Samples</span>
                <b className="num">
                  {ai.available_samples} / min {ai.minimum_required}
                  {ai.available_samples < ai.minimum_required && (
                    <span className="text-amber-300 ml-1.5">— confidence withheld</span>
                  )}
                </b>
              </div>
              <p className="text-[10px] text-mist-600 mt-1.5 leading-relaxed">
                Weighted indicator from local sensor history — not a guaranteed prediction.
              </p>
            </>
          )}
        </div>

        {/* live streaming window (Phase 4 §46) — bounded in-memory buffer */}
        {liveChart.length > 1 && (
          <div className="rounded-md border border-line bg-ink-850 p-2.5" data-testid="sensor-live-chart">
            <div className="flex items-center justify-between mb-2">
              <span className="label-cap">Live — streamed readings</span>
              <span className="num text-[10px] text-mist-500">{liveChart.length} pts</span>
            </div>
            <div style={{ height: 90 }}>
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={liveChart} margin={{ top: 4, right: 4, bottom: 0, left: -18 }}>
                  <CartesianGrid stroke="#1f2e4a" strokeDasharray="3 3" vertical={false} />
                  <XAxis
                    dataKey="label"
                    interval={Math.max(0, Math.floor(liveChart.length / 3))}
                    tick={{ fontSize: 9, fill: '#7085a6' }}
                    tickLine={false}
                    axisLine={{ stroke: '#1f2e4a' }}
                  />
                  <YAxis
                    width={40}
                    tick={{ fontSize: 9, fill: '#7085a6' }}
                    tickLine={false}
                    axisLine={false}
                    domain={['auto', 'auto']}
                  />
                  <Tooltip
                    contentStyle={{
                      background: '#0d1626', border: '1px solid #2b3d5f',
                      borderRadius: 6, fontSize: 11,
                    }}
                    labelStyle={{ color: '#aebeda' }}
                    labelFormatter={(_v, payload) => payload?.[0]?.payload?.full ?? ''}
                    formatter={(value: number | string) => [`${Number(value).toFixed(2)} ${sensor.unit}`, label]}
                  />
                  <Area
                    type="monotone"
                    dataKey="v"
                    stroke="#34d399"
                    fill="#34d399"
                    fillOpacity={0.14}
                    strokeWidth={2}
                    isAnimationActive={false}
                    dot={false}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
            <p className="text-[10px] text-mist-600 mt-1.5">
              Bounded window (max 120 points) fed by live sensor events — cleared when you select a sensor.
            </p>
          </div>
        )}

        {/* context */}
        <div className="rounded-md border border-line bg-ink-850 p-2.5 space-y-1 text-[11.5px]">
          <div className="flex justify-between gap-2">
            <span className="text-mist-500">Location</span>
            <b className="text-right truncate">
              {building?.name ?? 'Campus'}
              {zone ? ` · ${zone.name}` : ''}
            </b>
          </div>
          <div className="flex justify-between">
            <span className="text-mist-500">Coordinates</span>
            <b className="num">X {sensor.x.toFixed(0)} · Z {sensor.z.toFixed(0)}</b>
          </div>
          <div className="flex justify-between">
            <span className="text-mist-500">Device status</span>
            <b className={sensor.healthy ? 'text-emerald-400' : 'text-red-400'}>
              {sensor.healthy ? 'Healthy' : 'Needs attention'}
            </b>
          </div>
          <div className="flex justify-between">
            <span className="text-mist-500">Sensor ID</span>
            <b className="num truncate">{sensor.id}</b>
          </div>
        </div>

        {/* 24 h history (spec §50) */}
        <div className="rounded-md border border-line bg-ink-850 p-2.5">
          <div className="flex items-center justify-between mb-2">
            <span className="label-cap">{label} — Last 24 Hours</span>
            <span className="num text-[10px] text-mist-500">{chart.length || '—'} pts</span>
          </div>

          {loading && (
            <div className="h-[148px] rounded bg-ink-800 animate-pulse" />
          )}
          {!loading && error && (
            <div className="rounded border border-red-800 bg-red-950/40 p-2.5 text-[11.5px] text-red-200">
              {error}
            </div>
          )}
          {!loading && !error && !historyMatches && (
            <div className="h-[148px] flex flex-col items-center justify-center text-center">
              <div className="text-[11.5px] text-mist-400">History unavailable</div>
              <div className="text-[10.5px] text-mist-600 mt-0.5">Select the sensor again to retry.</div>
            </div>
          )}
          {!loading && !error && historyMatches && chart.length === 0 && (
            <div className="h-[148px] flex items-center justify-center text-[11.5px] text-mist-500">
              No historical readings recorded yet.
            </div>
          )}
          {!loading && !error && chart.length > 0 && (
            <div style={{ height: 148 }}>
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={chart} margin={{ top: 4, right: 4, bottom: 0, left: -18 }}>
                  <CartesianGrid stroke="#1f2e4a" strokeDasharray="3 3" vertical={false} />
                  <XAxis
                    dataKey="label"
                    interval={Math.max(0, Math.floor(chart.length / 5))}
                    tick={{ fontSize: 9, fill: '#7085a6' }}
                    tickLine={false}
                    axisLine={{ stroke: '#1f2e4a' }}
                  />
                  <YAxis
                    width={40}
                    tick={{ fontSize: 9, fill: '#7085a6' }}
                    tickLine={false}
                    axisLine={false}
                    domain={['auto', 'auto']}
                  />
                  <Tooltip
                    contentStyle={{
                      background: '#0d1626', border: '1px solid #2b3d5f',
                      borderRadius: 6, fontSize: 11,
                    }}
                    labelStyle={{ color: '#aebeda' }}
                    labelFormatter={(_v, payload) => payload?.[0]?.payload?.full ?? ''}
                    formatter={(value: number | string) => [`${Number(value).toFixed(2)} ${sensor.unit}`, label]}
                  />
                  <Area
                    type="monotone"
                    dataKey="v"
                    stroke={color}
                    fill={color}
                    fillOpacity={0.14}
                    strokeWidth={2}
                    isAnimationActive={false}
                    dot={false}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>

        <div className="flex gap-2">
          {building && (
            <button
              className="btn flex-1"
              onClick={() => { selectSensor(null); void selectBuilding(building.id); }}
            >
              <IconTarget width={13} height={13} /> View Building
            </button>
          )}
          <button className="btn flex-1" onClick={onClose}>Close</button>
        </div>

        <p className="text-[10px] text-mist-500 leading-relaxed">
          Telemetry is generated by the Phase 2 simulator (<b className="text-amber-300">{source}</b>) and stored
          as time-series readings. No real IoT devices are connected.
        </p>
      </div>
    </div>
  );
}
