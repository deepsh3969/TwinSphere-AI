import { useEffect, useMemo, useState } from 'react';
import CampusScene from '../components/3d/CampusScene';
import { IconAlert, IconCube, IconRefresh, IconRoad, IconSearch, IconTarget } from '../components/Icons';
import BuildingInspector from '../components/twin/BuildingInspector';
import CampusLegend from '../components/twin/CampusLegend';
import CampusOverview from '../components/twin/CampusOverview';
import LayerControls from '../components/twin/LayerControls';
import LiveEvents from '../components/twin/LiveEvents';
import RoutePanel from '../components/twin/RoutePanel';
import SensorInspector from '../components/twin/SensorInspector';
import SimControlPanel from '../components/twin/SimControlPanel';
import SystemStatus from '../components/twin/SystemStatus';
import TwinStatusBar from '../components/twin/TwinStatusBar';
import TwinToolbar from '../components/twin/TwinToolbar';
import { useCampus } from '../hooks/useCampus';
import { useTwinCamera } from '../hooks/useTwinCamera';
import { useTwinSelection } from '../hooks/useTwinSelection';
import { useTwinStore } from '../store/useTwinStore';
import { fmtNum, levelChip, scenarioLabel } from '../utils/colors';

const LOAD_STAGES = [
  'Connecting to backend…',
  'Loading campus model…',
  'Preparing 3D scene…',
] as const;

function TwinLoader() {
  const [stage, setStage] = useState(0);
  useEffect(() => {
    const t = window.setInterval(() => setStage((s) => (s + 1) % LOAD_STAGES.length), 1100);
    return () => window.clearInterval(t);
  }, []);

  return (
    <div className="h-full flex flex-col items-center justify-center gap-4 px-6" data-testid="twin-loader">
      <div className="w-12 h-12 rounded-full border-2 border-line-strong border-t-brand-400 animate-spin" aria-hidden="true" />
      <div className="text-center">
        <div className="text-[13px] font-bold tracking-[0.22em] text-white">INITIALIZING DIGITAL TWIN</div>
        <div className="text-[11.5px] text-mist-400 mt-1.5 num">{LOAD_STAGES[stage]}</div>
      </div>
    </div>
  );
}

function TwinErrorPanel({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="h-full flex items-center justify-center px-6" data-testid="twin-error">
      <div className="panel rounded-xl p-6 max-w-[420px] w-full text-center border-red-800/70">
        <div className="mx-auto w-11 h-11 rounded-full bg-red-950/70 border border-red-800 flex items-center justify-center">
          <IconAlert width={20} height={20} className="text-red-400" />
        </div>
        <h2 className="text-[14px] font-bold tracking-wide text-white mt-3">DIGITAL TWIN CONNECTION ERROR</h2>
        <p className="text-[12px] text-mist-400 mt-2 leading-relaxed">
          Live campus data is unavailable. The backend may be offline or still starting.
          The 3D scene cannot be trusted until the connection is restored.
        </p>
        <button className="btn btn-primary mt-4" onClick={onRetry} aria-label="Retry connection">
          <IconRefresh width={14} height={14} /> Retry Connection
        </button>
      </div>
    </div>
  );
}

