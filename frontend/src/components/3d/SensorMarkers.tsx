import { Html } from '@react-three/drei';
import { useFrame } from '@react-three/fiber';
import { memo, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import * as THREE from 'three';
import { useTwinStore } from '../../store/useTwinStore';
import type { Sensor, Snapshot } from '../../types';
import { sensorTypeColor, sensorTypeLabel } from '../../types/twin';
import { getRiskColor, levelChip } from '../../utils/colors';

function fmtTime(epochSec: number): string {
  if (!epochSec) return '—';
  const d = new Date(epochSec * 1000);
  return d.toLocaleTimeString(undefined, { hour12: false });
}

function markerY(sensor: Sensor, buildingsById: Map<string, { height: number }>): number {
  const b = sensor.building_id ? buildingsById.get(sensor.building_id) : undefined;
  if (b) return b.height + 2.2; // float above the roofline so markers are always visible
  return (sensor.y ?? 0) + 2.2;
}

function isDynamic(s: Sensor, selectedId: string | null): boolean {
  return s.id === selectedId || !s.healthy || s.status === 'OFFLINE'
    || (s.type === 'smoke' && s.value > 10);
}

// scratch objects — zero per-frame allocation in the pulse loop
const SCRATCH_MAT = new THREE.Matrix4();
const SCRATCH_QUAT = new THREE.Quaternion();
const SCRATCH_SCALE = new THREE.Vector3();
const SCRATCH_POS = new THREE.Vector3();

/**
 * Sensor markers (spec §19/§20/§22): instanced, type-filtered, clickable,
 * hover tooltip with SIMULATED source labelling. Only the small dynamic
 * subset (warn/selected) is animated per frame — static instances are
 * written once in a layout effect.
 */
function SensorMarkers({ snapshot }: { snapshot: Snapshot }) {
  const filter = useTwinStore((s) => s.sensorFilter);
  const selectedId = useTwinStore((s) => s.selectedSensorId);
  const selectSensor = useTwinStore((s) => s.selectSensor);
  const viewMode = useTwinStore((s) => s.viewMode);
  const sensorAiStatus = useTwinStore((s) => s.sensorAiStatus);
  const [hoveredId, setHoveredId] = useState<string | null>(null);

  const meshRef = useRef<THREE.InstancedMesh>(null);
  const poleRef = useRef<THREE.InstancedMesh>(null);

  const buildingsById = useMemo(
    () => new Map(snapshot.buildings.map((b) => [b.id, b])),
    [snapshot.buildings],
  );

  const sensors = useMemo(
    () => (filter === 'all' ? snapshot.sensors : snapshot.sensors.filter((s) => s.type === filter)),
    [snapshot.sensors, filter],
  );

  // Phase 5 — AI anomaly band per sensor id (NORMAL/INSUFFICIENT skipped)
  const anomStatus = useMemo(() => {
    const m = new Map<string, string>();
    for (const [id, st] of Object.entries(sensorAiStatus ?? {})) {
      if (st && st.status && st.status !== 'NORMAL' && st.status !== 'INSUFFICIENT_DATA') m.set(id, st.status);
    }
    return m;
  }, [sensorAiStatus]);

  const emphasis = viewMode === 'sensors' ? 1.4 : 1;
  const source = snapshot.data_source ?? snapshot.metadata?.data_source ?? 'SIMULATED';

  const basePos = useMemo(
    () => sensors.map((s) => new THREE.Vector3(s.x, markerY(s, buildingsById), s.z)),
    [sensors, buildingsById],
  );

  const colorFor = useMemo(() => (s: Sensor) => {
    if (s.id === selectedId) return new THREE.Color('#ffffff');
    if (s.status === 'OFFLINE') return new THREE.Color('#94a3b8');
    const band = anomStatus.get(s.id);
    // flagged sensors shift to their anomaly band colour — colour is never
    // the only signal: the marker also pulses and carries a "!" badge
    if (band) return new THREE.Color(band === 'MODERATE' ? '#eab308' : band === 'LOW' ? '#38bdf8' : getRiskColor(band));
    if (!s.healthy) return new THREE.Color('#ef4444');
    return new THREE.Color(sensorTypeColor(s.type));
  }, [selectedId, anomStatus]);

  // Live telemetry replaces sensor objects every tick — gate the expensive
  // instance writes by what actually changed: geometry (ids/positions/filter)
  // for matrices, visual flags for colors. A 2 s sensor update that moves
  // nothing rewrites neither buffer (Phase 4 §43: no full-scene rework).
  const geoKey = useMemo(
    () => sensors.map((s) => `${s.id}:${s.x}:${s.z}:${s.building_id ?? ''}`).join('|'),
    [sensors],
  );
  const colorKey = useMemo(
    () => sensors.map((s) =>
      `${s.id === selectedId ? 'S' : ''}${s.status}${s.healthy ? '1' : '0'}:${anomStatus.get(s.id) ?? ''}`).join('|'),
    [sensors, selectedId, anomStatus],
  );

  // static instance matrices + poles (written only when geometry changes)
  useLayoutEffect(() => {
    const mesh = meshRef.current;
    if (!mesh) return;
    const m = new THREE.Matrix4();
    const q = new THREE.Quaternion();
    const sc = new THREE.Vector3(emphasis, emphasis, emphasis);
    sensors.forEach((s, i) => {
      const y = basePos[i]?.y ?? 2.2;
      m.compose(new THREE.Vector3(s.x, y, s.z), q, sc);
      mesh.setMatrixAt(i, m);
    });
    mesh.instanceMatrix.needsUpdate = true;

    const poles = poleRef.current;
    if (poles) {
      const pc = new THREE.Color('#31435f');
      sensors.forEach((s, i) => {
        const hasPole = !s.building_id;
        const top = basePos[i]?.y ?? 2.2;
        if (hasPole) {
          m.compose(new THREE.Vector3(s.x, top / 2, s.z), q, new THREE.Vector3(1, top, 1));
        } else {
          m.compose(new THREE.Vector3(0, -100, 0), q, new THREE.Vector3(0.001, 0.001, 0.001));
        }
        poles.setMatrixAt(i, m);
        poles.setColorAt(i, pc);
      });
      poles.instanceMatrix.needsUpdate = true;
      if (poles.instanceColor) poles.instanceColor.needsUpdate = true;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed by geoKey/emphasis
  }, [geoKey, emphasis, sensors, basePos]);

  // instance colors (written only when selection/health changes)
  useLayoutEffect(() => {
    const mesh = meshRef.current;
    if (!mesh) return;
    sensors.forEach((s, i) => mesh.setColorAt(i, colorFor(s)));
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed by colorKey
  }, [colorKey, sensors, colorFor]);

  const dynamicIdx = useMemo(
    () => sensors
      .map((s, i) => (isDynamic(s, selectedId) || anomStatus.has(s.id) ? i : -1))
      .filter((i) => i >= 0),
    [sensors, selectedId, anomStatus],
  );

  // marker position lookup for the "!" anomaly badges
  const posById = useMemo(
    () => new Map(sensors.map((s, i) => [s.id, basePos[i]] as const)),
    [sensors, basePos],
  );

  // drop a tooltip if its sensor left the filtered set
  useEffect(() => {
    if (hoveredId && !sensors.some((s) => s.id === hoveredId)) setHoveredId(null);
  }, [sensors, hoveredId]);

  useFrame(({ clock }) => {
    const mesh = meshRef.current;
    if (!mesh || dynamicIdx.length === 0) return;
    const t = clock.elapsedTime;
    for (const i of dynamicIdx) {
      const s = sensors[i];
      const base = basePos[i];
      if (!s || !base) continue;
      const pulse = s.id === selectedId
        ? 1.6 + Math.sin(t * 5) * 0.4
        : 1.3 + Math.sin(t * 6 + i) * 0.4;
      const sc = pulse * emphasis;
      SCRATCH_SCALE.set(sc, sc, sc);
      SCRATCH_MAT.compose(base, SCRATCH_QUAT, SCRATCH_SCALE);
      mesh.setMatrixAt(i, SCRATCH_MAT);
    }
    mesh.instanceMatrix.needsUpdate = true;
  });

  const handlePoint = (e: { instanceId?: number; stopPropagation: () => void }, over: boolean) => {
    e.stopPropagation();
    const idx = e.instanceId;
    if (idx === undefined) return;
    const s = sensors[idx];
    if (!s) return;
    if (over) {
      setHoveredId(s.id);
      document.body.style.cursor = 'pointer';
    } else {
      setHoveredId(null);
      document.body.style.cursor = 'auto';
    }
  };

  if (sensors.length === 0) {
    return (
      <div hidden data-testid="no-sensor-markers" />
    );
  }

  const selected = selectedId ? sensors.find((s) => s.id === selectedId) : null;
  // derive the hovered sensor fresh each render so the tooltip shows live
  // values even while the pointer stays put (Phase 4 §43)
  const hovered = hoveredId ? sensors.find((s) => s.id === hoveredId) ?? null : null;
  const hoveredAi = hovered ? sensorAiStatus[hovered.id] : null;
  const flagged = sensors.filter((s) => anomStatus.has(s.id)).slice(0, 24);

  return (
    <group>
      <instancedMesh
        ref={meshRef}
        args={[undefined, undefined, sensors.length]}
        frustumCulled={false}
        onClick={(e) => {
          e.stopPropagation();
          const s = e.instanceId !== undefined ? sensors[e.instanceId] : undefined;
          if (s) selectSensor(s.id);
        }}
        onPointerOver={(e) => handlePoint(e, true)}
        onPointerOut={(e) => handlePoint(e, false)}
      >
        <sphereGeometry args={[0.8, 10, 10]} />
        <meshBasicMaterial toneMapped={false} />
      </instancedMesh>

      {/* poles for outdoor sensors */}
      <instancedMesh
        ref={poleRef}
        args={[undefined, undefined, sensors.length]}
        frustumCulled={false}
      >
        <cylinderGeometry args={[0.06, 0.06, 1, 5]} />
        <meshStandardMaterial color="#31435f" />
      </instancedMesh>

      {/* selected sensor ring */}
      {selected && (
        <SelectedRing
          position={[
            selected.x,
            (basePos[sensors.indexOf(selected)]?.y ?? 2.2) - 0.4,
            selected.z,
          ]}
        />
      )}

      {/* Phase 5 — anomaly "!" badges (icon + pulse + colour, never colour alone) */}
      {flagged.map((s) => {
        const band = anomStatus.get(s.id);
        if (!band) return null;
        const pos = posById.get(s.id);
        if (!pos) return null;
        return (
          <Html
            key={`ai-${s.id}`}
            position={[s.x, pos.y + 1.5, s.z]}
            center
            zIndexRange={[20, 0]}
            style={{ pointerEvents: 'none' }}
          >
            <div className={`chip !text-[10px] !px-1 font-bold border ${levelChip(band)}`} title={`AI anomaly: ${band}`}>
              !
            </div>
          </Html>
        );
      })}

      {/* hover tooltip (spec §20) */}
      {hovered && (
        <Html
          position={[hovered.x, (basePos[sensors.indexOf(hovered)]?.y ?? 2.2) + 1.6, hovered.z]}
          center
          zIndexRange={[30, 0]}
          style={{ pointerEvents: 'none' }}
        >
          <div className="rounded-md border border-line-strong bg-ink-900/96 px-2.5 py-2 shadow-xl shadow-black/60 min-w-[176px]">
            <div className="flex items-center gap-1.5">
              <span
                className="w-2 h-2 rounded-full shrink-0"
                style={{ background: sensorTypeColor(hovered.type) }}
              />
              <span className="num text-[11px] font-bold text-white">
                {hovered.sensor_code || hovered.id}
              </span>
            </div>
            <div className="mt-1 flex items-baseline justify-between gap-3">
              <span className="text-[10px] uppercase tracking-wider text-mist-500">
                {sensorTypeLabel(hovered.type)}
              </span>
              <span className="num text-[13px] font-bold text-mist-100">
                {hovered.value.toFixed(hovered.type === 'energy' ? 1 : 2)}
                <span className="text-[10px] text-mist-400 ml-0.5">{hovered.unit}</span>
              </span>
            </div>
            <div className="mt-1 flex items-center justify-between text-[10px]">
              <span className={hovered.status === 'ONLINE' ? 'text-emerald-400' : 'text-red-400'}>
                ● {hovered.status}
              </span>
              <span className="num text-mist-500">{fmtTime(hovered.updated_at)}</span>
            </div>
            <div className="mt-1 pt-1 border-t border-line flex items-center justify-between text-[9.5px]">
              <span className="uppercase tracking-wider text-mist-500">Source</span>
              <span className="font-bold text-amber-300">{source}</span>
            </div>
            {/* Phase 5 — AI status row (status derived server-side; absent when unknown) */}
            {hoveredAi && hoveredAi.status && hoveredAi.status !== 'NORMAL' && hoveredAi.status !== 'INSUFFICIENT_DATA' && (
              <div className="mt-1 pt-1 border-t border-line flex items-center justify-between text-[9.5px]">
                <span className="uppercase tracking-wider text-mist-500">AI Status</span>
                <span className="font-bold" style={{ color: getRiskColor(hoveredAi.status) }}>
                  {hoveredAi.status}
                  {typeof hoveredAi.score === 'number' ? ` · ${hoveredAi.score}` : ''}
                </span>
              </div>
            )}
          </div>
        </Html>
      )}
    </group>
  );
}

function SelectedRing({ position }: { position: [number, number, number] }) {
  const ref = useRef<THREE.Mesh>(null);
  useFrame(({ clock }) => {
    if (ref.current) {
      const s = 1 + Math.sin(clock.elapsedTime * 4) * 0.18;
      ref.current.scale.set(s, s, 1);
    }
  });
  return (
    <mesh ref={ref} position={position} rotation={[-Math.PI / 2, 0, 0]}>
      <ringGeometry args={[1.5, 2.1, 28]} />
      <meshBasicMaterial color="#ffffff" transparent opacity={0.85} toneMapped={false} side={THREE.DoubleSide} />
    </mesh>
  );
}

export default memo(SensorMarkers);
