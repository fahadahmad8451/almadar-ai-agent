import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  getEvalSummary,
  getMe,
  runEvals,
  type EvalSummary,
  type User,
} from '../api/client'
import Shell from '../components/Shell'

// Sprint 3: scripted evals (Design section 10). Twelve scenarios
// run against the seeded database and compare outputs with expected
// values. Targets: task success >= 0.85, tool accuracy >= 0.90,
// approval compliance = 100%, self-check catch >= 0.80.

function pct(value: number | null): string {
  return value === null || value === undefined ? '—' : `${(value * 100).toFixed(1)}%`
}

export default function Evals() {
  const [user, setUser] = useState<User | null>(null)
  const [summary, setSummary] = useState<EvalSummary | null>(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const navigate = useNavigate()

  const load = useCallback(async () => {
    const data = await getEvalSummary()
    setSummary(data)
  }, [])

  useEffect(() => {
    getMe()
      .then(({ user: me }) => {
        setUser(me)
        return load()
      })
      .catch(() => navigate('/login'))
  }, [load, navigate])

  const canRun =
    user?.role === 'ADMIN' || user?.role === 'OPERATIONS_MANAGER'

  async function onRun() {
    setError(null)
    setRunning(true)
    try {
      const data = await runEvals()
      setSummary(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Eval run failed.')
    } finally {
      setRunning(false)
    }
  }

  return (
    <Shell user={user} title="Evaluations">
        <p className="mt-1 text-emerald-600">
          Twelve scripted scenarios against the seeded database.
          Targets: task success ≥ 0.85, tool accuracy ≥ 0.90, approval
          compliance = 100%, self-check catch ≥ 0.80.
        </p>

        {error && (
          <p className="mt-6 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">
            {error}
          </p>
        )}

        <div className="mt-6 flex flex-wrap items-center gap-3">
          {canRun && (
            <button
              type="button"
              disabled={running}
              onClick={onRun}
              className="hero-gold-btn rounded-md px-4 py-2 font-semibold disabled:opacity-50"
            >
              {running ? 'Running evals…' : 'Run evals'}
            </button>
          )}
          {summary?.run_at && (
            <span className="text-sm text-emerald-600">
              Last run: {new Date(summary.run_at).toLocaleString()}
            </span>
          )}
        </div>

        {summary && summary.total > 0 && (
          <>
            <section className="mt-6 grid gap-4 sm:grid-cols-4">
              <div className="rounded-[14px] border border-[#EAE5D9] bg-white p-4 shadow-sm">
                <p className="text-sm text-emerald-600">Pass rate</p>
                <p className="text-2xl font-bold text-emerald-900">
                  {pct(summary.pass_rate)} · {summary.passed}/{summary.total}
                </p>
              </div>
              <div className="rounded-[14px] border border-[#EAE5D9] bg-white p-4 shadow-sm">
                <p className="text-sm text-emerald-600">Tool accuracy</p>
                <p className="text-2xl font-bold text-emerald-900">
                  {pct(summary.tool_accuracy_avg)}
                </p>
              </div>
              <div className="rounded-[14px] border border-[#EAE5D9] bg-white p-4 shadow-sm">
                <p className="text-sm text-emerald-600">Approval compliance</p>
                <p className="text-2xl font-bold text-emerald-900">
                  {pct(summary.approval_compliance_rate)}
                </p>
              </div>
              <div className="rounded-[14px] border border-[#EAE5D9] bg-white p-4 shadow-sm">
                <p className="text-sm text-emerald-600">Self-check catch</p>
                <p className="text-2xl font-bold text-emerald-900">
                  {pct(summary.self_check_catch_rate)}
                </p>
              </div>
            </section>

            <section className="mt-8 rounded-[14px] border border-[#EAE5D9] bg-white p-6 shadow-sm">
              <h2 className="text-lg font-bold text-emerald-900">Scenarios</h2>
              <table className="mt-4 w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-emerald-100 text-emerald-600">
                    <th className="py-2 pr-2">Scenario</th>
                    <th className="py-2 pr-2">Result</th>
                    <th className="py-2 pr-2">Tool accuracy</th>
                    <th className="py-2">Latency</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.results.map((item) => (
                    <tr key={item.scenario} className="border-b border-emerald-50">
                      <td className="py-2 pr-2 text-emerald-900">{item.name}</td>
                      <td className="py-2 pr-2 font-semibold">
                        {item.success ? (
                          <span className="text-teal-700">PASS</span>
                        ) : (
                          <span className="text-red-700">FAIL</span>
                        )}
                      </td>
                      <td className="py-2 pr-2 text-emerald-900">
                        {item.tool_accuracy !== null
                          ? pct(item.tool_accuracy)
                          : '—'}
                      </td>
                      <td className="py-2 text-emerald-900">
                        {item.latency_ms !== null ? `${item.latency_ms} ms` : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-3 text-sm text-emerald-600">
                Latency p95: {summary.latency_ms_p95 ?? '—'} ms (target &lt;
                60,000 ms).
              </p>
            </section>
          </>
        )}

        {summary && summary.total === 0 && (
          <p className="mt-6 text-emerald-600">
            {summary.note ?? 'No eval run yet.'}
          </p>
        )}
    </Shell>
  )
}
