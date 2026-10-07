import { useCallback, useEffect, useState } from 'react';
import { api } from '../services/api';
import { useTwinStore } from '../store/useTwinStore';
import type { Snapshot } from '../types';

export type CampusDataState = 'loading' | 'ready' | 'error';

const SENSOR_ZONE_SYNC_MS = 15_000;
const SUMMARY_REFRESH_MS = 60_000;

/**
 * Campus data hook (spec §30/§44):
 * - WS `state` frames are the primary live feed for the 3D scene.
 * - When the WS link is down (or zones/sensors are still missing after boot),
 *   falls back to REST `/api/zones` + `/api/sensors` on a slow, controlled poll.
 * - Campus summary/metadata refreshes on an even slower cadence.
 * - Never fetches inside the render/animation loop.
 */
export function useCampus() {
  const snapshot = useTwinStore((s) => s.snapshot);
  const connection = useTwinStore((s) => s.connection);
  const backendOffline = useTwinStore((s) => s.backendOffline);
  const lastUpdate = useTwinStore((s) => s.lastUpdate);
  const [syncing, setSyncing] = useState(false);

  const hasSnapshot = Boolean(snapshot);
  const wsLive = connection === 'CONNECTED';

  // --- zones + sensors REST fallback -------------------------------------
  useEffect(() => {
    if (!hasSnapshot) return;
    let cancelled = false;

    const sync = async () => {
      const st = useTwinStore.getState();
      const snap = st.snapshot;
      if (!snap) return;
      const needSensors = !snap.sensors?.length || st.connection !== 'CONNECTED';
      const needZones = !snap.zones?.length || st.connection !== 'CONNECTED';
      if (!needSensors && !needZones) return;

      setSyncing(true);
      try {
        const [sensors, zones] = await Promise.all([
          needSensors ? api.sensors() : Promise.resolve(null),
          needZones ? api.zones() : Promise.resolve(null),
        ]);
        if (cancelled) return;
        const cur = useTwinStore.getState().snapshot;
        if (!cur) return;
        useTwinStore.setState({
          snapshot: {
            ...cur,
            sensors: sensors ?? cur.sensors,
            zones: zones ?? cur.zones,
          } as Snapshot,
          backendOffline: false,
        });
      } catch {
        // health poll owns the offline flag; silent here to avoid toast spam
      } finally {
        if (!cancelled) setSyncing(false);
      }
    };

    void sync();
    const timer = window.setInterval(sync, SENSOR_ZONE_SYNC_MS);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [hasSnapshot, wsLive]);

  // --- slower campus summary / metadata refresh --------------------------
  useEffect(() => {
    let cancelled = false;

    const refreshSummary = async () => {
      const st = useTwinStore.getState();
      if (!st.token || !st.snapshot) return;
      try {
        const campus = await api.campus();
        if (cancelled) return;
        const cur = useTwinStore.getState().snapshot;
        if (!cur) return;
        useTwinStore.setState({
          snapshot: {
            ...cur,
            summary: campus.summary,
            data_source: campus.data_source,
            metadata: campus.metadata,
          } as Snapshot,
        });
      } catch { /* ignore — health polling owns connectivity state */ }
    };

    if (hasSnapshot) void refreshSummary();
    const timer = window.setInterval(refreshSummary, SUMMARY_REFRESH_MS);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [hasSnapshot]);

  const retry = useCallback(() => useTwinStore.getState().retryConnection(), []);

  const dataState: CampusDataState = !snapshot ? (backendOffline ? 'error' : 'loading') : 'ready';

  return { snapshot, dataState, retry, syncing, lastUpdate, connection, backendOffline };
}
