import { memo, useMemo } from 'react';

type P3 = [number, number, number];

/**
 * Phase 7 §18 — direction chevrons along a route polyline.
 * One cone per segment midpoint, yawed to the segment heading so operators
 * can read travel direction at a glance (matches evacuation flow arrows).
 */
function RouteArrows({ points, color, y = 1.75, spacing = 28, size = 0.62 }:
  { points: P3[]; color: string; y?: number; spacing?: number; size?: number }) {
  const arrows = useMemo(() => {
    const out: { pos: P3; yaw: number }[] = [];
    let carry = spacing * 0.5;
    for (let i = 0; i < points.length - 1; i++) {
      const [x1, y1, z1] = points[i];
      const [x2, , z2] = points[i + 1];
      const dx = x2 - x1;
      const dz = z2 - z1;
      const len = Math.hypot(dx, dz);
      if (len < 1e-3) continue;
      const yaw = Math.atan2(dx, dz);
      let t = carry;
      while (t < len) {
        out.push({
          pos: [x1 + (dx * t) / len, y, z1 + (dz * t) / len],
          yaw,
        });
        t += spacing;
      }
      carry = t - len;   // keep spacing continuous across segments
    }
    return out;
  }, [points, spacing, y]);

  if (!arrows.length) return null;
  return (
    <group>
      {arrows.map((a, i) => (
        <group key={i} position={a.pos} rotation={[0, a.yaw, 0]}>
          <mesh rotation={[Math.PI / 2, 0, 0]}>
            <coneGeometry args={[size, size * 2.2, 4]} />
            <meshBasicMaterial color={color} transparent opacity={0.95} />
          </mesh>
        </group>
      ))}
    </group>
  );
}

export default memo(RouteArrows);
