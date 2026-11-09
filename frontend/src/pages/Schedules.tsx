import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  getMe,
  listScheduleRuns,
  listSchedules,
  runScheduleNow,
  type ScheduleItem,
  type ScheduleRunItem,
  type User,
  type WorkflowRunResult,
} from '../api/client'
import Shell from '../components/Shell'

// Sprint 3: the three locked scheduled jobs (daily invoice check
// 08:00, weekly CRM digest Monday 09:00, month-end supplier summary
// 1st 09:00, Asia/Riyadh). APScheduler runs them in-process; a
// scheduled run is a normal workflow run that stops at
// AWAITING_APPROVAL. "Run now" triggers the same pipeline manually.

const CRON_LABELS: Record<string, string> = {
  '0 8 * * *': 'Daily 08:00',
  '0 9 * * 1': 'Monday 09:00',
  '0 9 1 * *': '1st of month 09:00',
}

export default function Schedules() {
  const [user, setUser] = useState<User | null>(null)
  const [schedules, setSchedules] = useState<ScheduleItem[]>([])
  const [histories, setHistories] = useState<Record<number, ScheduleRunItem[]>>({})
  const [runningId, setRunningId] = useState<number | null>(null)
  const [lastResult, setLastResult] = useState<Record<number, WorkflowRunResult>>({})
  const [error, setError] = useState<string | null>(null)
  const navigate = useNavigate()

  const load = useCallback(async () => {
    const { schedules: list } = await listSchedules()
    setSchedules(list)
    const all: Record<number, ScheduleRunItem[]> = {}
    for (const item of list) {
      const { runs } = await listScheduleRuns(item.id)
      all[item.id] = runs
    }
    setHistories(all)
  }, [])

  useEffect(() => {
    getMe()
      .then(({ user: me }) => {
        setUser(me)
        return load()
      })
      .catch(() => navigate('/login'))
  }, [load, navigate])

  const canManage =
    user?.role === 'ADMIN' || user?.role === 'OPERATIONS_MANAGER'

  async function onRunNow(id: number) {
    setError(null)
    setRunningId(id)
    try {
      const result = await runScheduleNow(id)
      setLastResult((prev) => ({ ...prev, [id]: result }))
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Run failed.')
    } finally {
      setRunningId(null)
    }
  }

  return (
    <Shell user={user} title="Schedules">
        <p className="mt-1 text-emerald-600">
          Three locked schedules (Asia/Riyadh). A scheduled run builds
          the report and queues it for approval — nothing executes on
          its own.
        </p>

        {error && (
          <p className="mt-6 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">
            {error}
          </p>
        )}

        <div className="mt-6 space-y-4">
          {schedules.map((schedule) => {
            const result = lastResult[schedule.id]
            const history = histories[schedule.id] ?? []
            return (
              <section
                key={schedule.id}
                className="rounded-[14px] border border-[#EAE5D9] bg-white p-6 shadow-sm"
              >
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h2 className="text-lg font-bold text-emerald-900">
                      {schedule.workflow_name ?? schedule.workflow_key}
                    </h2>
                    <p className="mt-1 text-sm text-emerald-600">
                      {CRON_LABELS[schedule.cron] ?? schedule.cron} · cron{' '}
                      <code>{schedule.cron}</code> ·{' '}
                      {schedule.is_active ? 'Active' : 'Inactive'}
                    </p>
                    <p className="mt-1 text-sm text-emerald-600">
                      Next run:{' '}
                      {schedule.next_run_at
                        ? new Date(schedule.next_run_at).toLocaleString()
                        : '—'}
                    </p>
                  </div>
                  {canManage && (
                    <button
                      type="button"
                      disabled={runningId === schedule.id || !schedule.is_active}
                      onClick={() => onRunNow(schedule.id)}
                      className="hero-gold-btn rounded-md px-4 py-2 font-semibold disabled:opacity-50"
                    >
                      {runningId === schedule.id ? 'Running…' : 'Run now'}
                    </button>
                  )}
                </div>
                {result && (
                  <div className="mt-4 rounded-md bg-[#F7F5F0] p-3 text-sm text-emerald-900">
                    <p>
                      <strong>Run #{result.run_id}:</strong> {result.status} ·
                      confidence {result.confidence?.toFixed(2) ?? '—'}
                    </p>
                    <p className="mt-1">{result.summary}</p>
                  </div>
                )}
                <div className="mt-4">
                  <h3 className="text-sm font-semibold text-emerald-900">
                    History ({history.length})
                  </h3>
                  {history.length === 0 ? (
                    <p className="mt-1 text-sm text-emerald-600">
                      No scheduled or manual runs yet.
                    </p>
                  ) : (
                    <ul className="mt-2 space-y-1">
                      {history.slice(0, 5).map((run) => (
                        <li
                          key={run.id}
                          className="flex flex-wrap items-center justify-between gap-2 border-b border-emerald-50 pb-1 text-sm"
                        >
                          <span className="text-emerald-900">
                            Run #{run.id} — {run.trigger ?? 'manual'}
                          </span>
                          <span className="text-emerald-600">
                            {run.status}
                            {run.confidence !== null &&
                              ` · confidence ${run.confidence.toFixed(2)}`}
                            {run.started_at &&
                              ` · ${new Date(run.started_at).toLocaleString()}`}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </section>
            )
          })}
        </div>
    </Shell>
  )
}
