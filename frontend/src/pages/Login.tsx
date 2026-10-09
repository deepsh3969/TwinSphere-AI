import { useEffect, useState, type FormEvent } from 'react';
import { Link, Navigate, useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { useTwinStore } from '../store/useTwinStore';
import { api } from '../services/api';
import type { DemoAccountsResponse } from '../types';
import { IconAlert, IconCube, IconX } from '../components/Icons';

export default function Login() {
  const token = useTwinStore((s) => s.token);
  const login = useTwinStore((s) => s.login);
  const authError = useTwinStore((s) => s.authError);
  const authLoading = useTwinStore((s) => s.authLoading);
  const backendOffline = useTwinStore((s) => s.backendOffline);
  const [username, setUsername] = useState('operator');
  const [password, setPassword] = useState('operator123');
  const [demo, setDemo] = useState<DemoAccountsResponse | null>(null);
  const navigate = useNavigate();

  // Phase 10 §6/§23 — demo accounts come from the server (never hardcoded
  // credentials in the bundle); the endpoint exposes usernames/roles only.
  useEffect(() => {
    let alive = true;
    api.demoAccounts()
      .then((d) => { if (alive) setDemo(d); })
      .catch(() => { /* demo list is optional */ });
    return () => { alive = false; };
  }, []);

  if (token) return <Navigate to="/dashboard" replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await login(username, password);
      navigate('/dashboard');
    } catch {
      /* error surfaced via store */
    }
  };

  const demoUsers = demo?.enabled ? demo.users : [];

  return (
    <div className="min-h-screen bg-ink-950 flex items-center justify-center px-4 relative overflow-hidden">
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(37,99,235,0.14),transparent_65%)]" />
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        className="w-full max-w-[420px] relative"
      >
        <Link to="/" className="flex items-center gap-2.5 mb-6 justify-center">
          <div className="w-9 h-9 rounded-md bg-gradient-to-br from-brand-500 to-aqua-400 flex items-center justify-center text-ink-950 font-black">TS</div>
          <div>
            <div className="font-bold tracking-wide">TWINSPHERE AI</div>
            <div className="text-[10px] tracking-[0.18em] text-mist-500 uppercase">Campus Digital Twin</div>
          </div>
        </Link>

        <div className="panel rounded-xl p-6">
          <h1 className="text-lg font-bold mb-1">Operator sign in</h1>
          <p className="text-[12.5px] text-mist-500 mb-5">Role-based access to the command platform.</p>

          {backendOffline && (
            <div className="mb-4 rounded-md border border-red-800 bg-red-950/50 px-3 py-2 text-[12px] text-red-200 flex items-center gap-2">
              <IconAlert width={14} height={14} /> BACKEND OFFLINE — start the API server first.
            </div>
          )}
          {authError && (
            <div className="mb-4 rounded-md border border-red-800 bg-red-950/50 px-3 py-2 text-[12px] text-red-200 flex items-center gap-2">
              <IconX width={14} height={14} /> {authError}
            </div>
          )}

          <form onSubmit={submit} className="space-y-3.5">
            <label className="block">
              <span className="label-cap">Username</span>
              <input
                className="mt-1 w-full rounded-md bg-ink-900 border border-line px-3 py-2.5 text-[13.5px] outline-none focus:border-brand-500"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                required
              />
            </label>
            <label className="block">
              <span className="label-cap">Password</span>
              <input
                type="password"
                className="mt-1 w-full rounded-md bg-ink-900 border border-line px-3 py-2.5 text-[13.5px] outline-none focus:border-brand-500"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
              />
            </label>
            <button type="submit" className="btn btn-primary w-full !py-2.5 !text-[13.5px]" disabled={authLoading}>
              {authLoading ? 'Signing in…' : 'Sign in'}
            </button>
          </form>

          {demoUsers.length > 0 && (
            <div className="mt-5 pt-4 border-t border-line">
              <div className="flex items-center justify-between mb-2">
                <div className="label-cap">Demo accounts (click to fill)</div>
                <span className="chip border-amber-800 bg-amber-950/60 text-amber-300 !text-[9.5px]">
                  DEMO — local development
                </span>
              </div>
              <div className="grid grid-cols-2 gap-1.5">
                {demoUsers.map((u) => (
                  <button
                    key={u.username}
                    type="button"
                    className="text-left rounded-md border border-line bg-ink-850 hover:border-brand-500 px-2.5 py-1.5 transition-colors"
                    onClick={() => { setUsername(u.username); setPassword(''); }}
                  >
                    <div className="text-[11.5px] font-semibold">{u.username}</div>
                    <div className="text-[10px] text-mist-500">{u.role} · {u.desc}</div>
                  </button>
                ))}
              </div>
              <p className="text-[10.5px] text-mist-500 mt-2">
                Seeded demo passwords are documented in README.md — never used in production.
              </p>
            </div>
          )}
        </div>

        <div className="mt-4 text-center text-[12px] text-mist-500 flex items-center justify-center gap-2">
          <IconCube width={13} height={13} /> <Link to="/" className="hover:text-white">Back to overview</Link>
        </div>
      </motion.div>
    </div>
  );
}
