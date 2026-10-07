import { useEffect, useMemo, useState } from 'react';
import { api } from '../../services/api';
import { useTwinCamera } from '../../hooks/useTwinCamera';
import { useTwinStore } from '../../store/useTwinStore';
import type { Floor, Sensor } from '../../types';
import { floorLabel, zoneTypeColor } from '../../types/twin';
import { fmtNum, levelChip, trendDir, trendLabel } from '../../utils/colors';
import { IconTarget, IconX } from '../Icons';

const STATUS_CHIP: Record<string, string> = {
  OPERATIONAL: 'border-emerald-700 bg-emerald-950/60 text-emerald-300',
  EVACUATING: 'border-amber-700 bg-amber-950/60 text-amber-300',
};

const ZONE_STATUS_CHIP: Record<string, string> = {
  NORMAL: 'border-emerald-800 text-emerald-300',
  AFFECTED: 'border-amber-700 text-amber-300',
  SMOKE: 'border-orange-700 text-orange-300',
  FIRE: 'border-red-700 text-red-300',
};

function Stat({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-line bg-ink-850 px-2.5 py-2">
      <div className="label-cap">{label}</div>
      <div className="mt-0.5">{children}</div>
    </div>
  );
}

function SensorChip({ sensor, selected, onClick }: {
  sensor: Sensor; selected: boolean; onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      title={`${sensor.sensor_code || sensor.id} — click for details`}
      className={`chip !text-[9px] transition-colors ${
        selected ? 'border-brand-400 bg-brand-950/70 text-brand-200'
          : sensor.status === 'ONLINE' && sensor.healthy
            ? 'border-emerald-800 text-emerald-400 hover:border-emerald-500'
            : 'border-red-700 text-red-300 hover:border-red-500'
      }`}
    >
      {sensor.sensor_code || sensor.id}
    </button>
  );
}

/**
 * Building inspector (spec §9/§18/§49/§51): details from Phase 2
 * `/api/buildings/{id}` + `/api/buildings/{id}/floors`, with a real floor
 * selector that scopes zones and sensors to the chosen floor.
 */
