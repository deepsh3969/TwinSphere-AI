import { useTwinCamera } from '../../hooks/useTwinCamera';
import { useTwinStore } from '../../store/useTwinStore';
import { IconRefresh, IconTarget } from '../Icons';

/** Camera command cluster (spec §17/§52): Reset View, Top View, Focus. */
export default function CameraControls() {
  const { reset, top, focusSelected } = useTwinCamera();
  const hasSelection = useTwinStore((s) => Boolean(s.selectedBuildingId));

  return (
    <div className="flex items-center gap-1.5" role="group" aria-label="Camera controls">
      <button
        className="chip !text-[10.5px]"
        onClick={reset}
        title="Reset camera to the default overview (R)"
        aria-label="Reset view to campus overview"
      >
        <IconRefresh width={11} height={11} /> Reset View
      </button>
      <button
        className="chip !text-[10.5px]"
        onClick={top}
        title="Top-down plan view"
        aria-label="Switch to top-down view"
      >
        Top View
      </button>
      <button
        className="chip !text-[10.5px]"
        onClick={focusSelected}
        disabled={!hasSelection}
        title={hasSelection ? 'Fly camera to the selected building' : 'Select a building first'}
        aria-label="Focus selected building"
      >
        <IconTarget width={11} height={11} /> Focus
      </button>
    </div>
  );
}
