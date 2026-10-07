import { memo, useEffect, useMemo, useRef } from 'react';
import * as THREE from 'three';

const TREE_SPOTS: [number, number][] = [
  [-88, 20], [-88, -20], [-88, 44], [-64, 60], [-40, 60], [-14, 60], [14, 60], [40, 60], [66, 60], [88, 44],
  [88, 20], [88, -20], [88, -48], [66, -70], [40, -70], [14, -70], [-14, -70], [-40, -70], [-66, -70], [-88, -48],
  [-32, 6], [-32, -14], [32, 6], [32, -14], [-75, 40], [-75, -8], [75, 40], [75, -8],
  [-20, 47], [20, 47], [-58, 40], [56, 6], [-56, -6], [16, -26], [-16, -26], [70, 34],
];

const LAMP_SPOTS: [number, number][] = [
  [-78, 40], [-78, 10], [-78, -22], [-78, -50], [-40, 52], [-10, 52], [20, 52], [50, 52], [78, 40],
  [78, 10], [78, -22], [78, -50], [40, -60], [10, -60], [-20, -60], [-50, -60],
  [-27, 24], [27, 24], [-27, -20], [27, -20],
];

function Nature({ night }: { night: boolean }) {
  const trunkRef = useRef<THREE.InstancedMesh>(null);
  const leafRef = useRef<THREE.InstancedMesh>(null);
  const poleRef = useRef<THREE.InstancedMesh>(null);
  const bulbRef = useRef<THREE.InstancedMesh>(null);

  const dummy = useMemo(() => new THREE.Object3D(), []);

  useEffect(() => {
    TREE_SPOTS.forEach(([x, z], i) => {
      const s = 0.85 + ((i * 13) % 7) / 12;
      dummy.position.set(x, 1.6 * s, z);
      dummy.scale.set(0.9 * s, 1.15 * s, 0.9 * s);
      dummy.rotation.set(0, i, 0);
      dummy.updateMatrix();
      trunkRef.current?.setMatrixAt(i, dummy.matrix);
      dummy.position.set(x, 4.6 * s, z);
      dummy.scale.set(s * 1.5, s * 2.1, s * 1.5);
      dummy.updateMatrix();
      leafRef.current?.setMatrixAt(i, dummy.matrix);
    });
    if (trunkRef.current) trunkRef.current.instanceMatrix.needsUpdate = true;
    if (leafRef.current) leafRef.current.instanceMatrix.needsUpdate = true;

    LAMP_SPOTS.forEach(([x, z], i) => {
      dummy.position.set(x, 2.6, z);
      dummy.scale.setScalar(1);
      dummy.rotation.set(0, 0, 0);
      dummy.updateMatrix();
      poleRef.current?.setMatrixAt(i, dummy.matrix);
      dummy.position.set(x, 5.4, z);
      dummy.updateMatrix();
      bulbRef.current?.setMatrixAt(i, dummy.matrix);
    });
    if (poleRef.current) poleRef.current.instanceMatrix.needsUpdate = true;
    if (bulbRef.current) bulbRef.current.instanceMatrix.needsUpdate = true;
  }, [dummy]);

  return (
    <group>
      <instancedMesh ref={trunkRef} args={[undefined, undefined, TREE_SPOTS.length]} frustumCulled={false}>
        <cylinderGeometry args={[0.35, 0.5, 3.2, 6]} />
        <meshStandardMaterial color="#4a3626" roughness={1} />
      </instancedMesh>
      <instancedMesh ref={leafRef} args={[undefined, undefined, TREE_SPOTS.length]} frustumCulled={false}>
        <coneGeometry args={[2.4, 6.4, 7]} />
        <meshStandardMaterial color={night ? '#12351f' : '#1e5c38'} roughness={0.95} />
      </instancedMesh>

      <instancedMesh ref={poleRef} args={[undefined, undefined, LAMP_SPOTS.length]} frustumCulled={false}>
        <cylinderGeometry args={[0.14, 0.2, 5.2, 6]} />
        <meshStandardMaterial color="#3a4a66" roughness={0.7} metalness={0.4} />
      </instancedMesh>
      <instancedMesh ref={bulbRef} args={[undefined, undefined, LAMP_SPOTS.length]} frustumCulled={false}>
        <sphereGeometry args={[0.55, 10, 10]} />
        <meshStandardMaterial
          color={night ? '#ffe6a8' : '#cdd8ee'}
          emissive={night ? '#ffbb44' : '#8aa4d6'}
          emissiveIntensity={night ? 2.2 : 0.35}
        />
      </instancedMesh>
      {night && LAMP_SPOTS.filter((_, i) => i % 4 === 0).map(([x, z], i) => (
        <pointLight key={i} position={[x, 5.4, z]} color="#ffcf87" intensity={7} distance={34} decay={2} />
      ))}
    </group>
  );
}

export default memo(Nature);
