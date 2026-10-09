import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { IconRefresh, IconSearch, IconUsers } from '../components/Icons';
import { api, ApiError } from '../services/api';
import { useTwinStore } from '../store/useTwinStore';
import type { Role, UserListResponse, UserProfile } from '../types';

const ROLES: Role[] = ['ADMIN', 'OPERATOR', 'ANALYST', 'VIEWER'];
const PAGE_SIZE = 10;

const roleClass = (role: string) => (
  role === 'ADMIN' ? 'border-red-700 text-red-300'
    : role === 'OPERATOR' ? 'border-amber-700 text-amber-300'
      : role === 'ANALYST' ? 'border-blue-700 text-blue-300'
        : 'border-emerald-700 text-emerald-300'
);

/**
 * Phase 10 §17/§23 — ADMIN user administration UI: list/create, role changes,
 * enable/disable, one-time password reset.  Every action hits the
 * `manage`-permission API; the server re-validates (last-admin, self-lockout).
 */
export default function AdminUsers() {
  const handleApiError = useTwinStore((s) => s.handleApiError);
  const pushToast = useTwinStore((s) => s.pushToast);
  const me = useTwinStore((s) => s.user);

  const [data, setData] = useState<UserListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState('');
  const [roleFilter, setRoleFilter] = useState('');
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);
  const [tempPassword, setTempPassword] = useState<{ username: string; password: string } | null>(null);

  const [newUser, setNewUser] = useState({ username: '', email: '', password: '', role: 'VIEWER' as Role });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.listUsers({
        q: q || undefined, role: roleFilter || undefined, page, page_size: PAGE_SIZE,
      });
      setData(res);
    } catch (err) {
      handleApiError(err);
      if (err instanceof ApiError && err.status === 403) setData(null);
    } finally {
      setLoading(false);
    }
  }, [q, roleFilter, page, handleApiError]);

  useEffect(() => { void load(); }, [load]);

  const createUser = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.createUser(newUser);
      pushToast('success', 'USER CREATED', `${newUser.username} (${newUser.role})`);
      setCreating(false);
      setNewUser({ username: '', email: '', password: '', role: 'VIEWER' });
      await load();
    } catch (err) {
      handleApiError(err);
    } finally {
      setBusy(false);
    }
  };

  const patch = async (id: string, body: { role?: Role; is_active?: boolean }, label: string) => {
    setBusy(true);
    try {
      await api.updateUser(id, body);
      pushToast('success', label, '');
      await load();
    } catch (err) {
      handleApiError(err);
    } finally {
      setBusy(false);
    }
  };

  const resetPassword = async (u: UserProfile) => {
    setBusy(true);
    try {
      const res = await api.resetUserPassword(u.id);
      setTempPassword({ username: u.username, password: res.temporary_password });
      pushToast('warn', 'PASSWORD RESET', `Sessions revoked for ${u.username}`);
    } catch (err) {
      handleApiError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="h-full overflow-y-auto scroll-y p-4 space-y-4 max-w-6xl">
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-lg font-bold flex items-center gap-2">
          <IconUsers width={17} height={17} className="text-brand-400" /> User Administration
        </h1>
        <span className="chip border-line-strong bg-ink-800 text-mist-300">ADMIN only</span>
        {data && (
          <span className="chip border-line-strong bg-ink-800 text-mist-300 num">
            {data.active_admins} active admin{data.active_admins === 1 ? '' : 's'}
          </span>
        )}
        <div className="flex-1" />
        <button className="btn" onClick={() => void load()}>
          <IconRefresh width={13} height={13} /> Reload
        </button>
        <button className="btn btn-primary" data-testid="create-user-toggle"
                onClick={() => setCreating((v) => !v)}>
          + New user
        </button>
      </div>

      {tempPassword && (
        <div className="rounded-lg border border-amber-700 bg-amber-950/50 px-3 py-2.5 text-[12.5px] text-amber-200 flex items-start gap-2"
             data-testid="temp-password">
          <span className="flex-1">
            One-time password for <b>{tempPassword.username}</b> — shown exactly once:{' '}
            <code className="num bg-ink-900 px-1.5 py-0.5 rounded select-all">{tempPassword.password}</code>
            . The user must change it after signing in; all their sessions were revoked.
          </span>
          <button className="btn !py-0.5 !text-[11px]" onClick={() => setTempPassword(null)}>Dismiss</button>
        </div>
      )}

      {creating && (
        <form onSubmit={createUser} className="panel rounded-xl p-4 grid sm:grid-cols-4 gap-3 items-end"
              data-testid="create-user-form">
          <label className="block">
            <span className="label-cap">Username</span>
            <input className="mt-1 w-full rounded-md bg-ink-900 border border-line px-3 py-2 text-[13px] outline-none focus:border-brand-500"
                   value={newUser.username} required minLength={3} maxLength={64}
                   onChange={(e) => setNewUser({ ...newUser, username: e.target.value })} />
          </label>
          <label className="block">
            <span className="label-cap">Email</span>
            <input type="email" required
                   className="mt-1 w-full rounded-md bg-ink-900 border border-line px-3 py-2 text-[13px] outline-none focus:border-brand-500"
                   value={newUser.email}
                   onChange={(e) => setNewUser({ ...newUser, email: e.target.value })} />
          </label>
          <label className="block">
            <span className="label-cap">Password (min 8)</span>
            <input type="password" required minLength={8} maxLength={128}
                   className="mt-1 w-full rounded-md bg-ink-900 border border-line px-3 py-2 text-[13px] outline-none focus:border-brand-500"
                   value={newUser.password}
                   onChange={(e) => setNewUser({ ...newUser, password: e.target.value })} />
          </label>
          <div className="flex gap-2">
            <select className="rounded-md bg-ink-900 border border-line px-2 py-2 text-[13px] outline-none flex-1"
                    value={newUser.role}
                    onChange={(e) => setNewUser({ ...newUser, role: e.target.value as Role })}>
              {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
            <button className="btn btn-primary" disabled={busy} type="submit">Create</button>
          </div>
        </form>
      )}

      <div className="panel rounded-xl overflow-hidden">
        <div className="flex items-center gap-2 p-3 border-b border-line/60 flex-wrap">
          <div className="relative">
            <IconSearch width={13} height={13}
                        className="absolute left-2.5 top-1/2 -translate-y-1/2 text-mist-500" />
            <input
              data-testid="users-search"
              className="rounded-md bg-ink-900 border border-line pl-8 pr-3 py-1.5 text-[12.5px] outline-none focus:border-brand-500 w-52"
              placeholder="Search username / email"
              value={q}
              onChange={(e) => { setQ(e.target.value); setPage(1); }}
            />
          </div>
          <select className="rounded-md bg-ink-900 border border-line px-2 py-1.5 text-[12.5px] outline-none"
                  value={roleFilter}
                  onChange={(e) => { setRoleFilter(e.target.value); setPage(1); }}>
            <option value="">All roles</option>
            {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
          <div className="flex-1" />
          <span className="text-[11px] text-mist-500 num">{data?.total ?? 0} users</span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-[12.5px]" data-testid="users-table">
            <thead>
              <tr className="text-left text-mist-500 border-b border-line/60">
                <th className="px-3 py-2 font-medium">Username</th>
                <th className="px-3 py-2 font-medium">Email</th>
                <th className="px-3 py-2 font-medium">Role</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Last login</th>
                <th className="px-3 py-2 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={6} className="px-3 py-6 text-center text-mist-500">Loading…</td></tr>
              )}
              {!loading && data?.users.length === 0 && (
                <tr><td colSpan={6} className="px-3 py-6 text-center text-mist-500">No users match.</td></tr>
              )}
              {!loading && data?.users.map((u) => {
                const isSelf = u.id === me?.id;
                return (
                  <tr key={u.id} className="border-b border-line/40 hover:bg-ink-850/60">
                    <td className="px-3 py-2 font-semibold">
                      {u.username}
                      {isSelf && <span className="ml-2 text-[10px] text-mist-500">(you)</span>}
                    </td>
                    <td className="px-3 py-2 text-mist-400">{u.email}</td>
                    <td className="px-3 py-2">
                      <select
                        className={`chip bg-transparent outline-none ${roleClass(u.role)}`}
                        value={u.role}
                        disabled={busy || isSelf}
                        data-testid={`role-select-${u.username}`}
                        onChange={(e) => patch(u.id, { role: e.target.value as Role },
                          `ROLE UPDATED — ${u.username} → ${e.target.value}`)}
                      >
                        {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                      </select>
                    </td>
                    <td className="px-3 py-2">
                      <span className={`chip ${u.is_active
                        ? 'border-emerald-700 text-emerald-300'
                        : 'border-red-700 text-red-300'}`}>
                        {u.is_active ? 'ACTIVE' : 'DISABLED'}
                      </span>
                    </td>
                    <td className="px-3 py-2 num text-mist-400">
                      {u.last_login_at ? u.last_login_at.slice(0, 16).replace('T', ' ') : '—'}
                    </td>
                    <td className="px-3 py-2 text-right whitespace-nowrap">
                      <button className="btn !py-0.5 !text-[11px] mr-1.5" disabled={busy || isSelf}
                              data-testid={`toggle-active-${u.username}`}
                              onClick={() => patch(u.id, { is_active: !u.is_active },
                                `${u.is_active ? 'DISABLED' : 'ENABLED'} — ${u.username}`)}>
                        {u.is_active ? 'Disable' : 'Enable'}
                      </button>
                      <button className="btn !py-0.5 !text-[11px]" disabled={busy || isSelf}
                              data-testid={`reset-pw-${u.username}`}
                              onClick={() => void resetPassword(u)}>
                        Reset password
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <div className="flex items-center gap-2 px-3 py-2 border-t border-line/60">
          <span className="text-[11px] text-mist-500 num">
            page {page} / {data?.pages ?? 1} · {data?.total ?? 0} users
          </span>
          <div className="flex-1" />
          <button className="btn !py-0.5 !text-[11px]" disabled={loading || page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}>
            ‹ Prev
          </button>
          <button className="btn !py-0.5 !text-[11px]"
                  disabled={loading || page >= (data?.pages ?? 1)}
                  onClick={() => setPage((p) => p + 1)}>
            Next ›
          </button>
        </div>
      </div>

      <p className="text-[11.5px] text-mist-500">
        Guards enforced by the API: the last active administrator cannot be demoted or disabled,
        you cannot disable your own account, and password resets revoke every session for the
        target user (all actions are written to the audit log).
      </p>
    </div>
  );
}
