import { Html } from '@react-three/drei';
import { useFrame } from '@react-three/fiber';
import { memo, useMemo, useRef, useState } from 'react';
import * as THREE from 'three';
import { useTwinStore } from '../../store/useTwinStore';
import type { Building } from '../../types';
import { levelChip, riskColor } from '../../utils/colors';

interface Props {
  building: Building;
  selected: boolean;
  onSelect: (id: string) => void;
  night: boolean;
  /** x-ray shell: shown when this building is inspected floor-by-floor or when the zones layer is on. */
  xray: boolean;
}

const BASE = new THREE.Color('#0f172a');

/**
 * Building (spec §7/§8): type-aware architecture — academic window grids,
 * library overhang roof, canteen awning, medical cross + emergency pad,
 * admin entrance steps. Height always derives from the API floor count.
 */
function BuildingBlock({ building, selected, onSelect, night, xray }: Props) {
  const [hovered, setHovered] = useState(false);
  const outlineRef = useRef<THREE.Mesh>(null);
  const riskMode = useTwinStore((s) => s.toggles.risk);
  const risk = building.risk;
  const danger = building.status !== 'OPERATIONAL' || risk > 60;

  const fh = building.height / Math.max(1, building.floors);
  const floors = Math.max(1, Math.min(building.floors, 6));
  const sx = building.size.x;
  const sz = building.size.z;

  const bodyColor = useMemo(() => {
    let c = new THREE.Color(building.color);
    // Phase 5 RISK MODE: subtle blend of the building hue toward its risk band colour
    if (riskMode) c = c.lerp(new THREE.Color(riskColor(risk)), 0.55);
    if (!building.power) c.multiplyScalar(0.45);
    if (night) c.multiplyScalar(0.8);
    return c;
  }, [building.color, building.power, night, riskMode, risk]);

  const emissive = useMemo(() => {
    if (riskMode) return new THREE.Color(riskColor(risk)).multiplyScalar(risk > 60 ? 0.5 : 0.28);
    if (danger) return new THREE.Color(riskColor(risk)).multiplyScalar(0.35);
    if (hovered || selected) return new THREE.Color('#2563eb').multiplyScalar(0.4);
    return new THREE.Color('#000000');
  }, [riskMode, danger, risk, hovered, selected]);

  useFrame(({ clock }) => {
    if (outlineRef.current) {
      const mat = outlineRef.current.material as THREE.MeshBasicMaterial;
      mat.opacity = 0.45 + Math.sin(clock.elapsedTime * 3.2) * 0.3;
      outlineRef.current.visible = selected || danger || riskMode;
    }
  });

  const windowColor = building.power ? (night ? '#ffd98a' : '#8fd0ff') : '#334155';
  const windowEmissive = building.power ? (night ? '#ffb347' : '#3b82f6') : '#000000';
  const windowIntensity = night ? 0.85 : 0.35;

  // window rows per floor (front + back) — academic/library density differs
  const windowRows = useMemo(() => {
    const rows: number[] = [];
    for (let f = 1; f <= floors; f += 1) rows.push((f - 0.5) * fh);
    return rows;
  }, [floors, fh]);

  const hasWindows = !xray && building.type !== 'AMENITY';
  const isAcademic = building.type === 'ACADEMIC';
  const isLibrary = building.type === 'LIBRARY';
  const isAdmin = building.type === 'ADMIN';
  const isMedical = building.type === 'MEDICAL';
  const isAmenity = building.type === 'AMENITY';

  return (
    <group position={[building.position.x, 0, building.position.z]}>
      {/* main mass (transparent shell in x-ray inspection mode) */}
      <mesh
        position={[0, building.height / 2, 0]}
        onClick={(e) => { e.stopPropagation(); onSelect(building.id); }}
        onPointerOver={(e) => { e.stopPropagation(); setHovered(true); document.body.style.cursor = 'pointer'; }}
        onPointerOut={() => { setHovered(false); document.body.style.cursor = 'auto'; }}
      >
        <boxGeometry args={[sx, building.height, sz]} />
        {xray ? (
          <meshStandardMaterial
            color={bodyColor}
            transparent
            opacity={0.13}
            depthWrite={false}
            roughness={0.8}
            side={THREE.DoubleSide}
          />
        ) : (
          <meshStandardMaterial
            color={bodyColor}
            emissive={emissive}
            emissiveIntensity={riskMode ? (risk > 60 ? 0.9 : 0.6) : danger ? 0.9 : hovered ? 0.7 : 0.25}
            roughness={0.72}
            metalness={0.15}
          />
        )}
      </mesh>

      {/* ---- x-ray mode: structural wireframe + floor dividers ---- */}
      {xray && (
        <>
          <mesh position={[0, building.height / 2, 0]}>
            <boxGeometry args={[sx + 0.08, building.height + 0.08, sz + 0.08]} />
            <meshBasicMaterial color="#3b82f6" wireframe transparent opacity={0.5} />
          </mesh>
          {Array.from({ length: floors - 1 }).map((_, i) => (
            <mesh key={`xr-${i}`} position={[0, fh * (i + 1), 0]}>
              <boxGeometry args={[sx + 0.12, 0.1, sz + 0.12]} />
              <meshBasicMaterial color="#60a5fa" transparent opacity={0.55} />
            </mesh>
          ))}
        </>
      )}

      {/* ---- floor division bands ---- */}
      {!xray && Array.from({ length: floors - 1 }).map((_, i) => (
        <mesh key={`fb-${i}`} position={[0, fh * (i + 1), 0]}>
          <boxGeometry args={[sx + 0.14, 0.16, sz + 0.14]} />
          <meshStandardMaterial color="#0b1220" roughness={0.9} />
        </mesh>
      ))}

      {/* ---- window grids (front/back, per floor) ---- */}
      {hasWindows && windowRows.map((y, i) => (
        <group key={`w-${i}`}>
          <mesh position={[0, y, sz / 2 + 0.03]}>
            <boxGeometry args={[sx * (isLibrary ? 0.9 : 0.84), Math.max(1.1, fh * (isAmenity ? 0.5 : 0.34)), 0.06]} />
            <meshStandardMaterial color={windowColor} emissive={windowEmissive} emissiveIntensity={windowIntensity} roughness={0.3} />
          </mesh>
          <mesh position={[0, y, -sz / 2 - 0.03]}>
            <boxGeometry args={[sx * 0.84, Math.max(1.1, fh * 0.34), 0.06]} />
            <meshStandardMaterial color={windowColor} emissive={windowEmissive} emissiveIntensity={windowIntensity} roughness={0.3} />
          </mesh>
          {isAcademic && (
            <>
              <mesh position={[sx / 2 + 0.03, y, 0]}>
                <boxGeometry args={[0.06, Math.max(1.1, fh * 0.34), sz * 0.8]} />
                <meshStandardMaterial color={windowColor} emissive={windowEmissive} emissiveIntensity={windowIntensity} roughness={0.3} />
              </mesh>
              <mesh position={[-sx / 2 - 0.03, y, 0]}>
                <boxGeometry args={[0.06, Math.max(1.1, fh * 0.34), sz * 0.8]} />
                <meshStandardMaterial color={windowColor} emissive={windowEmissive} emissiveIntensity={windowIntensity} roughness={0.3} />
              </mesh>
            </>
          )}
        </group>
      ))}

      {/* ---- entrance ---- */}
      {!xray && (
        <group>
          {/* door recess */}
          <mesh position={[0, Math.min(2.1, fh * 0.45), sz / 2 + 0.08]}>
            <boxGeometry args={[Math.min(5, sx * 0.24), Math.min(4.2, fh * 0.9), 0.3]} />
            <meshStandardMaterial
              color="#0b1220"
              emissive={building.power ? '#1e3a8a' : '#000'}
              emissiveIntensity={0.6}
              roughness={0.4}
            />
          </mesh>
          {/* entrance canopy */}
          <mesh
            position={[0, Math.min(4.6, fh * 1.02), sz / 2 + 1.4]}
            rotation={[isAmenity ? -0.35 : 0, 0, 0]}
          >
            <boxGeometry args={[Math.min(9, sx * 0.4), 0.35, 3]} />
            <meshStandardMaterial color={isMedical ? '#7f1d1d' : '#1e293b'} roughness={0.6} metalness={0.3} />
          </mesh>
          {/* entrance step pad */}
          <mesh position={[0, 0.06, sz / 2 + 2.6]} rotation={[-Math.PI / 2, 0, 0]}>
            <planeGeometry args={[Math.min(10, sx * 0.45), 3.4]} />
            <meshStandardMaterial color="#1a2740" roughness={1} />
          </mesh>
          {isAdmin && [0, 1, 2].map((i) => (
            <mesh key={`st-${i}`} position={[0, 0.14 + i * 0.22, sz / 2 + 1.6 - i * 0.5]}>
              <boxGeometry args={[Math.min(9, sx * 0.4), 0.24, 1.1]} />
              <meshStandardMaterial color="#243250" roughness={0.9} />
            </mesh>
          ))}
        </group>
      )}

      {/* ---- roofs / type identity ---- */}
      {!xray && (
        <>
          {isLibrary && (
            <mesh position={[0, building.height + 0.3, 0]}>
              <boxGeometry args={[sx + 2.6, 0.6, sz + 2.6]} />
              <meshStandardMaterial color="#312e81" roughness={0.75} />
            </mesh>
          )}
          {isAcademic && (
            <mesh position={[0, building.height + 0.35, 0]}>
              <boxGeometry args={[sx + 0.7, 0.7, sz + 0.7]} />
              <meshStandardMaterial color="#1e293b" roughness={0.85} />
            </mesh>
          )}
          {(isAcademic || isAdmin) && (
            <mesh position={[sx * 0.22, building.height + 1.1, -sz * 0.18]}>
              <boxGeometry args={[sx * 0.22, 1.4, sz * 0.24]} />
              <meshStandardMaterial color="#243250" roughness={0.85} />
            </mesh>
          )}
          {isAdmin && (
            <>
              {[-0.3, 0, 0.3].map((p) => (
                <mesh key={`fin-${p}`} position={[sx * p, building.height * 0.62, sz / 2 + 0.1]}>
                  <boxGeometry args={[0.5, building.height * 0.72, 0.5]} />
                  <meshStandardMaterial color="#334155" roughness={0.6} metalness={0.35} />
                </mesh>
              ))}
            </>
          )}
          {isAmenity && (
            <>
              {[-sx * 0.22, sx * 0.22].map((vx) => (
                <mesh key={`vent-${vx}`} position={[vx, building.height + 0.8, -sz * 0.1]}>
                  <cylinderGeometry args={[0.7, 0.9, 1.6, 10]} />
                  <meshStandardMaterial color="#475569" roughness={0.7} metalness={0.4} />
                </mesh>
              ))}
            </>
          )}
          {isMedical && (
            <group position={[0, building.height * 0.78, sz / 2 + 0.14]}>
              <mesh>
                <boxGeometry args={[0.9, 3.4, 0.3]} />
                <meshStandardMaterial color="#ef4444" emissive="#b91c1c" emissiveIntensity={0.7} roughness={0.4} />
              </mesh>
              <mesh>
                <boxGeometry args={[2.6, 0.9, 0.3]} />
                <meshStandardMaterial color="#ef4444" emissive="#b91c1c" emissiveIntensity={0.7} roughness={0.4} />
              </mesh>
            </group>
          )}
        </>
      )}

      {/* selection / hazard outline */}
      <mesh ref={outlineRef} position={[0, building.height / 2, 0]} visible={selected}>
        <boxGeometry args={[sx + 1.1, building.height + 1.1, sz + 1.1]} />
        <meshBasicMaterial
          color={riskMode ? riskColor(risk) : danger ? riskColor(risk) : '#60a5fa'}
          transparent
          opacity={0.5}
          wireframe
        />
      </mesh>

      {/* hazard beacon */}
      {danger && !xray && (
        <mesh position={[0, building.height + 2.6, 0]}>
          <sphereGeometry args={[0.85, 12, 12]} />
          <meshBasicMaterial color={riskColor(risk)} />
        </mesh>
      )}

      {!building.power && (
        <Html position={[0, building.height + 4.4, 0]} center zIndexRange={[10, 0]}>
          <div className="chip border-red-600 bg-red-950/90 text-red-200 whitespace-nowrap">POWER OFF</div>
        </Html>
      )}

      {/* Phase 5 RISK MODE — score + level chip (honest indicator, not a probability) */}
      {riskMode && (
        <Html position={[0, building.height + 2.4, 0]} center zIndexRange={[10, 0]} style={{ pointerEvents: 'none' }}>
          <div className={`chip !text-[9.5px] font-bold whitespace-nowrap border bg-ink-950/95 ${levelChip(building.risk_level)}`}>
            <span className="num">{risk}</span>
            <span className="opacity-80">{building.risk_level}</span>
          </div>
        </Html>
      )}

      <mesh position={[0, 0.04, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <planeGeometry args={[sx + 3, sz + 3]} />
        <meshBasicMaterial color={BASE} transparent opacity={selected ? 0.45 : hovered ? 0.25 : 0} />
      </mesh>
    </group>
  );
}

export default memo(BuildingBlock);
