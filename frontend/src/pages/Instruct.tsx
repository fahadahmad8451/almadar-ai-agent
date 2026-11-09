import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  getMe,
  getRunTrace,
  instruct,
  type InstructResult,
  type TraceStep,
  type User,
} from '../api/client'
import Shell from '../components/Shell'

// Sprint 2: the first live agent surface. Type an instruction in
// English or Arabic; the Supervisor parses the intent, the Data Agent
// queries the real database, and the answer shows the numbers plus
// which tools ran and the step trace. Workflows, Reports and
// Approvals are live on their own pages.

const EXAMPLES = [
  'Show me the pending invoices',
  'Who are the overdue suppliers?',
  'How many stale leads do we have?',
]

export default function Instruct() {
  const [user, setUser] = useState<User | null>(null)
  const [instruction, setInstruction] = useState('')
  const [language, setLanguage] = useState<'en' | 'ar'>('en')
  const [result, setResult] = useState<InstructResult | null>(null)
  const [trace, setTrace] = useState<TraceStep[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const prefilledRef = useRef(false)

  useEffect(() => {
    getMe()
      .then(({ user: me }) => setUser(me))
      .catch(() => navigate('/login'))
  }, [navigate])

  // The sidebar search sends its query here (?q=...) — prefill the box.
  useEffect(() => {
    if (prefilledRef.current) return
    prefilledRef.current = true
    const q = searchParams.get('q')
    if (q) setInstruction(q)
  }, [searchParams])

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (!instruction.trim()) return
    setError(null)
    setResult(null)
    setTrace(null)
    setBusy(true)
    try {
      const answer = await instruct(instruction.trim(), language)
      setResult(answer)
      const { trace: steps } = await getRunTrace(answer.run_id)
      setTrace(steps)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The agent failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Shell user={user} title="Instruct">
      <p className="text-emerald-600">
        Ask about invoices, suppliers, leads and expenses. The agent reads
        the live operations database — every number comes from real data.
      </p>

        <form className="mt-6 space-y-3" onSubmit={onSubmit}>
          <textarea
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            rows={3}
            placeholder="Show me the pending invoices"
            className="w-full rounded-md border border-emerald-200 bg-white px-3 py-2"
          />
          <div className="flex flex-wrap items-center gap-3">
            <label className="text-sm font-semibold text-emerald-900">
              Language
              <select
                value={language}
                onChange={(e) =>
                  setLanguage(e.target.value as 'en' | 'ar')
                }
                className="ml-2 rounded-md border border-emerald-200 bg-white px-2 py-1"
              >
                <option value="en">English</option>
                <option value="ar">Arabic</option>
              </select>
            </label>
            <button
              type="submit"
              disabled={busy || !instruction.trim()}
              className="hero-gold-btn rounded-md px-4 py-2 font-semibold disabled:opacity-50"
            >
              {busy ? 'Running…' : 'Ask the agent'}
            </button>
            <div className="flex flex-wrap gap-2">
              {EXAMPLES.map((example) => (
                <button
                  key={example}
                  type="button"
                  onClick={() => setInstruction(example)}
                  className="rounded-md border border-emerald-200 bg-white px-2 py-1 text-sm text-emerald-900 hover:bg-emerald-50"
                >
                  {example}
                </button>
              ))}
            </div>
          </div>
        </form>

        {error && (
          <p className="mt-6 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">
            {error}
          </p>
        )}

        {result && (
          <section className="mt-6 rounded-[14px] border border-[#EAE5D9] bg-white p-6 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-lg font-bold text-emerald-900">Answer</h2>
              <span className="rounded-full bg-emerald-50 px-3 py-1 text-sm text-emerald-700">
                {result.status} · confidence {result.confidence.toFixed(2)} ·
                intent {result.intent}
              </span>
            </div>
            <p className="mt-3 text-emerald-900">{result.summary}</p>
            {result.rows.length > 0 && (
              <div className="mt-4 overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr className="border-b border-emerald-100 text-emerald-600">
                      {Object.keys(result.rows[0]).map((key) => (
                        <th key={key} className="px-2 py-1 font-semibold">
                          {key}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {result.rows.map((row, i) => (
                      <tr key={i} className="border-b border-emerald-50">
                        {Object.values(row).map((value, j) => (
                          <td key={j} className="px-2 py-1 text-emerald-900">
                            {String(value ?? '')}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <p className="mt-4 text-sm text-emerald-600">
              Tools used:{' '}
              {result.tools_used.length > 0
                ? result.tools_used.join(', ')
                : 'none — no database lookup was needed'}
            </p>
            {result.escalated && (
              <p className="mt-2 text-sm font-semibold text-amber-700">
                This request was escalated to a human — the agent was not
                confident enough to answer on its own.
              </p>
            )}
          </section>
        )}

        {trace && trace.length > 0 && (
          <section className="mt-6 rounded-[14px] border border-[#EAE5D9] bg-white p-6 shadow-sm">
            <h2 className="text-lg font-bold text-emerald-900">Steps trace</h2>
            <ol className="mt-3 space-y-3">
              {trace.map((step) => (
                <li key={step.step_index} className="border-l-2 border-teal-600 pl-3">
                  <p className="font-semibold text-emerald-900">
                    {step.step_index + 1}. {step.agent} — {step.action}{' '}
                    <span className="font-normal text-emerald-600">
                      — {step.status}
                      {step.latency_ms !== null && ` · ${step.latency_ms} ms`}
                    </span>
                  </p>
                  {step.output && (
                    <p className="text-sm text-emerald-600">{step.output}</p>
                  )}
                  {step.tool_calls.length > 0 && (
                    <p className="text-sm text-emerald-600">
                      Tools:{' '}
                      {step.tool_calls
                        .map((t) => `${t.tool} (${t.status})`)
                        .join(', ')}
                    </p>
                  )}
                </li>
              ))}
            </ol>
          </section>
        )}
    </Shell>
  )
}
