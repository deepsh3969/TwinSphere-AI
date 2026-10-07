import { useFrame } from '@react-three/fiber';
import { memo, useMemo, useRef } from 'react';
import * as THREE from 'three';
import type { Snapshot } from '../../types';

function Vehicle({ snapshot }: { snapshot: Snapshot }) {
  const groupRef = useRef<THREE.Group>(null);
  const beaconA = useRef<THREE.Mesh>(null);
  const beaconB = useRef<THREE.Mesh>(null);
  const sim = snapshot.active_sim;

  const path = useMemo(() => {
    if (!sim || sim.scenario !== 'fire') return null;
    const route = snapshot.routes.find((r) => r.building_id === sim.target_id && r.node_path.length > 1)
      ?? snapshot.routes.find((r) => r.node_path.length > 1);
    if (!route) return null;
    const pts = route.node_path
      .map((nid) => snapshot.nodes.find((n) => n.id === nid))
      .filter(Boolean) as { x: number; z: number }[];
    if (pts.length < 2) return null;
    const cum: number[] = [0];
    for (let i = 1; i < pts.length; i += 1) {
      cum.push(cum[i - 1] + Math.hypot(pts[i].x - pts[i - 1].x, pts[i].z - pts[i - 1].z));
    }
    return { pts, cum, total: cum[cum.length - 1] };
  }, [sim, snapshot.routes, snapshot.nodes]);

  useFrame(({ clock }) => {
    if (!groupRef.current || !path) return;
    const t = clock.elapsedTime;
    const travel = (t * 9) % (path.total * 2);
    const d = travel > path.total ? path.total * 2 - travel : travel;
    let seg = 0;
    while (seg < path.cum.length - 2 && path.cum[seg + 1] < d) seg += 1;
    const a = path.pts[seg];
    const b = path.pts[seg + 1];
    const segLen = path.cum[seg + 1] - path.cum[seg] || 1;
    const f = (d - path.cum[seg]) / segLen;
    groupRef.current.position.set(a.x + (b.x - a.x) * f, 0.1, a.z + (b.z - a.z) * f);
    groupRef.current.rotation.y = Math.atan2(-(b.z - a.z), b.x - a.x);

    const flash = Math.sin(t * 12) > 0;
    if (beaconA.current) (beaconA.current.material as THREE.MeshBasicMaterial).opacity = flash ? 1 : 0.2;
    if (beaconB.current) (beaconB.current.material as THREE.MeshBasicMaterial).opacity = flash ? 0.2 : 1;
  });

  if (!path) return null;

  return (
    <group ref={groupRef}>
      <mesh position={[0, 1.1, 0]}>
        <boxGeometry args={[5.4, 2.0, 2.4]} />
        <meshStandardMaterial color="#b91c1c" roughness={0.4} metalness={0.3} />
      </mesh>
      <mesh position={[-0.7, 2.35, 0]}>
        <boxGeometry args={[2.6, 1.3, 2.2]} />
        <meshStandardMaterial color="#7f1d1d" roughness={0.35} />
      </mesh>
      <mesh position={[2.2, 2.6, 0]} ref={beaconA}>
        <boxGeometry args={[0.7, 0.5, 1.9]} />
        <meshBasicMaterial color="#3b82f6" transparent opacity={1} />
      </mesh>
      <mesh position={[1.4, 2.6, 0]} ref={beaconB}>
        <boxGeometry args={[0.7, 0.5, 1.9]} />
        <meshBasicMaterial color="#ef4444" transparent opacity={0.2} />
      </mesh>
      {[-1, 1].map((s) => (
        <mesh key={s} position={[1.6, 0.55, s * 1.25]} rotation={[Math.PI / 2, 0, 0]}>
          <cylinderGeometry args={[0.55, 0.55, 0.4, 10]} />
          <meshStandardMaterial color="#111827" />
        </mesh>
      ))}
      {[-1.7, 1.7].map((s) => (
        <mesh key={s} position={[s, 0.55, s > 0 ? 1.25 : -1.25]} rotation={[Math.PI / 2, 0, 0]}>
          <cylinderGeometry args={[0.55, 0.55, 0.4, 10]} />
          <meshStandardMaterial color="#111827" />
        </mesh>
      ))}
    </group>
  );
}

export default memo(Vehicle);
