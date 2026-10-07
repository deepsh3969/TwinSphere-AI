import type { RiskResult } from '../../types';
import { levelChip, riskColor, riskTextClass } from '../../utils/colors';

export default function RiskGauge({ risk, compact = false }: { risk: RiskResult | undefined; compact?: boolean }) {
  const score = risk?.score ?? 0;
  const pct = Math.max(2, Math.min(100, score));
  const color = riskColor(score);

  if (compact) {
    return (
      <div className="flex items-center gap-2">
        <span className={`num text-lg font-bold ${riskTextClass(score)}`}>{score.toFixed(0)}</span>
        <div className="flex-1 h-1.5 rounded-full bg-ink-700 overflow-hidden min-w-[60px]">
          <div className="h-full rounded-full transition-all duration-700" style={{ width: `${pct}%`, background: color }} />
        </div>
        <span className={`chip ${levelChip(risk?.level ?? 'LOW')}`}>{risk?.level ?? 'LOW'}</span>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-end justify-between mb-2">
        <div>
          <div className="label-cap">Campus Risk Index</div>
          <div className="flex items-baseline gap-2">
            <span className={`num text-[34px] font-black leading-none ${riskTextClass(score)}`}>{score.toFixed(0)}</span>
            <span className="text-mist-500 text-sm num">/ 100</span>
          </div>
        </div>
        <span className={`chip ${levelChip(risk?.level ?? 'LOW')}`}>{risk?.level ?? 'LOW'}</span>
      </div>
      <div className="h-2 rounded-full bg-ink-700 overflow-hidden relative">
        <div
          className="h-full rounded-full transition-all duration-700"
          style={{ width: `${pct}%`, background: `linear-gradient(90deg, #22c55e, ${color})` }}
        />
        <div className="absolute inset-0 flex">
          {[20, 40, 60, 80].map((m) => (
            <div key={m} className="flex-1 border-r border-ink-950/70 last:border-0" />
          ))}
        </div>
      </div>
      <div className="flex justify-between text-[9.5px] text-mist-500 mt-1 num">
        <span>0</span><span>21</span><span>41</span><span>61</span><span>81</span><span>100</span>
      </div>
      {risk?.explanation && (
        <p className="text-[11.5px] text-mist-300 mt-2 leading-snug">{risk.explanation}</p>
      )}
    </div>
  );
}
