import { useFrame } from '@react-three/fiber';
import { memo, useMemo, useRef } from 'react';
import * as THREE from 'three';
import type { Snapshot, Zone } from '../../types';

interface Placed {
  zone: Zone;
  x: number;
  z: number;
  seed: number;
}

function place(snapshot: Snapshot, zones: Zone[]): Placed[] {
  return zones.map((z, i) => {
    const b = snapshot.buildings.find((bb) => bb.id === z.building_id);
    return {
      zone: z,
      x: (b?.position.x ?? 0) + z.local_x,
      z: (b?.position.z ?? 0) + z.local_z,
      seed: i * 1.7,
    };
  });
}

function FireEffect({ snapshot }: { snapshot: Snapshot }) {
  const sim = snapshot.active_sim;
  const flamesRef = useRef<(THREE.Group | null)[]>([]);
  const smokeRef = useRef<(THREE.Group | null)[]>([]);
  const hazardRef = useRef<THREE.Mesh>(null);
  const lightRef = useRef<THREE.PointLight>(null);

  const burning = useMemo(
    () => place(snapshot, snapshot.zones.filter((z) => z.fire > 0.04 || z.smoke > 4)),
    [snapshot.zones, snapshot.buildings],
  );
  const ignited = useMemo(() => burning.filter((p) => p.zone.fire > 0.04), [burning]);

  const hazard = useMemo(() => {
    if (!ignited.length) return null;
    const cx = ignited.reduce((s, p) => s + p.x, 0) / ignited.length;
    const cz = ignited.reduce((s, p) => s + p.z, 0) / ignited.length;
    let radius = 10;
    for (const p of burning) {
      radius = Math.max(radius, Math.hypot(p.x - cx, p.z - cz) + 6);
    }
    const progress = (sim?.t ?? 0) / Math.max(1, sim?.duration ?? 300);
    return { cx, cz, radius: radius + progress * 14 };
  }, [ignited, burning, sim]);

  useFrame(({ clock }) => {
    const t = clock.elapsedTime;
    flamesRef.current.forEach((g, i) => {
      if (!g) return;
      const s = 0.85 + Math.sin(t * 7 + i) * 0.18;
      g.scale.set(s, 0.9 + Math.sin(t * 5.5 + i * 2) * 0.25, s);
      g.rotation.y = t * (0.6 + i * 0.1);
    });
    smokeRef.current.forEach((g, i) => {
      if (!g) return;
      const cycle = (t * 0.55 + i * 2.3) % 1;
      g.position.y = 3 + cycle * 15;
      g.scale.setScalar(0.7 + cycle * 1.6);
      const mesh = (g.children[0] as THREE.Mesh | undefined) ?? (g as unknown as THREE.Mesh);
      const m = mesh?.material as THREE.MeshBasicMaterial | undefined;
      if (m) m.opacity = Math.max(0, 0.55 * (1 - cycle));
    });
    if (hazardRef.current) {
      const m = hazardRef.current.material as THREE.MeshBasicMaterial;
      m.opacity = 0.12 + Math.sin(t * 2.4) * 0.05;
      hazardRef.current.scale.setScalar(1 + Math.sin(t * 1.6) * 0.015);
    }
    if (lightRef.current && ignited.length) {
      lightRef.current.intensity = 26 + Math.sin(t * 9) * 8;
    }
  });

  if (!ignited.length) return null;

  return (
    <group>
      {hazard && (
        <mesh ref={hazardRef} position={[hazard.cx, 0.24, hazard.cz]} rotation={[-Math.PI / 2, 0, 0]}>
          <ringGeometry args={[Math.max(2, hazard.radius - 2.4), hazard.radius, 48]} />
          <meshBasicMaterial color="#ef4444" transparent opacity={0.16} side={THREE.DoubleSide} />
        </mesh>
      )}

      <pointLight
        ref={lightRef}
        position={[ignited[0].x, 6, ignited[0].z]}
        color="#ff7b24"
        intensity={30}
        distance={70}
        decay={2}
      />

      {burning.map((p, i) => (
        <group key={p.zone.id}>
          {/* floor burn */}
          <mesh position={[p.x, 0.3, p.z]} rotation={[-Math.PI / 2, 0, 0]}>
            <circleGeometry args={[3.4 + p.zone.fire * 2.4, 24]} />
            <meshBasicMaterial
              color={p.zone.fire > 0.04 ? '#ff4d1c' : '#7c2d12'}
              transparent
              opacity={p.zone.fire > 0.04 ? 0.55 : 0.22}
            />
          </mesh>

          {p.zone.fire > 0.04 && (
            <group
              position={[p.x, 0, p.z]}
              ref={(el) => { flamesRef.current[i] = el; }}
            >
              {[0, 1, 2].map((k) => (
                <mesh key={k} position={[(k - 1) * 1.5, 2.1 + k * 0.4, (k % 2) * 1.1]}>
                  <coneGeometry args={[1.25 - k * 0.18, 4.6 - k * 0.7, 10]} />
                  <meshBasicMaterial color={k === 1 ? '#ffb020' : '#ff5a1f'} transparent opacity={0.88} />
                </mesh>
              ))}
              <mesh position={[0, 4.6, 0]}>
                <sphereGeometry args={[1.5, 10, 10]} />
                <meshBasicMaterial color="#ffe08a" transparent opacity={0.5} />
              </mesh>
            </group>
          )}

          {/* smoke plumes */}
          <group
            position={[p.x, 0, p.z]}
            ref={(el) => { smokeRef.current[i * 2] = el; }}
          >
            <mesh>
              <sphereGeometry args={[2.1, 10, 10]} />
              <meshBasicMaterial color={p.zone.fire > 0.04 ? '#57534e' : '#6b7280'} transparent opacity={0.4} />
            </mesh>
          </group>
          <group position={[p.x + 2.5, 0, p.z - 1.5]} ref={(el) => { smokeRef.current[i * 2 + 1] = el; }}>
            <mesh>
              <sphereGeometry args={[1.6, 9, 9]} />
              <meshBasicMaterial color="#6b7280" transparent opacity={0.3} />
            </mesh>
          </group>

          {/* zone status halo */}
          {p.zone.status !== 'NORMAL' && (
            <mesh position={[p.x, 5.4, p.z]} rotation={[-Math.PI / 2, 0, 0]}>
              <ringGeometry args={[3.6, 4.3, 26]} />
              <meshBasicMaterial
                color={p.zone.status === 'FIRE' ? '#ef4444' : p.zone.status === 'SMOKE' ? '#f59e0b' : '#facc15'}
                transparent opacity={0.75}
                side={THREE.DoubleSide}
              />
            </mesh>
          )}
        </group>
      ))}
    </group>
  );
}

export default memo(FireEffect);
