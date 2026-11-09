import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { getHealth, login } from '../api/client'
import { APP_VERSION } from '../App'

// Demo accounts are seeded in development only; in production the
// backend refuses them, and /health reports demo_accounts_enabled
// as false — the buttons below are hidden then, so production never
// advertises a login that cannot work.
const DEMO_ACCOUNTS = [
  { label: 'Admin', email: 'admin@almadar.local', password: 'Admin123!' },
  {
    label: 'Operations Manager',
    email: 'manager@almadar.local',
    password: 'Manager123!',
  },
  {
    label: 'Operations Officer',
    email: 'ops@almadar.local',
    password: 'Ops123!',
  },
]

export default function Login() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [demoEnabled, setDemoEnabled] = useState(true)
  const navigate = useNavigate()

  useEffect(() => {
    getHealth()
      .then((health) => setDemoEnabled(health.demo_accounts_enabled))
      .catch(() => undefined)
  }, [])

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      // JWT arrives in an httpOnly cookie set by the backend; the
      // token never touches JavaScript or localStorage.
      await login(email, password)
      navigate('/dashboard')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign-in failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-emerald-900 px-4">
      <div className="w-full max-w-md">
        <div className="mb-6 text-center">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-gold-500 text-2xl font-extrabold text-emerald-900">
            M
          </div>
          <p className="mt-3 text-lg font-bold text-white">Al Madar Holding</p>
          <p className="text-[11px] uppercase tracking-[2px] text-gold-400">
            Operations · Enterprise AI Agent
          </p>
        </div>
        <div className="rounded-[14px] bg-white p-8 shadow-sm">
          <h1 className="text-2xl font-bold text-emerald-900">Sign in</h1>
          <p className="mt-2 text-emerald-600">
            Sign in to instruct the agent. Your role decides which tools and
            approvals you can use.
          </p>
          <form className="mt-6 space-y-4" onSubmit={onSubmit}>
            <div>
              <label htmlFor="email" className="block text-sm font-semibold text-emerald-900">
                Email
              </label>
              <input
                id="email"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="mt-1 w-full rounded-md border border-emerald-200 px-3 py-2"
              />
            </div>
            <div>
              <label htmlFor="password" className="block text-sm font-semibold text-emerald-900">
                Password
              </label>
              <input
                id="password"
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="mt-1 w-full rounded-md border border-emerald-200 px-3 py-2"
              />
            </div>
            {error && (
              <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">
                {error}
              </p>
            )}
            <button
              type="submit"
              disabled={busy}
              className="hero-gold-btn w-full rounded-md px-4 py-2 font-semibold disabled:opacity-50"
            >
              {busy ? 'Signing in…' : 'Sign in'}
            </button>
          </form>
          {demoEnabled && (
            <div className="mt-6 border-t border-emerald-100 pt-4">
              <p className="text-sm font-semibold text-emerald-900">
                Demo accounts (development only)
              </p>
              <div className="mt-2 flex flex-wrap gap-2">
                {DEMO_ACCOUNTS.map((account) => (
                  <button
                    key={account.email}
                    type="button"
                    onClick={() => {
                      setEmail(account.email)
                      setPassword(account.password)
                    }}
                    className="rounded-md border border-emerald-200 px-3 py-1 text-sm font-semibold text-emerald-900 hover:bg-emerald-50"
                  >
                    {account.label}
                  </button>
                ))}
              </div>
            </div>
          )}
          <p className="mt-4 text-center text-sm text-emerald-600">
            Accounts are created by an Admin. Demo environment — synthetic
            data only.
          </p>
        </div>
        <p className="mt-4 text-center text-sm text-white/60">v{APP_VERSION}</p>
      </div>
    </div>
  )
}
