import { memo, useEffect, useMemo, useRef } from 'react';
import * as THREE from 'three';

const CAR_COLORS = ['#3b82f6', '#e5e7eb', '#ef4444', '#111827', '#f59e0b', '#14b8a6', '#8b5cf6', '#64748b'];
const CAR_SPOTS: [number, number, number][] = [
  [49, 42, 0], [55, 42, 0], [61, 42, 0], [67, 42, 0],
  [49, 47, Math.PI], [55, 47, Math.PI], [61, 47, Math.PI], [67, 47, Math.PI],
];

function Parking({ night }: { night: boolean }) {
  const carRefs = useRef<(THREE.Mesh | null)[]>([]);

  useEffect(() => {
    carRefs.current.forEach((m, i) => {
      if (!m) return;
      const mat = m.material as THREE.MeshStandardMaterial;
      mat.color.set(CAR_COLORS[i % CAR_COLORS.length]);
    });
  }, []);

  const slots = useMemo(() => Array.from({ length: 9 }, (_, i) => 46 + i * 3.4), []);

  return (
    <group position={[58, 0, 44.5]}>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.03, 0]}>
        <planeGeometry args={[30, 13]} />
        <meshStandardMaterial color={night ? '#0f1626' : '#1a2437'} roughness={1} />
      </mesh>
      {slots.map((x, i) => (
        <mesh key={i} rotation={[-Math.PI / 2, 0, 0]} position={[x - 58, 0.05, 0]}>
          <planeGeometry args={[0.25, 11]} />
          <meshBasicMaterial color="#47577d" />
        </mesh>
      ))}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.05, 6.2]}>
        <planeGeometry args={[30, 0.3]} />
        <meshBasicMaterial color="#47577d" />
      </mesh>
      {CAR_SPOTS.map(([x, z, r], i) => (
        <mesh
          key={i}
          position={[x - 58, 0.9, z - 44.5]}
          rotation={[0, r, 0]}
          ref={(el) => { carRefs.current[i] = el; }}
        >
          <boxGeometry args={[4.2, 1.5, 1.9]} />
          <meshStandardMaterial color="#3b82f6" roughness={0.35} metalness={0.5} />
        </mesh>
      ))}
      {/* parking sign */}
      <mesh position={[0, 3.4, -6.8]}>
        <boxGeometry args={[4.4, 2.2, 0.2]} />
        <meshStandardMaterial color="#1d4ed8" emissive="#1e40af" emissiveIntensity={0.55} />
      </mesh>
      <mesh position={[0, 1.5, -6.8]}>
        <cylinderGeometry args={[0.16, 0.16, 3, 6]} />
        <meshStandardMaterial color="#47577d" />
      </mesh>
    </group>
  );
}

export default memo(Parking);
