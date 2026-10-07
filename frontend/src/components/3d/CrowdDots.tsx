import { useFrame } from '@react-three/fiber';
import { memo, useEffect, useMemo, useRef } from 'react';
import * as THREE from 'three';
import type { Snapshot } from '../../types';

interface Dot {
  x: number;
  z: number;
  color: string;
  seed: number;
}

function stateColor(ratio: number): string {
  if (ratio >= 1) return '#ef4444';
  if (ratio >= 0.8) return '#f59e0b';
  if (ratio >= 0.6) return '#eab308';
  return '#22c55e';
}

function CrowdDots({ snapshot }: { snapshot: Snapshot }) {
  const meshRef = useRef<THREE.InstancedMesh>(null);

  const dots = useMemo(() => {
    const out: Dot[] = [];
    for (const b of snapshot.buildings) {
      const ratio = b.occupancy / Math.max(1, b.capacity);
      if (ratio < 0.55) continue;
      const count = Math.min(14, Math.round(ratio * 12));
      const color = stateColor(ratio);
      const halfX = b.size.x / 2 + 2.6;
      const halfZ = b.size.z / 2 + 2.6;
      for (let i = 0; i < count; i += 1) {
        const angle = (i / count) * Math.PI * 2;
        const wobble = 0.75 + ((i * 37) % 10) / 14;
        out.push({
          x: b.position.x + Math.cos(angle) * halfX * wobble,
          z: b.position.z + Math.sin(angle) * halfZ * wobble,
          color,
          seed: i * 1.31 + b.id.length,
        });
      }
    }
    return out;
  }, [snapshot.buildings]);

  const dummy = useMemo(() => new THREE.Object3D(), []);

  useEffect(() => {
    const mesh = meshRef.current;
    if (!mesh) return;
    dots.forEach((d, i) => mesh.setColorAt(i, new THREE.Color(d.color)));
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  }, [dots]);

  useFrame(({ clock }) => {
    const mesh = meshRef.current;
    if (!mesh) return;
    const t = clock.elapsedTime;
    dots.forEach((d, i) => {
      dummy.position.set(
        d.x + Math.sin(t * 1.3 + d.seed) * 0.9,
        1.1 + Math.abs(Math.sin(t * 3 + d.seed)) * 0.5,
        d.z + Math.cos(t * 1.1 + d.seed) * 0.9,
      );
      dummy.scale.setScalar(0.9 + Math.sin(t * 2.2 + d.seed) * 0.15);
      dummy.updateMatrix();
      mesh.setMatrixAt(i, dummy.matrix);
    });
    mesh.instanceMatrix.needsUpdate = true;
  });

  if (!dots.length) return null;

  return (
    <instancedMesh ref={meshRef} args={[undefined, undefined, dots.length]} frustumCulled={false}>
      <sphereGeometry args={[0.55, 8, 8]} />
      <meshBasicMaterial toneMapped={false} />
    </instancedMesh>
  );
}

export default memo(CrowdDots);
