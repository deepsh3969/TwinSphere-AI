import { useEffect, useMemo, useState } from 'react';
import { api } from '../../services/api';
import { useTwinStore } from '../../store/useTwinStore';
import type { RouteMode } from '../../types';
import { fmtNum } from '../../utils/colors';
import { routeModeColor, routeSafetyColor, severityChip } from '../../utils/colors';
import { IconAlert, IconCheck, IconHistory, IconRefresh, IconRoad, IconTarget, IconX } from '../Icons';
import RouteLegend from './RouteLegend';

const MODES: RouteMode[] = ['shortest', 'fastest', 'safest', 'balanced'];

function fmtEta(seconds: number): string {
  if (!seconds || seconds <= 0) return '—';
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m > 0 ? `${m}m ${String(s).padStart(2, '0')}s` : `${s}s`;
}

function planStatusChip(status: string): string {
  switch (status) {
    case 'RECOMMENDED': return 'border-emerald-700 bg-emerald-950/70 text-emerald-300';
    case 'ALTERNATIVE': return 'border-sky-700 bg-sky-950/70 text-sky-300';
    case 'NO_SAFE_ROUTE':
    case 'BLOCKED': return 'border-red-600 bg-red-950/70 text-red-300';
    case 'NOT_RECOMMENDED': return 'border-amber-600 bg-amber-950/70 text-amber-300';
    default: return 'border-line-strong text-mist-400';
  }
}

function evacStatusChip(status: string): string {
  switch (status) {
    case 'CRITICAL': return 'border-red-600 bg-red-950/70 text-red-300';
    case 'ACTIVE': return 'border-orange-600 bg-orange-950/70 text-orange-300';
    case 'STANDBY': return 'border-amber-600 bg-amber-950/70 text-amber-300';
    default: return 'border-emerald-700 bg-emerald-950/70 text-emerald-300';
  }
}

/**
 * Phase 7 §17/§41 — route & evacuation control panel.
 * Rendered as a right-side overlay (onClose provided) or embedded block
 * (TwinExplorer routes tab). All data flows through the store (WS-fed).
 */
