import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  getMe,
  listRuns,
  listWorkflows,
  runWorkflow,
  uploadInvoice,
  type InvoiceUploadResult,
  type RunItem,
  type User,
  type WorkflowItem,
  type WorkflowRunResult,
} from '../api/client'
import Shell from '../components/Shell'

// Sprint 2: the four live workflows. Run starts the full pipeline
// (Supervisor -> Data Agent -> Self-Check -> Report Agent ->
// Approval Agent) and stops at AWAITING_APPROVAL — nothing executes
// until a manager approves on the Approvals page.
// Sprint 3: attach an invoice PDF — it is extracted, matched against
// its purchase order, and queued for approval before anything is
// recorded in ERP.

export default function Workflows() {
  const [user, setUser] = useState<User | null>(null)
  const [workflows, setWorkflows] = useState<WorkflowItem[]>([])
  const [runs, setRuns] = useState<RunItem[]>([])
  const [formats, setFormats] = useState<Record<string, string>>({})
  const [runningKey, setRunningKey] = useState<string | null>(null)
  const [lastResult, setLastResult] = useState<Record<string, WorkflowRunResult>>({})
  const [error, setError] = useState<string | null>(null)
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadResult, setUploadResult] = useState<InvoiceUploadResult | null>(null)
  const navigate = useNavigate()

  const load = useCallback(async () => {
    const [{ workflows: list }, { runs: runList }] = await Promise.all([
      listWorkflows(),
      listRuns(),
    ])
    setWorkflows(list)
    setRuns(runList)
  }, [])

  useEffect(() => {
    getMe()
      .then(({ user: me }) => {
        setUser(me)
        return load()
      })
      .catch(() => navigate('/login'))
  }, [load, navigate])

  async function onRun(key: string) {
    setError(null)
    setRunningKey(key)
    try {
      const result = await runWorkflow(key, {
        export_format: formats[key] ?? 'pdf',
      })
      setLastResult((prev) => ({ ...prev, [key]: result }))
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Workflow run failed.')
    } finally {
      setRunningKey(null)
    }
  }

  async function onUpload() {
    if (!uploadFile) return
    setError(null)
    setUploadResult(null)
    setUploading(true)
    try {
      const result = await uploadInvoice(uploadFile)
      setUploadResult(result)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Invoice upload failed.')
    } finally {
      setUploading(false)
    }
  }

  return (
    <Shell user={user} title="Workflows">
        <p className="mt-1 text-emerald-600">
          Four scheduled operations workflows. Running one builds the
          report and queues it for approval — nothing executes until a
          manager approves.
        </p>

        {error && (
          <p className="mt-6 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">
            {error}
          </p>
        )}

        <div className="mt-6 grid gap-4 md:grid-cols-2">
          {workflows.map((workflow) => {
            const result = lastResult[workflow.key]
            return (
              <section
                key={workflow.key}
                className="rounded-[14px] border border-[#EAE5D9] bg-white p-6 shadow-sm"
              >
                <h2 className="text-lg font-bold text-emerald-900">
                  {workflow.name}
                </h2>
                <p className="mt-1 text-sm text-emerald-600">
                  {workflow.description}
                </p>
                <p className="mt-2 text-sm text-emerald-600">
                  Schedule: {workflow.trigger_type} ·{' '}
                  {workflow.is_active ? 'Active' : 'Inactive'}
                </p>
                <div className="mt-4 flex flex-wrap items-center gap-2">
                  <label className="text-sm font-semibold text-emerald-900">
                    Export
                    <select
                      value={formats[workflow.key] ?? 'pdf'}
                      onChange={(e) =>
                        setFormats((prev) => ({
                          ...prev,
                          [workflow.key]: e.target.value,
                        }))
                      }
                      className="ml-2 rounded-md border border-emerald-200 bg-white px-2 py-1"
                    >
                      <option value="pdf">PDF</option>
                      <option value="csv">CSV</option>
                      <option value="xlsx">XLSX</option>
                    </select>
                  </label>
                  <button
                    type="button"
                    disabled={runningKey === workflow.key || !workflow.is_active}
                    onClick={() => onRun(workflow.key)}
                    className="hero-gold-btn rounded-md px-4 py-2 font-semibold disabled:opacity-50"
                  >
                    {runningKey === workflow.key ? 'Running…' : 'Run'}
                  </button>
                </div>
                {result && (
                  <div className="mt-4 rounded-md bg-[#F7F5F0] p-3 text-sm text-emerald-900">
                    <p>
                      <strong>Run #{result.run_id}:</strong> {result.status} ·
                      confidence {result.confidence?.toFixed(2) ?? '—'}
                    </p>
                    <p className="mt-1">{result.summary}</p>
                    <p className="mt-1 text-emerald-600">
                      {result.approval_ids.length} approval(s) created — see
                      the Approvals page.
                    </p>
                  </div>
                )}
              </section>
            )
          })}
        </div>

        <section className="mt-8 rounded-[14px] border border-[#EAE5D9] bg-white p-6 shadow-sm">
          <h2 className="text-lg font-bold text-emerald-900">
            Attach invoice PDF
          </h2>
          <p className="mt-1 text-sm text-emerald-600">
            Upload a supplier invoice (PDF, max 10 MB). The fields are
            extracted and matched against the purchase order — a match
            is queued to record the invoice, a mismatch is queued as
            disputed. Nothing is recorded until a manager approves.
          </p>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <input
              type="file"
              accept="application/pdf"
              onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)}
              className="text-sm text-emerald-900"
            />
            <button
              type="button"
              disabled={!uploadFile || uploading}
              onClick={onUpload}
              className="hero-gold-btn rounded-md px-4 py-2 font-semibold disabled:opacity-50"
            >
              {uploading ? 'Uploading…' : 'Upload & match'}
            </button>
          </div>
          {uploadResult && (
            <div className="mt-4 rounded-md bg-[#F7F5F0] p-3 text-sm text-emerald-900">
              <p>
                <strong>{uploadResult.file_name}:</strong>{' '}
                {uploadResult.match_status} · method {uploadResult.method} ·
                run #{uploadResult.run_id} ({uploadResult.run_status})
              </p>
              <p className="mt-1">
                Invoice {uploadResult.fields.invoice_no ?? '—'} ·{' '}
                {uploadResult.fields.supplier ?? '—'} ·{' '}
                {uploadResult.fields.amount_sar !== null
                  ? `${uploadResult.fields.amount_sar.toLocaleString()} SAR`
                  : '—'}{' '}
                · PO {uploadResult.fields.po_no ?? '—'}
              </p>
              {uploadResult.mismatches.length > 0 && (
                <ul className="mt-2 list-disc pl-5">
                  {uploadResult.mismatches.map((m, i) => (
                    <li key={i}>
                      {m.field}: extracted {String(m.extracted)} — expected{' '}
                      {String(m.expected)}
                    </li>
                  ))}
                </ul>
              )}
              <p className="mt-2 text-emerald-600">{uploadResult.note}</p>
              {uploadResult.approval_id !== null && (
                <p className="mt-1">
                  Approval #{uploadResult.approval_id} created — see the
                  Approvals page.
                </p>
              )}
            </div>
          )}
        </section>

        <section className="mt-8 rounded-[14px] border border-[#EAE5D9] bg-white p-6 shadow-sm">
          <h2 className="text-lg font-bold text-emerald-900">Run history</h2>
          {runs.length === 0 ? (
            <p className="mt-2 text-emerald-600">No runs yet.</p>
          ) : (
            <ul className="mt-3 space-y-2">
              {runs.slice(0, 10).map((run) => (
                <li
                  key={run.id}
                  className="flex flex-wrap items-center justify-between gap-2 border-b border-emerald-50 pb-2 text-sm"
                >
                  <span className="text-emerald-900">
                    Run #{run.id} — {run.instruction}
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
        </section>
    </Shell>
  )
}
