import { useEffect, useState, type FormEvent } from 'react';
import {
  IconAlert, IconCheck, IconCube, IconGear, IconRefresh, IconRocket,
} from '../components/Icons';
import { api } from '../services/api';
import { useTwinStore } from '../store/useTwinStore';
import { fmtNum } from '../utils/colors';

interface SettingsData {
  speed: number;
  clock_hour: number;
  sensor_interval: number;
  random_seed: number;
  llm_configured: boolean;
  scenario_params: Record<string, { label?: string; duration?: number; recover?: number }>;
}

interface SystemStatus {
  health: Record<string, boolean | string>;
  ai: Record<string, unknown>;
  metrics: Record<string, number | string>;
  clock_hour: number;
  speed: number;
  status: string;
  recovery_progress: number;
  scenarios: Record<string, string>;
}

export default function Settings() {
  const user = useTwinStore((s) => s.user);
  const health = useTwinStore((s) => s.health);
  const snapshot = useTwinStore((s) => s.snapshot);
  const toggles = useTwinStore((s) => s.toggles);
  const toggle = useTwinStore((s) => s.toggle);
  const pushToast = useTwinStore((s) => s.pushToast);
  const handleApiError = useTwinStore((s) => s.handleApiError);
  const logout = useTwinStore((s) => s.logout);

  const [settings, setSettings] = useState<SettingsData | null>(null);
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [speed, setSpeed] = useState(1);
  const [interval_, setInterval_] = useState(2);
  const [busy, setBusy] = useState(false);
  const [resetArmed, setResetArmed] = useState(false);

  const isAdmin = user?.role === 'ADMIN';

  const load = async () => {
    try {
      const [s, st] = await Promise.all([
        api.settings() as unknown as Promise<SettingsData>,
        api.systemStatus() as unknown as Promise<SystemStatus>,
      ]);
      setSettings(s);
      setSpeed(s.speed);
      setInterval_(s.sensor_interval);
      setStatus(st);
    } catch (err) {
      handleApiError(err);
    }
  };

  useEffect(() => { void load(); }, []);

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const res = await api.updateSettings({ speed, sensor_interval: interval_ });
      pushToast('success', 'SETTINGS SAVED', JSON.stringify((res as { changed?: unknown }).changed ?? {}));
      await load();
    } catch (err) {
      handleApiError(err);
    } finally {
      setBusy(false);
    }
  };

  const reset = async () => {
    setBusy(true);
    try {
      const res = await api.demoReset();
      pushToast('success', 'STATE RESET', 'Campus twin reset to the demo baseline.');
      setResetArmed(false);
      await load();
      return res;
    } catch (err) {
      handleApiError(err);
      return null;
    } finally {
      setBusy(false);
    }
  };

  const tone = (ok: boolean | string) =>
    ok === true || ok === 'ok' ? 'text-emerald-400' : ok === false ? 'text-red-400' : 'text-amber-300';

  return (
    <div className="h-full overflow-y-auto scroll-y p-4 space-y-4 max-w-5xl">
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-lg font-bold flex items-center gap-2">
          <IconGear width={17} height={17} className="text-brand-400" /> System Settings
        </h1>
        <span className="chip border-line-strong bg-ink-800 text-mist-300">{user?.role}</span>
        <div className="flex-1" />
        <button className="btn" onClick={() => void load()}>
          <IconRefresh width={13} height={13} /> Reload
        </button>
      </div>

      <div className="grid lg:grid-cols-2 gap-4 items-start">
        {/* account */}
        <div className="panel rounded-xl p-4">
          <div className="label-cap mb-3">Account</div>
          <div className="space-y-2 text-[13px]">
            <div className="flex justify-between"><span className="text-mist-400">Username</span><b>{user?.username}</b></div>
            <div className="flex justify-between"><span className="text-mist-400">Role</span><b>{user?.role}</b></div>
            <div className="flex justify-between"><span className="text-mist-400">Permissions</span>
              <span className="num text-[11.5px] text-mist-300 text-right">
                {user?.role === 'ADMIN' ? 'read simulate analyze manage apply'
                  : user?.role === 'OPERATOR' ? 'read simulate apply'
                    : user?.role === 'ANALYST' ? 'read analyze' : 'read'}
              </span>
            </div>
          </div>
          <button className="btn w-full mt-4" onClick={logout}>Sign out</button>
        </div>

        {/* simulation controls */}
        <form onSubmit={save} className="panel rounded-xl p-4">
          <div className="label-cap mb-3">Simulation controls {isAdmin ? '' : '· ADMIN only'}</div>

          <label className="block mb-3.5">
            <div className="flex justify-between">
              <span className="text-[13px] text-mist-300">Clock speed multiplier</span>
              <span className="num text-[13px] font-bold text-brand-300">{speed}×</span>
            </div>
            <input
              type="range" min={1} max={30} value={speed}
              disabled={!isAdmin || busy}
              onChange={(e) => setSpeed(Number(e.target.value))}
              className="w-full mt-1.5 accent-blue-500"
            />
            <p className="text-[11px] text-mist-500 mt-1">
              Virtual campus time advances {speed} × 15 virtual-seconds per real second.
            </p>
          </label>

          <label className="block mb-4">
            <div className="flex justify-between">
              <span className="text-[13px] text-mist-300">Sensor tick interval</span>
              <span className="num text-[13px] font-bold text-brand-300">{interval_}s</span>
            </div>
            <input
              type="range" min={1} max={10} value={interval_}
              disabled={!isAdmin || busy}
              onChange={(e) => setInterval_(Number(e.target.value))}
              className="w-full mt-1.5 accent-blue-500"
            />
            <p className="text-[11px] text-mist-500 mt-1">
              Real seconds between telemetry updates (also drives anomaly windows).
            </p>
          </label>

          <div className="flex items-center gap-2 text-[12px] mb-3">
            <span className="text-mist-400">LLM analyst:</span>
            <span className={`chip ${settings?.llm_configured ? 'border-emerald-700 text-emerald-300' : 'border-amber-700 text-amber-300'}`}>
              {settings?.llm_configured ? 'CONFIGURED' : 'NOT CONFIGURED — fallback'}
            </span>
          </div>

          <button type="submit" className="btn btn-primary w-full" disabled={!isAdmin || busy}>
            {busy ? 'Saving…' : 'Save settings'}
          </button>
          {!isAdmin && (
            <p className="text-[11px] text-amber-300 mt-2">Your role cannot modify system settings.</p>
          )}
        </form>

        {/* system status */}
        <div className="panel rounded-xl p-4">
          <div className="label-cap mb-3">System status</div>
          <div className="grid grid-cols-2 gap-2 text-[12.5px]">
            {(Object.entries(status?.health ?? health ?? {}) as [string, boolean | string][]).map(([k, v]) => (
              <div key={k} className="rounded border border-line bg-ink-850 px-2.5 py-2 flex justify-between">
                <span className="text-mist-400 capitalize">{k}</span>
                <span className={`font-semibold ${tone(v)}`}>{String(v)}</span>
              </div>
            ))}
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-3 text-[12px]">
            <div className="rounded border border-line bg-ink-850 p-2.5">
              <div className="label-cap">Twin status</div>
              <div className="font-bold">{snapshot?.status ?? status?.status ?? '—'}</div>
            </div>
            <div className="rounded border border-line bg-ink-850 p-2.5">
              <div className="label-cap">WS clients</div>
              <div className="num font-bold">{snapshot?.connected_clients ?? 0}</div>
            </div>
            <div className="rounded border border-line bg-ink-850 p-2.5">
              <div className="label-cap">Occupancy</div>
              <div className="num font-bold">{fmtNum(snapshot?.metrics.occupancy ?? 0)}</div>
            </div>
            <div className="rounded border border-line bg-ink-850 p-2.5">
              <div className="label-cap">Energy</div>
              <div className="num font-bold text-amber-300">{(snapshot?.metrics.energy ?? 0).toFixed(0)} kW</div>
            </div>
          </div>

          <div className="mt-3">
            <div className="label-cap mb-1.5">Display defaults</div>
            <div className="flex flex-wrap gap-1.5">
              {([
                ['labels', 'Labels'], ['grid', 'Grid'], ['sensors', 'Sensors'], ['heatmap', 'Heatmap'],
                ['occupancy', 'Crowd'], ['routes', 'Routes'], ['night', 'Night mode'],
              ] as const).map(([key, label]) => (
                <button
                  key={key}
                  onClick={() => toggle(key)}
                  className={`chip !text-[10.5px] ${
                    toggles[key] ? 'border-brand-400 bg-brand-950/70 text-brand-200' : 'border-line-strong text-mist-400'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* scenario timings + reset */}
        <div className="panel rounded-xl p-4">
          <div className="label-cap mb-3">Scenario timings (backend)</div>
          <div className="space-y-1.5">
            {Object.entries(settings?.scenario_params ?? {}).map(([key, cfg]) => (
              <div key={key} className="flex items-center justify-between text-[12.5px] border border-line rounded-md bg-ink-850 px-2.5 py-2">
                <span className="capitalize font-semibold">{cfg.label ?? key}</span>
                <span className="num text-mist-400">{cfg.duration}s + {cfg.recover}s recovery</span>
              </div>
            ))}
            {Object.keys(settings?.scenario_params ?? {}).length === 0 && (
              <div className="text-[12px] text-mist-500">Loading…</div>
            )}
          </div>

          <div className="mt-4 pt-4 border-t border-line">
            <div className="label-cap text-amber-300 mb-1.5 flex items-center gap-1.5">
              <IconAlert width={13} height={13} /> Danger zone
            </div>
            <p className="text-[12px] text-mist-400 leading-relaxed mb-3">
              <b>Reset demo state</b> clears active simulations, incidents and recommendations, and
              restores the campus to its seeded baseline — useful between presentations.
              Requires {isAdmin ? 'ADMIN' : 'OPERATOR+'} role.
            </p>
            {!resetArmed ? (
              <button className="btn btn-danger" disabled={busy} onClick={() => setResetArmed(true)}>
                <IconAlert width={13} height={13} /> Reset demo state
              </button>
            ) : (
              <div className="flex gap-2">
                <button className="btn btn-danger" disabled={busy} onClick={() => void reset()}>
                  <IconCheck width={13} height={13} /> {busy ? 'Resetting…' : 'Confirm reset'}
                </button>
                <button className="btn" disabled={busy} onClick={() => setResetArmed(false)}>Cancel</button>
              </div>
            )}
          </div>

          <div className="mt-4 pt-4 border-t border-line text-[12px] text-mist-500 space-y-1.5">
            <div className="flex items-center gap-2"><IconCube width={13} height={13} /> TwinSphere AI v1.0.0 — simulated campus environment</div>
            <div className="flex items-center gap-2"><IconRocket width={13} height={13} /> Demo script available from the DEMO MODE button</div>
          </div>
        </div>
      </div>
    </div>
  );
}