export default function TwinExplorer() {
  const { snapshot, dataState, retry } = useCampus();
  const { openBuilding, clearSelection, inspectorMode, selectedBuilding, selectedBuildingId } = useTwinSelection();
  const selectBuilding = useTwinStore((s) => s.selectBuilding);
  const selectSensor = useTwinStore((s) => s.selectSensor);
  const { focusAt, focusSelected } = useTwinCamera();
  const [query, setQuery] = useState('');
  const [tab, setTab] = useState<'buildings' | 'roads' | 'exits' | 'routes' | 'live'>('buildings');
  // Phase 7 §17 — route panel + route slice
  const routePlan = useTwinStore((s) => s.routePlan);
  const evacuation = useTwinStore((s) => s.evacuation);
  const routePanelOpen = useTwinStore((s) => s.routePanelOpen);
  const setRoutePanelOpen = useTwinStore((s) => s.setRoutePanelOpen);
  const routesLayer = useTwinStore((s) => s.toggles.routes);
  const toggle = useTwinStore((s) => s.toggle);

  const buildings = useMemo(() => {
    const list = snapshot?.buildings ?? [];
    const q = query.trim().toLowerCase();
    return q
      ? list.filter((b) => b.name.toLowerCase().includes(q) || b.type.toLowerCase().includes(q))
      : list;
  }, [snapshot, query]);

  if (dataState === 'loading') return <TwinLoader />;
  if (dataState === 'error') return <TwinErrorPanel onRetry={retry} />;
  if (!snapshot) return <TwinLoader />;

  const exits = snapshot.nodes.filter((n) => n.is_exit);

  return (
    <div className="h-full flex min-h-0">
      {/* explorer rail */}
      <div className="w-[268px] shrink-0 border-r border-line bg-ink-900/70 flex flex-col min-h-0 max-md:hidden">
        <div className="p-3 border-b border-line">
          <div className="flex items-center gap-2 mb-2.5">
            <IconCube width={15} height={15} className="text-brand-400" />
            <span className="text-[13px] font-bold tracking-wide">3D TWIN EXPLORER</span>
          </div>
          <div className="relative">
            <IconSearch width={13} height={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-mist-500" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search buildings…"
              aria-label="Search buildings"
              className="w-full rounded-md bg-ink-850 border border-line pl-8 pr-3 py-2 text-[12.5px] outline-none focus:border-brand-500"
            />
          </div>
          <div className="flex gap-1.5 mt-2.5">
            {(['buildings', 'roads', 'exits', 'routes', 'live'] as const).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                aria-pressed={tab === t}
                className={`chip flex-1 justify-center ${tab === t ? 'border-brand-400 bg-brand-950/70 text-brand-200' : ''}`}
              >
                {t}
              </button>
            ))}
          </div>
        </div>

        <div className="flex-1 min-h-0 scroll-y p-2 space-y-1.5">
          {tab === 'buildings' && buildings.map((b) => (
            <button
              key={b.id}
              onClick={() => openBuilding(b.id)}
              aria-pressed={b.id === selectedBuildingId}
              className={`w-full text-left rounded-md border px-2.5 py-2 transition-colors ${
                b.id === selectedBuildingId
                  ? 'border-brand-500 bg-brand-950/40'
                  : 'border-line bg-ink-850 hover:border-line-strong'
              }`}
            >
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-sm shrink-0" style={{ background: b.color }} />
                <span className="text-[12.5px] font-semibold truncate flex-1">{b.name}</span>
                <span className={`chip !py-0 !px-1.5 !text-[9px] ${levelChip(b.risk_level)}`}>{b.risk.toFixed(0)}</span>
              </div>
              <div className="flex items-center justify-between mt-1 text-[10.5px] text-mist-500">
                <span className="capitalize">{b.type}</span>
                <span className="num">
                  {fmtNum(b.occupancy)}/{fmtNum(b.capacity)} · {b.occupancy_pct.toFixed(0)}% · {b.temperature.toFixed(1)}°C
                </span>
              </div>
            </button>
          ))}

          {tab === 'roads' && snapshot.roads.slice(0, 40).map((r) => (
            <div key={r.id} className="rounded-md border border-line bg-ink-850 px-2.5 py-2">
              <div className="flex items-center justify-between">
                <span className="text-[12px] font-semibold truncate">{r.name}</span>
                <span className={`chip !py-0 !px-1.5 !text-[9px] ${r.blocked ? 'border-red-700 text-red-300' : 'border-emerald-800 text-emerald-300'}`}>
                  {r.blocked ? 'BLOCKED' : r.kind}
                </span>
              </div>
              <div className="flex justify-between text-[10.5px] text-mist-500 mt-0.5">
                <span className="num">{r.length} m</span>
                <span className="num">congestion {(r.congestion * 100).toFixed(0)}% · risk {r.risk.toFixed(0)}</span>
              </div>
            </div>
          ))}

          {tab === 'exits' && exits.map((e) => {
            const routesHere = snapshot.routes.filter((r) => r.exit_id === e.id);
            const worst = routesHere.reduce((acc, r) => Math.max(acc, r.risk), 0);
            return (
              <button
                key={e.id}
                onClick={() => focusAt(e.x, e.z)}
                className="w-full text-left rounded-md border border-line bg-ink-850 hover:border-line-strong px-2.5 py-2"
              >
                <div className="flex items-center justify-between">
                  <span className="text-[12.5px] font-semibold">{e.name}</span>
                  <span className={`chip !py-0 !px-1.5 !text-[9px] ${levelChip(worst > 60 ? 'HIGH' : worst > 35 ? 'MODERATE' : 'LOW')}`}>
                    risk {worst.toFixed(0)}
                  </span>
                </div>
                <div className="text-[10.5px] text-mist-500 mt-0.5 num">
                  node {e.id} · {routesHere.length} routes · cap {e.exit_capacity ?? '—'}
                </div>
              </button>
            );
          })}

          {tab === 'routes' && (
            <div className="space-y-1.5" data-testid="routes-tab">
              <div className="rounded-md border border-line bg-ink-850 px-2.5 py-2">
                <div className="flex items-center justify-between">
                  <span className="text-[12.5px] font-semibold">Campus evacuation</span>
                  <span className={`chip !py-0 !px-1.5 !text-[9px] ${
                    evacuation?.status === 'CRITICAL' ? 'border-red-600 text-red-300'
                      : evacuation?.status === 'ACTIVE' ? 'border-orange-600 text-orange-300'
                        : evacuation?.status === 'STANDBY' ? 'border-amber-600 text-amber-300'
                          : 'border-emerald-700 text-emerald-300'}`}>
                    {evacuation?.status ?? 'IDLE'}
                  </span>
                </div>
                <div className="text-[10.5px] text-mist-500 mt-0.5 num">
                  {fmtNum(evacuation?.people_at_risk ?? 0)} at risk ·
                  {' '}{evacuation?.totals.safe_routes ?? 0}/{evacuation?.totals.buildings ?? 0} safe ·
                  {' '}{evacuation?.bottleneck_count ?? 0} bottlenecks
                </div>
              </div>

              <div className="rounded-md border border-line bg-ink-850 px-2.5 py-2">
                <div className="flex items-center justify-between">
                  <span className="text-[12.5px] font-semibold">Active route</span>
                  {routePlan && (
                    <span className={`chip !py-0 !px-1.5 !text-[9px] ${
                      routePlan.status === 'RECOMMENDED' ? 'border-emerald-700 text-emerald-300'
                        : routePlan.status === 'ALTERNATIVE' ? 'border-sky-700 text-sky-300'
                          : routePlan.status === 'NO_SAFE_ROUTE' || routePlan.status === 'BLOCKED'
                            ? 'border-red-600 text-red-300' : 'border-amber-600 text-amber-300'}`}>
                      {routePlan.status}
                    </span>
                  )}
                </div>
                {routePlan ? (
                  <div className="text-[10.5px] text-mist-500 mt-0.5 num">
                    {routePlan.origin ?? '?'} → {(routePlan.destination_name || routePlan.destination) ?? '?'}
                    {' · '}{routePlan.mode} · {routePlan.distance.toFixed(0)}m ·
                    {' '}v{routePlan.route_version}
                  </div>
                ) : (
                  <div className="text-[10.5px] text-mist-500 mt-0.5">
                    No plan yet — calculate a route or run an emergency drill.
                  </div>
                )}
              </div>

              <button
                className="btn btn-primary w-full !py-1.5"
                onClick={() => setRoutePanelOpen(true)}
                data-testid="open-route-panel"
              >
                <IconRoad width={12} height={12} /> Open route panel
              </button>
              {!routesLayer && (
                <button className="btn w-full !py-1" onClick={() => toggle('routes')}>
                  Show routes layer
                </button>
              )}
            </div>
          )}

          {tab === 'live' && (
            <div className="space-y-1.5" data-testid="live-tab">
              <SystemStatus />
              <LiveEvents />
            </div>
          )}

          {tab === 'buildings' && buildings.length === 0 && (
            <div className="text-[12px] text-mist-500 text-center py-6 border border-dashed border-line rounded-md">
              No buildings match “{query}”.
            </div>
          )}
        </div>

        <div className="p-3 border-t border-line">
          <CampusLegend />
          {snapshot.active_sim && (
            <div className="mt-2.5 text-[11px] text-mist-300 space-y-1.5">
              <div>
                Active: <b>{scenarioLabel(snapshot.active_sim.scenario)}</b> · {snapshot.active_sim.status}
              </div>
              {snapshot.active_sim.target_id && (
                <button
                  className="btn btn-danger w-full !py-1 !text-[11px]"
                  data-testid="focus-incident"
                  onClick={() => {
                    const id = snapshot.active_sim!.target_id!;
                    const b = snapshot.buildings.find((x) => x.id === id);
                    if (b) focusAt(b.position.x, b.position.z);
                    void selectBuilding(id);
                  }}
                >
                  <IconTarget width={12} height={12} /> Focus incident
                </button>
              )}
            </div>
          )}
        </div>
      </div>

      {/* viewport */}
      <div className="flex-1 relative min-w-0 min-h-0">
        <CampusScene />

        {/* view modes + layers + realtime controls */}
        <div className="absolute top-3 left-3 z-10 flex flex-col gap-2 items-start max-md:left-2 max-md:right-2">
          <TwinToolbar />
          <div className="max-md:hidden">
            <LayerControls />
          </div>
          <div className="max-md:hidden">
            <SimControlPanel />
          </div>
        </div>

        {/* persistent right inspector */}
        {inspectorMode === 'sensor' && (
          <SensorInspector onClose={() => selectSensor(null)} />
        )}
        {inspectorMode === 'building' && (
          <BuildingInspector onClose={() => { selectSensor(null); void selectBuilding(null); }} />
        )}
        {inspectorMode === 'campus' && !routePanelOpen && (
          <div className="absolute top-3 right-3 bottom-10 w-[335px] z-10 panel rounded-xl shadow-2xl shadow-black/60 overflow-hidden max-lg:w-[300px] max-sm:inset-x-2 max-sm:w-auto max-sm:bottom-14">
            <CampusOverview />
          </div>
        )}
        {/* Phase 7 §17 — route panel takes the right slot when opened
            (sensor/building inspectors keep priority) */}
        {routePanelOpen && inspectorMode !== 'sensor' && inspectorMode !== 'building' && (
          <RoutePanel onClose={() => setRoutePanelOpen(false)} />
        )}

        {/* orbit hint */}
        <div className="absolute bottom-10 left-3 z-10 panel rounded-md px-3 py-1.5 text-[11px] text-mist-400 max-md:hidden">
          Drag to orbit · scroll to zoom · click a building for detail
          {selectedBuilding && <span className="text-white font-semibold"> · {selectedBuilding.name} selected</span>}
        </div>

        <TwinStatusBar />
      </div>

      {/* focus helper on mobile */}
      <button
        className="md:hidden fixed bottom-20 right-4 z-20 btn btn-primary !rounded-full !px-3"
        onClick={() => { if (!focusSelected()) clearSelection(); }}
        title="Focus selected building"
        aria-label="Focus selected building"
      >
        <IconTarget width={16} height={16} />
      </button>
    </div>
  );
}
