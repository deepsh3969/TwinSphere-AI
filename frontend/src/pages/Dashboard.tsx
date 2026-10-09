import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import AIPanel from '../components/dashboard/AIPanel';
import BuildingPanel from '../components/dashboard/BuildingPanel';
import EventTimeline from '../components/dashboard/EventTimeline';
import HealthChangesPanel from '../components/dashboard/HealthChangesPanel';
import KpiStrip from '../components/dashboard/KpiStrip';
import MetricTile from '../components/dashboard/MetricTile';
import RiskGauge from '../components/dashboard/RiskGauge';
import SystemHealthBar from '../components/dashboard/SystemHealthBar';
import CampusScene from '../components/3d/CampusScene';
import ReplayControls, { ReplayBanner } from '../components/replay/ReplayControls';
import {
  IconAlert, IconActivity, IconBrain, IconChart, IconCheck, IconFire, IconRefresh,
  IconRoad, IconTarget, IconThermo, IconUsers, IconX, IconZap,
} from '../components/Icons';
import { useTwinStore } from '../store/useTwinStore';
import { fmtClock, fmtNum, scenarioIcon, scenarioLabel, trendLabel } from '../utils/colors';

export default function Dashboard() {
  const snapshot = useTwinStore((s) => s.snapshot);
  const selectedId = useTwinStore((s) => s.selectedBuildingId);
  const selectBuilding = useTwinStore((s) => s.selectBuilding);
  const toggle = useTwinStore((s) => s.toggle);
  const toggles = useTwinStore((s) => s.toggles);
  const timeline = useTwinStore((s) => s.timeline);
  const lastUpdate = useTwinStore((s) => s.lastUpdate);
  const connection = useTwinStore((s) => s.connection);

  // Phase 5 AI slice
  const anomalies = useTwinStore((s) => s.anomalies);
  const sensorAiStatus = useTwinStore((s) => s.sensorAiStatus);
  const aiPredictions = useTwinStore((s) => s.aiPredictions);
  const aiDegraded = useTwinStore((s) => s.aiDegraded);
  const anomalyDataQuality = useTwinStore((s) => s.anomalyDataQuality);
  const riskPublished = useTwinStore((s) => s.riskPublished);

  // Phase 7 §42 — evacuation/route card data
  const evacuation = useTwinStore((s) => s.evacuation);
  const routePlan = useTwinStore((s) => s.routePlan);
  const refreshRouteData = useTwinStore((s) => s.refreshRouteData);
  const setRoutePanelOpen = useTwinStore((s) => s.setRoutePanelOpen);
  const navigate = useNavigate();
  useEffect(() => {
    if (!useTwinStore.getState().evacuation) void refreshRouteData();
  }, [refreshRouteData]);

  // Phase 9 §63 — replay is URL-driven (?replay=<simId>) and separate from live
  const [searchParams, setSearchParams] = useSearchParams();
  const replayParam = searchParams.get('replay');
  const replay = useTwinStore((s) => s.replay);
  const replayLoading = useTwinStore((s) => s.replayLoading);
  const loadReplay = useTwinStore((s) => s.loadReplay);
  const replayActive = Boolean(replay) || replayLoading;

  useEffect(() => {
    if (replayParam) {
      void loadReplay(replayParam);
    } else {
      const st = useTwinStore.getState();
      if (st.replay || st.replayError) st.closeReplay();
    }
  }, [replayParam, loadReplay]);
  useEffect(() => () => useTwinStore.getState().closeReplay(), []);

  const clearReplayParam = useCallback(() => {
    setSearchParams((prev) => {
      const p = new URLSearchParams(prev);
      p.delete('replay');
      return p;
    }, { replace: true });
  }, [setSearchParams]);

  const [railTab, setRailTab] = useState<'ai' | 'health'>('ai');

  const m = snapshot?.metrics;
  const sim = snapshot?.active_sim;
  const latestEvent = timeline[0] ?? sim?.events[sim.events.length - 1];

  const aiCards = useMemo(() => {
    const crit = anomalies.filter((a) => {
      const b = (a.band ?? a.severity ?? '').toUpperCase();
      return b === 'CRITICAL' || b === 'HIGH';
    }).length;
    const statusVals = Object.values(sensorAiStatus);
    const flagged = statusVals.filter((v) => v.status !== 'NORMAL' && v.status !== 'INSUFFICIENT_DATA').length;
    const insufficient = statusVals.filter((v) => v.status === 'INSUFFICIENT_DATA').length;
    const next = [...aiPredictions].sort(
      (a, b) => a.horizon_min - b.horizon_min || b.confidence - a.confidence,
    )[0];
    return { crit, flagged, insufficient, next };
  }, [anomalies, sensorAiStatus, aiPredictions]);

  const quickToggles = useMemo(
    () => ([
      { key: 'labels', label: 'Labels' },
      { key: 'sensors', label: 'Sensors' },
      { key: 'routes', label: 'Routes' },
      { key: 'heatmap', label: 'Heatmap' },
      { key: 'night', label: 'Night' },
    ] as const),
    [],
  );

  if (!snapshot) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center">
          <div className="w-9 h-9 mx-auto mb-3 border-2 border-brand-400 border-t-transparent rounded-full animate-spin" />
          <div className="label-cap">Connecting to twin…</div>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex min-h-0">
      <div className="flex-1 flex flex-col min-w-0 min-h-0">
        {/* viewport */}
        <div className="flex-1 relative min-h-0">
          <CampusScene />

          {/* top-left status overlay */}
          <div className="absolute top-3 left-3 z-10 flex flex-col gap-2 max-w-[calc(100%-360px)] max-sm:max-w-[calc(100%-24px)]">
            <div className="panel rounded-lg px-3 py-2 flex items-center gap-3">
              <div>
                <div className="label-cap">Virtual Clock</div>
                <div className="num text-xl font-bold leading-none">{fmtClock(snapshot.clock_hour)}</div>
              </div>
              <div className="w-px h-8 bg-line" />
              <div>
                <div className="label-cap">Campus</div>
                <div className="text-[12.5px] font-semibold">
                  {snapshot.buildings.length} buildings · {snapshot.sensors.length} sensors
                </div>
                {replayActive ? (
                  <div className="text-[10px] text-amber-300 num flex items-center gap-1">
                    <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
                    REPLAY · historical view
                  </div>
                ) : (
                  <div className="text-[10px] text-mist-500 num">
                    {connection === 'CONNECTED' ? `live · ${Math.max(0, Math.round((Date.now() - lastUpdate) / 1000))}s ago` : 'reconnecting…'}
                  </div>
                )}
              </div>
            </div>

            <ReplayBanner onExit={clearReplayParam} />

            {sim && !replayActive && (
              <div className="panel rounded-lg px-3 py-2 w-[260px] border-orange-700/70">
                <div className="flex items-center gap-2">
                  <span className="text-base">{scenarioIcon(sim.scenario)}</span>
                  <span className="text-[12.5px] font-bold flex-1 truncate">{scenarioLabel(sim.scenario)} drill</span>
                  <span className={`chip !py-0 !px-1.5 ${
                    sim.status === 'RUNNING' ? 'border-red-700 text-red-300'
                      : sim.status === 'PAUSED' ? 'border-amber-700 text-amber-300'
                        : sim.status === 'RECOVERING' ? 'border-sky-700 text-sky-300'
                          : 'border-emerald-700 text-emerald-300'
                  }`}>{sim.status}</span>
                </div>
                <div className="h-1.5 rounded-full bg-ink-700 mt-2 overflow-hidden">
                  <div
                    className="h-full bg-gradient-to-r from-orange-500 to-red-500 transition-all"
                    style={{ width: `${Math.min(100, sim.progress)}%` }}
                  />
                </div>
                <div className="flex justify-between text-[10px] text-mist-500 mt-1 num">
                  <span>{sim.phase}</span>
                  <span>T+{sim.t.toFixed(0)}s / {sim.duration}s</span>
                </div>
                {sim.people_at_risk > 0 && (
                  <div className="text-[11px] text-red-300 mt-1.5 flex items-center gap-1.5">
                    <IconUsers width={12} height={12} /> {fmtNum(sim.people_at_risk)} people at risk
                  </div>
                )}
              </div>
            )}
          </div>

          {/* quick toggles */}
          <div className="absolute top-3 right-3 z-10 flex flex-wrap gap-1.5 justify-end max-lg:right-auto max-lg:left-3 max-lg:top-auto max-lg:bottom-3">
            {quickToggles.map((t) => (
              <button
                key={t.key}
                onClick={() => toggle(t.key)}
                className={`chip !text-[10.5px] transition-colors ${
                  toggles[t.key]
                    ? 'border-brand-400 bg-brand-950/80 text-brand-200'
                    : 'border-line-strong bg-ink-900/85 text-mist-400'
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          {/* latest event ticker */}
          {latestEvent && (
            <div className="absolute bottom-3 left-3 z-10 panel rounded-md px-3 py-1.5 flex items-center gap-2 max-w-[60%] max-sm:max-w-[calc(100%-24px)]">
              <IconActivity width={13} height={13} className="text-brand-400 shrink-0 pulse-soft" />
              <span className="num text-[10.5px] text-mist-500 shrink-0">T+{latestEvent.t.toFixed(0)}s</span>
              <span className="text-[11.5px] truncate">{latestEvent.message}</span>
            </div>
          )}

          {selectedId && <BuildingPanel onClose={() => void selectBuilding(null)} />}
          {replayActive && <ReplayControls onExit={clearReplayParam} />}
        </div>

        {/* bottom metric strip */}
        <div className="shrink-0 border-t border-line bg-ink-900/70 px-3 py-2.5">
          {/* Phase 9 §60 — server-computed KPI strip with trends */}
          <div className="mb-2">
            <KpiStrip />
          </div>
          <div className="grid grid-cols-4 xl:grid-cols-8 gap-2">
            <MetricTile
              label="Occupancy" value={fmtNum(m?.occupancy ?? 0)}
              sub={`${(m?.occupancy_pct ?? 0).toFixed(0)}% of 26,400`} icon={<IconUsers width={12} height={12} />}
            />
            <MetricTile
              label="Energy" value={(m?.energy ?? 0).toFixed(0)} unit="kW"
              tone="info" icon={<IconZap width={12} height={12} />}
            />
            <MetricTile
              label="Avg Temp" value={(m?.temperature ?? 0).toFixed(1)} unit="°C"
              tone={(m?.temperature ?? 0) > 30 ? 'warn' : 'default'} icon={<IconThermo width={12} height={12} />}
            />
            <MetricTile
              label="Risk Index" value={(m?.risk ?? 0).toFixed(0)}
              tone={snapshot.risk.score > 60 ? 'bad' : snapshot.risk.score > 30 ? 'warn' : 'good'}
              sub={snapshot.risk.level} icon={<IconAlert width={12} height={12} />}
            />
            <MetricTile
              label="Incidents" value={m?.incidents ?? 0}
              tone={(m?.incidents ?? 0) > 0 ? 'bad' : 'good'} icon={<IconFire width={12} height={12} />}
            />
            <MetricTile
              label="People at Risk" value={fmtNum(m?.people_at_risk ?? 0)}
              tone={(m?.people_at_risk ?? 0) > 0 ? 'bad' : 'good'} icon={<IconUsers width={12} height={12} />}
            />
            <MetricTile
              label="Anomalies" value={m?.anomalies ?? snapshot.anomalies.length}
              tone={(m?.anomalies ?? 0) > 0 ? 'warn' : 'good'} icon={<IconActivity width={12} height={12} />}
            />
            <MetricTile
              label="Sensor Health" value={`${(snapshot.system_health.sensors_ok ? 100 : 97).toFixed(0)}%`}
              tone="good" sub="streaming" icon={<IconCheck width={12} height={12} />}
            />
            {/* Phase 7 §42 — evacuation route card */}
            <MetricTile
              label="Evac Plan"
              value={evacuation?.status ?? 'IDLE'}
              tone={evacuation?.status === 'CRITICAL' ? 'bad'
                : evacuation?.status === 'ACTIVE' ? 'warn' : 'good'}
              sub={`${fmtNum(evacuation?.people_at_risk ?? 0)} at risk · ${
                routePlan ? `${routePlan.mode} v${routePlan.route_version}` : 'no plan'}`}
              icon={<IconRoad width={12} height={12} />}
              onClick={() => { setRoutePanelOpen(true); navigate('/twin'); }}
            />
          </div>

          {/* Phase 5 — AI intelligence strip */}
          <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-5 gap-2 mt-2 pt-2.5 border-t border-line/70">
            <MetricTile
              label="AI Risk (smoothed)"
              value={fmtNum(riskPublished?.score ?? snapshot.risk.score, 0)}
              tone={snapshot.risk.score > 60 ? 'bad' : snapshot.risk.score > 30 ? 'warn' : 'good'}
              sub={`raw ${fmtNum(m?.risk ?? snapshot.risk.score, 0)} · ${trendLabel(riskPublished?.trend)}`}
              icon={<IconAlert width={12} height={12} />}
            />
            <MetricTile
              label="Active Anomalies"
              value={anomalies.length}
              tone={anomalies.length > 0 ? 'warn' : 'good'}
              sub={`${aiCards.crit} high/critical · ${anomalyDataQuality} data`}
              icon={<IconActivity width={12} height={12} />}
            />
            <MetricTile
              label="Next Forecast"
              value={aiCards.next ? `+${aiCards.next.horizon_min}m` : '—'}
              tone="info"
              sub={aiCards.next
                ? `${aiCards.next.metric} → ${fmtNum(aiCards.next.predicted_value, 0)} · ${Math.round((aiCards.next.confidence ?? 0) * 100)}%`
                : 'warming up (≥100 samples)'}
              icon={<IconChart width={12} height={12} />}
            />
            <MetricTile
              label="AI Sensor Flags"
              value={aiCards.flagged}
              tone={aiCards.flagged > 0 ? 'warn' : 'good'}
              sub={`${aiCards.insufficient} cold-start sensors`}
              icon={<IconZap width={12} height={12} />}
            />
            <MetricTile
              label="AI Health"
              value={aiDegraded ? 'DEGRADED' : 'OK'}
              tone={aiDegraded ? 'bad' : 'good'}
              sub={aiDegraded ? 'analysis isolated · sim unaffected' : 'anomaly + prediction engines live'}
              icon={<IconBrain width={12} height={12} />}
            />
          </div>

          {/* Phase 9 §60 — system-health bottom bar */}
          <div className="-mx-3 -mb-2.5 mt-2">
            <SystemHealthBar />
          </div>
        </div>
      </div>

      {/* right AI rail */}
      <aside className="w-[340px] shrink-0 border-l border-line bg-ink-900/60 flex flex-col min-h-0 max-xl:hidden">
        <div className="flex-1 min-h-0 flex flex-col">
          <div className="border-b border-line px-3 py-2.5">
            <RiskGauge risk={riskPublished ?? snapshot.risk} />
          </div>
          <div className="flex gap-1 px-3 py-1.5 border-b border-line shrink-0">
            <button
              className={`chip !text-[10.5px] ${railTab === 'ai' ? 'border-brand-400 bg-brand-950/70 text-brand-200' : ''}`}
              onClick={() => setRailTab('ai')}
            >
              AI feed
            </button>
            <button
              className={`chip !text-[10.5px] ${railTab === 'health' ? 'border-brand-400 bg-brand-950/70 text-brand-200' : ''}`}
              onClick={() => setRailTab('health')}
            >
              Health &amp; changes
            </button>
          </div>
          <div className="flex-1 min-h-0">
            {railTab === 'ai' ? <AIPanel /> : <HealthChangesPanel />}
          </div>
          <div className="h-[150px] shrink-0 border-t border-line">
            <EventTimeline compact />
          </div>
        </div>
      </aside>

      {/* compact gauge for smaller screens */}
      <div className="hidden max-xl:block fixed bottom-16 left-1/2 -translate-x-1/2 z-20 w-[280px] panel rounded-lg px-3 py-2">
        <RiskGauge risk={riskPublished ?? snapshot.risk} compact />
        <button
          className="btn btn-primary w-full mt-2 !py-1 !text-[11.5px]"
          onClick={() => useTwinStore.getState().setDemo(true)}
        >
          <IconTarget width={12} height={12} /> Open AI + Demo panel
        </button>
        <button className="btn w-full mt-1 !py-1 !text-[11px]" onClick={() => useTwinStore.getState().refreshAnalyst()}>
          <IconRefresh width={12} height={12} /> Refresh analyst
        </button>
        <button className="btn w-full mt-1 !py-1 !text-[11px]" onClick={() => selectBuilding(null)}>
          <IconX width={12} height={12} /> Clear selection
        </button>
      </div>
    </div>
  );
}
