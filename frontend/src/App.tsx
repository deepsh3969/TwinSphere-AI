import { useEffect, useRef } from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import AppShell from './components/layout/AppShell';
import ToastHost from './components/layout/ToastHost';
import { useTwinStore } from './store/useTwinStore';
import Landing from './pages/Landing';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import TwinExplorer from './pages/TwinExplorer';
import SimulationCenter from './pages/SimulationCenter';
import AIIntelligence from './pages/AIIntelligence';
import Analytics from './pages/Analytics';
import History from './pages/History';
import Settings from './pages/Settings';

function BootGate() {
  const token = useTwinStore((s) => s.token);
  const boot = useTwinStore((s) => s.boot);
  const logout = useTwinStore((s) => s.logout);
  const bootedFor = useRef<string | null>(null);

  useEffect(() => {
    const onUnauthorized = () => logout();
    window.addEventListener('ts:unauthorized', onUnauthorized);
    return () => window.removeEventListener('ts:unauthorized', onUnauthorized);
  }, [logout]);

  useEffect(() => {
    if (token && bootedFor.current !== token) {
      bootedFor.current = token;
      void boot();
    }
    if (!token) bootedFor.current = null;
  }, [token, boot]);

  return null;
}

export default function App() {
  return (
    <BrowserRouter>
      <BootGate />
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/login" element={<Login />} />
        <Route
          element={
            <RequireAuth>
              <AppShell />
            </RequireAuth>
          }
        >
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/twin" element={<TwinExplorer />} />
          <Route path="/simulation" element={<SimulationCenter />} />
          <Route path="/ai" element={<AIIntelligence />} />
          <Route path="/analytics" element={<Analytics />} />
          <Route path="/history" element={<History />} />
          <Route path="/settings" element={<Settings />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <ToastHost />
    </BrowserRouter>
  );
}

function RequireAuth({ children }: { children: JSX.Element }) {
  const token = useTwinStore((s) => s.token);
  if (!token) return <Navigate to="/login" replace />;
  return children;
}
