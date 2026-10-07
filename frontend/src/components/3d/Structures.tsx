import { memo } from 'react';
import type { Snapshot } from '../../types';

function Structures({ snapshot, night }: { snapshot: Snapshot; night: boolean }) {
  const gates = snapshot.nodes.filter((n) => n.is_exit);
  return (
    <group>
      {gates.map((gate) => {
        const rot = gate.x === 0 ? 0 : Math.PI / 2;
        const main = gate.id === 'gate_main';
        const w = main ? 16 : 12;
        return (
          <group key={gate.id} position={[gate.x, 0, gate.z]} rotation={[0, rot, 0]}>
            <mesh position={[-w / 2, 3.6, 0]}>
              <boxGeometry args={[1.6, 7.2, 1.6]} />
              <meshStandardMaterial color="#243b63" roughness={0.7} />
            </mesh>
            <mesh position={[w / 2, 3.6, 0]}>
              <boxGeometry args={[1.6, 7.2, 1.6]} />
              <meshStandardMaterial color="#243b63" roughness={0.7} />
            </mesh>
            <mesh position={[0, 7.6, 0]}>
              <boxGeometry args={[w + 2, 1.5, 1.8]} />
              <meshStandardMaterial
                color={main ? '#1d4ed8' : '#7f1d1d'}
                emissive={main ? '#2563eb' : '#b91c1c'}
                emissiveIntensity={night ? 1.1 : 0.55}
                roughness={0.5}
              />
            </mesh>
            <mesh position={[0, 9.6, 0]}>
              <boxGeometry args={[w * 0.6, 1.6, 0.4]} />
              <meshStandardMaterial
                color="#0b1220"
                emissive={main ? '#60a5fa' : '#f87171'}
                emissiveIntensity={0.6}
              />
            </mesh>
            {/* barrier arm */}
            <mesh position={[0, 2.2, 1.4]} rotation={[0, 0, main ? -0.5 : -1.35]}>
              <boxGeometry args={[w * 0.55, 0.3, 0.3]} />
              <meshStandardMaterial color="#e5e7eb" emissive="#ef4444" emissiveIntensity={0.25} />
            </mesh>
          </group>
        );
      })}

      {/* campus entrance plaza markers */}
      <mesh position={[-88, 0.05, 66]} rotation={[-Math.PI / 2, 0, 0]}>
        <circleGeometry args={[7, 24]} />
        <meshStandardMaterial color="#18294a" roughness={1} />
      </mesh>
      <mesh position={[88, 0.05, -66]} rotation={[-Math.PI / 2, 0, 0]}>
        <circleGeometry args={[6, 24]} />
        <meshStandardMaterial color="#26163a" roughness={1} />
      </mesh>
    </group>
  );
}

export default memo(Structures);
