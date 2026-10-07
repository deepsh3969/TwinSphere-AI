import { Html } from '@react-three/drei';
import { useFrame } from '@react-three/fiber';
import { memo, useMemo, useRef } from 'react';
import type { Mesh, MeshBasicMaterial } from 'three';
import { useTwinStore } from '../../store/useTwinStore';
import type { Snapshot, Zone } from '../../types';
import { floorLabel, zoneTypeColor } from '../../types/twin';
import { fmtNum } from '../../utils/colors';

interface ZoneItem {
  zone: Zone;
  x: number;
  z: number;
  y: number;
  w: number;
  d: number;
  h: number;
  emphasize: boolean;
  showLabel: boolean;
}

const MAX_FREE_LABELS = 8;

/** Phase 6 §55 — hazard footprint ring under a burning/smoky/affected zone. */
const HAZARD_COLOR: Record<string, string> = {
  FIRE: '#ff3b1f', SMOKE: '#ff9a3c', AFFECTED: '#fbbf24',
};

function HazardPulse({ w, d, h, status }: { w: number; d: number; h: number; status: string }) {
  const ref = useRef<Mesh>(null);
  const fast = status === 'FIRE';
  useFrame(({ clock }) => {
    const m = ref.current;
    if (!m) return;
    const t = clock.getElapsedTime();
    const s = 1 + Math.sin(t * (fast ? 6 : 3)) * 0.12;
    m.scale.set(s, s, s);
    const mat = m.material as MeshBasicMaterial;
    mat.opacity = 0.3 + Math.sin(t * (fast ? 5 : 3)) * 0.18;
  });
  return (
    <mesh ref={ref} position={[0, -h / 2 + 0.05, 0]} rotation={[-Math.PI / 2, 0, 0]}>
      <ringGeometry args={[Math.min(w, d) * 0.55, Math.max(w, d) * 0.78, 40]} />
      <meshBasicMaterial
        color={HAZARD_COLOR[status] ?? '#fbbf24'}
        transparent
        opacity={0.4}
        side={2}
        depthWrite={false}
      />
    </mesh>
  );
}

/**
 * Zone visualization (spec §10):
 * - Layers off + no floor selected → zones hidden.
 * - Zones layer on → all zones, subtle; emphasized for the selected building.
 * - Floor selected → only that floor's zones, inspection emphasis + labels.
 * Color = functional type tint; risk outline only when risk data exists.
 */
function CampusZones({ snapshot }: { snapshot: Snapshot }) {
  const zonesOn = useTwinStore((s) => s.toggles.zones);
  const labelsOn = useTwinStore((s) => s.toggles.labels);
  const viewMode = useTwinStore((s) => s.viewMode);
  const selectedBuildingId = useTwinStore((s) => s.selectedBuildingId);
  const selectedFloorId = useTwinStore((s) => s.selectedFloorId);

  const items = useMemo(() => {
    const buildingsById = new Map(snapshot.buildings.map((b) => [b.id, b]));
    const out: ZoneItem[] = [];
    let freeLabels = 0;

    for (const z of snapshot.zones) {
      if (selectedFloorId && z.floor_id !== selectedFloorId) continue;
      // §55 — hazard zones stay visible even when the zones layer is off
      if (!selectedFloorId && !zonesOn && z.status === 'NORMAL') continue;
      const b = buildingsById.get(z.building_id);
      if (!b) continue;

      const floorH = b.height / Math.max(1, b.floors);
      const h = z.height > 0 ? Math.min(z.height, floorH * 1.2) : floorH;
      const isFloorZone = Boolean(selectedFloorId) && z.floor_id === selectedFloorId;
      const isSelBuilding = z.building_id === selectedBuildingId;
      const emphasize = isFloorZone || (zonesOn && isSelBuilding && viewMode === 'zones');

      let showLabel = false;
      if (labelsOn) {
        if (isFloorZone) showLabel = true;
        else if (zonesOn && viewMode === 'zones' && freeLabels < MAX_FREE_LABELS) {
          showLabel = true;
          freeLabels += 1;
        }
      }

      out.push({
        zone: z,
        x: b.position.x + z.local_x,
        z: b.position.z + z.local_z,
        y: (Math.max(1, z.floor) - 1) * floorH + h / 2,
        w: z.width > 0 ? z.width : b.size.x * 0.28,
        d: z.depth > 0 ? z.depth : b.size.z * 0.28,
        h,
        emphasize,
        showLabel,
      });
    }
    return out;
  }, [snapshot, zonesOn, labelsOn, viewMode, selectedBuildingId, selectedFloorId]);

  if (items.length === 0) return null;

  return (
    <group>
      {items.map((it) => {
        const hazard = it.zone.status !== 'NORMAL' ? it.zone.status : null;
        const base = hazard ? (HAZARD_COLOR[hazard] ?? '#fbbf24') : zoneTypeColor(it.zone.kind);
        const alpha = hazard ? 0.66 : it.emphasize ? 0.5 : zonesOn && viewMode === 'zones' ? 0.28 : 0.16;
        return (
          <group key={it.zone.id} position={[it.x, it.y, it.z]}>
            <mesh>
              <boxGeometry args={[it.w, it.h, it.d]} />
              <meshStandardMaterial
                color={base}
                transparent
                opacity={alpha}
                emissive={base}
                emissiveIntensity={hazard ? 1.4 : it.emphasize ? 0.55 : 0.18}
                depthWrite={false}
                roughness={0.6}
              />
            </mesh>
            <mesh>
              <boxGeometry args={[it.w + 0.12, it.h + 0.12, it.d + 0.12]} />
              <meshBasicMaterial
                color={base}
                wireframe
                transparent
                opacity={hazard ? 1 : it.emphasize ? 0.95 : 0.4}
              />
            </mesh>
            {hazard && <HazardPulse w={it.w} d={it.d} h={it.h} status={hazard} />}
            {it.showLabel && (
              <Html
                position={[0, it.h / 2 + 1.1, 0]}
                center
                zIndexRange={[16, 0]}
                style={{ pointerEvents: 'none' }}
              >
                <div className="rounded border border-line-strong bg-ink-900/92 px-1.5 py-0.5 shadow-lg backdrop-blur-sm whitespace-nowrap">
                  <span className="text-[9.5px] font-semibold text-mist-100">{it.zone.name}</span>
                  <span className="num ml-1.5 text-[9px] text-mist-400">
                    {fmtNum(it.zone.occupancy)}/{fmtNum(it.zone.capacity)}
                  </span>
                  <span className="ml-1 text-[8.5px] uppercase tracking-wider text-mist-500">
                    {floorLabel(it.zone.floor)}
                  </span>
                </div>
              </Html>
            )}
          </group>
        );
      })}
    </group>
  );
}

export default memo(CampusZones);
