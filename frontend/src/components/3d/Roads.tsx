import { memo, useMemo } from 'react';
import type { Snapshot } from '../../types';

function segColor(road: { blocked: boolean; risk: number; congestion: number }): string {
  if (road.blocked) return '#ef4444';
  if (road.risk > 60) return '#f97316';
  if (road.congestion > 0.6) return '#eab308';
  if (road.congestion > 0.3) return '#3b5f9e';
  return '#243b63';
}

/**
 * Campus roads (spec §12) from Phase 2 road data: surface + sidewalks +
 * lane dashes. Road states map to color (OPEN default) and BLOCKED renders a
 * closure bar — prepared for future road-closure simulation.
 */
function Roads({ snapshot }: { snapshot: Snapshot }) {
  const strips = useMemo(() => {
    return snapshot.roads.map((road) => {
      const a = snapshot.nodes.find((n) => n.id === road.from_node);
      const b = snapshot.nodes.find((n) => n.id === road.to_node);
      if (!a || !b) return null;
      const dx = b.x - a.x;
      const dz = b.z - a.z;
      const len = Math.hypot(dx, dz);
      return {
        id: road.id,
        x: (a.x + b.x) / 2,
        z: (a.z + b.z) / 2,
        len,
        rot: Math.atan2(dz, dx),
        color: segColor(road),
        blocked: road.blocked,
        congestion: road.congestion,
      };
    }).filter(Boolean) as Array<{
      id: string; x: number; z: number; len: number; rot: number;
      color: string; blocked: boolean; congestion: number;
    }>;
  }, [snapshot.roads, snapshot.nodes]);

  return (
    <group>
      {strips.map((s) => (
        <group key={s.id} position={[s.x, 0.08, s.z]} rotation={[0, -s.rot, 0]}>
          {/* sidewalks flanking the surface */}
          <mesh position={[0, 0.0, 3.6]} rotation={[0, 0, 0]}>
            <boxGeometry args={[s.len, 0.1, 1.9]} />
            <meshStandardMaterial color="#26334d" roughness={1} />
          </mesh>
          <mesh position={[0, 0.0, -3.6]}>
            <boxGeometry args={[s.len, 0.1, 1.9]} />
            <meshStandardMaterial color="#26334d" roughness={1} />
          </mesh>
          {/* road surface */}
          <mesh>
            <boxGeometry args={[s.len, 0.12, 5.2]} />
            <meshStandardMaterial color={s.color} roughness={0.9} />
          </mesh>
          {/* centre dashes */}
          <mesh position={[0, 0.09, 0]}>
            <boxGeometry args={[s.len * 0.9, 0.02, 0.28]} />
            <meshStandardMaterial
              color={s.blocked ? '#fecaca' : '#7f9ccf'}
              transparent
              opacity={s.blocked ? 0.9 : 0.55}
            />
          </mesh>
          {s.blocked && (
            <mesh position={[0, 0.5, 0]}>
              <boxGeometry args={[Math.min(s.len, 6), 1.4, 0.5]} />
              <meshStandardMaterial color="#ef4444" emissive="#b91c1c" emissiveIntensity={0.7} />
            </mesh>
          )}
        </group>
      ))}
    </group>
  );
}

export default memo(Roads);
