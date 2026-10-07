import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import EventTimeline from '../components/dashboard/EventTimeline';
import {
  IconAlert, IconCheck, IconFire, IconPause, IconPlay, IconRefresh,
  IconRoad, IconTarget, IconThermo, IconUsers, IconX, IconZap,
} from '../components/Icons';
import { api } from '../services/api';
import { useTwinStore } from '../store/useTwinStore';
import type { ActiveSim, SimulationResults } from '../types';
import { fmtNum, scenarioIcon, scenarioLabel } from '../utils/colors';

const SCENARIOS = [
  { id: 'fire', icon: IconFire, desc: 'Ignition → smoke spread → zone damage → evacuation routing → response.', dur: 330, rec: 130 },
  { id: 'crowd', icon: IconUsers, desc: 'Occupancy surge until density threshold breached; throttling advice.', dur: 300, rec: 90 },
  { id: 'power', icon: IconZap, desc: 'Mains loss, backup pickup, thermal drift from offline HVAC.', dur: 240, rec: 110 },
  { id: 'road', icon: IconRoad, desc: 'Segment blocked; congestion redistributed; routes re-optimized.', dur: 300, rec: 80 },
  { id: 'temperature', icon: IconThermo, desc: 'Heat wave: cooling load surge, clinic standby, pre-cooling advice.', dur: 360, rec: 120 },
] as const;

type ScenarioId = (typeof SCENARIOS)[number]['id'];

