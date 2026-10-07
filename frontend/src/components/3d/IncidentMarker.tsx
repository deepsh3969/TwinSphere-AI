import { Html } from '@react-three/drei';
import { useFrame } from '@react-three/fiber';
import { memo, useRef } from 'react';
import * as THREE from 'three';
import type { Snapshot } from '../../types';

const SEVERITY_COLOR: Record<string, string> = {
  LOW: '#eab308',
  MEDIUM: '#f59e0b',
  HIGH: '#f97316',
  CRITICAL: '#ef4444',
};

function severityColor(severity: string): string {
  return SEVERITY_COLOR[severity.toUpperCase()] ?? '#f59e0b';
}

/**
 * Incident markers (spec §48) — ready for Phase 6.
 * Renders ONLY incidents the backend reports as ACTIVE (real API data);
 * nothing is simulated in Phase 3. Future phases extend this component with
 * click-through details, propagation rings and timeline linkage.
 */
function IncidentMarkers({ snapshot }: { snapshot: Snapshot }) {
  const active = snapshot.incidents.filter((i) => i.status === 'ACTIVE');
  if (active.length === 0) return null;

  const buildingsById = new Map(snapshot.buildings.map((b) => [b.id, b]));

  return (
    <group>
      {active.map((incident) => {
        const building = incident.building_id ? buildingsById.get(incident.building_id) : undefined;
        if (!building) return null;
        const color = severityColor(incident.severity);
        return (
          <IncidentBeacon
            key={incident.id}
            x={building.position.x}
            y={building.height + 5.5}
            z={building.position.z}
            color={color}
            title={incident.title}
            severity={incident.severity}
          />
        );
      })}
    </group>
  );
}

function IncidentBeacon({
  x, y, z, color, title, severity,
}: {
  x: number; y: number; z: number; color: string;
  title: string; severity: string;
}) {
  const meshRef = useRef<THREE.Mesh>(null);

  useFrame((_, dt) => {
    if (meshRef.current) meshRef.current.rotation.y += dt * 0.9;
  });

  return (
    <group position={[x, y, z]}>
      <mesh ref={meshRef}>
        <octahedronGeometry args={[1.5, 0]} />
        <meshBasicMaterial color={color} toneMapped={false} />
      </mesh>
      <mesh>
        <octahedronGeometry args={[2.3, 0]} />
        <meshBasicMaterial color={color} wireframe transparent opacity={0.45} />
      </mesh>
      <Html position={[0, 3.6, 0]} center zIndexRange={[19, 0]} style={{ pointerEvents: 'none' }}>
        <div
          className="rounded border bg-ink-900/95 px-1.5 py-0.5 shadow-lg whitespace-nowrap"
          style={{ borderColor: color }}
        >
          <span className="text-[9.5px] font-bold" style={{ color }}>{severity}</span>
          <span className="ml-1.5 text-[9.5px] text-mist-200">{title}</span>
        </div>
      </Html>
    </group>
  );
}

export default memo(IncidentMarkers);
