import { Html } from '@react-three/drei';
import { memo } from 'react';

type P3 = [number, number, number];

/**
 * Phase 7 §18 — origin / destination markers for the active route.
 * Origin: filled sphere + label pole. Destination: double ring + label.
 */
function RouteMarkers({ origin, destination, color, originLabel, destinationLabel }:
  { origin: P3 | null; destination: P3 | null; color: string;
    originLabel?: string; destinationLabel?: string }) {
  return (
    <group>
      {origin && (
        <group position={origin}>
          <mesh>
            <sphereGeometry args={[0.85, 16, 16]} />
            <meshBasicMaterial color={color} />
          </mesh>
          <mesh position={[0, 1.6, 0]}>
            <cylinderGeometry args={[0.08, 0.08, 3.2, 6]} />
            <meshBasicMaterial color={color} transparent opacity={0.75} />
          </mesh>
          {originLabel && (
            <Html position={[0, 3.8, 0]} center distanceFactor={90} zIndexRange={[10, 0]}>
              <div className="rounded bg-ink-950/90 border border-line px-1.5 py-0.5
                              text-[9.5px] uppercase tracking-wider text-brand-200
                              whitespace-nowrap pointer-events-none">
                {originLabel}
              </div>
            </Html>
          )}
        </group>
      )}
      {destination && (
        <group position={destination}>
          <mesh rotation={[-Math.PI / 2, 0, 0]}>
            <ringGeometry args={[1.7, 2.9, 32]} />
            <meshBasicMaterial color={color} transparent opacity={0.9} side={2} />
          </mesh>
          <mesh>
            <sphereGeometry args={[0.7, 16, 16]} />
            <meshBasicMaterial color={color} />
          </mesh>
          {destinationLabel && (
            <Html position={[0, 3.4, 0]} center distanceFactor={90} zIndexRange={[10, 0]}>
              <div className="rounded bg-ink-950/90 border border-line px-1.5 py-0.5
                              text-[9.5px] uppercase tracking-wider text-brand-200
                              whitespace-nowrap pointer-events-none">
                {destinationLabel}
              </div>
            </Html>
          )}
        </group>
      )}
    </group>
  );
}

export default memo(RouteMarkers);
