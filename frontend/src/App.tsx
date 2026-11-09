import { useEffect, useState } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import Login from './pages/Login'
import Instruct from './pages/Instruct'
import Workflows from './pages/Workflows'
import Approvals from './pages/Approvals'
import Reports from './pages/Reports'
import Schedules from './pages/Schedules'
import Admin from './pages/Admin'
import Evals from './pages/Evals'
import Monitoring from './pages/Monitoring'
import { getMe } from './api/client'

export const APP_VERSION = '0.9.0'

// v0.8.0 — Production. Sidebar console structure (Demo 1), plus the
// dedicated GET /dashboard/summary endpoint: the Dashboard home reads
// live figures straight from the database (no instruct calls any
// more), and the Login page hides demo accounts in production.
// There is no landing hero page: "/" sends a signed-in user to the
// Dashboard and everyone else to Sign in.

function RootRedirect() {
  const [state, setState] = useState<'checking' | 'signed-in' | 'signed-out'>(
    'checking',
  )

  useEffect(() => {
    getMe()
      .then(() => setState('signed-in'))
      .catch(() => setState('signed-out'))
  }, [])

  if (state === 'checking') {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#F7F5F0] text-emerald-900">
        <p className="text-sm font-semibold">Al Madar Holding — loading…</p>
      </div>
    )
  }
  return <Navigate to={state === 'signed-in' ? '/dashboard' : '/login'} replace />
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<RootRedirect />} />
      <Route path="/login" element={<Login />} />
      <Route path="/dashboard" element={<Dashboard />} />
      <Route path="/instruct" element={<Instruct />} />
      <Route path="/workflows" element={<Workflows />} />
      <Route path="/approvals" element={<Approvals />} />
      <Route path="/reports" element={<Reports />} />
      <Route path="/schedules" element={<Schedules />} />
      <Route path="/admin" element={<Admin />} />
      <Route path="/evals" element={<Evals />} />
      <Route path="/monitoring" element={<Monitoring />} />
      <Route path="*" element={<RootRedirect />} />
    </Routes>
  )
}
