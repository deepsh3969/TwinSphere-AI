import { useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { useTwinStore } from '../../store/useTwinStore';
import {
  IconActivity, IconAlert, IconBrain, IconChart, IconCube, IconDashboard,
  IconGear, IconHistory, IconMenu, IconPause, IconPlay, IconRocket, IconUsers, IconX,
} from '../Icons';
import TopBar from './TopBar';
import DemoMode from './DemoMode';

const NAV = [
  { to: '/dashboard', label: 'Command Center', icon: IconDashboard },
  { to: '/twin', label: '3D Twin Explorer', icon: IconCube },
  { to: '/simulation', label: 'Simulation Center', icon: IconPlay },
  { to: '/ai', label: 'AI Intelligence', icon: IconBrain },
  { to: '/analytics', label: 'Analytics', icon: IconChart },
  { to: '/history', label: 'Simulation History', icon: IconHistory },
  { to: '/settings', label: 'System Settings', icon: IconGear },
];

/** Phase 10 §23 — administration entries appear only for roles that can use them. */
function adminNav(role: string | undefined) {
  if (role === 'ADMIN') {
    return [
      { to: '/admin/users', label: 'User Administration', icon: IconUsers },
      { to: '/admin/audit', label: 'Audit Log', icon: IconHistory },
    ];
  }
  if (role === 'OPERATOR') {
    return [{ to: '/admin/audit', label: 'Audit Log', icon: IconHistory }];
  }
  return [];
}

export default function AppShell() {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();
  const backendOffline = useTwinStore((s) => s.backendOffline);
  const connection = useTwinStore((s) => s.connection);
  const setDemo = useTwinStore((s) => s.setDemo);
  const snapshot = useTwinStore((s) => s.snapshot);
  const user = useTwinStore((s) => s.user);
  const adminItems = adminNav(user?.role);

  return (
    <div className="h-screen w-screen flex flex-col bg-ink-950 text-mist-100 overflow-hidden">
      <TopBar onMenu={() => setMobileOpen((v) => !v)} onDemo={() => setDemo(true)} />

      {backendOffline && (
        <div className="flex items-center gap-2 bg-red-950/80 border-b border-red-800 px-4 py-1.5 text-[12px] font-semibold text-red-200">
          <IconAlert width={14} height={14} /> BACKEND OFFLINE — data shown may be stale.
        </div>
      )}
      {!backendOffline && connection !== 'CONNECTED' && (
        <div className="flex items-center gap-2 bg-amber-950/80 border-b border-amber-800 px-4 py-1.5 text-[12px] font-semibold text-amber-200">
          <IconActivity width={14} height={14} className="pulse-soft" />
          {connection === 'OFFLINE' ? 'REAL-TIME CONNECTION LOST — reconnecting…' : 'REAL-TIME LINK DEGRADED — retrying…'}
        </div>
      )}
      {snapshot?.active_sim && snapshot.active_sim.status === 'RUNNING' && (
        <div className="flex items-center gap-2 bg-red-950/85 border-b border-red-700 px-4 py-1.5 text-[12px] font-semibold text-red-200">
          <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
          SIMULATION ACTIVE — {snapshot.active_sim.scenario.toUpperCase()}
          {snapshot.active_sim.target_id ? ` · ${snapshot.active_sim.target_id}` : ''}
          {' · '}<span className="num">T+{snapshot.active_sim.t.toFixed(0)}s</span>
          {' · '}<span className="num">{snapshot.active_sim.people_at_risk}</span> people at risk
          <NavLink to="/simulation" className="ml-auto underline hover:text-white">
            open Simulation Center →
          </NavLink>
        </div>
      )}
      {snapshot?.active_sim && snapshot.active_sim.status === 'PAUSED' && (
        <div className="flex items-center gap-2 bg-amber-950/85 border-b border-amber-700 px-4 py-1.5 text-[12px] font-semibold text-amber-200">
          <IconPause width={13} height={13} /> SIMULATION PAUSED — {snapshot.active_sim.scenario.toUpperCase()}
          <NavLink to="/simulation" className="ml-auto underline hover:text-white">resume →</NavLink>
        </div>
      )}
      {snapshot?.status === 'RECOVERING' && (
        <div className="flex items-center gap-2 bg-blue-950/80 border-b border-blue-800 px-4 py-1.5 text-[12px] font-semibold text-blue-200">
          <IconActivity width={14} height={14} /> RECOVERY IN PROGRESS — {snapshot.recovery_progress.toFixed(0)}% complete
        </div>
      )}

      <div className="flex flex-1 min-h-0">
        {mobileOpen && (
          <button
            className="fixed inset-0 z-30 bg-black/60 lg:hidden"
            onClick={() => setMobileOpen(false)}
            aria-label="Close navigation"
          />
        )}
        <nav
          className={`${collapsed ? 'w-[64px]' : 'w-[218px]'} shrink-0 z-40 border-r border-line bg-ink-900 flex flex-col transition-all duration-200
            max-lg:fixed max-lg:top-[52px] max-lg:bottom-0 max-lg:left-0
            ${mobileOpen ? 'max-lg:flex' : 'max-lg:hidden'}`}
        >
          <div className="flex-1 py-2">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                onClick={() => setMobileOpen(false)}
                className={({ isActive }) =>
                  `flex items-center gap-3 px-4 py-2.5 text-[13px] font-medium border-l-2 transition-colors
                  ${isActive
                    ? 'border-brand-400 bg-ink-800 text-white'
                    : 'border-transparent text-mist-300 hover:text-white hover:bg-ink-850'}`
                }
              >
                <item.icon width={17} height={17} className="shrink-0" />
                {!collapsed && <span className="truncate">{item.label}</span>}
              </NavLink>
            ))}
            {adminItems.length > 0 && !collapsed && (
              <div className="px-4 pt-4 pb-1 label-cap">Administration</div>
            )}
            {adminItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                onClick={() => setMobileOpen(false)}
                className={({ isActive }) =>
                  `flex items-center gap-3 px-4 py-2.5 text-[13px] font-medium border-l-2 transition-colors
                  ${isActive
                    ? 'border-brand-400 bg-ink-800 text-white'
                    : 'border-transparent text-mist-300 hover:text-white hover:bg-ink-850'}`
                }
              >
                <item.icon width={17} height={17} className="shrink-0" />
                {!collapsed && <span className="truncate">{item.label}</span>}
              </NavLink>
            ))}
          </div>

          {!collapsed && (
            <div className="p-3 mx-3 mb-3 rounded-lg panel-flat">
              <div className="label-cap mb-1">Simulated Telemetry</div>
              <p className="text-[11px] leading-relaxed text-mist-500">
                Live Digital Twin — simulated sensor feeds. Replaceable with real IoT streams.
              </p>
            </div>
          )}
          <button
            className="border-t border-line py-2.5 text-mist-500 hover:text-white text-[12px] flex items-center justify-center gap-2"
            onClick={() => setCollapsed((v) => !v)}
          >
            {collapsed ? '›' : '‹ Collapse'}
          </button>
        </nav>

        <main className="flex-1 min-w-0 min-h-0 overflow-hidden relative">
          <Outlet key={location.pathname} />
        </main>
      </div>

      <button
        onClick={() => setDemo(true)}
        className="fixed bottom-5 right-5 z-30 btn btn-primary shadow-lg shadow-blue-900/40"
        title="Run the guided hackathon demo"
      >
        <IconRocket width={14} height={14} /> DEMO MODE
      </button>
      <DemoMode />
    </div>
  );
}
