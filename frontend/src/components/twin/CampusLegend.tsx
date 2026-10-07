import { useTwinStore } from '../../store/useTwinStore';
import { SENSOR_TYPES, SENSOR_TYPE_COLORS, SENSOR_TYPE_LABELS } from '../../types/twin';
import { levelChip } from '../../utils/colors';

/** Campus legend (spec §26): risk ladder, sensor type colors, status swatches. */
export default function CampusLegend() {
  const snapshot = useTwinStore((s) => s.snapshot);
  const riskLevel = snapshot?.summary?.risk_level ?? snapshot?.metrics?.risk_level ?? 'LOW';

  return (
    <div className="space-y-3">
      <div>
        <div className="label-cap mb-1.5">Risk Levels</div>
        <div className="flex flex-wrap gap-1">
          {(['LOW', 'MODERATE', 'ELEVATED', 'HIGH', 'CRITICAL'] as const).map((l) => (
            <span
              key={l}
              className={`chip !text-[9px] ${levelChip(l)} ${riskLevel === l ? 'ring-1 ring-white/40' : ''}`}
              title={riskLevel === l ? 'Current campus risk level' : l}
            >
              {l}
            </span>
          ))}
        </div>
      </div>

      <div>
        <div className="label-cap mb-1.5">Sensor Types</div>
        <div className="grid grid-cols-2 gap-x-2 gap-y-1">
          {SENSOR_TYPES.map((t) => (
            <div key={t} className="flex items-center gap-1.5 text-[10.5px] text-mist-400">
              <span className="w-2 h-2 rounded-full shrink-0" style={{ background: SENSOR_TYPE_COLORS[t] }} />
              <span className="truncate">{SENSOR_TYPE_LABELS[t]}</span>
            </div>
          ))}
        </div>
      </div>

      <div>
        <div className="label-cap mb-1.5">Sensor Status</div>
        <div className="flex gap-3 text-[10.5px]">
          <span className="flex items-center gap-1.5 text-mist-400">
            <span className="w-2 h-2 rounded-full bg-emerald-400" /> Online
          </span>
          <span className="flex items-center gap-1.5 text-mist-400">
            <span className="w-2 h-2 rounded-full bg-slate-400" /> Offline
          </span>
          <span className="flex items-center gap-1.5 text-mist-400">
            <span className="w-2 h-2 rounded-full bg-red-500" /> Alert
          </span>
        </div>
      </div>

      <div className="text-[10px] leading-relaxed text-mist-500 border-t border-line pt-2">
        All telemetry is <b className="text-amber-300">SIMULATED</b> Phase 2 demo data — not live IoT.
      </div>
    </div>
  );
}