/** Phase 6 §14 — UI exposes 1-5 with labels; engine accepts 1-10. */
const INTENSITY_LABELS: Record<number, string> = {
  1: 'LOW', 2: 'MODERATE', 3: 'HIGH', 4: 'SEVERE', 5: 'EXTREME',
};
const WIND_DIRS = ['NONE', 'N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];

const STATUS_TONE: Record<string, string> = {
  RUNNING: 'border-red-700 bg-red-950/60 text-red-300',
  PAUSED: 'border-amber-700 bg-amber-950/60 text-amber-300',
  AWAITING_RECOVERY: 'border-violet-700 bg-violet-950/60 text-violet-300',
  RECOVERING: 'border-sky-700 bg-sky-950/60 text-sky-300',
  COMPLETED: 'border-emerald-700 bg-emerald-950/60 text-emerald-300',
  CREATED: 'border-line-strong bg-ink-800 text-mist-300',
  RESET: 'border-line-strong bg-ink-800 text-mist-300',
};

export default function SimulationCenter() {
  const snapshot = useTwinStore((s) => s.snapshot);
  const user = useTwinStore((s) => s.user);
  const history = useTwinStore((s) => s.history);
  const pushToast = useTwinStore((s) => s.pushToast);
  const handleApiError = useTwinStore((s) => s.handleApiError);
  const refreshHistory = useTwinStore((s) => s.refreshHistory);
  const refreshAnalyst = useTwinStore((s) => s.refreshAnalyst);
  const realtime = useTwinStore((s) => s.realtime);
  const realtimeBusy = useTwinStore((s) => s.realtimeBusy);
  const setRealtimeSpeed = useTwinStore((s) => s.setRealtimeSpeed);
  const setDemo = useTwinStore((s) => s.setDemo);
  const [params, setParams] = useSearchParams();

  const [scenario, setScenario] = useState<ScenarioId>('fire');
  const [target, setTarget] = useState('eng');
  const [intensity, setIntensity] = useState(3);
  const [wind, setWind] = useState('E');
  const [zoneId, setZoneId] = useState('');
  const [occupancyInc, setOccupancyInc] = useState(40);
  const [roadId, setRoadId] = useState('r_cw_cc');
  const [busy, setBusy] = useState<string | null>(null);
  const [resultsId, setResultsId] = useState<string | null>(null);
  const [results, setResults] = useState<SimulationResults | null>(null);
  const [resultsLoading, setResultsLoading] = useState(false);

  const canSimulate = !!user && ['ADMIN', 'OPERATOR'].includes(user.role);
  const sim = snapshot?.active_sim ?? null;
  const canCreate = !sim || !['RUNNING', 'PAUSED', 'AWAITING_RECOVERY', 'RECOVERING'].includes(sim.status);

  useEffect(() => {
    const s = params.get('scenario');
    const b = params.get('building');
    if (s && SCENARIOS.some((x) => x.id === s)) setScenario(s as ScenarioId);
    if (b) setTarget(b);
    if (s || b) setParams({}, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const buildings = snapshot?.buildings ?? [];
  const roads = useMemo(
    () => (snapshot?.roads ?? []).filter((r) => !r.blocked).slice(0, 24),
    [snapshot],
  );
  const targetZones = useMemo(
    () => (snapshot?.zones ?? []).filter((z) => z.building_id === target),
    [snapshot, target],
  );

  // Phase 6 §48 — live results for the active/last run
  const loadResults = async (id: string) => {
    setResultsId(id);
    setResultsLoading(true);
    try {
      const res = await api.simulationResults(id);
      setResults(res.results);
    } catch (err) {
      setResults(null);
      handleApiError(err);
    } finally {
      setResultsLoading(false);
    }
  };

  useEffect(() => {
    if (sim?.status === 'COMPLETED' && sim.id !== resultsId) void loadResults(sim.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sim?.status, sim?.id]);

  const act = async (fn: () => Promise<ActiveSim>, label: string) => {
    setBusy(label);
    try {
      await fn();
      await refreshHistory();
      await refreshAnalyst();
      pushToast('success', label.toUpperCase(), 'Simulation state updated.');
    } catch (err) {
      handleApiError(err);
    } finally {
      setBusy(null);
    }
  };

  const create = () =>
    act(async () => {
      const p: Record<string, unknown> = {};
      if (scenario === 'fire') {
        p.intensity = intensity;
        p.wind = wind;
        if (zoneId) p.ignition_zone = zoneId;
      }
      if (scenario === 'crowd') p.occupancy_increase = occupancyInc;
      if (scenario === 'road') p.road_id = roadId;
      const created = await api.createSimulation(
        scenario,
        ['fire', 'crowd', 'power'].includes(scenario) ? target : null,
        p,
      );
      setResultsId(null);
      setResults(null);
      return api.simAction(created.id, 'start');
    }, 'created & started');

  const control = (action: 'start' | 'pause' | 'resume' | 'reset' | 'recover') => {
    if (!sim) return;
    act(() => api.simAction(sim.id, action), action);
  };

  const bestRoute = snapshot?.routes.find(
    (r) => r.building_id === (sim?.target_id ?? target) && r.exit_id,
  );

  return (
    <div className="h-full overflow-y-auto scroll-y p-4 space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-lg font-bold">Simulation Center</h1>
        <span className="chip border-brand-500/60 bg-brand-950/50 text-brand-300">WHAT-IF ENGINE</span>
        <span className="chip border-amber-700 bg-amber-950/60 text-amber-300" title="Phase 6 scenarios run on the emergency what-if engine with synthetic data">
          SIMULATED DATA
        </span>
        {sim && <span className={`chip ${STATUS_TONE[sim.status] ?? ''}`}>{sim.status}</span>}
        <div className="flex-1" />
        <button className="btn" onClick={() => setDemo(true)} title="Open the guided drill (runs a live fire scenario)">
          <IconPlay width={13} height={13} /> Demo drill
        </button>
        <Link to="/twin" className="btn">
          <IconTarget width={13} height={13} /> Watch in 3D
        </Link>
      </div>

      <div className="grid xl:grid-cols-[440px_1fr] gap-4 items-start">
        {/* scenario picker + config */}
        <div className="space-y-4">
          <div className="panel rounded-xl p-4">
            <div className="label-cap mb-2.5">1 · Choose scenario</div>
            <div className="grid grid-cols-1 gap-2">
              {SCENARIOS.map((s) => (
                <button
                  key={s.id}
                  onClick={() => setScenario(s.id)}
                  disabled={!canCreate}
                  className={`text-left rounded-lg border px-3 py-2.5 transition-colors disabled:opacity-50 ${
                    scenario === s.id ? 'border-brand-500 bg-brand-950/40' : 'border-line bg-ink-850 hover:border-line-strong'
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <s.icon width={15} height={15} className={scenario === s.id ? 'text-brand-400' : 'text-mist-500'} />
                    <span className="font-semibold text-[13px]">{scenarioLabel(s.id)}</span>
                    <span className="ml-auto num text-[10.5px] text-mist-500">{s.dur}s + {s.rec}s rec</span>
                  </div>
                  <p className="text-[11.5px] text-mist-400 mt-1 leading-snug">{s.desc}</p>
                </button>
              ))}
            </div>
          </div>

          <div className="panel rounded-xl p-4">
            <div className="label-cap mb-3">2 · Configure parameters</div>

            {['fire', 'crowd', 'power'].includes(scenario) && (
              <label className="block mb-3">
                <span className="label-cap">Target building</span>
                <select
                  value={target}
                  onChange={(e) => setTarget(e.target.value)}
                  disabled={!canCreate}
                  className="mt-1 w-full rounded-md bg-ink-900 border border-line px-3 py-2 text-[13px] outline-none focus:border-brand-500 disabled:opacity-50"
                >
                  {buildings.map((b) => (
                    <option key={b.id} value={b.id}>
                      {b.name} — {b.type} ({b.occupancy_pct.toFixed(0)}% full)
                    </option>
                  ))}
                </select>
              </label>
            )}

            {scenario === 'fire' && (
              <div className="space-y-3">
                <label className="block">
                  <div className="flex justify-between">
                    <span className="label-cap">Ignition intensity</span>
                    <span className="num text-[12px] text-orange-300">
                      {intensity}/5 · {INTENSITY_LABELS[intensity]}
                    </span>
                  </div>
                  <input
                    type="range" min={1} max={5} value={intensity}
                    disabled={!canCreate}
                    onChange={(e) => setIntensity(Number(e.target.value))}
                    className="w-full mt-1 accent-orange-500"
                  />
                </label>
                <label className="block">
                  <span className="label-cap">Wind direction</span>
                  <div className="grid grid-cols-3 gap-1.5 mt-1">
                    {WIND_DIRS.map((w) => (
                      <button
                        key={w}
                        onClick={() => setWind(w)}
                        disabled={!canCreate}
                        className={`chip flex-1 justify-center ${wind === w ? 'border-brand-400 bg-brand-950/70 text-brand-200' : ''}`}
                      >
                        {w}
                      </button>
                    ))}
                  </div>
                </label>
                <label className="block">
                  <span className="label-cap">Ignition zone</span>
                  <select
                    value={zoneId}
                    disabled={!canCreate}
                    onChange={(e) => setZoneId(e.target.value)}
                    className="mt-1 w-full rounded-md bg-ink-900 border border-line px-3 py-2 text-[13px] outline-none focus:border-brand-500 disabled:opacity-50"
                  >
                    <option value="">Auto — first zone of the building</option>
                    {targetZones.map((z) => (
                      <option key={z.id} value={z.id}>
                        {z.name} — {z.kind} (cap {z.capacity})
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            )}

            {scenario === 'crowd' && (
              <label className="block">
                <div className="flex justify-between">
                  <span className="label-cap">Occupancy increase</span>
                  <span className="num text-[12px] text-amber-300">+{occupancyInc}%</span>
                </div>
                <input
                  type="range" min={10} max={120} step={10} value={occupancyInc}
                  disabled={!canCreate}
                  onChange={(e) => setOccupancyInc(Number(e.target.value))}
                  className="w-full mt-1 accent-amber-500"
                />
                <p className="text-[11px] text-mist-500 mt-1">
                  {occupancyInc >= 100 ? 'Will exceed capacity — overload event expected.' : 'Triggers density warning at 85% capacity.'}
                </p>
              </label>
            )}

            {scenario === 'road' && (
              <label className="block">
                <span className="label-cap">Road segment to close</span>
                <select
                  value={roadId}
                  onChange={(e) => setRoadId(e.target.value)}
                  disabled={!canCreate}
                  className="mt-1 w-full rounded-md bg-ink-900 border border-line px-3 py-2 text-[13px] outline-none focus:border-brand-500"
                >
                  {roads.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name} — {r.length}m, cong {(r.congestion * 100).toFixed(0)}%
                    </option>
                  ))}
                </select>
              </label>
            )}

            {scenario === 'temperature' && (
              <p className="text-[12px] text-mist-400 leading-relaxed border border-dashed border-line rounded-md p-3">
                Campus-wide heat event — no target required. Duration 360s virtual; triggers clinic
                standby at T+60 and pre-cooling recommendations.
              </p>
            )}

            <button
              className="btn btn-primary w-full mt-4 !py-2.5"
              disabled={!canSimulate || !canCreate || busy !== null}
              onClick={() => void create()}
              title={canSimulate ? 'Create and start' : 'Requires OPERATOR/ADMIN role'}
            >
              <IconPlay width={14} height={14} />
              {busy ? 'Working…' : canCreate ? `START ${scenarioLabel(scenario).toUpperCase()}` : 'Simulation active'}
            </button>
            {!canSimulate && (
              <p className="text-[11px] text-amber-300 mt-2">
                Signed in as {user?.role} — simulation control requires OPERATOR or ADMIN.
              </p>
            )}
          </div>
        </div>

        {/* live console */}
        <div className="space-y-4">
          <div className="panel rounded-xl p-4">
            <div className="flex items-center gap-3 flex-wrap mb-3">
              <span className="label-cap">Live console</span>
              {sim ? (
                <>
                  <span className="text-[13.5px] font-bold">{scenarioIcon(sim.scenario)} {scenarioLabel(sim.scenario)}</span>
                  <span className={`chip ${STATUS_TONE[sim.status] ?? ''}`}>{sim.status}</span>
                  <span className="chip border-line-strong bg-ink-800 text-mist-300">{sim.phase}</span>
                  <span className="num text-[11px] text-mist-500">id {sim.id}</span>
                </>
              ) : (
                <span className="text-[13px] text-mist-400">No simulation running — pick a scenario on the left.</span>
              )}
            </div>

            {sim && (
              <>
                <div className="h-2 rounded-full bg-ink-700 overflow-hidden">
                  <div
                    className={`h-full transition-all duration-500 ${
                      sim.status === 'RECOVERING'
                        ? 'bg-gradient-to-r from-sky-600 to-emerald-500'
                        : 'bg-gradient-to-r from-orange-500 to-red-500'
                    }`}
                    style={{ width: `${sim.status === 'RECOVERING' ? snapshot?.recovery_progress ?? 0 : sim.progress}%` }}
                  />
                </div>
                <div className="flex justify-between text-[11px] text-mist-500 mt-1 num">
                  <span>
                    {sim.status === 'RECOVERING'
                      ? `recovery ${(snapshot?.recovery_progress ?? 0).toFixed(0)}%`
                      : `T+${sim.t.toFixed(0)}s of ${sim.duration}s`}
                  </span>
                  <span>peak risk {sim.peak_risk.toFixed(0)}</span>
                </div>

                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-3">
                  <div className="rounded-md border border-line bg-ink-850 p-2.5">
                    <div className="label-cap">People at risk</div>
                    <div className={`num text-lg font-bold ${sim.people_at_risk > 0 ? 'text-red-400' : 'text-emerald-400'}`}>
                      {fmtNum(sim.people_at_risk)}
                    </div>
                  </div>
                  <div className="rounded-md border border-line bg-ink-850 p-2.5">
                    <div className="label-cap">Campus risk</div>
                    <div className={`num text-lg font-bold ${snapshot && snapshot.risk.score > 60 ? 'text-red-400' : 'text-amber-300'}`}>
                      {sim.risk ?? snapshot?.risk.score.toFixed(0) ?? '—'}
                    </div>
                  </div>
                  <div className="rounded-md border border-line bg-ink-850 p-2.5">
                    <div className="label-cap">Active alerts</div>
                    <div className="num text-lg font-bold">{snapshot?.alerts.length ?? 0}</div>
                  </div>
                  <div className="rounded-md border border-line bg-ink-850 p-2.5">
                    <div className="label-cap">Events</div>
                    <div className="num text-lg font-bold">{sim.events.length}</div>
                  </div>
                  <div className="rounded-md border border-line bg-ink-850 p-2.5">
                    <div className="label-cap">Affected zones</div>
                    <div className={`num text-lg font-bold ${(sim.affected_zones ?? 0) > 0 ? 'text-orange-300' : 'text-emerald-400'}`}>
                      {sim.affected_zones ?? '—'}
                    </div>
                  </div>
                  <div className="rounded-md border border-line bg-ink-850 p-2.5">
                    <div className="label-cap">Peak temp</div>
                    <div className="num text-lg font-bold text-orange-300">
                      {(sim.peak_temperature ?? sim.building_temperature ?? 24).toFixed(1)}°C
                    </div>
                  </div>
                  <div className="rounded-md border border-line bg-ink-850 p-2.5">
                    <div className="label-cap">Building smoke</div>
                    <div className={`num text-lg font-bold ${(sim.building_smoke ?? 0) > 30 ? 'text-red-400' : 'text-mist-200'}`}>
                      {sim.building_smoke ?? sim.peak_smoke ?? 0}
                    </div>
                  </div>
                  <div className="rounded-md border border-line bg-ink-850 p-2.5">
                    <div className="label-cap">Sim speed</div>
                    <div className="num text-lg font-bold text-brand-300">{sim.speed ?? realtime?.speed ?? 1}x</div>
                  </div>
                </div>

                <div className="flex flex-wrap gap-2 mt-3.5">
                  {['CREATED', 'PAUSED', 'RESET'].includes(sim.status) && (
                    <button className="btn btn-primary" disabled={!canSimulate || !!busy} onClick={() => control('start')}>
                      <IconPlay width={13} height={13} /> {sim.status === 'PAUSED' ? 'Resume' : 'Start'}
                    </button>
                  )}
                  {sim.status === 'RUNNING' && (
                    <button className="btn btn-danger" disabled={!canSimulate || !!busy} onClick={() => control('pause')}>
                      <IconPause width={13} height={13} /> Pause
                    </button>
                  )}
                  {sim.status === 'AWAITING_RECOVERY' && (
                    <button className="btn btn-primary" disabled={!canSimulate || !!busy} onClick={() => control('recover')}>
                      <IconRefresh width={13} height={13} /> Recover System
                    </button>
                  )}
                  {sim.status === 'RECOVERING' && (
                    <span className="chip border-sky-700 bg-sky-950/60 text-sky-300">
                      Recovery {(snapshot?.recovery_progress ?? 0).toFixed(0)}% — automatic
                    </span>
                  )}
                  <button className="btn" disabled={!canSimulate || !!busy} onClick={() => control('reset')}>
                    <IconX width={13} height={13} /> Reset
                  </button>
                  <div className="flex items-center gap-1.5 ml-auto">
                    <span className="label-cap">Speed</span>
                    {[0.5, 1, 2, 4].map((sp) => (
                      <button
                        key={sp}
                        disabled={realtimeBusy}
                        onClick={() => void setRealtimeSpeed(sp)}
                        className={`chip num ${ (realtime?.speed ?? 1) === sp ? 'border-brand-400 bg-brand-950/70 text-brand-200' : ''}`}
                      >
                        {sp}x
                      </button>
                    ))}
                  </div>
                </div>

                {bestRoute && sim.scenario === 'fire' && (
                  <div className="mt-3.5 rounded-md border border-emerald-800/70 bg-emerald-950/30 p-3">
                    <div className="flex items-center gap-2">
                      <IconCheck width={14} height={14} className="text-emerald-400" />
                      <span className="label-cap text-emerald-300">Optimal evacuation route</span>
                    </div>
                    <div className="text-[12.5px] mt-1">
                      <b>{bestRoute.building_name}</b> → <b>{bestRoute.exit_name}</b>
                      {' · '}<span className="num">{bestRoute.evac_time_s.toFixed(0)}s</span>
                      {' · '}<span className="num">{bestRoute.distance.toFixed(0)}m</span>
                      {' · '}risk <span className="num">{bestRoute.risk.toFixed(0)}</span>
                    </div>
                    <p className="text-[11.5px] text-emerald-200/70 mt-1">{bestRoute.reason}</p>
                  </div>
                )}
              </>
            )}
          </div>

          {/* Phase 6 §48 — results block */}
          {resultsId && (
            <div className="panel rounded-xl p-4">
              <div className="flex items-center gap-2 mb-2.5">
                <span className="label-cap">Results — {resultsId.slice(0, 12)}…</span>
                <button className="chip ml-auto" onClick={() => { setResultsId(null); setResults(null); }}>
                  <IconX width={11} height={11} /> Close
                </button>
              </div>
              {resultsLoading && <div className="text-[12px] text-mist-500">Loading results…</div>}
              {!resultsLoading && !results && (
                <div className="text-[12px] text-mist-500 border border-dashed border-line rounded-md p-4 text-center">
                  No results recorded for this simulation.
                </div>
              )}
              {!resultsLoading && results && (
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                  {[
                    ['Peak risk', `${Math.round(results.peak_risk ?? 0)}${results.peak_risk_level ? ` (${results.peak_risk_level})` : ''}`],
                    ['Peak people at risk', fmtNum(results.peak_people_at_risk ?? results.weighted_people_at_risk ?? 0)],
                    ['Weighted exposure', fmtNum(results.weighted_people_at_risk ?? 0)],
                    ['Affected zones', String(results.affected_zone_count ?? 0)],
                    ['Peak temperature', `${(results.peak_temperature ?? 0).toFixed(1)}°C`],
                    ['Peak smoke', `${Math.round(results.peak_smoke ?? 0)} · ${results.smoke_band ?? '—'}`],
                    ['Duration', results.duration_s != null ? `${results.duration_s.toFixed(0)}s` : '—'],
                    ['Recovery', results.recovery_time_s != null ? `${results.recovery_time_s.toFixed(0)}s` : '—'],
                    ['Events', String(results.events ?? 0)],
                    ['Intensity', results.intensity != null ? `${results.intensity}${results.intensity_label ? ` · ${results.intensity_label}` : ''}` : '—'],
                    ['Wind', results.wind ?? '—'],
                    ['Status', results.status ?? '—'],
                  ].map(([k, v]) => (
                    <div key={k} className="rounded-md border border-line bg-ink-850 p-2.5">
                      <div className="label-cap">{k}</div>
                      <div className="num text-[15px] font-bold">{v}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          <div className="grid lg:grid-cols-2 gap-4">
            <div className="panel rounded-xl overflow-hidden h-[320px]">
              <EventTimeline />
            </div>

            <div className="panel rounded-xl p-4">
              <div className="label-cap mb-2.5">Recent simulations</div>
              <div className="space-y-1.5 max-h-[270px] scroll-y pr-1">
                {history.length === 0 && (
                  <div className="text-[12px] text-mist-500 border border-dashed border-line rounded-md p-4 text-center">
                    Nothing yet. Completed drills appear here with peak risk and recovery time.
                  </div>
                )}
                {history.slice(0, 8).map((h) => (
                  <button
                    key={h.id}
                    onClick={() => void loadResults(h.id)}
                    className="w-full text-left rounded-md border border-line bg-ink-850 px-2.5 py-2 flex items-center gap-2 hover:border-brand-500/60 transition-colors"
                    title="View results"
                  >
                    <span className="text-sm">{scenarioIcon(h.scenario)}</span>
                    <div className="min-w-0 flex-1">
                      <div className="text-[12px] font-semibold truncate">{scenarioLabel(h.scenario)}</div>
                      <div className="text-[10.5px] text-mist-500 num">
                        {new Date(h.created_at).toLocaleString()} · peak {h.peak_risk.toFixed(0)} · {h.status}
                      </div>
                    </div>
                    <span className={`chip !text-[9px] ${
                      h.severity === 'CRITICAL' || h.severity === 'HIGH' ? 'border-red-700 text-red-300'
                        : h.severity === 'MEDIUM' ? 'border-amber-700 text-amber-300'
                          : 'border-emerald-700 text-emerald-300'
                    }`}>{h.severity}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>

          {(snapshot?.alerts.length ?? 0) > 0 && (
            <div className="panel rounded-xl p-4">
              <div className="label-cap mb-2">Active alerts</div>
              <div className="space-y-1.5">
                {snapshot?.alerts.map((a) => (
                  <div key={a.id} className="flex items-start gap-2 text-[12px]">
                    <IconAlert width={13} height={13} className={
                      a.level === 'CRITICAL' ? 'text-red-400 mt-0.5' : 'text-amber-300 mt-0.5'
                    } />
                    <b className="shrink-0">{a.title}</b>
                    <span className="text-mist-300">{a.message}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
