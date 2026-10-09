import { OrbitControls } from '@react-three/drei';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { useEffect, useMemo, useRef } from 'react';
import * as THREE from 'three';
import { useTwinStore } from '../../store/useTwinStore';
import { CAMERA_PRESETS, FOCUS_DISTANCE } from '../../types/twin';
import BuildingBlock from './BuildingBlock';
import CrowdDots from './CrowdDots';
import EvacuationRoutes from './EvacuationRoutes';
import FireEffect from './FireEffect';
import Floor from './Floor';
import Ground from './Ground';
import HeatmapOverlay from './HeatmapOverlay';
import IncidentMarker from './IncidentMarker';
import Labels from './Labels';
import Nature from './Nature';
import Parking from './Parking';
import Roads from './Roads';
import SceneLighting from './SceneLighting';
import SensorMarkers from './SensorMarkers';
import Structures from './Structures';
import Vehicle from './Vehicle';
import CampusZones from './Zone';

interface ControlsLike {
  target: THREE.Vector3;
  update: () => void;
  addEventListener?: (type: string, fn: () => void) => void;
  removeEventListener?: (type: string, fn: () => void) => void;
}

const CAM_POS = new THREE.Vector3();
const CAM_TARGET = new THREE.Vector3();

/**
 * CameraRig (spec §16/§17/§52): smooth, frame-rate-independent fly-to for
 * preset views (reset/top/front/north) and building focus. User drag cancels
 * the animation immediately.
 */
function CameraRig() {
  const focus = useTwinStore((s) => s.focusRequest);
  const viewReq = useTwinStore((s) => s.cameraView);
  const controls = useThree((s) => s.controls) as ControlsLike | null;
  const camera = useThree((s) => s.camera);
  const goal = useRef<{ pos: THREE.Vector3; target: THREE.Vector3 } | null>(null);
  const lastFocusSeq = useRef(0);
  const lastViewSeq = useRef(0);

  useEffect(() => {
    if (!controls) return;
    if (viewReq && viewReq.seq !== lastViewSeq.current) {
      lastViewSeq.current = viewReq.seq;
      const p = CAMERA_PRESETS[viewReq.view];
      goal.current = {
        pos: new THREE.Vector3(...p.pos),
        target: new THREE.Vector3(...p.target),
      };
      return;
    }
    if (focus && focus.seq !== lastFocusSeq.current) {
      lastFocusSeq.current = focus.seq;
      const t = new THREE.Vector3(focus.x, 0, focus.z);
      const dir = camera.position.clone().sub(controls.target);
      if (dir.lengthSq() < 1) dir.set(...CAMERA_PRESETS.iso.pos);
      dir.normalize().multiplyScalar(FOCUS_DISTANCE);
      goal.current = { pos: t.clone().add(dir), target: t };
    }
  }, [focus, viewReq, controls, camera]);

  // cancel fly-to when the user grabs the scene
  useEffect(() => {
    if (!controls?.addEventListener) return;
    const cancel = () => { goal.current = null; };
    controls.addEventListener('start', cancel);
    return () => controls.removeEventListener?.('start', cancel);
  }, [controls]);

  useFrame((_, dt) => {
    const g = goal.current;
    if (!g || !controls) return;
    const k = 1 - Math.exp(-6 * Math.min(dt, 0.1));
    CAM_POS.copy(camera.position).lerp(g.pos, k);
    CAM_TARGET.copy(controls.target).lerp(g.target, k);
    camera.position.copy(CAM_POS);
    controls.target.copy(CAM_TARGET);
    controls.update();
    if (camera.position.distanceTo(g.pos) < 0.5) {
      camera.position.copy(g.pos);
      controls.target.copy(g.target);
      controls.update();
      goal.current = null;
    }
  });

  return null;
}

function parseFloorNumber(floorId: string): number | null {
  const m = /F(\d+)$/.exec(floorId);
  return m ? Number(m[1]) : null;
}

export default function CampusScene({ height = 'h-full' }: { height?: string }) {
  // Phase 9 §63 — replay renders persisted frames; live is the default.
  const snapshot = useTwinStore((s) => s.replaySnapshot ?? s.snapshot);
  const toggles = useTwinStore((s) => s.toggles);
  const selectBuilding = useTwinStore((s) => s.selectBuilding);
  const selectedId = useTwinStore((s) => s.selectedBuildingId);
  const selectedFloorId = useTwinStore((s) => s.selectedFloorId);

  const bg = toggles.night ? '#070b14' : '#0b1426';
  const eventsKey = useMemo(() => snapshot?.active_sim?.id ?? 'none', [snapshot?.active_sim?.id]);

  const selectedBuilding = useMemo(
    () => snapshot?.buildings.find((b) => b.id === selectedId) ?? null,
    [snapshot, selectedId],
  );
  const selectedFloorNumber = selectedFloorId ? parseFloorNumber(selectedFloorId) : null;

  if (!snapshot) {
    return (
      <div className={`${height} flex items-center justify-center bg-ink-950`}>
        <div className="text-center">
          <div className="w-10 h-10 mx-auto mb-3 border-2 border-brand-400 border-t-transparent rounded-full animate-spin" />
          <div className="label-cap">Loading digital twin…</div>
          <p className="text-[12px] text-mist-500 mt-1">Waiting for live campus state</p>
        </div>
      </div>
    );
  }

  return (
    <div className={`${height} relative bg-ink-950`}>
      <Canvas
        dpr={[1, 1.75]}
        camera={{ position: [118, 96, 132], fov: 42, near: 1, far: 900 }}
        gl={{ antialias: true }}
        onPointerMissed={() => selectBuilding(null)}
      >
        <color attach="background" args={[bg]} />
        <SceneLighting night={toggles.night} />

        <Ground snapshot={snapshot} grid={toggles.grid} night={toggles.night} />
        {toggles.roads && <Roads snapshot={snapshot} />}
        {toggles.roads && <Structures snapshot={snapshot} night={toggles.night} />}
        {toggles.parking && <Parking night={toggles.night} />}
        {toggles.trees && <Nature night={toggles.night} />}

        {toggles.buildings && snapshot.buildings.map((b) => (
          <BuildingBlock
            key={b.id}
            building={b}
            selected={selectedId === b.id}
            onSelect={() => void selectBuilding(b.id)}
            night={toggles.night}
            xray={toggles.zones || (selectedId === b.id && Boolean(selectedFloorId))}
          />
        ))}

        {selectedBuilding && selectedFloorNumber !== null && (
          <Floor building={selectedBuilding} floorNumber={selectedFloorNumber} />
        )}

        <CampusZones snapshot={snapshot} />
        <IncidentMarker snapshot={snapshot} />

        {toggles.heatmap && <HeatmapOverlay snapshot={snapshot} />}
        {toggles.occupancy && <CrowdDots snapshot={snapshot} />}
        {toggles.sensors && <SensorMarkers snapshot={snapshot} />}
        {toggles.routes && <EvacuationRoutes snapshot={snapshot} />}
        {snapshot.active_sim && snapshot.active_sim.scenario === 'fire' && (
          <FireEffect key={eventsKey} snapshot={snapshot} />
        )}
        <Vehicle snapshot={snapshot} />

        {toggles.labels && <Labels snapshot={snapshot} />}

        <CameraRig />
        <OrbitControls
          makeDefault
          enableDamping
          dampingFactor={0.08}
          minDistance={18}
          maxDistance={340}
          maxPolarAngle={Math.PI / 2.15}
        />
      </Canvas>
    </div>
  );
}
