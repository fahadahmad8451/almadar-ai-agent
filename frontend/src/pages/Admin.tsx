import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  changeUserRole,
  getMe,
  getObservability,
  listAdminUsers,
  listAuditLogs,
  resetUserPassword,
  type AdminUserItem,
  type AuditLogItem,
  type ObservabilityData,
  type User,
} from '../api/client'
import Shell from '../components/Shell'

// Sprint 3: Admin page (Admin role only). Users + role changes,
// password resets (the new password is shown once — there is no
// email server, so it is shared out-of-band), observability, and
// the filterable audit log. Every admin action is audited.

const ROLES = ['ADMIN', 'OPERATIONS_MANAGER', 'OPERATIONS_OFFICER'] as const

export default function Admin() {
  const [user, setUser] = useState<User | null>(null)
  const [users, setUsers] = useState<AdminUserItem[]>([])
  const [roles, setRoles] = useState<Record<string, string>>({})
  const [resetResult, setResetResult] = useState<Record<string, string>>({})
  const [observability, setObservability] = useState<ObservabilityData | null>(null)
  const [auditLogs, setAuditLogs] = useState<AuditLogItem[]>([])
  const [actionFilter, setActionFilter] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const navigate = useNavigate()

  const load = useCallback(async () => {
    const [{ users: list }, obs, { audit_logs }] = await Promise.all([
      listAdminUsers(),
      getObservability(),
      listAuditLogs({ limit: 50 }),
    ])
    setUsers(list)
    setObservability(obs)
    setAuditLogs(audit_logs)
  }, [])

  useEffect(() => {
    getMe()
      .then(({ user: me }) => {
        setUser(me)
        if (me.role !== 'ADMIN') {
          navigate('/dashboard')
          return
        }
        return load()
      })
      .catch(() => navigate('/login'))
  }, [load, navigate])

  async function onRoleChange(email: string) {
    const role = roles[email]
    if (!role) return
    setError(null)
    setNotice(null)
    try {
      await changeUserRole(email, role)
      setNotice(`Role for ${email} changed to ${role}.`)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Role change failed.')
    }
  }

  async function onResetPassword(email: string) {
    setError(null)
    setNotice(null)
    try {
      const { new_password } = await resetUserPassword(email)
      setResetResult((prev) => ({ ...prev, [email]: new_password }))
      setNotice(`Password reset for ${email}. Share the new password out-of-band.`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Password reset failed.')
    }
  }

  async function onFilterAudit() {
    setError(null)
    try {
      const { audit_logs } = await listAuditLogs({
        action: actionFilter.trim() || undefined,
        limit: 50,
      })
      setAuditLogs(audit_logs)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Audit log load failed.')
    }
  }

  return (
    <Shell user={user} title="Admin">
        <p className="mt-1 text-emerald-600">
          Users, roles, password resets, observability, and the audit
          log. Every action here is recorded in the audit log.
        </p>

        {error && (
          <p className="mt-6 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">
            {error}
          </p>
        )}
        {notice && (
          <p className="mt-6 rounded-md bg-teal-50 px-3 py-2 text-sm text-teal-800" role="status">
            {notice}
          </p>
        )}

        {observability && (
          <section className="mt-6 grid gap-4 sm:grid-cols-4">
            <div className="rounded-[14px] border border-[#EAE5D9] bg-white p-4 shadow-sm">
              <p className="text-sm text-emerald-600">Runs</p>
              <p className="text-2xl font-bold text-emerald-900">{observability.runs_total}</p>
            </div>
            <div className="rounded-[14px] border border-[#EAE5D9] bg-white p-4 shadow-sm">
              <p className="text-sm text-emerald-600">Success rate</p>
              <p className="text-2xl font-bold text-emerald-900">
                {observability.success_rate !== null
                  ? `${(observability.success_rate * 100).toFixed(1)}%`
                  : '—'}
              </p>
            </div>
            <div className="rounded-[14px] border border-[#EAE5D9] bg-white p-4 shadow-sm">
              <p className="text-sm text-emerald-600">Latency p50 / p95</p>
              <p className="text-2xl font-bold text-emerald-900">
                {observability.latency_ms.p50 ?? '—'} / {observability.latency_ms.p95 ?? '—'} ms
              </p>
            </div>
            <div className="rounded-[14px] border border-[#EAE5D9] bg-white p-4 shadow-sm">
              <p className="text-sm text-emerald-600">Pending approvals</p>
              <p className="text-2xl font-bold text-emerald-900">{observability.pending_approvals}</p>
            </div>
          </section>
        )}

        <section className="mt-8 rounded-[14px] border border-[#EAE5D9] bg-white p-6 shadow-sm">
          <h2 className="text-lg font-bold text-emerald-900">Users</h2>
          <table className="mt-4 w-full text-left text-sm">
            <thead>
              <tr className="border-b border-emerald-100 text-emerald-600">
                <th className="py-2 pr-2">Name</th>
                <th className="py-2 pr-2">Email</th>
                <th className="py-2 pr-2">Role</th>
                <th className="py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-b border-emerald-50">
                  <td className="py-2 pr-2 text-emerald-900">{u.name}</td>
                  <td className="py-2 pr-2 text-emerald-900">{u.email}</td>
                  <td className="py-2 pr-2">
                    <select
                      value={roles[u.email] ?? u.role}
                      onChange={(e) =>
                        setRoles((prev) => ({ ...prev, [u.email]: e.target.value }))
                      }
                      disabled={u.email === user?.email}
                      className="rounded-md border border-emerald-200 bg-white px-2 py-1"
                    >
                      {ROLES.map((role) => (
                        <option key={role} value={role}>
                          {role.replace(/_/g, ' ')}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="py-2">
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        disabled={
                          u.email === user?.email ||
                          (roles[u.email] ?? u.role) === u.role
                        }
                        onClick={() => onRoleChange(u.email)}
                        className="rounded-md border border-emerald-200 px-3 py-1 font-semibold text-emerald-900 hover:bg-emerald-50 disabled:opacity-50"
                      >
                        Save role
                      </button>
                      <button
                        type="button"
                        onClick={() => onResetPassword(u.email)}
                        className="rounded-md border border-emerald-200 px-3 py-1 font-semibold text-emerald-900 hover:bg-emerald-50"
                      >
                        Reset password
                      </button>
                    </div>
                    {resetResult[u.email] && (
                      <p className="mt-1 text-emerald-600">
                        New password: <strong>{resetResult[u.email]}</strong>
                      </p>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="mt-8 rounded-[14px] border border-[#EAE5D9] bg-white p-6 shadow-sm">
          <h2 className="text-lg font-bold text-emerald-900">Audit log</h2>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <input
              type="text"
              value={actionFilter}
              onChange={(e) => setActionFilter(e.target.value)}
              placeholder="Filter by action, e.g. APPROVE"
              className="rounded-md border border-emerald-200 px-3 py-2 text-sm"
            />
            <button
              type="button"
              onClick={onFilterAudit}
              className="rounded-md border border-emerald-200 px-3 py-2 text-sm font-semibold text-emerald-900 hover:bg-emerald-50"
            >
              Filter
            </button>
          </div>
          {auditLogs.length === 0 ? (
            <p className="mt-4 text-emerald-600">No audit entries found.</p>
          ) : (
            <ul className="mt-4 space-y-2">
              {auditLogs.slice(0, 20).map((log) => (
                <li
                  key={log.id}
                  className="flex flex-wrap items-center justify-between gap-2 border-b border-emerald-50 pb-2 text-sm"
                >
                  <span className="text-emerald-900">
                    <strong>{log.action}</strong> — {log.resource ?? '—'}
                  </span>
                  <span className="text-emerald-600">
                    {log.result}
                    {log.created_at &&
                      ` · ${new Date(log.created_at).toLocaleString()}`}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
    </Shell>
  )
}
