import { Line } from '@react-three/drei';
import { memo, useMemo } from 'react';
import { useTwinStore } from '../../store/useTwinStore';
import type { Snapshot } from '../../types';
import { routeColor, routeModeColor } from '../../utils/colors';
import EmergencyRoutes from './EmergencyRoutes';
import RouteArrows from './RouteArrows';
import RouteMarkers from './RouteMarkers';

type P3 = [number, number, number];

function EvacuationRoutes({ snapshot }: { snapshot: Snapshot }) {
  const selectedId = useTwinStore((s) => s.selectedBuildingId);
  const routePlan = useTwinStore((s) => s.routePlan);
  const bottlenecks = useTwinStore((s) => s.routeBottlenecks);
  const routes = snapshot.routes;

  const nodeById = useMemo(
    () => new Map(snapshot.nodes.map((n) => [n.id, n])), [snapshot.nodes]);
  const roadById = useMemo(
    () => new Map(snapshot.roads.map((r) => [r.id, r])), [snapshot.roads]);

  const toPoints = (ids: string[], y: number): P3[] => ids
    .map((nid) => {
      const n = nodeById.get(nid);
      return n ? ([n.x, y, n.z] as P3) : null;
    })
    .filter((p): p is P3 => p !== null);

  // Active optimized plan (§18): thick mode-colored line + arrows + markers
  const planPoints = routePlan ? toPoints(routePlan.node_path, 1.95) : [];
  const planColor = routePlan
    ? (routePlan.status === 'NO_SAFE_ROUTE' || routePlan.status === 'BLOCKED'
      ? '#ef4444' : routeModeColor(routePlan.mode))
    : '';
  const planOrigin = routePlan?.origin ? nodeById.get(routePlan.origin) : null;
  const planDestId = routePlan?.destination ?? '';
  const planDest = planDestId ? nodeById.get(planDestId) : null;

  return (
    <group>
      {/* legacy per-building exit routes (§8 baseline) */}
      {routes.map((route) => {
        if (!route.node_path || route.node_path.length < 2) return null;
        const points = toPoints(route.node_path, 1.6);
        if (points.length < 2) return null;
        const color = routeColor(route.status);
        const isFocus = selectedId === route.building_id;
        const dim = selectedId && !isFocus;
        return (
          <group key={route.id}>
            <Line
              points={points}
              color={color}
              lineWidth={isFocus ? 4.5 : 2.6}
              dashed={route.status === 'BLOCKED'}
              transparent
              opacity={dim ? 0.18 : 0.92}
            />
            {route.exit_id && (() => {
              const exit = nodeById.get(route.exit_id);
              return exit ? (
                <mesh position={[exit.x, 1.6, exit.z]} rotation={[-Math.PI / 2, 0, 0]}>
                  <ringGeometry args={[2.2, 3.4, 24]} />
                  <meshBasicMaterial color={color} transparent opacity={dim ? 0.25 : 0.85} side={2} />
                </mesh>
              ) : null;
            })()}
          </group>
        );
      })}

      {/* active optimized route (Phase 7) — highest visual priority */}
      {routePlan && planPoints.length >= 2 && (
        <group>
          <Line
            points={planPoints}
            color={planColor}
            lineWidth={5.2}
            dashed={routePlan.status === 'NO_SAFE_ROUTE' || routePlan.status === 'BLOCKED'}
            transparent
            opacity={0.95}
          />
          <RouteArrows points={planPoints} color={planColor} />
          <RouteMarkers
            origin={planOrigin ? [planOrigin.x, 2.0, planOrigin.z] : null}
            destination={planDest ? [planDest.x, 2.0, planDest.z] : null}
            color={planColor}
            originLabel={routePlan.origin ?? undefined}
            destinationLabel={routePlan.destination_name || routePlan.destination || undefined}
          />
        </group>
      )}

      {/* emergency vehicle response routes (§16) */}
      <EmergencyRoutes snapshot={snapshot} />

      {/* bottleneck markers (§13): EXIT/NODE rings + EDGE midpoints */}
      {bottlenecks.map((b) => {
        const node = nodeById.get(b.location_id);
        const road = roadById.get(b.location_id);
        let pos: P3 | null = null;
        if (node) pos = [node.x, 1.7, node.z];
        else if (road) {
          const a = nodeById.get(road.from_node);
          const c = nodeById.get(road.to_node);
          if (a && c) pos = [(a.x + c.x) / 2, 1.7, (a.z + c.z) / 2];
        }
        if (!pos) return null;
        const color = b.severity === 'HIGH' ? '#ef4444' : '#f59e0b';
        return (
          <group key={`bn-${b.location_id}`} position={pos}>
            <mesh rotation={[-Math.PI / 2, 0, 0]}>
              <ringGeometry args={[1.4, 2.4, 6]} />
              <meshBasicMaterial color={color} transparent opacity={0.9} side={2} />
            </mesh>
            <mesh>
              <sphereGeometry args={[0.45, 10, 10]} />
              <meshBasicMaterial color={color} />
            </mesh>
          </group>
        );
      })}
    </group>
  );
}

export default memo(EvacuationRoutes);
