import { Html } from '@react-three/drei';
import { memo } from 'react';
import { useTwinStore } from '../../store/useTwinStore';
import type { Snapshot } from '../../types';
import { levelChip } from '../../utils/colors';

function Labels({ snapshot }: { snapshot: Snapshot }) {
  const selectBuilding = useTwinStore((s) => s.selectBuilding);

  return (
    <group>
      {snapshot.buildings.map((b) => (
        <Html
          key={b.id}
          position={[b.position.x, b.height + 3.5, b.position.z]}
          center
          zIndexRange={[20, 0]}
          style={{ pointerEvents: 'none' }}
        >
          <button
            onClick={(e) => { e.stopPropagation(); void selectBuilding(b.id); }}
            style={{ pointerEvents: 'auto' }}
            className="flex items-center gap-1.5 rounded-md border border-line-strong bg-ink-900/92 px-2 py-1 shadow-lg backdrop-blur-sm whitespace-nowrap hover:border-brand-400 transition-colors"
          >
            <span className="w-1.5 h-1.5 rounded-full" style={{ background: b.color }} />
            <span className="text-[10.5px] font-semibold text-mist-100">{b.name}</span>
            <span className={`num text-[10px] font-bold ${b.risk > 60 ? 'text-red-400' : b.risk > 40 ? 'text-amber-300' : 'text-emerald-400'}`}>
              {b.risk.toFixed(0)}
            </span>
          </button>
        </Html>
      ))}

      {snapshot.nodes.filter((n) => n.is_exit).map((gate) => (
        <Html key={gate.id} position={[gate.x, 7.5, gate.z]} center zIndexRange={[15, 0]} style={{ pointerEvents: 'none' }}>
          <div className={`chip ${levelChip(snapshot.routes.some((r) => r.exit_id === gate.id && r.status === 'BLOCKED') ? 'CRITICAL' : 'LOW')} whitespace-nowrap`}>
            {gate.name}
          </div>
        </Html>
      ))}

      <Html position={[0, 0.4, -2]} center zIndexRange={[10, 0]} style={{ pointerEvents: 'none' }}>
        <div className="text-[10px] tracking-[0.2em] uppercase text-mist-500 font-bold">Central Courtyard</div>
      </Html>
    </group>
  );
}

export default memo(Labels);
