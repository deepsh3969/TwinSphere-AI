import { useCallback } from 'react';
import { useTwinStore } from '../store/useTwinStore';
import type { CameraPresetName } from '../types/twin';

/**
 * Camera command surface (spec §16/§17/§52): reset, top view, overview and
 * focus-selected, all routed through the store so the CameraRig inside the
 * canvas can animate smoothly to the requested pose.
 */
export function useTwinCamera() {
  const setCameraView = useTwinStore((s) => s.setCameraView);
  const focusCamera = useTwinStore((s) => s.focusCamera);
  const selectedBuildingId = useTwinStore((s) => s.selectedBuildingId);

  const gotoPreset = useCallback(
    (view: CameraPresetName) => setCameraView(view),
    [setCameraView],
  );

  /** Reset = default isometric overview pose. */
  const reset = useCallback(() => setCameraView('iso'), [setCameraView]);
  const top = useCallback(() => setCameraView('top'), [setCameraView]);
  const overview = useCallback(() => setCameraView('iso'), [setCameraView]);

  const focusSelected = useCallback(() => {
    const id = useTwinStore.getState().selectedBuildingId;
    if (!id) return false;
    const b = useTwinStore.getState().snapshot?.buildings.find((x) => x.id === id);
    if (!b) return false;
    focusCamera(b.position.x, b.position.z);
    return true;
  }, [focusCamera, selectedBuildingId]);

  const focusAt = useCallback((x: number, z: number) => focusCamera(x, z), [focusCamera]);

  return { gotoPreset, reset, top, overview, focusSelected, focusAt };
}
