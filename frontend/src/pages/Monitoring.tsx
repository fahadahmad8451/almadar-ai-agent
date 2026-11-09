import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  getMetricsTimeseries,
  getMonitoringOverview,
  listAlerts,
  listDailyReports,
  resolveAlert,
  type AlertItem,
  type DailyReportItem,
  type MonitoringOverview,
  type TimeseriesBucket,
  type User,
} from '../api/client'
import { getMe } from '../api/client'
import Shell from '../components/Shell'

// v0.9.0 — Monitoring page (Admin only). Every number comes from the
// real database via /admin/monitoring/overview: system health, request
// counts + latency p50/p95, runs + approvals, active alerts (with a
// resolve button), eval status and the newest daily report. Charts
// are plain CSS bars over the per-hour timeseries — no chart library.

function fmtMs(value: number | null): string {
  return value === null ? '—' : `${value} ms`
}

function fmtPct(value: number | null): string {
  return value === null ? '—' : `${(value * 100).toFixed(1)}%`
}

export default function Monitoring() {
  const [user, setUser] = useState<User | null>(null)
  const [overview, setOverview] = useState<MonitoringOverview | null>(null)
  const [buckets, setBuckets] = useState<TimeseriesBucket[]>([])
  const [alerts, setAlerts] = useState<AlertItem[]>([])
  const [reports, setReports] = useState<DailyReportItem[]>([])
  const [latestReport, setLatestReport] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [resolving, setResolving] = useState<number | null>(null)
  const navigate = useNavigate()

  const load = useCallback(async () => {
    const [ov, ts, al, dr] = await Promise.all([
      getMonitoringOverview(),
      getMetricsTimeseries(24),
      listAlerts(),
      listDailyReports(),
    ])
    setOverview(ov)
    setBuckets(ts.buckets)
    setAlerts(al.alerts)
    setReports(dr.reports)
    setLatestReport(dr.latest_markdown)
  }, [])

  useEffect(() => {
    getMe()
      .then(({ user: me }) => {
        setUser(me)
        if (me.role !== 'ADMIN') {
          navigate('/dashboard')
          return
        }
        return load().catch((e: Error) => setError(e.message))
      })
      .catch(() => navigate('/login'))
  }, [load, navigate])

  async function onResolve(id: number) {
    setResolving(id)
    setNotice(null)
    try {
      await resolveAlert(id)
      setNotice(`Alert #${id} resolved.`)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Resolve failed.')
    } finally {
      setResolving(null)
    }
  }

  const maxBucket = Math.max(1, ...buckets.map((b) => b.requests))
  const summary = overview?.summary
  const runEntries = summary ? Object.entries(summary.runs_by_status) : []

  return (
    <Shell user={user} title="Monitoring">
      {error && (
        <p className="mb-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="mb-4 rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-800" role="status">
          {notice}
        </p>
      )}
      {!overview || !summary ? (
        <p className="text-sm text-[#8A938C]">Loading monitoring data…</p>
      ) : (
        <div className="space-y-6">
          <section aria-label="System health">
            <h3 className="mb-2 text-sm font-bold uppercase tracking-wide text-[#8A938C]">
              System health
            </h3>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <div className="rounded-xl border border-[#E6E1D6] bg-white p-4">
                <p className="text-xs text-[#8A938C]">API</p>
                <p className="mt-1 text-lg font-bold text-emerald-900">
                  {overview.database === 'connected' ? '● Healthy' : '● Unhealthy'}
                </p>
                <p className="text-xs text-[#8A938C]">
                  v{overview.version} · {overview.environment}
                </p>
              </div>
              <div className="rounded-xl border border-[#E6E1D6] bg-white p-4">
                <p className="text-xs text-[#8A938C]">Database</p>
                <p className="mt-1 text-lg font-bold text-emerald-900">{overview.database}</p>
                <p className="text-xs text-[#8A938C]">
                  Uptime {Math.round(overview.uptime_seconds / 60)} min
                </p>
              </div>
              <div className="rounded-xl border border-[#E6E1D6] bg-white p-4">
                <p className="text-xs text-[#8A938C]">Scheduler</p>
                <p className="mt-1 text-lg font-bold text-emerald-900">
                  {overview.scheduler_running ? 'Running' : 'Stopped'}
                </p>
                <p className="text-xs text-[#8A938C]">
                  Alert checks {overview.monitoring_alerts_enabled ? 'ON (5 min)' : 'OFF'}
                </p>
              </div>
              <div className="rounded-xl border border-[#E6E1D6] bg-white p-4">
                <p className="text-xs text-[#8A938C]">Disk used</p>
                <p className="mt-1 text-lg font-bold text-emerald-900">
                  {overview.disk.used_percent === null ? '—' : `${overview.disk.used_percent}%`}
                </p>
                <p className="text-xs text-[#8A938C]">
                  Data dir {(overview.disk.data_dir_bytes / 1024 / 1024).toFixed(1)} MB
                </p>
              </div>
            </div>
          </section>

          <section aria-label="Requests and latency">
            <h3 className="mb-2 text-sm font-bold uppercase tracking-wide text-[#8A938C]">
              Requests &amp; latency (last 24 h)
            </h3>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <div className="rounded-xl border border-[#E6E1D6] bg-white p-4">
                <p className="text-xs text-[#8A938C]">Requests (24 h)</p>
                <p className="mt-1 text-2xl font-bold text-emerald-900">{summary.requests_24h}</p>
                <p className="text-xs text-[#8A938C]">{summary.requests_total} total</p>
              </div>
              <div className="rounded-xl border border-[#E6E1D6] bg-white p-4">
                <p className="text-xs text-[#8A938C]">Latency p50 / p95</p>
                <p className="mt-1 text-2xl font-bold text-emerald-900">
                  {fmtMs(summary.latency_ms.p50)} / {fmtMs(summary.latency_ms.p95)}
                </p>
                <p className="text-xs text-[#8A938C]">{summary.latency_ms.samples} samples</p>
              </div>
              <div className="rounded-xl border border-[#E6E1D6] bg-white p-4">
                <p className="text-xs text-[#8A938C]">Instruct p95</p>
                <p className="mt-1 text-2xl font-bold text-emerald-900">
                  {fmtMs(summary.instruct_latency_ms.p95)}
                </p>
                <p className="text-xs text-[#8A938C]">
                  {summary.instruct_latency_ms.samples} instructs · alert over 500 ms
                </p>
              </div>
              <div className="rounded-xl border border-[#E6E1D6] bg-white p-4">
                <p className="text-xs text-[#8A938C]">5xx errors (24 h)</p>
                <p className="mt-1 text-2xl font-bold text-emerald-900">{summary.errors_5xx_24h}</p>
                <p className="text-xs text-[#8A938C]">
                  Rate {(summary.error_rate_5xx_24h * 100).toFixed(2)}% · alert over 5%
                </p>
              </div>
            </div>
            <div className="mt-3 rounded-xl border border-[#E6E1D6] bg-white p-4">
              <p className="mb-3 text-xs font-semibold text-[#8A938C]">
                Requests per hour (last 24 h)
              </p>
              <div className="flex h-28 items-end gap-1">
                {buckets.map((b) => (
                  <div
                    key={b.hour}
                    className="flex-1 rounded-t bg-emerald-700"
                    style={{ height: `${Math.max(2, Math.round((b.requests / maxBucket) * 100))}%` }}
                    title={`${b.hour}: ${b.requests} requests, ${b.errors_5xx} errors, p95 ${fmtMs(b.p95_ms)}`}
                  />
                ))}
              </div>
              <p className="mt-2 text-xs text-[#8A938C]">
                {buckets[0]?.hour} → {buckets[buckets.length - 1]?.hour} (UTC)
              </p>
            </div>
          </section>

          <section aria-label="Runs and approvals">
            <h3 className="mb-2 text-sm font-bold uppercase tracking-wide text-[#8A938C]">
              Runs &amp; approvals
            </h3>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <div className="rounded-xl border border-[#E6E1D6] bg-white p-4">
                <p className="text-xs text-[#8A938C]">Workflow runs (24 h)</p>
                <p className="mt-1 text-2xl font-bold text-emerald-900">{summary.runs_24h}</p>
                <p className="text-xs text-[#8A938C]">{summary.runs_total} total</p>
              </div>
              <div className="rounded-xl border border-[#E6E1D6] bg-white p-4">
                <p className="text-xs text-[#8A938C]">Escalations</p>
                <p className="mt-1 text-2xl font-bold text-emerald-900">{summary.escalations_total}</p>
                <p className="text-xs text-[#8A938C]">
                  Avg confidence {summary.confidence_avg ?? '—'}
                </p>
              </div>
              <div className="rounded-xl border border-[#E6E1D6] bg-white p-4">
                <p className="text-xs text-[#8A938C]">Approvals</p>
                <p className="mt-1 text-2xl font-bold text-emerald-900">
                  {summary.approvals.pending} pending
                </p>
                <p className="text-xs text-[#8A938C]">
                  {summary.approvals.approved} approved · {summary.approvals.rejected} rejected
                </p>
              </div>
              <div className="rounded-xl border border-[#E6E1D6] bg-white p-4">
                <p className="text-xs text-[#8A938C]">Latest evals</p>
                <p className="mt-1 text-2xl font-bold text-emerald-900">
                  {fmtPct(summary.evals_latest.pass_rate)}
                </p>
                <p className="text-xs text-[#8A938C]">
                  {summary.evals_latest.passed}/{summary.evals_latest.total} passed
                  {summary.evals_latest.failed > 0 ? ` · ${summary.evals_latest.failed} failed` : ''}
                </p>
              </div>
            </div>
            {runEntries.length > 0 && (
              <div className="mt-3 rounded-xl border border-[#E6E1D6] bg-white p-4">
                <p className="mb-3 text-xs font-semibold text-[#8A938C]">Runs by status</p>
                <div className="space-y-2">
                  {runEntries.map(([status, count]) => (
                    <div key={status} className="flex items-center gap-3 text-sm">
                      <span className="w-40 shrink-0 font-medium">{status}</span>
                      <div
                        className="h-4 rounded bg-gold-500"
                        style={{
                          width: `${Math.max(2, Math.round((count / Math.max(1, summary.runs_total)) * 100))}%`,
                        }}
                      />
                      <span className="text-[#8A938C]">{count}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </section>

          <section aria-label="Alerts">
            <h3 className="mb-2 text-sm font-bold uppercase tracking-wide text-[#8A938C]">
              Alerts ({overview.active_alert_count} active)
            </h3>
            <div className="overflow-hidden rounded-xl border border-[#E6E1D6] bg-white">
              {alerts.length === 0 ? (
                <p className="p-4 text-sm text-[#8A938C]">No alerts recorded.</p>
              ) : (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-[#E6E1D6] text-left text-xs uppercase text-[#8A938C]">
                      <th className="px-4 py-2">Rule</th>
                      <th className="px-4 py-2">Severity</th>
                      <th className="px-4 py-2">Message</th>
                      <th className="px-4 py-2">Status</th>
                      <th className="px-4 py-2">Created</th>
                      <th className="px-4 py-2" />
                    </tr>
                  </thead>
                  <tbody>
                    {alerts.slice(0, 20).map((a) => (
                      <tr key={a.id} className="border-b border-[#F0EDE4] last:border-0">
                        <td className="px-4 py-2 font-medium">{a.rule}</td>
                        <td className="px-4 py-2">{a.severity}</td>
                        <td className="px-4 py-2">{a.message}</td>
                        <td className="px-4 py-2">{a.status}</td>
                        <td className="px-4 py-2 text-[#8A938C]">
                          {a.created_at ? a.created_at.slice(0, 16).replace('T', ' ') : '—'}
                        </td>
                        <td className="px-4 py-2 text-right">
                          {a.status === 'ACTIVE' && (
                            <button
                              type="button"
                              disabled={resolving === a.id}
                              onClick={() => onResolve(a.id)}
                              className="rounded-lg bg-emerald-900 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50"
                            >
                              {resolving === a.id ? 'Resolving…' : 'Resolve'}
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
            {overview.recent_errors.length > 0 && (
              <div className="mt-3 rounded-xl border border-[#E6E1D6] bg-white p-4">
                <p className="mb-2 text-xs font-semibold text-[#8A938C]">Newest 5xx errors</p>
                <ul className="space-y-1 text-sm">
                  {overview.recent_errors.map((e, i) => (
                    <li key={i}>
                      {e.method} {e.endpoint} — {e.status} ({e.latency_ms} ms)
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </section>

          <section aria-label="Daily report">
            <h3 className="mb-2 text-sm font-bold uppercase tracking-wide text-[#8A938C]">
              Daily report {reports.length > 0 ? `(${reports[0].date})` : ''}
            </h3>
            <div className="rounded-xl border border-[#E6E1D6] bg-white p-4">
              {latestReport ? (
                <pre className="whitespace-pre-wrap text-sm text-emerald-900">{latestReport}</pre>
              ) : (
                <p className="text-sm text-[#8A938C]">
                  No daily report yet — run scripts/daily_report.py (daily 08:00 on the
                  production machine).
                </p>
              )}
              {reports.length > 1 && (
                <p className="mt-3 text-xs text-[#8A938C]">
                  Older reports: {reports.slice(1).map((r) => r.name).join(', ')}
                </p>
              )}
            </div>
          </section>
        </div>
      )}
    </Shell>
  )
}
