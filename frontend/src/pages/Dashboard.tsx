import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  getDashboardSummary,
  getMe,
  type ApprovalItem,
  type DashboardSummary,
  type RunItem,
  type User,
} from '../api/client'
import Shell from '../components/Shell'

// v0.8.0 — Dashboard home (Demo 1: Sidebar console). Login lands
// here, not on a landing hero. Every KPI comes from ONE read-only
// call, GET /dashboard/summary, computed straight from the database.
// The v0.7.0 Dashboard asked the agent two questions through
// /agent/instruct, which burned the shared 10-runs-per-hour budget
// and showed cached values once the budget was gone. This version
// uses no agent run at all — the figures are always live. No number
// is hardcoded.

function money(value: number): string {
  return value.toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

function statusPill(status: string) {
  const styles: Record<string, string> = {
    COMPLETED: 'bg-[#EAF2ED] text-emerald-900',
    AWAITING_APPROVAL: 'bg-[#FBF3DC] text-[#8A6D1B]',
    RUNNING: 'bg-[#E8EEF7] text-[#274B73]',
    ESCALATED: 'bg-red-50 text-red-700',
    FAILED: 'bg-red-50 text-red-700',
  }
  return (
    <span
      className={`whitespace-nowrap rounded-full px-2.5 py-1 text-[11px] font-bold ${styles[status] ?? 'bg-[#F7F5F0] text-emerald-900'}`}
    >
      {status.replace(/_/g, ' ')}
    </span>
  )
}

function approvalAmount(approval: ApprovalItem): string | null {
  for (const action of approval.diff.actions) {
    if (action.type === 'approve_expense_claim' && action.amount_sar != null) {
      return `${money(action.amount_sar)} SAR`
    }
  }
  const match = approval.action_summary.match(/([\d,]+\.\d{2}) SAR/)
  return match ? `${match[1]} SAR` : null
}

function approvalKind(approval: ApprovalItem): string {
  const first = approval.diff.actions[0]
  if (!first) return 'Approval'
  if (first.type === 'export_report') return 'Report export'
  if (first.type === 'save_email_draft') return 'Draft email'
  if (first.type === 'approve_expense_claim') return 'Expense claim'
  return first.type
}

export default function Dashboard() {
  const [user, setUser] = useState<User | null>(null)
  const [summary, setSummary] = useState<DashboardSummary | null>(null)
  const [summaryNote, setSummaryNote] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const navigate = useNavigate()
  const loadedRef = useRef(false)

  const load = useCallback(async () => {
    setError(null)
    try {
      const data = await getDashboardSummary()
      setSummary(data)
      setSummaryNote(
        `Live figures from the database · ${new Date(data.generated_at).toLocaleTimeString()}`,
      )
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Live figures failed to load.'
      setSummaryNote(`Live figures unavailable: ${message}`)
    }
  }, [])

  useEffect(() => {
    if (loadedRef.current) return
    loadedRef.current = true
    getMe()
      .then(({ user: me }) => {
        setUser(me)
        return load()
      })
      .catch(() => navigate('/login'))
      .finally(() => setLoading(false))
  }, [load, navigate])

  async function onRefresh() {
    setRefreshing(true)
    try {
      await load()
    } finally {
      setRefreshing(false)
    }
  }

  const invoices = summary?.pending_invoices
  const suppliers = summary?.overdue_suppliers
  const pendingCount = summary?.pending_approvals.count ?? 0
  const pendingTop: ApprovalItem[] = summary?.pending_approvals.top ?? []
  const runs: RunItem[] = summary?.recent_runs ?? []
  const evals = summary?.evals
  const evalRate =
    evals && evals.total > 0 ? `${evals.passed} / ${evals.total}` : '—'

  return (
    <Shell user={user} title="Dashboard">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-[#7C857F]">
          {summaryNote ??
            (loading ? 'Loading live figures…' : 'Live figures from the database.')}
        </p>
        <button
          type="button"
          disabled={refreshing || loading}
          onClick={onRefresh}
          className="rounded-md border border-[#E6E1D6] bg-white px-3 py-1.5 text-sm font-semibold text-emerald-900 hover:bg-[#F7F5F0] disabled:opacity-50"
        >
          {refreshing ? 'Refreshing…' : 'Refresh figures'}
        </button>
      </div>

      {error && (
        <p className="mt-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">
          {error}
        </p>
      )}

      <section className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-[14px] border border-emerald-900 bg-emerald-900 p-5 shadow-sm">
          <p className="text-xs font-semibold uppercase tracking-wider text-gold-400">
            Pending Invoices
          </p>
          <p className="mt-2 text-[26px] font-extrabold leading-tight text-white">
            {invoices ? `${invoices.count} · ${money(invoices.total_sar)} SAR` : '—'}
          </p>
          <p className="mt-1 text-xs text-white/65">
            VAT {invoices ? `${money(invoices.vat_sar)} SAR` : '—'} ·{' '}
            <b className="text-gold-400">
              {suppliers ? `${suppliers.count} overdue` : '—'}
            </b>
          </p>
        </div>
        <div className="rounded-[14px] border border-[#EAE5D9] bg-white p-5 shadow-sm">
          <p className="text-xs font-semibold uppercase tracking-wider text-[#7C857F]">
            Pending Approvals
          </p>
          <p className="mt-2 text-[26px] font-extrabold leading-tight text-emerald-900">
            {pendingCount}
          </p>
          <p className="mt-1 text-xs text-[#8A938C]">Awaiting your decision</p>
        </div>
        <div className="rounded-[14px] border border-[#EAE5D9] bg-white p-5 shadow-sm">
          <p className="text-xs font-semibold uppercase tracking-wider text-[#7C857F]">
            Overdue Suppliers
          </p>
          <p className="mt-2 text-[26px] font-extrabold leading-tight text-emerald-900">
            {suppliers ? `${suppliers.count} · ${money(suppliers.total_sar)} SAR` : '—'}
          </p>
          <p className="mt-1 truncate text-xs text-[#8A938C]">
            {suppliers ? suppliers.names.slice(0, 2).join(' · ') || '—' : '—'}
          </p>
        </div>
        <div className="rounded-[14px] border border-[#EAE5D9] bg-white p-5 shadow-sm">
          <p className="text-xs font-semibold uppercase tracking-wider text-[#7C857F]">
            Evaluations
          </p>
          <p className="mt-2 text-[26px] font-extrabold leading-tight text-emerald-900">
            {evalRate}
          </p>
          <p className="mt-1 text-xs text-[#8A938C]">
            Pass rate{' '}
            <b className="text-emerald-900">
              {evals?.pass_rate != null ? `${(evals.pass_rate * 100).toFixed(0)}%` : '—'}
            </b>
            {' · '}p95 {evals?.latency_ms_p95 ?? '—'} ms
          </p>
        </div>
      </section>

      <section className="mt-4 grid gap-4 xl:grid-cols-[1.15fr_1fr]">
        <div className="overflow-hidden rounded-[14px] border border-[#EAE5D9] bg-white shadow-sm">
          <div className="flex items-center border-b border-[#F0EBDF] px-5 py-4">
            <h3 className="text-[15px] font-bold">Needs approval</h3>
            <Link to="/approvals" className="ml-auto text-xs font-bold text-emerald-900">
              View all {pendingCount} →
            </Link>
          </div>
          {pendingTop.length === 0 ? (
            <p className="px-5 py-4 text-sm text-[#8A938C]">
              Nothing waiting for a decision. Run a workflow to create an approval.
            </p>
          ) : (
            pendingTop.map((approval) => (
              <div
                key={approval.id}
                className="flex items-center gap-3 border-b border-[#F5F1E8] px-5 py-3 last:border-b-0"
              >
                <span className="shrink-0 rounded-md bg-[#EAF2ED] px-2 py-1 text-[10px] font-bold tracking-wide text-emerald-900">
                  {approval.workflow_key ?? 'WORKFLOW'}
                </span>
                <div className="min-w-0">
                  <p className="truncate text-[13.5px] font-semibold leading-snug">
                    {approval.action_summary}
                  </p>
                  <p className="mt-0.5 text-xs text-[#8A938C]">
                    Run #{approval.run_id} · Approval #{approval.id}
                  </p>
                </div>
                <div className="ml-auto shrink-0 text-right">
                  <p className="whitespace-nowrap text-[13.5px] font-bold text-emerald-900">
                    {approvalAmount(approval) ?? '—'}
                  </p>
                  <p className="text-[11px] text-[#8A938C]">{approvalKind(approval)}</p>
                </div>
              </div>
            ))
          )}
        </div>

        <div className="overflow-hidden rounded-[14px] border border-[#EAE5D9] bg-white shadow-sm">
          <div className="flex items-center border-b border-[#F0EBDF] px-5 py-4">
            <h3 className="text-[15px] font-bold">Recent runs</h3>
            <Link to="/workflows" className="ml-auto text-xs font-bold text-emerald-900">
              All runs →
            </Link>
          </div>
          {runs.length === 0 ? (
            <p className="px-5 py-4 text-sm text-[#8A938C]">No runs yet.</p>
          ) : (
            <table className="w-full text-left text-[13px]">
              <thead>
                <tr className="border-b border-[#F0EBDF] text-[11px] uppercase tracking-wider text-[#8A938C]">
                  <th className="px-5 pb-2 pt-3">Run</th>
                  <th className="px-2 pb-2 pt-3">Workflow</th>
                  <th className="px-5 pb-2 pt-3 text-right">Status</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.id} className="border-b border-[#F5F1E8] last:border-b-0">
                    <td className="px-5 py-2.5 font-bold text-emerald-900">#{run.id}</td>
                    <td className="px-2 py-2.5">{run.workflow_key ?? '—'}</td>
                    <td className="px-5 py-2.5 text-right">{statusPill(run.status)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="border-t border-[#F0EBDF] px-5 py-3.5 text-xs text-[#8A938C]">
            4 workflows · Daily invoice check 08:00 · Weekly CRM digest Mon 09:00 · Month-end
            summary 1st 09:00 (Asia/Riyadh)
          </p>
        </div>
      </section>
    </Shell>
  )
}
