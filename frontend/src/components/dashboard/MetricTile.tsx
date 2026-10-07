import type { ReactNode } from 'react';

interface Props {
  label: string;
  value: ReactNode;
  unit?: string;
  sub?: string;
  tone?: 'default' | 'good' | 'warn' | 'bad' | 'info';
  icon?: ReactNode;
  onClick?: () => void;
}

const TONE: Record<string, string> = {
  default: 'text-white',
  good: 'text-emerald-400',
  warn: 'text-amber-300',
  bad: 'text-red-400',
  info: 'text-sky-300',
};

export default function MetricTile({ label, value, unit, sub, tone = 'default', icon, onClick }: Props) {
  const Tag = onClick ? 'button' : 'div';
  return (
    <Tag
      className={`panel rounded-lg px-3 py-2.5 min-w-0 text-left w-full ${onClick ? 'hover:border-brand-500 transition-colors cursor-pointer' : ''}`}
      onClick={onClick}
    >
      <div className="flex items-center gap-1.5 mb-1">
        {icon && <span className="text-mist-500">{icon}</span>}
        <span className="label-cap truncate">{label}</span>
      </div>
      <div className="flex items-baseline gap-1">
        <span className={`num text-[21px] font-bold leading-none ${TONE[tone]}`}>{value}</span>
        {unit && <span className="text-[11px] text-mist-500">{unit}</span>}
      </div>
      {sub && <div className="text-[10.5px] text-mist-500 mt-1 truncate">{sub}</div>}
    </Tag>
  );
}