export default function BuildingInspector({ onClose }: { onClose: () => void }) {
  const detail = useTwinStore((s) => s.buildingDetail);
  const loading = useTwinStore((s) => s.buildingLoading);
  const error = useTwinStore((s) => s.buildingError);
  const selectedFloorId = useTwinStore((s) => s.selectedFloorId);
  const selectedSensorId = useTwinStore((s) => s.selectedSensorId);
  const selectFloor = useTwinStore((s) => s.selectFloor);
  const selectSensor = useTwinStore((s) => s.selectSensor);
  const lastUpdate = useTwinStore((s) => s.lastUpdate);
  const snapshot = useTwinStore((s) => s.snapshot);
  const riskPublishedBuildings = useTwinStore((s) => s.riskPublishedBuildings);
  const { focusSelected } = useTwinCamera();

  const [floors, setFloors] = useState<Floor[] | null>(null);

  const buildingId = detail?.id ?? null;

  useEffect(() => {
    if (!buildingId) { setFloors(null); return; }
    let dead = false;
    setFloors(null);
    api.buildingFloors(buildingId)
      .then((f) => { if (!dead) setFloors(Array.isArray(f) ? f : []); })
      .catch(() => { if (!dead) setFloors(null); });
    return () => { dead = true; };
  }, [buildingId]);

  // floor fallback derived from zone floor_ids (identical id format)
  const derivedFloors = useMemo<Floor[]>(() => {
    if (!detail) return [];
    const byId = new Map<number, Floor>();
    for (const z of detail.zones) {
      if (!z.floor_id || byId.has(z.floor)) continue;
      byId.set(z.floor, {
        id: z.floor_id,
        building_id: detail.id,
        floor_number: z.floor,
        name: floorLabel(z.floor),
        zone_count: detail.zones.filter((x) => x.floor === z.floor).length,
        area_sqm: 0,
        is_evacuation_level: false,
      });
    }
    return [...byId.values()].sort((a, b) => a.floor_number - b.floor_number);
  }, [detail]);

  // live zone readings from the streamed snapshot (Phase 4); falls back to
  // the REST detail's zone rows when no streamed snapshot has arrived
  const liveZones = useMemo(
    () => new Map((snapshot?.zones ?? []).map((z) => [z.id, z])),
    [snapshot],
  );

  if (loading && !detail) {
    return (
      <div className="absolute top-3 right-3 bottom-10 w-[335px] z-20 panel rounded-xl shadow-2xl shadow-black/60 flex flex-col overflow-hidden max-lg:w-[300px] max-sm:inset-x-2 max-sm:w-auto">
        <div className="px-3.5 py-3 border-b border-line">
          <div className="h-4 w-40 rounded bg-ink-800 animate-pulse" />
          <div className="h-3 w-24 rounded bg-ink-800 animate-pulse mt-2" />
        </div>
        <div className="p-3.5 space-y-2">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="h-12 rounded-md bg-ink-800 animate-pulse" />
          ))}
        </div>
      </div>
    );
  }

  if (!detail) return null;

  const floorList = (floors && floors.length > 0 ? floors : derivedFloors);
  const zonesForFloor = selectedFloorId
    ? detail.zones.filter((z) => z.floor_id === selectedFloorId)
    : detail.zones;
  const floorZoneIds = new Set(zonesForFloor.map((z) => z.id));
  const sensorsForFloor = selectedFloorId
    ? detail.sensors.filter((s) => s.zone_id && floorZoneIds.has(s.zone_id))
    : detail.sensors;
  const onlineCount = detail.sensors.filter((s) => s.status === 'ONLINE').length;
  // live values: prefer the streamed snapshot (Phase 4 building.update/state)
  // over the one-time REST detail fetch, so occupancy moves in real time
  const live = snapshot?.buildings.find((b) => b.id === detail.id) ?? null;
  const occupancy = live?.occupancy ?? detail.occupancy;
  const status = live?.status ?? detail.status;
  const risk = live?.risk ?? detail.risk;
  const riskLevel = live?.risk_level ?? detail.risk_level;
  const published = riskPublishedBuildings[detail.id] ?? null;
  const topFactors = (published?.factors ?? []).slice().sort((a, b) => b.contribution - a.contribution).slice(0, 3);
  const occPct = detail.capacity > 0 ? (occupancy / detail.capacity) * 100 : 0;
  const updated = lastUpdate ? new Date(lastUpdate).toLocaleTimeString(undefined, { hour12: false }) : '—';

  return (
    <div className="absolute top-3 right-3 bottom-10 w-[335px] z-20 panel rounded-xl shadow-2xl shadow-black/60 flex flex-col overflow-hidden max-lg:w-[300px] max-sm:inset-x-2 max-sm:w-auto max-sm:bottom-14">
      {/* header */}
      <div className="px-3.5 py-3 border-b border-line flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ background: detail.color }} />
            <h2 className="text-[15px] font-bold truncate">{detail.name}</h2>
          </div>
          <div className="flex items-center gap-1.5 mt-1.5 flex-wrap">
            <span className="chip !text-[9px] border-line-strong bg-ink-800 text-mist-300 num">{detail.code}</span>
            <span className="chip !text-[9px] border-line-strong bg-ink-800 text-mist-300">{detail.type}</span>
            <span className={`chip !text-[9px] ${STATUS_CHIP[status] ?? 'border-red-700 bg-red-950/60 text-red-300'}`}>
              {status}
            </span>
            <span className={`chip !text-[9px] ${levelChip(riskLevel)}`}>
              RISK {risk.toFixed(0)}
            </span>
          </div>
        </div>
        <button className="btn !px-2 !py-1" title="Focus camera" onClick={() => focusSelected()}>
          <IconTarget width={13} height={13} />
        </button>
        <button className="btn !px-2 !py-1" onClick={onClose} title="Close inspector" aria-label="Close inspector">
          <IconX width={13} height={13} />
        </button>
      </div>

      <div className="flex-1 min-h-0 scroll-y px-3.5 py-3 space-y-3 pb-10">
        {error && (
          <div className="rounded-md border border-red-800 bg-red-950/50 p-2.5 text-[12px] text-red-200">{error}</div>
        )}

        {detail.description && (
          <p className="text-[11.5px] leading-relaxed text-mist-400">{detail.description}</p>
        )}

        {/* core stats */}
        <div className="grid grid-cols-2 gap-2">
          <Stat label="Floors"><span className="num text-lg font-bold">{detail.floors}</span></Stat>
          <Stat label="Capacity">
            <span className="num text-lg font-bold">{fmtNum(detail.capacity)}</span>
          </Stat>
          <Stat label="Occupancy">
            <span className="num text-lg font-bold">{fmtNum(occupancy)}</span>
            <div className="h-1.5 rounded-full bg-ink-700 mt-1.5 overflow-hidden">
              <div
                className={`h-full ${occPct > 95 ? 'bg-red-500' : occPct > 80 ? 'bg-amber-400' : 'bg-emerald-500'}`}
                style={{ width: `${Math.min(100, occPct)}%` }}
              />
            </div>
            <div className="text-[10px] text-mist-500 mt-0.5 num">{occPct.toFixed(0)}% of capacity</div>
          </Stat>
          <Stat label="Sensors">
            <span className="num text-lg font-bold">{detail.sensors.length}</span>
            <div className="text-[10px] text-mist-500 mt-0.5 num">{onlineCount} online</div>
          </Stat>
          <div className="col-span-2 rounded-md border border-line bg-ink-850 px-2.5 py-2 flex justify-between items-center">
            <div>
              <div className="label-cap">Coordinates</div>
              <div className="num text-[11.5px] text-mist-200 mt-0.5">
                X {detail.position.x.toFixed(0)} · Z {detail.position.z.toFixed(0)}
                {detail.latitude != null && detail.longitude != null && (
                  <span className="text-mist-500"> · {detail.latitude.toFixed(5)}, {detail.longitude.toFixed(5)}</span>
                )}
              </div>
            </div>
            <div className="text-right">
              <div className="label-cap">Data Updated</div>
              <div className="num text-[11.5px] text-mist-200 mt-0.5">{updated}</div>
            </div>
          </div>
        </div>

        {/* Phase 5 — published (smoothed) risk for this building */}
        <div className="rounded-md border border-line bg-ink-850 p-2.5" data-testid="building-published-risk">
          <div className="flex items-center justify-between mb-1.5">
            <span className="label-cap">Risk — Published</span>
            <span className="num text-[10px] text-mist-500">smoothed · EMA + hysteresis</span>
          </div>
          {!published ? (
            <div className="text-[11.5px] text-mist-500">
              Not published yet — the AI cycle publishes a stabilised score every cycle.
            </div>
          ) : (
            <>
              <div className="flex items-center gap-2 flex-wrap">
                <span className={`chip !text-[10px] font-bold border ${levelChip(published.level)}`}>
                  <span className="num">{published.score?.toFixed(0) ?? '—'}</span>
                  <span className="opacity-80">{published.level}</span>
                </span>
                <span className="num text-[11px] text-mist-400">
                  raw {published.raw_score != null ? published.raw_score.toFixed(0) : risk.toFixed(0)}
                </span>
                <span className={`chip !text-[9px] border-line-strong ${
                  trendDir(published.trend) === 'rising' ? 'text-red-300'
                    : trendDir(published.trend) === 'falling' ? 'text-emerald-300' : 'text-mist-400'
                }`}>
                  {trendLabel(published.trend)}
                </span>
              </div>
              {topFactors.length > 0 && (
                <div className="space-y-1 mt-2">
                  {topFactors.map((f) => (
                    <div key={f.label} className="flex items-center justify-between text-[11px]">
                      <span className="text-mist-400 truncate">{f.label}</span>
                      <span className="num text-mist-200 ml-2">+{f.contribution.toFixed(1)}</span>
                    </div>
                  ))}
                </div>
              )}
              {published.explanation && (
                <p className="text-[10px] text-mist-600 mt-1.5 leading-relaxed">{published.explanation}</p>
              )}
              <p className="text-[10px] text-mist-600 mt-1.5 leading-relaxed">
                Weighted indicator for prioritisation — not a probability or guaranteed outcome.
              </p>
            </>
          )}
        </div>

        {/* floor selector (spec §9/§51) */}
        <div>
          <div className="label-cap mb-1.5">Floors</div>
          <div className="flex flex-wrap gap-1.5">
            <button
              onClick={() => selectFloor(null)}
              aria-pressed={selectedFloorId === null}
              className={`chip !text-[10px] ${
                selectedFloorId === null ? 'border-brand-400 bg-brand-950/70 text-brand-200' : 'border-line-strong text-mist-400'
              }`}
            >
              All Floors
            </button>
            {floorList.map((f) => (
              <button
                key={f.id}
                onClick={() => selectFloor(selectedFloorId === f.id ? null : f.id)}
                aria-pressed={selectedFloorId === f.id}
                title={`${f.name} · ${f.zone_count} zones`}
                className={`chip !text-[10px] ${
                  selectedFloorId === f.id ? 'border-brand-400 bg-brand-950/70 text-brand-200' : 'border-line-strong text-mist-400'
                }`}
              >
                {floorLabel(f.floor_number)}
              </button>
            ))}
            {floors === null && floorList.length === 0 && !loading && (
              <span className="text-[10.5px] text-mist-500">Floor data unavailable</span>
            )}
          </div>
          {selectedFloorId && (
            <p className="text-[10.5px] text-brand-300 mt-1.5">
              Floor highlighted in the scene — zones and sensors below are scoped to it.
            </p>
          )}
        </div>

        {/* zones */}
        <div className="rounded-md border border-line bg-ink-850 p-2.5">
          <div className="flex items-center justify-between mb-1.5">
            <span className="label-cap">Zones{selectedFloorId ? ` · ${floorLabel(floorList.find((f) => f.id === selectedFloorId)?.floor_number ?? 1)}` : ''}</span>
            <span className="num text-[10px] text-mist-500">{zonesForFloor.length}</span>
          </div>
          {zonesForFloor.length === 0 ? (
            <div className="text-[11.5px] text-mist-500">No zones recorded for this floor.</div>
          ) : (
            <div className="space-y-1 max-h-44 overflow-y-auto pr-1">
              {zonesForFloor.map((z) => {
                const lz = liveZones.get(z.id);
                const occ = lz?.occupancy ?? z.occupancy;
                const cap = lz?.capacity ?? z.capacity;
                const zstatus = lz?.status ?? z.status;
                return (
                  <div key={z.id} className="flex items-center justify-between gap-2 text-[11.5px]">
                    <span className="flex items-center gap-1.5 min-w-0">
                      <span className="w-1.5 h-1.5 rounded-sm shrink-0" style={{ background: zoneTypeColor(z.kind) }} />
                      <span className="truncate text-mist-300">{z.name}</span>
                      <span className="chip !py-0 !px-1 !text-[8px] border-line-strong text-mist-500 shrink-0">
                        {z.zone_type}
                      </span>
                    </span>
                    <span className="flex items-center gap-1.5 shrink-0">
                      <span className="num text-mist-500">{occ}/{cap}</span>
                      <span className={`chip !py-0 !px-1.5 !text-[8.5px] ${ZONE_STATUS_CHIP[zstatus] ?? ZONE_STATUS_CHIP.NORMAL}`}>
                        {zstatus}
                      </span>
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* sensors scoped to floor */}
        <div className="rounded-md border border-line bg-ink-850 p-2.5">
          <div className="flex items-center justify-between mb-1.5">
            <span className="label-cap">Sensors{selectedFloorId ? ' · this floor' : ''}</span>
            <span className="num text-[10px] text-mist-500">{sensorsForFloor.length}</span>
          </div>
          {sensorsForFloor.length === 0 ? (
            <div className="text-[11.5px] text-mist-500">No sensors on this floor.</div>
          ) : (
            <div className="flex flex-wrap gap-1.5">
              {sensorsForFloor.map((s) => (
                <SensorChip
                  key={s.id}
                  sensor={s}
                  selected={selectedSensorId === s.id}
                  onClick={() => selectSensor(s.id)}
                />
              ))}
            </div>
          )}
          <p className="text-[10px] text-mist-500 mt-1.5">Click a sensor for live value + 24 h history.</p>
        </div>
      </div>
    </div>
  );
}
