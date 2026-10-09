import { useCallback, useEffect, useState } from 'react';
import { IconHistory, IconRefresh, IconSearch } from '../components/Icons';
import { api } from '../services/api';
import { useTwinStore } from '../store/useTwinStore';
import type { AuditListResponse } from '../types';

const PAGE_SIZE = 25;

const outcomeClass = (outcome: string) => (
  outcome === 'SUCCESS' ? 'border-emerald-700 text-emerald-300'
    : outcome === 'DENIED' ? 'border-red-700 text-red-300'
      : 'border-amber-700 text-amber-300'
);

/**
 * Phase 10 §15/§23 — read-only audit trail browser.  The API is append-only;
 * ADMIN sees the full scope, OPERATOR the operational subset (auth/authz/admin
 * internals are ADMIN-only — reflected in the scope badge).
 */
export default function AuditLog() {
  const handleApiError = useTwinStore((s) => s.handleApiError);

  const [data, setData] = useState<AuditListResponse | null>(null);
  const [actions, setActions] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState('');
  const [action, setAction] = useState('');
  const [outcome, setOutcome] = useState('');
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [page, setPage] = useState(1);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.auditLogs({
        q: q || undefined,
        action: action || undefined,
        outcome: outcome || undefined,
        start: start ? new Date(start).toISOString() : undefined,
        end: end ? new Date(end).toISOString() : undefined,
        page,
        page_size: PAGE_SIZE,
      });
      setData(res);
    } catch (err) {
      handleApiError(err);
    } finally {
      setLoading(false);
    }
  }, [q, action, outcome, start, end, page, handleApiError]);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    api.auditActions()
      .then((r) => setActions(r.actions))
      .catch(() => { /* filter list is optional */ });
  }, []);

  return (
    <div className="h-full overflow-y-auto scroll-y p-4 space-y-4 max-w-6xl">
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-lg font-bold flex items-center gap-2">
          <IconHistory width={17} height={17} className="text-brand-400" /> Audit Log
        </h1>
        <span className={`chip ${data?.scope === 'full'
          ? 'border-red-700 text-red-300'
          : 'border-blue-700 text-blue-300'}`}>
          {(data?.scope ?? 'operational').toUpperCase()} SCOPE
        </span>
        <div className="flex-1" />
        <button className="btn" onClick={() => void load()}>
          <IconRefresh width={13} height={13} /> Reload
        </button>
      </div>

      <div className="panel rounded-xl p-3 flex flex-wrap items-end gap-2.5">
        <label className="block">
          <span className="label-cap">Search</span>
          <div className="relative mt-1">
            <IconSearch width={13} height={13}
                        className="absolute left-2.5 top-1/2 -translate-y-1/2 text-mist-500" />
            <input
              data-testid="audit-search"
              className="rounded-md bg-ink-900 border border-line pl-8 pr-3 py-1.5 text-[12.5px] outline-none focus:border-brand-500 w-52"
              placeholder="detail / action"
              value={q}
              onChange={(e) => { setQ(e.target.value); setPage(1); }}
            />
          </div>
        </label>
        <label className="block">
          <span className="label-cap">Action</span>
          <select className="mt-1 rounded-md bg-ink-900 border border-line px-2 py-1.5 text-[12.5px] outline-none"
                  value={action}
                  onChange={(e) => { setAction(e.target.value); setPage(1); }}>
            <option value="">All actions</option>
            {actions.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
        </label>
        <label className="block">
          <span className="label-cap">Outcome</span>
          <select className="mt-1 rounded-md bg-ink-900 border border-line px-2 py-1.5 text-[12.5px] outline-none"
                  value={outcome}
                  onChange={(e) => { setOutcome(e.target.value); setPage(1); }}>
            <option value="">All</option>
            <option value="SUCCESS">SUCCESS</option>
            <option value="DENIED">DENIED</option>
          </select>
        </label>
        <label className="block">
          <span className="label-cap">From</span>
          <input type="datetime-local"
                 className="mt-1 rounded-md bg-ink-900 border border-line px-2 py-1.5 text-[12.5px] outline-none"
                 value={start}
                 onChange={(e) => { setStart(e.target.value); setPage(1); }} />
        </label>
        <label className="block">
          <span className="label-cap">To</span>
          <input type="datetime-local"
                 className="mt-1 rounded-md bg-ink-900 border border-line px-2 py-1.5 text-[12.5px] outline-none"
                 value={end}
                 onChange={(e) => { setEnd(e.target.value); setPage(1); }} />
        </label>
        {(q || action || outcome || start || end) && (
          <button className="btn !py-1.5 !text-[11.5px]"
                  onClick={() => { setQ(''); setAction(''); setOutcome(''); setStart(''); setEnd(''); setPage(1); }}>
            Clear
          </button>
        )}
      </div>

      <div className="panel rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-[12.5px]" data-testid="audit-table">
            <thead>
              <tr className="text-left text-mist-500 border-b border-line/60">
                <th className="px-3 py-2 font-medium">Time</th>
                <th className="px-3 py-2 font-medium">Actor</th>
                <th className="px-3 py-2 font-medium">Action</th>
                <th className="px-3 py-2 font-medium">Outcome</th>
                <th className="px-3 py-2 font-medium">Entity</th>
                <th className="px-3 py-2 font-medium">Detail</th>
                <th className="px-3 py-2 font-medium">IP / Request</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={7} className="px-3 py-6 text-center text-mist-500">Loading…</td></tr>
              )}
              {!loading && data?.records.length === 0 && (
                <tr><td colSpan={7} className="px-3 py-6 text-center text-mist-500">No audit records match.</td></tr>
              )}
              {!loading && data?.records.map((r) => (
                <tr key={r.id} className="border-b border-line/40 hover:bg-ink-850/60">
                  <td className="px-3 py-2 num text-mist-400 whitespace-nowrap">
                    {r.created_at ? r.created_at.slice(0, 19).replace('T', ' ') : '—'}
                  </td>
                  <td className="px-3 py-2 font-semibold">{r.actor ?? '—'}</td>
                  <td className="px-3 py-2 num text-brand-300">{r.action}</td>
                  <td className="px-3 py-2">
                    <span className={`chip ${outcomeClass(r.outcome)}`}>{r.outcome}</span>
                  </td>
                  <td className="px-3 py-2 num text-mist-400">
                    {r.entity_type ? `${r.entity_type}${r.entity_id ? `:${r.entity_id}` : ''}` : '—'}
                  </td>
                  <td className="px-3 py-2 text-mist-300 max-w-[320px] truncate" title={r.detail ?? ''}>
                    {r.detail ?? '—'}
                  </td>
                  <td className="px-3 py-2 num text-[11px] text-mist-500 whitespace-nowrap">
                    {r.ip_address ?? '—'}{r.request_id ? ` · ${r.request_id.slice(0, 8)}` : ''}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="flex items-center gap-2 px-3 py-2 border-t border-line/60">
          <span className="text-[11px] text-mist-500 num">
            page {page} / {data?.pages ?? 1} · {data?.total ?? 0} records
            {data?.scope === 'operational' ? ' · auth/admin events hidden' : ''}
          </span>
          <div className="flex-1" />
          <button className="btn !py-0.5 !text-[11px]" data-testid="audit-prev"
                  disabled={loading || page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}>
            ‹ Prev
          </button>
          <button className="btn !py-0.5 !text-[11px]" data-testid="audit-next"
                  disabled={loading || page >= (data?.pages ?? 1)}
                  onClick={() => setPage((p) => p + 1)}>
            Next ›
          </button>
        </div>
      </div>

      <p className="text-[11.5px] text-mist-500">
        The audit trail is append-only: the API exposes no create/update/delete endpoints, every
        request is correlated by <span className="num">X-Request-ID</span>, and secrets (passwords,
        tokens) are redacted before storage.
      </p>
    </div>
  );
}
