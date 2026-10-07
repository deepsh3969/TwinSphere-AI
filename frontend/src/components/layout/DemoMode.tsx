import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../../services/api';
import { useTwinStore } from '../../store/useTwinStore';
import { IconCheck, IconPause, IconPlay, IconRefresh, IconRocket, IconX } from '../Icons';

interface DemoStep {
  id: number;
  title: string;
  detail: string;
  action: {
    type: string;
    target?: string;
    building?: string;
    params?: Record<string, unknown>;
    seconds?: number;
  };
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export default function DemoMode() {
  const open = useTwinStore((s) => s.demoOpen);
  const step = useTwinStore((s) => s.demoStep);
  const running = useTwinStore((s) => s.demoRunning);
  const setDemo = useTwinStore((s) => s.setDemo);
  const setDemoStep = useTwinStore((s) => s.setDemoStep);
  const setDemoRunning = useTwinStore((s) => s.setDemoRunning);
  const pushToast = useTwinStore((s) => s.pushToast);
  const handleApiError = useTwinStore((s) => s.handleApiError);

  const [steps, setSteps] = useState<DemoStep[]>([]);
  const [busy, setBusy] = useState(false);
  const cancelRef = useRef(false);
  const navigate = useNavigate();

  useEffect(() => {
    if (!open) return;
    api.demoScript()
      .then((res) => setSteps(res.steps as unknown as DemoStep[]))
      .catch(() => setSteps([]));
    return () => { cancelRef.current = true; };
  }, [open]);

  const execute = useCallback(async (s: DemoStep) => {
    const a = s.action;
    switch (a.type) {
      case 'navigate':
        if (a.target) navigate(a.target);
        break;
      case 'select_building': {
        navigate('/twin');
        if (a.target) {
          await useTwinStore.getState().selectBuilding(a.target);
          const b = useTwinStore.getState().snapshot?.buildings.find((x) => x.id === a.target);
          useTwinStore.getState().focusCamera(b?.position.x ?? 0, b?.position.z ?? 0);
        }
        break;
      }
      case 'show_predictions':
        navigate('/ai');
        break;
      case 'show_ai':
        navigate('/ai');
        await useTwinStore.getState().refreshAnalyst();
        break;
      case 'show_routes': {
        const st = useTwinStore.getState();
        if (!st.toggles.routes) st.toggle('routes');
        navigate('/twin');
        break;
      }
      case 'show_route_panel': {
        // Phase 7 §41 — surface the route optimization panel over the twin
        const st = useTwinStore.getState();
        if (!st.toggles.routes) st.toggle('routes');
        st.setRoutePanelOpen(true);
        await st.refreshRouteData();
        navigate('/twin');
        break;
      }
      case 'start_simulation': {
        const state = useTwinStore.getState();
        const existing = state.snapshot?.active_sim;
        if (existing && !['COMPLETED', 'RESET'].includes(existing.status)) {
          pushToast('info', 'DEMO SKIPPED STEP', 'A simulation is already active — reset first to replay.');
          break;
        }
        try {
          const created = await api.createSimulation(a.target ?? 'fire', a.building ?? null, a.params ?? {});
          await api.simAction(created.id, 'start');
          pushToast('success', 'FIRE DRILL STARTED', 'Ignition registered in the digital twin.');
          navigate('/simulation');
        } catch (err) {
          handleApiError(err);
        }
        break;
      }
      case 'apply_recommendation': {
        try {
          const recs = await api.recommendations('PENDING');
          const rec = Array.isArray(recs) ? recs[0] : undefined;
          if (rec) {
            const applied = await api.applyRecommendation(rec.id);
            pushToast('success', 'RECOMMENDATION APPLIED', applied.applied_detail ?? applied.title);
            await useTwinStore.getState().refreshAnalyst();
          } else {
            pushToast('warn', 'NO PENDING RECOMMENDATIONS', 'Run the fire drill a little longer first.');
          }
        } catch (err) {
          handleApiError(err);
        }
        break;
      }
      case 'recover': {
        const sim = useTwinStore.getState().snapshot?.active_sim;
        if (sim && sim.status !== 'COMPLETED') {
          try {
            await api.simAction(sim.id, 'recover');
            pushToast('success', 'RECOVERY STARTED', 'Restoring campus systems 0 → 100%.');
          } catch (err) {
            handleApiError(err);
          }
        }
        break;
      }
      case 'wait':
      case 'watch':
        await sleep(Math.min(15, a.seconds ?? 3) * 1000);
        break;
      default:
        break;
    }
  }, [navigate, pushToast, handleApiError]);

  const run = useCallback(async (from: number) => {
    cancelRef.current = false;
    setDemoRunning(true);
    for (let i = from; i < steps.length; i += 1) {
      if (cancelRef.current) break;
      setDemoStep(i);
      setBusy(true);
      await execute(steps[i]);
      setBusy(false);
      if (cancelRef.current) break;
      await sleep(700);
    }
    setDemoRunning(false);
    if (!cancelRef.current) pushToast('success', 'DEMO COMPLETE', 'Reset the demo state to replay the flow.');
  }, [steps, execute, setDemoRunning, setDemoStep, pushToast]);

  const resetAll = async () => {
    cancelRef.current = true;
    setDemoRunning(false);
    setBusy(true);
    try {
      await api.demoReset();
      setDemoStep(0);
      // Phase 7 — demo reset clears server route state; sync the client slice
      const st = useTwinStore.getState();
      st.setRoutePanelOpen(false);
      useTwinStore.setState({
        routePlan: null, evacuation: null, routeBottlenecks: [],
        buildingEvacuation: null, routeAlternatives: null, routeHistory: [],
      });
      void st.refreshRouteData();
      navigate('/dashboard');
      pushToast('success', 'DEMO RESET', 'Twin restored to the presentation baseline.');
    } catch (err) {
      handleApiError(err);
    } finally {
      setBusy(false);
    }
  };

  if (!open) return null;
  const current = steps[step];
  const pct = steps.length ? ((step + 1) / steps.length) * 100 : 0;

  return (
    <div className="fixed right-4 bottom-20 z-40 w-[370px] max-w-[calc(100vw-32px)] panel rounded-xl shadow-2xl shadow-black/70 fade-in flex flex-col max-h-[72vh]">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-line">
        <IconRocket width={15} height={15} className="text-brand-400" />
        <span className="font-bold text-[13px] tracking-wide">DEMO MODE</span>
        <span className="chip border-line-strong bg-ink-800 text-mist-300 num">
          {steps.length ? step + 1 : 0}/{steps.length || '—'}
        </span>
        <button className="ml-auto text-mist-500 hover:text-white" onClick={() => { cancelRef.current = true; setDemoRunning(false); setDemo(false); }}>
          <IconX width={15} height={15} />
        </button>
      </div>

      <div className="h-1 bg-ink-700">
        <div className="h-full bg-gradient-to-r from-brand-500 to-aqua-400 transition-all duration-500" style={{ width: `${pct}%` }} />
      </div>

      {current && (
        <div className="px-4 py-3 border-b border-line bg-ink-850/60">
          <div className="label-cap text-brand-300">Step {current.id}</div>
          <div className="text-[14px] font-bold mt-0.5">{current.title}</div>
          <p className="text-[12.5px] text-mist-300 mt-1 leading-relaxed">{current.detail}</p>
        </div>
      )}

      <div className="flex-1 min-h-0 scroll-y px-3 py-2 space-y-1">
        {steps.length === 0 && (
          <div className="text-[12px] text-mist-500 py-6 text-center">
            Loading demo script… (backend required)
          </div>
        )}
        {steps.map((s, i) => (
          <button
            key={s.id}
            onClick={() => setDemoStep(i)}
            className={`w-full text-left flex items-center gap-2 rounded px-2 py-1.5 text-[12px] transition-colors ${
              i === step ? 'bg-brand-950/70 border border-brand-500 text-white'
                : i < step ? 'text-mist-400 border border-transparent' : 'text-mist-300 border border-transparent hover:bg-ink-850'
            }`}
          >
            <span className={`w-4 h-4 rounded-full flex items-center justify-center shrink-0 text-[9px] ${
              i < step ? 'bg-emerald-600 text-white' : i === step ? 'bg-brand-500 text-white' : 'bg-ink-700 text-mist-400'
            }`}>
              {i < step ? <IconCheck width={9} height={9} /> : s.id}
            </span>
            <span className="truncate">{s.title}</span>
            {i < step && <span className="ml-auto text-emerald-400">done</span>}
          </button>
        ))}
      </div>

      <div className="p-3 border-t border-line flex gap-2">
        {!running ? (
          <button className="btn btn-primary flex-1" disabled={busy || steps.length === 0} onClick={() => void run(step >= steps.length - 1 ? 0 : step)}>
            <IconPlay width={13} height={13} /> {step > 0 && step < steps.length - 1 ? 'Resume demo' : 'Run demo'}
          </button>
        ) : (
          <button className="btn btn-danger flex-1" onClick={() => { cancelRef.current = true; setDemoRunning(false); }}>
            <IconPause width={13} height={13} /> Pause demo
          </button>
        )}
        <button
          className="btn"
          disabled={busy || running || step === 0}
          onClick={async () => {
            const next = Math.max(0, step - 1);
            setDemoStep(next);
            setBusy(true);
            await execute(steps[next]);
            setBusy(false);
          }}
        >
          ◀
        </button>
        <button
          className="btn"
          disabled={busy || running || step >= steps.length - 1}
          onClick={async () => {
            const next = step + 1;
            setDemoStep(next);
            setBusy(true);
            await execute(steps[next]);
            setBusy(false);
          }}
        >
          ▶
        </button>
        <button className="btn" disabled={busy} onClick={() => void resetAll()} title="Reset demo state">
          <IconRefresh width={13} height={13} />
        </button>
      </div>
    </div>
  );
}
