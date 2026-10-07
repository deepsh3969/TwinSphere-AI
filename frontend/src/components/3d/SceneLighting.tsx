import { memo } from 'react';

/** Professional scene lighting rig (spec §36): ambient + directional + hemisphere + fog. */
function SceneLighting({ night }: { night: boolean }) {
  return (
    <>
      <ambientLight intensity={night ? 0.35 : 0.85} color={night ? '#4c6fb5' : '#dfe9ff'} />
      <directionalLight
        position={night ? [-70, 60, -40] : [90, 120, 60]}
        intensity={night ? 0.55 : 1.15}
        color={night ? '#89a7ff' : '#ffffff'}
      />
      <hemisphereLight args={[night ? '#1b2b52' : '#bcd4ff', night ? '#0a0f1c' : '#26344f', night ? 0.35 : 0.5]} />
      <fog attach="fog" args={[night ? '#070b14' : '#0a1223', 240, 520]} />
    </>
  );
}

export default memo(SceneLighting);
