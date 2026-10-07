import { Line } from '@react-three/drei';
import { memo, useMemo } from 'react';
import { useTwinStore } from '../../store/useTwinStore';
import type { Snapshot } from '../../types';
import { vehicleColor } from '../../utils/colors';

type P3 = [number, number, number];

/**
 * Phase 7 §16 — emergency vehicle response routes (dashed, per-vehicle color).
 * Fed by `GET /api/emergency-response/routes` (activate=False — display only).
 */
function EmergencyRoutes({ snapshot }: { snapshot: Snapshot }) {
  const routes = useTwinStore((s) => s.emergencyRoutes);
  const nodeById = useMemo(
    () => new Map(snapshot.nodes.map((n) => [n.id, n])), [snapshot.nodes]);

  return (
    <group>
      {routes.map((r) => {
        if (!r.node_path?.length && !r.path?.length) return null;
        const ids = r.node_path?.length ? r.node_path : r.path;
        const points = ids
          .map((nid) => {
            const n = nodeById.get(nid);
            return n ? ([n.x, 2.3, n.z] as P3) : null;
          })
          .filter((p): p is P3 => p !== null);
        if (points.length < 2) return null;
        const color = vehicleColor(r.vehicle);
        return (
          <group key={`${r.vehicle}-${r.origin}-${r.destination}`}>
            <Line
              points={points}
              color={color}
              lineWidth={2.2}
              dashed
              transparent
              opacity={r.status === 'NO_SAFE_ROUTE' ? 0.25 : 0.8}
            />
          </group>
        );
      })}
    </group>
  );
}

export default memo(EmergencyRoutes);
