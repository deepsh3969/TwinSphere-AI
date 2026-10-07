import { useNavigate } from 'react-router-dom';
import { useTwinStore } from '../../store/useTwinStore';
import { IconAlert, IconLogout, IconMenu, IconRocket } from '../Icons';

function clockLabel(hour: number): string {
  const h = Math.floor(hour) % 24;
  const m = Math.floor((hour % 1) * 60);
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
}

export default function TopBar({ onMenu, onDemo }: { onMenu: () => void; onDemo: () => void }) {
  const snapshot = useTwinStore((s) => s.snapshot);
  const connection = useTwinStore((s) => s.connection);
  const user = useTwinStore((s) => s.user);
  const logout = useTwinStore((s) => s.logout);
  const navigate = useNavigate();

  const metrics = snapshot?.metrics;
  const connColor =
    connection === 'CONNECTED' ? 'text-emerald-300 border-emerald-700 bg-emerald-950/60'
      : connection === 'DEGRADED' ? 'text-amber-300 border-amber-700 bg-amber-950/60'
        : 'text-red-300 border-red-700 bg-red-950/60';

  return (
    <header className="h-[52px] shrink-0 border-b border-line bg-ink-900 flex items-center gap-4 px-3 lg:px-4">
      <button className="lg:hidden text-mist-300 hover:text-white" onClick={onMenu} aria-label="Menu">
        <IconMenu width={18} height={18} />
      </button>

      <div className="flex items-center gap-2.5 select-none">
        <div className="w-7 h-7 rounded-md bg-gradient-to-br from-brand-500 to-aqua-400 flex items-center justify-center text-[13px] font-black text-ink-950">
          TS
        </div>
        <div className="leading-none">
          <div className="text-[13.5px] font-bold tracking-wide">TWINSPHERE AI</div>
          <div className="text-[9.5px] tracking-[0.18em] text-mist-500 uppercase">Campus Digital Twin</div>
        </div>
      </div>

      <span className={`chip ${connColor}`} title="WebSocket telemetry link">
        <span className={`w-1.5 h-1.5 rounded-full ${connection === 'CONNECTED' ? 'bg-emerald-400 pulse-soft' : connection === 'DEGRADED' ? 'bg-amber-400' : 'bg-red-400'}`} />
        {connection}
      </span>

      <div className="hidden md:flex items-center gap-4 text-[11.5px] text-mist-300">
        <span className="num text-mist-100">{clockLabel(snapshot?.clock_hour ?? 0)}</span>
        <span className="text-mist-500">·</span>
        <span>Speed <span className="num text-white">{snapshot?.speed ?? 1}x</span></span>
        <span className="text-mist-500">·</span>
        <span>
          Risk{' '}
          <span className={`num font-bold ${
            (metrics?.risk ?? 0) > 80 ? 'text-red-400' : (metrics?.risk ?? 0) > 60 ? 'text-orange-400'
              : (metrics?.risk ?? 0) > 40 ? 'text-amber-300' : 'text-emerald-400'}`}>
            {metrics ? metrics.risk.toFixed(0) : '--'}
          </span>
        </span>
        {metrics && metrics.incidents > 0 && (
          <span className="text-red-300 flex items-center gap-1">
            <IconAlert width={12} height={12} /> {metrics.incidents} incident{metrics.incidents > 1 ? 's' : ''}
          </span>
        )}
        <span className="chip border-line-strong bg-ink-800 text-mist-300">SIMULATED DATA</span>
      </div>

      <div className="flex-1" />

      <button className="btn hidden sm:inline-flex" onClick={onDemo} title="Guided presentation flow">
        <IconRocket width={13} height={13} /> Demo
      </button>

      <div className="flex items-center gap-2.5 pl-2 border-l border-line">
        <div className="text-right hidden sm:block leading-tight">
          <div className="text-[12.5px] font-semibold">{user?.username ?? 'operator'}</div>
          <div className="text-[10px] text-brand-400 font-bold tracking-wider">{user?.role ?? 'OPERATOR'}</div>
        </div>
        <button
          className="w-8 h-8 rounded-md bg-ink-800 border border-line flex items-center justify-center text-mist-300 hover:text-white hover:border-line-strong"
          title="Sign out"
          onClick={() => { logout(); navigate('/login'); }}
        >
          <IconLogout width={15} height={15} />
        </button>
      </div>
    </header>
  );
}
