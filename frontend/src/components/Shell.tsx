import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { listApprovals, logout, type User } from '../api/client'
import { APP_VERSION } from '../App'

// v0.7.0 — Sidebar console shell (Demo 1). Every signed-in page
// renders inside this shell: a dark emerald sidebar on the left and
// a top bar with the page title, search and the approvals bell.
// The old top-nav (Nav.tsx) is gone. The Approvals badge and the
// bell dot come from one live listApprovals call — no run is created.

const WORKSPACE_LINKS = [
  { to: '/dashboard', label: 'Dashboard', icon: '▦' },
  { to: '/instruct', label: 'Instruct', icon: '✦' },
  { to: '/workflows', label: 'Workflows', icon: '⚙' },
  { to: '/approvals', label: 'Approvals', icon: '✓' },
  { to: '/reports', label: 'Reports', icon: '▤' },
]

const MANAGE_LINKS = [
  { to: '/schedules', label: 'Schedules', icon: '◷' },
  { to: '/evals', label: 'Evals', icon: '◎' },
]

function initials(name: string): string {
  const parts = name.trim().split(/\s+/)
  const first = parts[0]?.[0] ?? '?'
  const last = parts.length > 1 ? (parts[parts.length - 1][0] ?? '') : ''
  return `${first}${last}`.toUpperCase()
}

export default function Shell({
  user,
  title,
  children,
}: {
  user: User | null
  title: string
  children: React.ReactNode
}) {
  const location = useLocation()
  const navigate = useNavigate()
  const [pendingCount, setPendingCount] = useState(0)
  const [query, setQuery] = useState('')

  useEffect(() => {
    listApprovals()
      .then(({ pending_count }) => setPendingCount(pending_count))
      .catch(() => setPendingCount(0))
  }, [])

  async function onSignOut() {
    await logout().catch(() => undefined)
    navigate('/login')
  }

  function onSearch(e: FormEvent) {
    e.preventDefault()
    if (!query.trim()) return
    navigate(`/instruct?q=${encodeURIComponent(query.trim())}`)
  }

  function navLink(link: { to: string; label: string; icon: string }) {
    const active = location.pathname === link.to
    const badge =
      link.to === '/approvals' && pendingCount > 0 ? (
        <span className="ml-auto flex h-5 min-w-[22px] items-center justify-center rounded-full bg-gold-500 px-1.5 text-[11px] font-bold text-emerald-900">
          {pendingCount}
        </span>
      ) : null
    return (
      <Link
        key={link.to}
        to={link.to}
        className={
          active
            ? 'flex items-center gap-3 rounded-lg bg-white/10 px-3 py-2.5 text-sm font-semibold text-white shadow-[inset_3px_0_0_#C8A24B]'
            : 'flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm text-[#D8E4DC] hover:bg-white/10'
        }
      >
        <span className="w-5 text-center text-[15px]">{link.icon}</span>
        {link.label}
        {badge}
      </Link>
    )
  }

  return (
    <div className="flex min-h-screen bg-[#F7F5F0] text-emerald-900">
      <aside className="sticky top-0 flex h-screen w-[220px] shrink-0 flex-col bg-emerald-900 text-[#E7EFEA] lg:w-[248px]">
        <div className="border-b border-white/10 px-5 pb-4 pt-5">
          <div className="flex h-10 w-10 items-center justify-center rounded-[10px] bg-gold-500 text-xl font-extrabold text-emerald-900">
            M
          </div>
          <h1 className="mt-2.5 whitespace-nowrap text-[17px] font-bold tracking-wide text-white">
            Al Madar Holding
          </h1>
          <p className="mt-0.5 text-[11px] uppercase tracking-[2px] text-gold-400">
            Operations
          </p>
        </div>

        <nav className="flex-1 space-y-0.5 overflow-y-auto px-3 py-4" aria-label="Main">
          <p className="px-3 pb-1.5 pt-2.5 text-[10px] uppercase tracking-[2px] text-white/45">
            Workspace
          </p>
          {WORKSPACE_LINKS.map(navLink)}
          <p className="px-3 pb-1.5 pt-4 text-[10px] uppercase tracking-[2px] text-white/45">
            Manage
          </p>
          {MANAGE_LINKS.map(navLink)}
          {user?.role === 'ADMIN' &&
            navLink({ to: '/admin', label: 'Admin', icon: '⚑' })}
          {user?.role === 'ADMIN' &&
            navLink({ to: '/monitoring', label: 'Monitoring', icon: '◉' })}
        </nav>

        <div className="p-3">
          <div className="flex items-center gap-2.5 rounded-xl border border-white/10 bg-white/5 p-3">
            <div className="flex h-[38px] w-[38px] shrink-0 items-center justify-center rounded-full bg-gold-500 text-sm font-extrabold text-emerald-900">
              {user ? initials(user.name) : '…'}
            </div>
            <div className="min-w-0">
              <p className="truncate text-[13px] font-semibold text-white">
                {user ? user.name : 'Loading…'}
              </p>
              <p className="truncate text-[11px] tracking-wide text-white/60">
                {user ? user.role.replace(/_/g, ' ') : ''}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onSignOut}
            className="mt-2 w-full rounded-lg border border-white/20 px-3 py-2 text-sm font-semibold text-[#E7EFEA] hover:bg-white/10"
          >
            Sign out
          </button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-[62px] shrink-0 items-center gap-4 border-b border-[#E6E1D6] bg-white px-7">
          <div className="min-w-0">
            <h2 className="truncate text-[19px] font-bold">{title}</h2>
            <p className="truncate text-xs text-[#8A938C]">
              Al Madar Holding / Operations
            </p>
          </div>
          <form onSubmit={onSearch} className="ml-auto hidden shrink-0 sm:block">
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search invoices, suppliers, runs…"
              aria-label="Search"
              className="w-40 rounded-full border border-[#E6E1D6] bg-[#F7F5F0] px-3.5 py-1.5 text-[13px] text-emerald-900 placeholder:text-[#8A938C] lg:w-72"
            />
          </form>
          <Link
            to="/approvals"
            aria-label="Approvals"
            className="relative flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-[#E6E1D6] bg-white text-[15px]"
          >
            🔔
            {pendingCount > 0 && (
              <span className="absolute right-[7px] top-[7px] h-2 w-2 rounded-full border-2 border-white bg-red-600" />
            )}
          </Link>
        </header>

        <div className="mx-auto w-full max-w-[1400px] px-7 py-6">
          {children}
          <p className="pt-5 text-center text-[11px] text-[#A9B0A9]">
            Al Madar Holding — Enterprise AI Agent · v{APP_VERSION}
          </p>
        </div>
      </div>
    </div>
  )
}
