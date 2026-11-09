import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  approveApproval,
  getMe,
  listApprovals,
  rejectApproval,
  type ApprovalAction,
  type ApprovalItem,
  type User,
} from '../api/client'
import Shell from '../components/Shell'

// Sprint 2: the live approval queue. Every entry shows exactly what
// will execute (the diff) before a manager decides. Approving runs
// the actions through the tool layer with the approval token;
// rejecting runs nothing. Only Operations Manager / Admin see the
// Approve / Reject buttons.

function actionText(action: ApprovalAction): string {
  if (action.type === 'export_report') {
    return `Export the report as ${(action.format ?? 'pdf').toUpperCase()}`
  }
  if (action.type === 'save_email_draft' && action.draft) {
    return `Save email draft to ${action.draft.to_email} — “${action.draft.subject}”`
  }
  if (action.type === 'approve_expense_claim') {
    return `Approve expense claim #${action.claim_id} — ${action.employee_name ?? ''}, ${action.amount_sar ?? ''} SAR (${action.category ?? ''})`
  }
  return action.type
}

function statusBadge(status: string) {
  const styles: Record<string, string> = {
    PENDING: 'bg-amber-100 text-amber-800',
    APPROVED: 'bg-teal-100 text-teal-800',
    REJECTED: 'bg-red-100 text-red-800',
  }
  return (
    <span
      className={`rounded-full px-3 py-1 text-sm font-semibold ${styles[status] ?? 'bg-emerald-50 text-emerald-700'}`}
    >
      {status}
    </span>
  )
}

export default function Approvals() {
  const [user, setUser] = useState<User | null>(null)
  const [approvals, setApprovals] = useState<ApprovalItem[]>([])
  const [pendingCount, setPendingCount] = useState(0)
  const [filter, setFilter] = useState<'ALL' | 'PENDING' | 'APPROVED' | 'REJECTED'>('PENDING')
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [rejectId, setRejectId] = useState<number | null>(null)
  const [comment, setComment] = useState('')
  const navigate = useNavigate()

  const load = useCallback(async () => {
    const { approvals: list, pending_count } = await listApprovals()
    setApprovals(list)
    setPendingCount(pending_count)
  }, [])

  useEffect(() => {
    getMe()
      .then(({ user: me }) => {
        setUser(me)
        return load()
      })
      .catch(() => navigate('/login'))
  }, [load, navigate])

  const canDecide =
    user?.role === 'OPERATIONS_MANAGER' || user?.role === 'ADMIN'

  async function onApprove(id: number) {
    setError(null)
    setBusyId(id)
    try {
      const result = await approveApproval(id)
      await load()
      alert(`Approved — ${result.executed.length} action(s) executed. Run is ${result.run_status}.`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Approval failed.')
    } finally {
      setBusyId(null)
    }
  }

  async function onReject(id: number) {
    setError(null)
    setBusyId(id)
    try {
      await rejectApproval(id, comment || undefined)
      setRejectId(null)
      setComment('')
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Rejection failed.')
    } finally {
      setBusyId(null)
    }
  }

  const shown =
    filter === 'ALL'
      ? approvals
      : approvals.filter((a) => a.status === filter)

  return (
    <Shell user={user} title="Approvals">
        <p className="mt-1 text-emerald-600">
          Nothing executes without a human approval. {pendingCount} request(s)
          waiting for a decision.
        </p>

        <div className="mt-6 flex flex-wrap gap-2">
          {(['ALL', 'PENDING', 'APPROVED', 'REJECTED'] as const).map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => setFilter(f)}
              className={
                filter === f
                  ? 'rounded-md bg-emerald-900 px-3 py-1 text-sm font-semibold text-white'
                  : 'rounded-md border border-emerald-200 bg-white px-3 py-1 text-sm font-semibold text-emerald-900 hover:bg-emerald-50'
              }
            >
              {f === 'ALL' ? `All (${approvals.length})` : f}
            </button>
          ))}
        </div>

        {error && (
          <p className="mt-6 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">
            {error}
          </p>
        )}

        {shown.length === 0 && (
          <p className="mt-6 rounded-[14px] border border-[#EAE5D9] bg-white p-6 text-emerald-600 shadow-sm">
            No approvals in this view yet. Run a workflow to create one.
          </p>
        )}

        <div className="mt-6 space-y-4">
          {shown.map((approval) => (
            <section
              key={approval.id}
              className="rounded-[14px] border border-[#EAE5D9] bg-white p-6 shadow-sm"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="text-lg font-bold text-emerald-900">
                  {approval.action_summary}
                </h2>
                {statusBadge(approval.status)}
              </div>
              <p className="mt-1 text-sm text-emerald-600">
                {approval.workflow_key ?? 'Workflow'} · Run #{approval.run_id} ·
                Approval #{approval.id}
                {approval.decided_at &&
                  ` · decided ${new Date(approval.decided_at).toLocaleString()}`}
                {approval.comment && ` · “${approval.comment}”`}
              </p>
              <div className="mt-4">
                <p className="text-sm font-semibold text-emerald-900">
                  What will happen on approval:
                </p>
                <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-emerald-900">
                  {approval.diff.actions.map((action, i) => (
                    <li key={i}>{actionText(action)}</li>
                  ))}
                </ul>
                {approval.diff.actions.some(
                  (a) => a.type === 'save_email_draft' && a.draft,
                ) && (
                  <div className="mt-3 rounded-md bg-[#F7F5F0] p-3 text-sm text-emerald-900">
                    {approval.diff.actions
                      .filter((a) => a.type === 'save_email_draft' && a.draft)
                      .map((a, i) => (
                        <p key={i} className="whitespace-pre-wrap">
                          {a.draft?.body}
                        </p>
                      ))}
                  </div>
                )}
              </div>
              {approval.status === 'PENDING' && canDecide && (
                <div className="mt-4 flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    disabled={busyId === approval.id}
                    onClick={() => onApprove(approval.id)}
                    className="hero-gold-btn rounded-md px-4 py-2 font-semibold disabled:opacity-50"
                  >
                    {busyId === approval.id ? 'Working…' : 'Approve'}
                  </button>
                  <button
                    type="button"
                    disabled={busyId === approval.id}
                    onClick={() =>
                      setRejectId(rejectId === approval.id ? null : approval.id)
                    }
                    className="rounded-md border border-red-200 px-4 py-2 font-semibold text-red-700 hover:bg-red-50 disabled:opacity-50"
                  >
                    Reject
                  </button>
                </div>
              )}
              {approval.status === 'PENDING' && !canDecide && (
                <p className="mt-4 text-sm text-emerald-600">
                  Waiting for a Operations Manager or Admin to decide.
                </p>
              )}
              {rejectId === approval.id && canDecide && (
                <div className="mt-4 space-y-2">
                  <textarea
                    value={comment}
                    onChange={(e) => setComment(e.target.value)}
                    rows={2}
                    placeholder="Reason for rejection (optional)"
                    className="w-full rounded-md border border-emerald-200 bg-white px-3 py-2"
                  />
                  <button
                    type="button"
                    disabled={busyId === approval.id}
                    onClick={() => onReject(approval.id)}
                    className="rounded-md bg-red-600 px-4 py-2 font-semibold text-white disabled:opacity-50"
                  >
                    {busyId === approval.id ? 'Working…' : 'Confirm rejection'}
                  </button>
                </div>
              )}
            </section>
          ))}
        </div>
    </Shell>
  )
}
