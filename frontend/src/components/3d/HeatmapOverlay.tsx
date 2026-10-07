import { memo } from 'react';
import type { Snapshot } from '../../types';
import { riskColor } from '../../utils/colors';

function HeatmapOverlay({ snapshot }: { snapshot: Snapshot }) {
  return (
    <group>
      {snapshot.buildings.map((b) => {
        const radius = 9 + b.risk * 0.22;
        return (
          <group key={b.id} position={[b.position.x, 0.16, b.position.z]}>
            <mesh rotation={[-Math.PI / 2, 0, 0]}>
              <circleGeometry args={[radius, 40]} />
              <meshBasicMaterial
                color={riskColor(b.risk)}
                transparent
                opacity={0.10 + (b.risk / 100) * 0.28}
                blending={2}
                depthWrite={false}
                side={2}
              />
            </mesh>
            <mesh rotation={[-Math.PI / 2, 0, 0]}>
              <ringGeometry args={[radius - 1.2, radius, 40]} />
              <meshBasicMaterial color={riskColor(b.risk)} transparent opacity={0.5} depthWrite={false} side={2} />
            </mesh>
          </group>
        );
      })}
    </group>
  );
}

export default memo(HeatmapOverlay);
