import { Html } from '@react-three/drei';
import { memo } from 'react';
import type { Building } from '../../types';
import { floorLabel } from '../../types/twin';

interface Props {
  building: Building;
  floorNumber: number;
}

/**
 * Selected-floor highlight (spec §9/§51): a protruding glowing band around the
 * building at the selected floor level + a floor plate. Rendered together with
 * the building's x-ray mode so interior zones/sensors become visible.
 */
function Floor({ building, floorNumber }: Props) {
  const floorH = building.height / Math.max(1, building.floors);
  const y = (floorNumber - 1) * floorH + floorH / 2;

  return (
    <group position={[building.position.x, 0, building.position.z]}>
      <mesh position={[0, y, 0]} renderOrder={2}>
        <boxGeometry args={[building.size.x + 1.8, floorH * 0.96, building.size.z + 1.8]} />
        <meshStandardMaterial
          color="#1d4ed8"
          transparent
          opacity={0.22}
          emissive="#3b82f6"
          emissiveIntensity={0.9}
          depthWrite={false}
          roughness={0.4}
        />
      </mesh>
      <mesh position={[0, y, 0]} renderOrder={3}>
        <boxGeometry args={[building.size.x + 1.9, floorH, building.size.z + 1.9]} />
        <meshBasicMaterial color="#60a5fa" wireframe transparent opacity={0.75} />
      </mesh>
      <Html
        position={[building.size.x / 2 + 4.5, y, 0]}
        center
        zIndexRange={[18, 0]}
        style={{ pointerEvents: 'none' }}
      >
        <div className="rounded border border-brand-400/70 bg-ink-900/95 px-1.5 py-0.5 shadow-lg shadow-blue-950/60 whitespace-nowrap">
          <span className="text-[9.5px] font-bold uppercase tracking-widest text-brand-300">
            {floorLabel(floorNumber)}
          </span>
        </div>
      </Html>
    </group>
  );
}

export default memo(Floor);
