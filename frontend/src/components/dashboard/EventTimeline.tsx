import { useTwinStore } from '../../store/useTwinStore';

const KIND_TONE: Record<string, string> = {
  ignition: 'text-red-400 border-red-800',
  smoke_detected: 'text-orange-300 border-orange-800',
  risk_zone_expanding: 'text-amber-300 border-amber-800',
  zones_affected: 'text-amber-300 border-amber-800',
  routes_recalculated: 'text-sky-300 border-sky-800',
  people_at_risk: 'text-orange-300 border-orange-800',
  route_optimized: 'text-emerald-300 border-emerald-800',
  response_recommended: 'text-violet-300 border-violet-800',
  completed: 'text-emerald-300 border-emerald-800',
  recovered: 'text-emerald-300 border-emerald-800',
  paused: 'text-amber-300 border-amber-800',
  overloaded: 'text-red-400 border-red-800',
  spread: 'text-orange-300 border-orange-800',
};

export default function EventTimeline({ compact = false }: { compact?: boolean }) {
  const timeline = useTwinStore((s) => s.timeline);
  const snapshot = useTwinStore((s) => s.snapshot);

  const items = [
    ...timeline,
    ...(snapshot?.active_sim?.events ?? []).filter(
      (e) => !timeline.some((t) => t.kind === e.kind && Math.abs(t.t - e.t) < 0.01),
    ),
  ].slice(0, compact ? 8 : 40);

  return (
    <div className="h-full flex flex-col min-h-0">
      <div className="px-3 py-2 border-b border-line flex items-center gap-2">
        <span className="label-cap">Event Timeline</span>
        <span className="text-[10px] text-mist-500 num">{items.length} events</span>
      </div>
      <div className="flex-1 min-h-0 scroll-y px-3 py-2 space-y-1.5">
        {items.length === 0 && (
          <div className="text-[11.5px] text-mist-500 py-4 text-center border border-dashed border-line rounded">
            No simulation events yet — start a scenario to see the timeline fill.
          </div>
        )}
        {items.map((ev, i) => (
          <div key={`${ev.kind}-${ev.t}-${i}`} className="flex items-start gap-2 text-[11.5px]">
            <span className="num text-mist-500 shrink-0 w-[52px]">T+{ev.t.toFixed(0)}s</span>
            <span className={`shrink-0 chip !py-0 !px-1.5 ${KIND_TONE[ev.kind] ?? 'border-line-strong text-mist-300'}`}>
              {ev.kind.replace(/_/g, ' ')}
            </span>
            <span className="text-mist-100 leading-snug">{ev.message}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
