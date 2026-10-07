import { useTwinStore } from '../../store/useTwinStore';

const LEVEL_DOT: Record<string, string> = {
  info: 'bg-brand-400',
  success: 'bg-emerald-400',
  warn: 'bg-amber-400',
  error: 'bg-red-500',
};

const LEVEL_TEXT: Record<string, string> = {
  info: 'text-mist-200',
  success: 'text-emerald-200',
  warn: 'text-amber-200',
  error: 'text-red-200',
};

/**
 * Live event timeline (spec §47): bounded stream of control actions,
 * simulator status transitions, risk changes and system health events.
 * Built exclusively from data the client actually observed — no invented
 * entries. Empty state says exactly that.
 */
export default function LiveEvents() {
  const log = useTwinStore((s) => s.liveLog);

  return (
    <div className="rounded-md border border-line bg-ink-850 p-2.5" data-testid="live-events">
      <div className="flex items-center justify-between mb-1.5">
        <span className="label-cap">Live Events</span>
        <span className="num text-[10px] text-mist-600">{log.length} · last {log.length >= 40 ? '40' : log.length}</span>
      </div>

      {log.length === 0 ? (
        <div className="text-[11px] text-mist-500 leading-relaxed">
          No live events observed yet. Control the simulation or wait for a
          status change — every entry below is something this session actually
          received.
        </div>
      ) : (
        <ul className="space-y-1.5 max-h-56 overflow-y-auto pr-1 scroll-y">
          {log.map((e) => (
            <li key={e.id} className="flex items-start gap-2 text-[11.5px]" data-testid="live-event-item">
              <span className={`w-1.5 h-1.5 rounded-full mt-1.5 shrink-0 ${LEVEL_DOT[e.level] ?? LEVEL_DOT.info}`} />
              <span className="min-w-0 flex-1">
                <span className={`font-semibold ${LEVEL_TEXT[e.level] ?? 'text-mist-200'}`}>{e.title}</span>
                {e.detail && <span className="text-mist-500"> · {e.detail}</span>}
                <span className="block num text-[10px] text-mist-600">
                  {new Date(e.ts).toLocaleTimeString(undefined, { hour12: false })}
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
