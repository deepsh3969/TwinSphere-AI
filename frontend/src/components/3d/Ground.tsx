import { Grid } from '@react-three/drei';
import { memo } from 'react';
import type { Snapshot } from '../../types';

function Ground({ snapshot, grid, night }: { snapshot: Snapshot; grid: boolean; night: boolean }) {
  const greens = [
    { x: -75, z: -12, r: 14 },
    { x: 75, z: -14, r: 12 },
    { x: -20, z: 62, r: 16 },
    { x: 32, z: -48, r: 10 },
    { x: -78, z: 66, r: 12 },
    { x: 84, z: 44, r: 14 },
  ];
  return (
    <group>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.05, 0]} receiveShadow={false}>
        <planeGeometry args={[300, 240]} />
        <meshStandardMaterial color={night ? '#0c1424' : '#152238'} roughness={1} />
      </mesh>

      {/* central courtyard */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.01, -2]}>
        <planeGeometry args={[52, 40]} />
        <meshStandardMaterial color={night ? '#111b2e' : '#1c2c47'} roughness={0.95} />
      </mesh>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.02, -2]}>
        <ringGeometry args={[7, 9, 40]} />
        <meshStandardMaterial color={night ? '#1d3357' : '#2f5fa8'} roughness={0.8} />
      </mesh>

      {/* green areas */}
      {greens.map((g, i) => (
        <mesh key={i} rotation={[-Math.PI / 2, 0, 0]} position={[g.x, 0.005, g.z]}>
          <circleGeometry args={[g.r, 28]} />
          <meshStandardMaterial color={night ? '#0f2118' : '#1b4030'} roughness={1} />
        </mesh>
      ))}

      {/* campus boundary */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.03, 0]}>
        <ringGeometry args={[118, 120, 4, 1, Math.PI / 4]} />
        <meshStandardMaterial color="#22406e" transparent opacity={0.5} />
      </mesh>

      {grid && (
        <Grid
          position={[0, 0.06, 0]}
          args={[300, 240]}
          cellSize={10}
          cellThickness={0.5}
          cellColor={night ? '#16233d' : '#1c2d4c'}
          sectionSize={50}
          sectionThickness={0.9}
          sectionColor={night ? '#23406e' : '#2b62ff'}
          fadeDistance={420}
          fadeStrength={1.2}
          infiniteGrid={false}
        />
      )}
    </group>
  );
}

export default memo(Ground);
