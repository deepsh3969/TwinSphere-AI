import { Fragment, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { IconHistory, IconRefresh, IconTarget } from '../components/Icons';
import { api } from '../services/api';
import { useTwinStore } from '../store/useTwinStore';
import type { SimEvent } from '../types';
import { fmtNum, scenarioIcon, scenarioLabel } from '../utils/colors';

const SCENARIO_FILTERS = ['all', 'fire', 'crowd', 'power', 'road', 'temperature'] as const;

export default function History() {
  const history = useTwinStore((s) => s.history);
  const loading = useTwinStore((s) => s.historyLoading);
  const refreshHistory = useTwinStore((s) => s.refreshHistory);
  const handleApiError = useTwinStore((s) => s.handleApiError);
  const focusCamera = useTwinStore((s) => s.focusCamera);
  const selectBuilding = useTwinStore((s) => s.selectBuilding);
  const snapshot = useTwinStore((s) => s.snapshot);
  const navigate = useNavigate();

  const locate = (targetId: string | null) => {
    navigate('/twin');
    if (!targetId) return;
    void selectBuilding(targetId);
    const b = snapshot?.buildings.find((x) => x.id === targetId);
    if (b) focusCamera(b.position.x, b.position.z);
  };

  const [filter, setFilter] = useState<(typeof SCENARIO_FILTERS)[number]>('all');
  const [openId, setOpenId] = useState<string | null>(null);
  const [events, setEvents] = useState<SimEvent[]>([]);
  const [eventsLoading, setEventsLoading] = useState(false);

  useEffect(() => { void refreshHistory(); }, [refreshHistory]);

  useEffect(() => {
    if (!openId) { setEvents([]); return; }
    let alive = true;
    setEventsLoading(true);
    api.simEvents(openId)
      .then((res) => { if (alive) setEvents([...res.live].reverse()); })
      .catch((err) => { if (alive) handleApiError(err); })
      .finally(() => { if (alive) setEventsLoading(false); });
    return () => { alive = false; };
  }, [openId, handleApiError]);

  const rows = history.filter((h) => filter === 'all' || h.scenario === filter);

  return (
    <div className="h-full overflow-y-auto scroll-y p-4 space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-lg font-bold flex items-center gap-2">
          <IconHistory width={17} height={17} className="text-brand-400" /> Simulation History
        </h1>
        <span className="chip border-line-strong bg-ink-800 text-mist-300 num">{rows.length} records</span>
        <div className="flex-1" />
        <button className="btn" onClick={() => void refreshHistory()} disabled={loading}>
          <IconRefresh width={13} height={13} className={loading ? 'animate-spin' : ''} /> Refresh
        </button>
      </div>

      <div className="flex gap-1.5 flex-wrap">
        {SCENARIO_FILTERS.map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`chip ${filter === f ? 'border-brand-400 bg-brand-950/70 text-brand-200' : ''}`}
          >
            {f === 'all' ? 'All scenarios' : scenarioLabel(f)}
          </button>
        ))}
      </div>

      <div className="panel rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-[12.5px]">
            <thead>
              <tr className="border-b border-line bg-ink-850/80 text-left">
                {['Scenario', 'Target', 'Status', 'Created', 'Peak risk', 'People', 'Recovery', 'Severity', ''].map((h) => (
                  <th key={h} className="label-cap px-3 py-2.5 whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((h) => (
                <Fragment key={h.id}>
                  <tr
                    className="border-b border-line/60 hover:bg-ink-850/60 cursor-pointer"
                    onClick={() => setOpenId(openId === h.id ? null : h.id)}
                  >
                    <td className="px-3 py-2.5 whitespace-nowrap">
                      <span className="flex items-center gap-2">
                        <span>{scenarioIcon(h.scenario)}</span>
                        <span className="font-semibold">{scenarioLabel(h.scenario)}</span>
                      </span>
                    </td>
                    <td className="px-3 py-2.5 text-mist-300">{h.target_id ?? 'campus-wide'}</td>
                    <td className="px-3 py-2.5">
                      <span className={`chip !text-[9.5px] ${
                        h.status === 'COMPLETED' ? 'border-emerald-700 text-emerald-300'
                          : h.status === 'RUNNING' ? 'border-red-700 text-red-300'
                            : 'border-line-strong text-mist-300'
                      }`}>{h.status}</span>
                    </td>
                    <td className="px-3 py-2.5 num text-mist-400 whitespace-nowrap">
                      {new Date(h.created_at).toLocaleString()}
                    </td>
                    <td className="px-3 py-2.5 num">
                      <span className={h.peak_risk > 60 ? 'text-red-400 font-bold' : h.peak_risk > 35 ? 'text-amber-300' : 'text-emerald-400'}>
                        {h.peak_risk.toFixed(0)}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 num">{fmtNum(h.people_affected)}</td>
                    <td className="px-3 py-2.5 num text-mist-300">
                      {h.recovery_time_s > 0 ? `${h.recovery_time_s.toFixed(0)}s` : '—'}
                    </td>
                    <td className="px-3 py-2.5">
                      <span className={`chip !text-[9.5px] ${
                        h.severity === 'CRITICAL' || h.severity === 'HIGH' ? 'border-red-700 text-red-300'
                          : h.severity === 'MEDIUM' ? 'border-amber-700 text-amber-300'
                            : 'border-emerald-700 text-emerald-300'
                      }`}>{h.severity}</span>
                    </td>
                    <td className="px-3 py-2.5 text-mist-500 text-right">{openId === h.id ? '▾' : '▸'}</td>
                  </tr>
                  {openId === h.id && (
                    <tr className="border-b border-line/60 bg-ink-900/70">
                      <td colSpan={9} className="px-4 py-3">
                        <div className="flex items-center gap-2 mb-2">
                          <span className="label-cap">Event log</span>
                          <span className="num text-[10.5px] text-mist-500">{h.id}</span>
                          <button
                            className="btn !py-0.5 !text-[11px] ml-auto"
                            onClick={(e) => { e.stopPropagation(); locate(h.target_id); }}
                          >
                            <IconTarget width={12} height={12} /> Locate
                          </button>
                        </div>
                        {eventsLoading ? (
                          <div className="text-[12px] text-mist-500 py-3">Loading events…</div>
                        ) : events.length === 0 ? (
                          <div className="text-[12px] text-mist-500 py-3">No persisted events for this run.</div>
                        ) : (
                          <div className="space-y-1 max-h-56 scroll-y pr-1">
                            {events.map((ev, i) => (
                              <div key={i} className="flex gap-2 text-[11.5px]">
                                <span className="num text-mist-500 w-[54px] shrink-0">T+{ev.t.toFixed(0)}s</span>
                                <span className="text-mist-300 w-[130px] shrink-0 truncate">{ev.kind.replace(/_/g, ' ')}</span>
                                <span className="text-mist-100">{ev.message}</span>
                              </div>
                            ))}
                          </div>
                        )}
                        {h.result && Object.keys(h.result).length > 0 && (
                          <div className="mt-2 text-[11px] text-mist-500 num">
                            result: {JSON.stringify(h.result)}
                          </div>
                        )}
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
        {rows.length === 0 && !loading && (
          <div className="px-4 py-10 text-center">
            <div className="text-[13px] text-mist-300 mb-1">No simulations match this filter.</div>
            <div className="text-[12px] text-mist-500">
              Run a drill in the <Link className="text-brand-400 underline" to="/simulation">Simulation Center</Link> to build history.
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
