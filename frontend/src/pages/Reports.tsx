import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  downloadExport,
  getMe,
  listDrafts,
  listReports,
  type EmailDraftItem,
  type ReportExportItem,
  type User,
} from '../api/client'
import Shell from '../components/Shell'

// Sprint 2: real report exports and approved email drafts. Exports
// download as real files (PDF / CSV / XLSX) from the backend; drafts
// are the saved, approved emails — they are never sent.

export default function Reports() {
  const [user, setUser] = useState<User | null>(null)
  const [exportsList, setExportsList] = useState<ReportExportItem[]>([])
  const [drafts, setDrafts] = useState<EmailDraftItem[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const navigate = useNavigate()

  const load = useCallback(async () => {
    const [{ exports: list }, { drafts: draftList }] = await Promise.all([
      listReports(),
      listDrafts(),
    ])
    setExportsList(list)
    setDrafts(draftList)
  }, [])

  useEffect(() => {
    getMe()
      .then(({ user: me }) => {
        setUser(me)
        return load()
      })
      .catch(() => navigate('/login'))
  }, [load, navigate])

  async function onDownload(runId: number, format: string) {
    setError(null)
    setBusy(`${runId}-${format}`)
    try {
      const { blob, fileName } = await downloadExport(runId, format)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = fileName
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Download failed.')
    } finally {
      setBusy(null)
    }
  }

  const runIds = [...new Set(exportsList.map((e) => e.run_id))].sort(
    (a, b) => b - a,
  )

  return (
    <Shell user={user} title="Reports">
        <p className="mt-1 text-emerald-600">
          Real export files from approved runs, and the approved email
          drafts. Exports are available only after the run completes.
        </p>

        {error && (
          <p className="mt-6 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">
            {error}
          </p>
        )}

        <section className="mt-6 rounded-[14px] border border-[#EAE5D9] bg-white p-6 shadow-sm">
          <h2 className="text-lg font-bold text-emerald-900">Exports</h2>
          {runIds.length === 0 ? (
            <p className="mt-2 text-emerald-600">
              No exports yet. Run a workflow and approve it.
            </p>
          ) : (
            <ul className="mt-3 space-y-4">
              {runIds.map((runId) => {
                const items = exportsList.filter((e) => e.run_id === runId)
                const first = items[0]
                return (
                  <li
                    key={runId}
                    className="flex flex-wrap items-center justify-between gap-3 border-b border-emerald-50 pb-3"
                  >
                    <div>
                      <p className="font-semibold text-emerald-900">
                        Run #{runId} — {first.workflow_key ?? 'Workflow'}
                      </p>
                      <p className="text-sm text-emerald-600">
                        {items.map((e) => e.file_name).join(' · ')}
                      </p>
                    </div>
                    <div className="flex gap-2">
                      {(['pdf', 'csv', 'xlsx'] as const).map((format) => (
                        <button
                          key={format}
                          type="button"
                          disabled={busy === `${runId}-${format}`}
                          onClick={() => onDownload(runId, format)}
                          className="rounded-md border border-emerald-200 px-3 py-1 text-sm font-semibold text-emerald-900 hover:bg-emerald-50 disabled:opacity-50"
                        >
                          {busy === `${runId}-${format}`
                            ? '…'
                            : format.toUpperCase()}
                        </button>
                      ))}
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
        </section>

        <section className="mt-6 rounded-[14px] border border-[#EAE5D9] bg-white p-6 shadow-sm">
          <h2 className="text-lg font-bold text-emerald-900">Email drafts</h2>
          <p className="mt-1 text-sm text-emerald-600">
            Approved drafts only. Drafts are never sent by this system.
          </p>
          {drafts.length === 0 ? (
            <p className="mt-2 text-emerald-600">No drafts yet.</p>
          ) : (
            <ul className="mt-3 space-y-4">
              {drafts.map((draft) => (
                <li
                  key={draft.id}
                  className="border-b border-emerald-50 pb-3"
                >
                  <p className="font-semibold text-emerald-900">
                    To: {draft.to_email} — {draft.subject}
                  </p>
                  <p className="text-sm text-emerald-600">
                    Run #{draft.run_id} · {draft.status}
                    {draft.created_at &&
                      ` · ${new Date(draft.created_at).toLocaleString()}`}
                  </p>
                  <p className="mt-1 whitespace-pre-wrap text-sm text-emerald-900">
                    {draft.body}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </section>
    </Shell>
  )
}
