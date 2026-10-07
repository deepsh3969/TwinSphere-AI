import { useNavigate } from 'react-router-dom';
import { useTwinStore } from '../../store/useTwinStore';
import { fmtNum, levelChip, riskTextClass, routeColor } from '../../utils/colors';
import { IconAlert, IconCheck, IconTarget, IconX } from '../Icons';
import RiskGauge from './RiskGauge';

const STATUS_TONE: Record<string, string> = {
  NORMAL: 'border-emerald-700 bg-emerald-950/60 text-emerald-300',
  AFFECTED: 'border-amber-700 bg-amber-950/60 text-amber-300',
  SMOKE: 'border-orange-700 bg-orange-950/60 text-orange-300',
  FIRE: 'border-red-700 bg-red-950/60 text-red-300',
};

export default function BuildingPanel({ onClose }: { onClose: () => void }) {
  const detail = useTwinStore((s) => s.buildingDetail);
  const loading = useTwinStore((s) => s.buildingLoading);
  const error = useTwinStore((s) => s.buildingError);
  const focusCamera = useTwinStore((s) => s.focusCamera);
  const user = useTwinStore((s) => s.user);
  const navigate = useNavigate();

  if (!detail && !loading) return null;

  const canSimulate = user && ['ADMIN', 'OPERATOR'].includes(user.role);
  const occPct = detail ? (detail.occupancy / Math.max(1, detail.capacity)) * 100 : 0;
  const route = detail?.routes?.[0];

  return (
    <div className="absolute top-3 right-3 bottom-3 w-[335px] z-20 panel rounded-xl shadow-2xl shadow-black/60 flex flex-col overflow-hidden fade-in max-lg:w-[300px] max-sm:inset-x-2 max-sm:w-auto">
      <div className="px-3.5 py-3 border-b border-line flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ background: detail?.color }} />
            <h2 className="text-[15px] font-bold truncate">{detail?.name ?? 'Building'}</h2>
          </div>
          <div className="flex items-center gap-1.5 mt-1 flex-wrap">
            <span className="chip border-line-strong bg-ink-800 text-mist-300">{detail?.type}</span>
            <span className={`chip ${
              detail?.status === 'OPERATIONAL' ? 'border-emerald-700 bg-emerald-950/60 text-emerald-300'
                : detail?.status === 'EVACUATING' ? 'border-amber-700 bg-amber-950/60 text-amber-300'
                  : 'border-red-700 bg-red-950/60 text-red-300'
            }`}>{detail?.status ?? '—'}</span>
            {detail && detail.risk > 0 && (
              <span className={`chip ${levelChip(detail.risk_detail?.level ?? 'LOW')}`}>
                RISK {detail.risk.toFixed(0)}
              </span>
            )}
          </div>
        </div>
        <button
          className="btn !px-2 !py-1"
          title="Focus camera"
          onClick={() => detail && focusCamera(detail.position.x, detail.position.z)}
        >
          <IconTarget width={13} height={13} />
        </button>
        <button className="btn !px-2 !py-1" onClick={onClose} title="Close">
          <IconX width={13} height={13} />
        </button>
      </div>

      <div className="flex-1 min-h-0 scroll-y px-3.5 py-3 space-y-4">
        {loading && (
          <div className="space-y-2">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="h-14 rounded-md bg-ink-800 animate-pulse" />
            ))}
          </div>
        )}
        {error && (
          <div className="rounded-md border border-red-800 bg-red-950/50 p-3 text-[12px] text-red-200">
            {error}
          </div>
        )}

        {detail && !loading && (
          <>
            <RiskGauge risk={detail.risk_detail} />

            <div className="grid grid-cols-2 gap-2">
              <div className="rounded-md border border-line bg-ink-850 p-2.5">
                <div className="label-cap">Occupancy</div>
                <div className="num text-lg font-bold">{fmtNum(detail.occupancy)}<span className="text-[11px] text-mist-500"> / {fmtNum(detail.capacity)}</span></div>
                <div className="h-1.5 rounded-full bg-ink-700 mt-1.5 overflow-hidden">
                  <div
                    className={`h-full ${occPct > 95 ? 'bg-red-500' : occPct > 80 ? 'bg-amber-400' : 'bg-emerald-500'}`}
                    style={{ width: `${Math.min(100, occPct)}%` }}
                  />
                </div>
                <div className="text-[10px] text-mist-500 mt-0.5 num">{occPct.toFixed(0)}% of capacity</div>
              </div>
              <div className="rounded-md border border-line bg-ink-850 p-2.5">
                <div className="label-cap">Temperature</div>
                <div className={`num text-lg font-bold ${detail.temperature > 35 ? 'text-orange-400' : 'text-white'}`}>
                  {detail.temperature.toFixed(1)}<span className="text-[11px] text-mist-500">°C</span>
                </div>
                <div className="text-[10px] text-mist-500 mt-1">Humidity {detail.humidity.toFixed(0)}%</div>
              </div>
              <div className="rounded-md border border-line bg-ink-850 p-2.5">
                <div className="label-cap">Energy</div>
                <div className="num text-lg font-bold text-amber-300">{detail.energy.toFixed(1)}<span className="text-[11px] text-mist-500"> kW</span></div>
                <div className="text-[10px] text-mist-500 mt-1">{detail.power ? (detail.backup_power ? 'Backup power' : 'Mains supply') : 'POWER OFF'}</div>
              </div>
              <div className="rounded-md border border-line bg-ink-850 p-2.5">
                <div className="label-cap">Air / Smoke</div>
                <div className={`num text-lg font-bold ${detail.smoke > 10 ? 'text-red-400' : 'text-white'}`}>
                  {detail.smoke.toFixed(0)}<span className="text-[11px] text-mist-500"> ppm</span>
                </div>
                <div className="text-[10px] text-mist-500 mt-1">AQI {detail.air_quality.toFixed(0)}</div>
              </div>
            </div>

            <div className="rounded-md border border-line bg-ink-850 p-2.5">
              <div className="flex justify-between items-center">
                <span className="label-cap">Sensor Health</span>
                <span className={`num text-[13px] font-bold ${detail.sensor_health < 90 ? 'text-amber-300' : 'text-emerald-400'}`}>
                  {detail.sensor_health.toFixed(0)}%
                </span>
              </div>
              <div className="flex flex-wrap gap-1 mt-1.5">
                {detail.sensors.slice(0, 8).map((s) => (
                  <span key={s.id} className={`chip !text-[9px] ${s.healthy ? 'border-emerald-800 text-emerald-400' : 'border-red-700 text-red-300'}`}>
                    {s.type}: {s.value.toFixed(s.type === 'energy' ? 0 : 1)}
                  </span>
                ))}
              </div>
            </div>

            {detail.predictions.length > 0 && (
              <div className="rounded-md border border-line bg-ink-850 p-2.5">
                <div className="label-cap mb-1.5">AI Predictions (20 min)</div>
                <div className="space-y-1.5">
                  {detail.predictions.slice(0, 2).map((p) => (
                    <div key={p.metric}>
                      <div className="flex justify-between text-[11.5px]">
                        <span className="capitalize text-mist-300">{p.metric}</span>
                        <span className="num">
                          {fmtNum(p.current_value, 1)} → <b className={p.predicted_value > p.current_value ? 'text-amber-300' : 'text-sky-300'}>
                            {fmtNum(p.predicted_value, 1)}
                          </b>
                        </span>
                      </div>
                      <div className="flex items-center gap-2 mt-0.5">
                        <div className="flex-1 h-1 rounded-full bg-ink-700 overflow-hidden">
                          <div className="h-full bg-brand-500" style={{ width: `${p.confidence * 100}%` }} />
                        </div>
                        <span className="text-[9.5px] text-mist-500 num">{(p.confidence * 100).toFixed(0)}% conf · {p.model_name}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="rounded-md border border-line bg-ink-850 p-2.5">
              <div className="label-cap mb-1.5">Zones ({detail.zones.length})</div>
              <div className="space-y-1 max-h-36 overflow-y-auto pr-1">
                {detail.zones.map((z) => (
                  <div key={z.id} className="flex items-center justify-between gap-2 text-[11.5px]">
                    <span className="truncate text-mist-300">{z.name}</span>
                    <span className="flex items-center gap-1.5 shrink-0">
                      <span className="num text-mist-500">{z.occupancy}/{z.capacity}</span>
                      <span className={`chip !py-0 !px-1.5 !text-[9px] ${STATUS_TONE[z.status] ?? STATUS_TONE.NORMAL}`}>
                        {z.status}{z.fire > 0.04 ? ` ${(z.fire * 100).toFixed(0)}%` : ''}
                      </span>
                    </span>
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-md border border-line bg-ink-850 p-2.5">
              <div className="label-cap mb-1.5">Evacuation</div>
              {route && route.exit_id ? (
                <div className="text-[11.5px] space-y-1">
                  <div className="flex justify-between">
                    <span className="text-mist-300">Best exit</span>
                    <b>{route.exit_name}</b>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-mist-300">ETA</span>
                    <span className="num">{route.evac_time_s.toFixed(0)}s · {route.distance.toFixed(0)}m</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-mist-300">Route status</span>
                    <span className="chip !text-[9px]" style={{ color: routeColor(route.status), borderColor: routeColor(route.status) }}>
                      {route.status}
                    </span>
                  </div>
                  <p className="text-[10.5px] text-mist-500 pt-1 border-t border-line">{route.reason}</p>
                </div>
              ) : (
                <div className="text-[11.5px] text-red-300">No passable evacuation route.</div>
              )}
              <div className="mt-2 text-[11px] text-mist-500">
                Exits: {detail.exits.map((e) => `${e.name} (${e.risk.toFixed(0)})`).join(' · ') || 'none'}
              </div>
            </div>

            {detail.incidents.filter((i) => i.status === 'ACTIVE').length > 0 && (
              <div className="rounded-md border border-red-800 bg-red-950/40 p-2.5">
                <div className="label-cap text-red-300 mb-1">Active Incidents</div>
                {detail.incidents.filter((i) => i.status === 'ACTIVE').map((i) => (
                  <div key={i.id} className="flex items-start gap-1.5 text-[11.5px] text-red-100">
                    <IconAlert width={12} height={12} className="mt-0.5 shrink-0" />
                    <span>{i.title} <span className="text-red-300/70">— {i.description}</span></span>
                  </div>
                ))}
              </div>
            )}

            <div className="flex gap-2 pb-1">
              <button
                className="btn btn-primary flex-1"
                disabled={!canSimulate}
                onClick={() => navigate(`/simulation?scenario=fire&building=${detail.id}`)}
                title={canSimulate ? 'Preconfigure a fire drill' : 'Requires OPERATOR/ADMIN role'}
              >
                Simulate Fire →
              </button>
              <button className="btn" onClick={() => navigate('/ai')}>
                <IconCheck width={13} height={13} /> AI
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
