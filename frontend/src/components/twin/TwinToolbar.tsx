import { useTwinStore } from '../../store/useTwinStore';
import type { ViewMode } from '../../types/twin';
import CameraControls from './CameraControls';

const MODES: { mode: ViewMode; label: string; title: string }[] = [
  { mode: 'overview', label: 'Overview', title: 'Complete campus view' },
  { mode: 'buildings', label: 'Buildings', title: 'Emphasise structures and labels' },
  { mode: 'sensors', label: 'Sensors', title: 'Emphasise sensor markers' },
  { mode: 'zones', label: 'Zones', title: 'Show zone volumes across campus' },
  { mode: 'risk', label: 'Risk', title: 'RISK MODE — tint campus by published risk (Phase 5)' },
];

/** Twin toolbar (spec §27/§28): view modes + camera commands. */
export default function TwinToolbar() {
  const viewMode = useTwinStore((s) => s.viewMode);
  const setViewMode = useTwinStore((s) => s.setViewMode);

  return (
    <div className="panel rounded-lg px-3 py-2 flex items-center gap-2 flex-wrap shadow-lg shadow-black/40">
      <span className="label-cap mr-1">Twin View</span>
      <div className="flex items-center gap-1.5" role="group" aria-label="View mode">
        {MODES.map((m) => (
          <button
            key={m.mode}
            aria-pressed={viewMode === m.mode}
            title={m.title}
            onClick={() => setViewMode(m.mode)}
            className={`chip !text-[10.5px] transition-colors ${
              viewMode === m.mode
                ? 'border-brand-400 bg-brand-950/70 text-brand-200'
                : 'border-line-strong text-mist-400 hover:text-mist-200'
            }`}
          >
            {m.label}
          </button>
        ))}
      </div>
      <span className="w-px h-4 bg-line mx-1" aria-hidden="true" />
      <CameraControls />
    </div>
  );
}