export default function RoutePanel({ onClose }: { onClose?: () => void }) {
  const snapshot = useTwinStore((s) => s.snapshot);
  const plan = useTwinStore((s) => s.routePlan);
  const alternatives = useTwinStore((s) => s.routeAlternatives);
  const buildingEvac = useTwinStore((s) => s.buildingEvacuation);
  const evacuation = useTwinStore((s) => s.evacuation);
  const bottlenecks = useTwinStore((s) => s.routeBottlenecks);
  const emergencyRoutes = useTwinStore((s) => s.emergencyRoutes);
  const routeHistory = useTwinStore((s) => s.routeHistory);
  const routeLoading = useTwinStore((s) => s.routeLoading);
  const routeError = useTwinStore((s) => s.routeError);
  const {
    refreshRouteData, calculateRoute, loadRouteAlternatives,
    loadBuildingEvacuation, loadEmergencyRoutes, refreshRouteHistory,
  } = useTwinStore.getState();

  const nodeOptions = useMemo(() => {
    const nodes = snapshot?.nodes ?? [];
    const gates = nodes.filter((n) => n.kind === 'GATE' || (n.is_exit && n.kind !== 'EXIT'));
    const exits = nodes.filter((n) => n.kind === 'EXIT');
    return { gates: gates.length ? gates : nodes.filter((n) => n.is_exit), exits };
  }, [snapshot]);

  const [origin, setOrigin] = useState('');
  const [destination, setDestination] = useState('');
  const [mode, setMode] = useState<RouteMode>(plan?.mode ?? 'balanced');
  const [buildingId, setBuildingId] = useState('eng');

  useEffect(() => {
    if (!origin && nodeOptions.exits[0]) setOrigin(nodeOptions.exits[0].id);
    if (!destination && nodeOptions.gates[0]) setDestination(nodeOptions.gates[0].id);
  }, [nodeOptions, origin, destination]);

  useEffect(() => {
    if (!useTwinStore.getState().evacuation) void refreshRouteData();
  }, [refreshRouteData]);

  useEffect(() => {
    if (plan?.mode) setMode(plan.mode);
  }, [plan?.mode]);

  const nodes = snapshot?.nodes ?? [];
  const nodeLabel = (id: string) => nodes.find((n) => n.id === id)?.name ?? id;
  const canCalculate = Boolean(origin && destination) && origin !== destination;

  const onCalculate = () => {
    if (canCalculate) void calculateRoute(origin, destination, mode);
  };
  const onAlternatives = () => {
    if (canCalculate) void loadRouteAlternatives(origin, destination, mode);
  };
  const onRecalculate = async () => {
    try {
      await api.routeRecalculate({ mode });
      await refreshRouteData();
    } catch { /* routeError surfaces via calculate path */ }
  };

  const body = (
    <div className="flex-1 min-h-0 scroll-y px-3.5 py-3 space-y-4">
      {/* evacuation status strip */}
      <div className="rounded-md border border-line bg-ink-850 p-2.5">
        <div className="flex items-center justify-between mb-1.5">
          <span className="label-cap text-mist-500">Campus evacuation</span>
          <span className={`chip ${evacStatusChip(evacuation?.status ?? 'IDLE')}`}>
            {evacuation?.status ?? 'IDLE'}
          </span>
        </div>
        <div className="grid grid-cols-4 gap-1.5 text-center">
          {[
            ['At risk', fmtNum(evacuation?.people_at_risk ?? 0)],
            ['Safe', `${evacuation?.totals.safe_routes ?? 0}/${evacuation?.totals.buildings ?? 0}`],
            ['Blocked', fmtNum(evacuation?.totals.blocked_routes ?? 0)],
            ['Bottlenecks', fmtNum(evacuation?.bottleneck_count ?? 0)],
          ].map(([label, value]) => (
            <div key={label}>
              <div className="num text-[13px] font-bold text-brand-200">{value}</div>
              <div className="label-cap text-mist-600 text-[8.5px]">{label}</div>
            </div>
          ))}
        </div>
      </div>

      {/* calculator */}
      <div className="rounded-md border border-line bg-ink-850 p-2.5 space-y-2">
        <div className="flex items-center justify-between">
          <span className="label-cap text-mist-500">Route calculator (A*)</span>
          <button className="btn !px-2 !py-1" onClick={() => void refreshRouteData()}
                  title="Refresh route data" disabled={routeLoading}>
            <IconRefresh width={12} height={12} />
          </button>
        </div>
        <label className="block">
          <span className="label-cap text-mist-600">Origin</span>
          <select className="mt-0.5 w-full bg-ink-800 border border-line rounded px-2 py-1.5
                             text-[11.5px] text-mist-200"
                  value={origin} onChange={(e) => setOrigin(e.target.value)}>
            <optgroup label="Building exits">
              {nodeOptions.exits.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}
            </optgroup>
            <optgroup label="Gates & assembly">
              {nodeOptions.gates.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}
            </optgroup>
          </select>
        </label>
        <label className="block">
          <span className="label-cap text-mist-600">Destination</span>
          <select className="mt-0.5 w-full bg-ink-800 border border-line rounded px-2 py-1.5
                             text-[11.5px] text-mist-200"
                  value={destination} onChange={(e) => setDestination(e.target.value)}>
            <optgroup label="Gates & assembly">
              {nodeOptions.gates.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}
            </optgroup>
            <optgroup label="Building exits">
              {nodeOptions.exits.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}
            </optgroup>
          </select>
        </label>
        <div className="flex flex-wrap gap-1">
          {MODES.map((m) => (
            <button key={m} className={`chip ${mode === m ? 'border-brand-400 bg-brand-950/70 text-brand-200' : ''}`}
                    aria-pressed={mode === m} onClick={() => setMode(m)}>
              {m}
            </button>
          ))}
        </div>
        <div className="flex gap-1.5">
          <button className="btn btn-primary flex-1 !py-1.5" onClick={onCalculate}
                  disabled={!canCalculate || routeLoading}>
            <IconTarget width={12} height={12} /> Calculate
          </button>
          <button className="btn flex-1 !py-1.5" onClick={onAlternatives}
                  disabled={!canCalculate || routeLoading}>
            Compare
          </button>
        </div>
        {routeError && (
          <div className="text-[10.5px] text-red-400">{routeError}</div>
        )}
      </div>

      {/* active plan */}
      <div className="rounded-md border border-line bg-ink-850 p-2.5 space-y-2">
        <div className="flex items-center justify-between">
          <span className="label-cap text-mist-500">Active route</span>
          {plan && (
            <span className={`chip ${planStatusChip(plan.status)}`}>{plan.status}</span>
          )}
        </div>
        {!plan ? (
          <div className="text-[11px] text-mist-500">
            No active plan — calculate a route or start an emergency simulation.
          </div>
        ) : (
          <>
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="chip border-line-strong text-mist-300"
                    style={{ color: routeModeColor(plan.mode), borderColor: routeModeColor(plan.mode) }}>
                {plan.mode}
              </span>
              <span className="text-[11px] text-mist-300">
                {plan.origin ? nodeLabel(plan.origin) : '?'}
                {' → '}
                {plan.destination_name || (plan.destination ? nodeLabel(plan.destination) : '?')}
              </span>
              <span className="chip" style={{
                color: routeSafetyColor(String(plan.safety)),
                borderColor: routeSafetyColor(String(plan.safety)),
              }}>
                {String(plan.safety)}
              </span>
              <span className="text-[9.5px] text-mist-600 num">v{plan.route_version}</span>
            </div>
            <div className="grid grid-cols-4 gap-1.5 text-center">
              {[
                ['Distance', `${fmtNum(plan.distance)}m`],
                ['ETA', fmtEta(plan.estimated_time)],
                ['Risk', fmtNum(plan.risk_score, 1)],
                ['Congestion', plan.congestion_label],
              ].map(([label, value]) => (
                <div key={label}>
                  <div className="num text-[12.5px] font-bold text-brand-200">{value}</div>
                  <div className="label-cap text-mist-600 text-[8.5px]">{label}</div>
                </div>
              ))}
            </div>
            {plan.people_at_risk > 0 && (
              <div className="text-[10.5px] text-amber-300">
                {fmtNum(plan.people_at_risk)} people at risk on this plan
              </div>
            )}
            {plan.reason && (
              <div className="text-[10.5px] text-mist-400 leading-snug">{plan.reason}</div>
            )}
            {plan.alternatives.length > 0 && (
              <div className="space-y-1">
                <span className="label-cap text-mist-600">
                  Alternatives ({plan.alternatives.length})
                </span>
                {plan.alternatives.slice(0, 3).map((alt, i) => (
                  <div key={i} className="flex items-center justify-between text-[10.5px]
                                          border-t border-line/60 pt-1">
                    <span className="text-mist-400 truncate">
                      {alt.destination_name || alt.destination || 'alt'} · {alt.status}
                    </span>
                    <span className="num text-mist-300 shrink-0 ml-2">
                      {fmtNum(alt.distance)}m · {fmtEta(alt.estimated_time)} · risk {fmtNum(alt.risk_score)}
                    </span>
                  </div>
                ))}
              </div>
            )}
            <div className="flex gap-1.5">
              <button className="btn flex-1 !py-1" onClick={() => void onRecalculate()}
                      disabled={routeLoading}>
                <IconRefresh width={12} height={12} /> Recalculate
              </button>
            </div>
          </>
        )}

        {alternatives && (
          <div className="border-t border-line/70 pt-2 space-y-1">
            <span className="label-cap text-mist-600">Cross-mode comparison</span>
            <table className="w-full text-[10px]">
              <thead>
                <tr className="text-mist-600 text-left">
                  <th className="label-cap font-normal">Mode</th>
                  <th className="label-cap font-normal text-right">Dist</th>
                  <th className="label-cap font-normal text-right">ETA</th>
                  <th className="label-cap font-normal text-right">Risk</th>
                </tr>
              </thead>
              <tbody>
                {alternatives.comparison.rows.map((row) => (
                  <tr key={row.mode}
                      className={`border-t border-line/50 ${row.recommended ? 'text-brand-200' : 'text-mist-400'}`}>
                    <td className="py-0.5 flex items-center gap-1">
                      <span className="inline-block w-2 h-2 rounded-sm"
                            style={{ background: routeModeColor(row.mode) }} />
                      {row.mode}
                      {row.recommended && <IconCheck width={10} height={10} />}
                    </td>
                    <td className="text-right num">{fmtNum(row.distance)}m</td>
                    <td className="text-right num">{fmtEta(row.estimated_time)}</td>
                    <td className="text-right num">{fmtNum(row.risk_score)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* per-building evacuation (§15) */}
      <div className="rounded-md border border-line bg-ink-850 p-2.5 space-y-2">
        <span className="label-cap text-mist-500">Building evacuation plans</span>
        <div className="flex gap-1.5">
          <select className="flex-1 bg-ink-800 border border-line rounded px-2 py-1
                             text-[11.5px] text-mist-200"
                  value={buildingId} onChange={(e) => setBuildingId(e.target.value)}>
            {(evacuation?.buildings ?? []).map((b) => (
              <option key={b.building_id} value={b.building_id}>{b.building_name}</option>
            ))}
            {!evacuation?.buildings.length && (
              <>
                <option value="eng">Engineering</option>
                <option value="cs">Computer Science</option>
                <option value="lib">Library</option>
              </>
            )}
          </select>
          <button className="btn !py-1" onClick={() => void loadBuildingEvacuation(buildingId, mode)}
                  disabled={routeLoading}>
            <IconRoad width={12} height={12} /> Plan
          </button>
        </div>
        {buildingEvac && (
          <div className="space-y-1.5 border-t border-line/60 pt-1.5">
            <div className="flex items-center justify-between text-[11px]">
              <span className="text-mist-300">{buildingEvac.building_name}</span>
              <span className={`chip ${
                buildingEvac.status === 'EVACUATION_CRITICAL'
                  ? 'border-red-600 bg-red-950/70 text-red-300'
                  : 'border-emerald-700 bg-emerald-950/70 text-emerald-300'}`}>
                {buildingEvac.status}
              </span>
            </div>
            <div className="text-[10.5px] text-mist-400">
              Primary exit: <span className="text-brand-200">{buildingEvac.primary_exit || '—'}</span>
              {buildingEvac.secondary_exit && (
                <> · Secondary: <span className="text-brand-200">{buildingEvac.secondary_exit}</span></>
              )}
            </div>
            <div className="text-[10.5px] text-mist-400 num">
              {fmtNum(buildingEvac.people_at_risk)} at risk ·
              {' '}{fmtEta(buildingEvac.estimated_evacuation_s)} ·
              {' '}risk {fmtNum(buildingEvac.route_risk, 1)}
            </div>
            <div className="flex flex-wrap gap-1">
              {buildingEvac.exits.map((e) => (
                <span key={e.id} className={`chip !text-[9px] ${
                  e.role === 'PRIMARY' ? 'border-emerald-700 text-emerald-300'
                    : e.role === 'SECONDARY' ? 'border-sky-700 text-sky-300'
                      : 'border-red-800 text-red-400'}`}>
                  {e.name} · {e.role.toLowerCase()}
                </span>
              ))}
            </div>
            {!buildingEvac.has_safe_route && buildingEvac.reason && (
              <div className="text-[10.5px] text-red-400 flex items-start gap-1">
                <IconAlert width={11} height={11} className="mt-0.5 shrink-0" />
                {buildingEvac.reason}
              </div>
            )}
          </div>
        )}
      </div>

      {/* bottlenecks (§13) */}
      <div className="rounded-md border border-line bg-ink-850 p-2.5 space-y-1.5">
        <span className="label-cap text-mist-500">Bottlenecks</span>
        {!bottlenecks.length ? (
          <div className="text-[11px] text-mist-500">No capacity bottlenecks detected.</div>
        ) : bottlenecks.map((b) => (
          <div key={b.location_id} className="border-t border-line/60 pt-1.5 space-y-0.5">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] text-mist-200 truncate">{b.location}</span>
              <span className={`chip !text-[9px] shrink-0 ${severityChip(b.severity)}`}>
                {b.severity} · {b.kind}
              </span>
            </div>
            <div className="text-[10px] text-mist-400 num">
              {fmtNum(b.estimated_people)} people / {fmtNum(b.capacity)} capacity
              {' · '}{b.congestion.toFixed(2)} cong
            </div>
            <div className="text-[10px] text-mist-500">{b.recommendation}</div>
          </div>
        ))}
      </div>

      {/* emergency vehicle routes (§16) */}
      <div className="rounded-md border border-line bg-ink-850 p-2.5 space-y-1.5">
        <div className="flex items-center justify-between">
          <span className="label-cap text-mist-500">Emergency response</span>
          <button className="btn !px-2 !py-1" onClick={() => void loadEmergencyRoutes()}>
            Dispatch
          </button>
        </div>
        {!emergencyRoutes.length ? (
          <div className="text-[11px] text-mist-500">
            No incident target — start a simulation or pick a destination.
          </div>
        ) : emergencyRoutes.map((r) => (
          <div key={`${r.vehicle}-${r.destination}`} className="border-t border-line/60 pt-1.5
                                                                flex items-center justify-between gap-2">
            <div className="min-w-0">
              <div className="text-[11px] text-mist-200 truncate">{r.vehicle_label}</div>
              <div className="text-[10px] text-mist-500 truncate">
                {r.origin_name ?? r.origin} → {r.destination_name ?? r.destination}
              </div>
            </div>
            <div className="text-right shrink-0">
              <div className="num text-[11px] text-brand-200">{fmtEta(r.eta_s)}</div>
              <span className={`chip !text-[9px] ${
                r.status === 'SAFE' ? 'border-emerald-700 text-emerald-300'
                  : r.status === 'WARNING' ? 'border-amber-600 text-amber-300'
                    : 'border-red-600 text-red-300'}`}>
                {r.status}
              </span>
            </div>
          </div>
        ))}
      </div>

      {/* history (§33) */}
      <div className="rounded-md border border-line bg-ink-850 p-2.5 space-y-1.5">
        <div className="flex items-center justify-between">
          <span className="label-cap text-mist-500">Route history</span>
          <button className="btn !px-2 !py-1" onClick={() => void refreshRouteHistory()}
                  title="Reload history">
            <IconHistory width={12} height={12} />
          </button>
        </div>
        {!routeHistory.length ? (
          <div className="text-[11px] text-mist-500">No calculations yet this session.</div>
        ) : routeHistory.slice(0, 6).map((h, i) => (
          <div key={`${h.route_id}-${i}`} className="flex items-center justify-between
                                                     border-t border-line/50 pt-1 text-[10.5px]">
            <span className="text-mist-400 truncate">
              {h.origin ?? '?'} → {h.destination ?? '?'}
              {h.event ? ` · ${h.event.replace(/[._]/g, ' ')}` : ''}
            </span>
            <span className="num text-mist-500 shrink-0 ml-2">
              {typeof h.risk_score === 'number' ? `risk ${fmtNum(h.risk_score)}` : h.status}
            </span>
          </div>
        ))}
      </div>

      <RouteLegend />
    </div>
  );

  const header = (
    <div className="px-3.5 py-3 border-b border-line flex items-start gap-2">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <IconRoad width={14} height={14} className="text-brand-300" />
          <h2 className="text-[15px] font-bold truncate">Routes & Evacuation</h2>
        </div>
        <div className="flex items-center gap-1.5 mt-1 flex-wrap">
          <span className={`chip ${evacStatusChip(evacuation?.status ?? 'IDLE')}`}>
            {evacuation?.status ?? 'IDLE'}
          </span>
          <span className="chip border-line-strong bg-ink-800 text-mist-300">
            {plan ? `v${plan.route_version}` : 'no plan'}
          </span>
        </div>
      </div>
      {onClose && (
        <button className="btn !px-2 !py-1" onClick={onClose} title="Close">
          <IconX width={13} height={13} />
        </button>
      )}
    </div>
  );

  if (onClose) {
    return (
      <div className="absolute top-3 right-3 bottom-3 w-[335px] z-20 panel rounded-xl
                      shadow-2xl shadow-black/60 flex flex-col overflow-hidden fade-in
                      max-lg:w-[300px] max-sm:inset-x-2 max-sm:w-auto">
        {header}
        {body}
      </div>
    );
  }
  return (
    <div className="panel rounded-xl flex flex-col overflow-hidden">
      {header}
      {body}
    </div>
  );
}
