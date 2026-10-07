import type { RouteMode } from '../../types';
import { routeModeColor, routeSafetyColor } from '../../utils/colors';

const MODES: RouteMode[] = ['shortest', 'fastest', 'safest', 'balanced'];

/** Phase 7 §7/§10 — mode + safety color key (shared by panel + embeds). */
export default function RouteLegend({ compact = false }: { compact?: boolean }) {
  return (
    <div className={`flex flex-wrap gap-x-3 gap-y-1 ${compact ? 'text-[9.5px]' : 'text-[10px]'}`}>
      <span className="label-cap text-mist-500 self-center">Modes</span>
      {MODES.map((m) => (
        <span key={m} className="flex items-center gap-1 text-mist-300">
          <span className="inline-block w-3 h-[3px] rounded"
                style={{ background: routeModeColor(m) }} />
          {m}
        </span>
      ))}
      <span className="flex items-center gap-1 text-mist-300">
        <span className="inline-block w-3 h-[3px] rounded" style={{ background: routeModeColor('emergency') }} />
        emergency
      </span>
      <span className="label-cap text-mist-500 self-center ml-1">Safety</span>
      {(['SAFE', 'WARNING', 'HIGH_RISK'] as const).map((s) => (
        <span key={s} className="flex items-center gap-1 text-mist-300">
          <span className="inline-block w-2 h-2 rounded-full"
                style={{ background: routeSafetyColor(s) }} />
          {s.toLowerCase().replace('_', ' ')}
        </span>
      ))}
    </div>
  );
}
