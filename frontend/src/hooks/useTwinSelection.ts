import { useCallback, useMemo } from 'react';
import { useTwinStore } from '../store/useTwinStore';
import type { Building, Sensor } from '../types';
import type { InspectorMode } from '../types/twin';

/**
 * Central selection model for the twin (spec §32):
 * building → floor → sensor, with explicit clearing rules.
 * Server data stays in the store snapshot; only UI selection lives here.
 */
export function useTwinSelection() {
  const snapshot = useTwinStore((s) => s.snapshot);
  const selectedBuildingId = useTwinStore((s) => s.selectedBuildingId);
  const selectedFloorId = useTwinStore((s) => s.selectedFloorId);
  const selectedSensorId = useTwinStore((s) => s.selectedSensorId);
  const buildingDetail = useTwinStore((s) => s.buildingDetail);

  const selectBuilding = useTwinStore((s) => s.selectBuilding);
  const selectFloor = useTwinStore((s) => s.selectFloor);
  const selectSensor = useTwinStore((s) => s.selectSensor);
  const focusCamera = useTwinStore((s) => s.focusCamera);

  const selectedBuilding: Building | null = useMemo(
    () => snapshot?.buildings.find((b) => b.id === selectedBuildingId) ?? null,
    [snapshot, selectedBuildingId],
  );

  const selectedSensor: Sensor | null = useMemo(
    () => snapshot?.sensors.find((s) => s.id === selectedSensorId) ?? null,
    [snapshot, selectedSensorId],
  );

  const inspectorMode: InspectorMode = selectedSensor ? 'sensor' : selectedBuildingId ? 'building' : 'campus';

  const openBuilding = useCallback((id: string) => {
    void selectBuilding(id);
    const b = useTwinStore.getState().snapshot?.buildings.find((x) => x.id === id);
    if (b) focusCamera(b.position.x, b.position.z);
  }, [selectBuilding, focusCamera]);

  const clearSelection = useCallback(() => {
    void selectBuilding(null);
    selectSensor(null);
  }, [selectBuilding, selectSensor]);

  const focusSelected = useCallback(() => {
    if (selectedBuilding) focusCamera(selectedBuilding.position.x, selectedBuilding.position.z);
  }, [selectedBuilding, focusCamera]);

  return {
    snapshot,
    selectedBuildingId,
    selectedFloorId,
    selectedSensorId,
    selectedBuilding,
    selectedSensor,
    buildingDetail,
    inspectorMode,
    openBuilding,
    selectBuilding,
    selectFloor,
    selectSensor,
    clearSelection,
    focusSelected,
  };
}
