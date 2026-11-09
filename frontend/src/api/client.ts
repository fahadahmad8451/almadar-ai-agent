// Real API client — talks to FastAPI at /api/v1 (proxied by Vite in dev).
// Sprint 2 v0.3: auth, instruct, workflows, approvals and reports are
// live. Tokens are never stored in localStorage; the browser sends the
// cookies automatically. Endpoints still marked 501 on the backend
// surface their error honestly — no fake data.

export interface HealthData {
  status: string
  version: string
  service: string
  environment: string
  database: string
  demo_accounts_enabled: boolean
  uptime_seconds: number
}

export interface User {
  id: number
  email: string
  name: string
  role: 'ADMIN' | 'OPERATIONS_MANAGER' | 'OPERATIONS_OFFICER'
}

export interface InstructResult {
  run_id: number
  status: 'COMPLETED' | 'ESCALATED'
  intent: string
  parser: 'llm' | 'rule'
  language: 'en' | 'ar'
  confidence: number
  escalated: boolean
  summary: string
  rows: Record<string, unknown>[]
  totals: { count: number; total_amount_sar: number; total_vat_sar: number }
  tools_used: string[]
}

export interface TraceStep {
  step_index: number
  agent: string
  action: string
  status: string
  latency_ms: number | null
  input: string | null
  output: string | null
  tool_calls: { tool: string; args: Record<string, unknown>; status: string; error: string | null }[]
}

export interface WorkflowItem {
  id: number
  key: string
  name: string
  name_ar: string
  description: string
  trigger_type: string
  is_active: boolean
}

export interface ApprovalAction {
  type: 'export_report' | 'save_email_draft' | 'approve_expense_claim'
  format?: string
  draft?: { to_email: string; subject: string; body: string }
  claim_id?: number
  employee_name?: string
  amount_sar?: number
  category?: string
}

export interface ApprovalItem {
  id: number
  run_id: number
  workflow_key: string | null
  action_summary: string
  diff: { actions: ApprovalAction[] }
  status: 'PENDING' | 'APPROVED' | 'REJECTED'
  requested_by: number
  approver_id: number | null
  decided_at: string | null
  comment: string | null
}

export interface WorkflowRunResult {
  run_id: number
  workflow_key: string
  status: string
  confidence: number | null
  escalated: boolean
  summary: string
  totals: Record<string, unknown>
  approval_ids: number[]
  report_title: string | null
  trace: { agent: string; action: string; status: string; latency_ms: number; note: string }[]
}

export interface RunItem {
  id: number
  workflow_id: number
  workflow_key?: string | null
  instruction: string
  language: string
  status: string
  confidence: number | null
  started_at: string | null
  finished_at: string | null
}

export interface ReportExportItem {
  id: number
  run_id: number
  workflow_key: string | null
  format: string
  file_name: string
  download_url: string
  created_at: string | null
}

export interface EmailDraftItem {
  id: number
  run_id: number
  workflow_key: string | null
  to_email: string
  subject: string
  body: string
  status: string
  created_at: string | null
}

interface Envelope<T> {
  success: boolean
  data: T | null
  error: { code: string; message: string } | null
  request_id: string
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/v1${path}`, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    ...init,
  })
  const body = (await res.json().catch(() => null)) as Envelope<T> | null
  if (!res.ok || !body || body.success === false) {
    const message =
      body?.error?.message ?? `Request failed with status ${res.status}.`
    throw new Error(message)
  }
  return body.data as T
}

export interface DashboardSummary {
  pending_invoices: { count: number; total_sar: number; vat_sar: number }
  overdue_suppliers: { count: number; total_sar: number; names: string[] }
  pending_approvals: { count: number; top: ApprovalItem[] }
  evals: {
    run_at: string | null
    total: number
    passed: number
    pass_rate: number | null
    latency_ms_p95: number | null
  }
  recent_runs: RunItem[]
  generated_at: string
}

export async function getDashboardSummary(): Promise<DashboardSummary> {
  return request<DashboardSummary>('/dashboard/summary')
}

export async function getHealth(): Promise<HealthData> {
  return request<HealthData>('/health')
}

export async function login(
  email: string,
  password: string,
): Promise<{ user: User }> {
  return request<{ user: User }>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
}

export async function getMe(): Promise<{ user: User }> {
  return request<{ user: User }>('/auth/me')
}

export async function logout(): Promise<void> {
  await request('/auth/logout', { method: 'POST' })
}

export async function instruct(
  instruction: string,
  language: 'en' | 'ar' = 'en',
): Promise<InstructResult> {
  return request<InstructResult>('/agent/instruct', {
    method: 'POST',
    body: JSON.stringify({ instruction, language }),
  })
}

export async function getRunTrace(
  runId: number,
): Promise<{ run_id: number; trace: TraceStep[] }> {
  return request<{ run_id: number; trace: TraceStep[] }>(
    `/agent/runs/${runId}/trace`,
  )
}

export async function listWorkflows(): Promise<{
  workflows: WorkflowItem[]
}> {
  return request<{ workflows: WorkflowItem[] }>('/workflows')
}

export async function runWorkflow(
  key: string,
  params: Record<string, unknown> = {},
): Promise<WorkflowRunResult> {
  return request<WorkflowRunResult>(`/workflows/${key}/run`, {
    method: 'POST',
    body: JSON.stringify({ params }),
  })
}

export async function listRuns(): Promise<{ runs: RunItem[]; count: number }> {
  return request<{ runs: RunItem[]; count: number }>('/agent/runs')
}

export async function listApprovals(): Promise<{
  approvals: ApprovalItem[]
  count: number
  pending_count: number
}> {
  return request<{
    approvals: ApprovalItem[]
    count: number
    pending_count: number
  }>('/approvals')
}

export async function getApproval(
  id: number,
): Promise<{ approval: ApprovalItem }> {
  return request<{ approval: ApprovalItem }>(`/approvals/${id}`)
}

export async function approveApproval(
  id: number,
): Promise<{ approval_id: number; executed: unknown[]; run_status: string }> {
  return request(`/approvals/${id}/approve`, { method: 'POST' })
}

export async function rejectApproval(
  id: number,
  comment?: string,
): Promise<{ approval: ApprovalItem }> {
  return request(`/approvals/${id}/reject`, {
    method: 'POST',
    body: JSON.stringify({ comment: comment ?? null }),
  })
}

export async function listReports(): Promise<{
  exports: ReportExportItem[]
  count: number
}> {
  return request<{ exports: ReportExportItem[]; count: number }>('/reports')
}

export async function downloadExport(
  runId: number,
  format: string,
): Promise<{ blob: Blob; fileName: string }> {
  const res = await fetch(
    `/api/v1/reports/${runId}/export?format=${format}`,
    { credentials: 'include' },
  )
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(
      body?.error?.message ?? `Download failed with status ${res.status}.`,
    )
  }
  const blob = await res.blob()
  const disposition = res.headers.get('content-disposition') ?? ''
  const match = disposition.match(/filename="?([^"]+)"?/)
  return { blob, fileName: match?.[1] ?? `report-${runId}.${format}` }
}

export async function listDrafts(): Promise<{
  drafts: EmailDraftItem[]
  count: number
}> {
  return request<{ drafts: EmailDraftItem[]; count: number }>('/drafts')
}

// --- Sprint 3: schedules, admin, evals, invoice upload ---

export interface ScheduleItem {
  id: number
  workflow_id: number
  workflow_key: string | null
  workflow_name: string | null
  cron: string
  next_run_at: string | null
  is_active: boolean
}

export interface ScheduleRunItem {
  id: number
  workflow_key: string | null
  trigger: string | null
  instruction: string
  status: string
  confidence: number | null
  started_at: string | null
  finished_at: string | null
}

export async function listSchedules(): Promise<{
  schedules: ScheduleItem[]
  count: number
}> {
  return request<{ schedules: ScheduleItem[]; count: number }>('/schedules')
}

export async function runScheduleNow(id: number): Promise<WorkflowRunResult> {
  return request<WorkflowRunResult>(`/schedules/${id}/run-now`, {
    method: 'POST',
  })
}

export async function listScheduleRuns(id: number): Promise<{
  schedule_id: number
  runs: ScheduleRunItem[]
  count: number
}> {
  return request<{
    schedule_id: number
    runs: ScheduleRunItem[]
    count: number
  }>(`/schedules/${id}/runs`)
}

export interface AdminUserItem {
  id: number
  email: string
  name: string
  role: 'ADMIN' | 'OPERATIONS_MANAGER' | 'OPERATIONS_OFFICER'
  created_at: string | null
}

export async function listAdminUsers(): Promise<{
  users: AdminUserItem[]
  count: number
}> {
  return request<{ users: AdminUserItem[]; count: number }>('/admin/users')
}

export async function changeUserRole(
  email: string,
  role: string,
): Promise<{ user: AdminUserItem; old_role: string }> {
  return request<{ user: AdminUserItem; old_role: string }>(
    `/admin/users/${encodeURIComponent(email)}/role`,
    { method: 'PUT', body: JSON.stringify({ role }) },
  )
}

export async function resetUserPassword(email: string): Promise<{
  email: string
  new_password: string
  note: string
}> {
  return request<{
    email: string
    new_password: string
    note: string
  }>(`/admin/users/${encodeURIComponent(email)}/reset-password`, {
    method: 'POST',
  })
}

export interface AuditLogItem {
  id: number
  user_id: number | null
  action: string
  resource: string | null
  result: string
  details: Record<string, unknown>
  created_at: string | null
}

export async function listAuditLogs(params?: {
  action?: string
  result?: string
  limit?: number
}): Promise<{ audit_logs: AuditLogItem[]; count: number }> {
  const query = new URLSearchParams()
  if (params?.action) query.set('action', params.action)
  if (params?.result) query.set('result', params.result)
  if (params?.limit) query.set('limit', String(params.limit))
  const suffix = query.toString() ? `?${query.toString()}` : ''
  return request<{ audit_logs: AuditLogItem[]; count: number }>(
    `/admin/audit${suffix}`,
  )
}

export interface ObservabilityData {
  runs_total: number
  runs_by_status: Record<string, number>
  success_rate: number | null
  latency_ms: { p50: number | null; p95: number | null; samples: number }
  tokens_total: number
  pending_approvals: number
  oldest_pending_approval_age_hours: number | null
}

export async function getObservability(): Promise<ObservabilityData> {
  return request<ObservabilityData>('/admin/observability')
}

export interface EvalResultItem {
  scenario: string
  name: string
  workflow_key: string
  success: boolean
  tool_accuracy: number | null
  approval_compliant: boolean | null
  self_check_catch: boolean | null
  latency_ms: number | null
  run_at?: string | null
}

export interface EvalSummary {
  run_at: string | null
  total: number
  passed: number
  failed: number
  pass_rate: number | null
  tool_accuracy_avg: number | null
  approval_compliance_rate: number | null
  self_check_catch_rate: number | null
  latency_ms_p95: number | null
  results: EvalResultItem[]
  note?: string
}

export async function runEvals(): Promise<EvalSummary> {
  return request<EvalSummary>('/eval/run', { method: 'POST' })
}

export async function getEvalSummary(): Promise<EvalSummary> {
  return request<EvalSummary>('/eval/summary')
}

export async function listEvalResults(): Promise<{
  results: EvalResultItem[]
  count: number
}> {
  return request<{ results: EvalResultItem[]; count: number }>(
    '/eval/results',
  )
}

export interface InvoiceUploadResult {
  upload_id: number
  run_id: number
  file_name: string
  method: string
  fields: {
    invoice_no: string | null
    po_no: string | null
    supplier: string | null
    amount_sar: number | null
    vat_sar: number | null
    issue_date: string | null
    due_date: string | null
  }
  match_status: 'MATCHED' | 'MISMATCHED' | 'EXTRACTION_FAILED'
  mismatches: {
    field: string
    extracted: unknown
    expected: unknown
  }[]
  recorded_invoice: Record<string, unknown> | null
  approval_id: number | null
  run_status: string
  note: string
}

export async function uploadInvoice(
  file: File,
): Promise<InvoiceUploadResult> {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch('/api/v1/invoices/upload', {
    method: 'POST',
    credentials: 'include',
    body: form,
  })
  const body = (await res.json().catch(() => null)) as Envelope<InvoiceUploadResult> | null
  if (!res.ok || !body || body.success === false) {
    throw new Error(
      body?.error?.message ?? `Upload failed with status ${res.status}.`,
    )
  }
  return body.data as InvoiceUploadResult
}

// --- Monitoring (v0.9.0): Admin only, real database-backed metrics ---

export interface MetricsSummary {
  window_hours: number
  generated_at: string
  requests_24h: number
  requests_total: number
  error_rate_5xx_24h: number
  errors_5xx_24h: number
  latency_ms: { p50: number | null; p95: number | null; samples: number }
  instruct_latency_ms: { p50: number | null; p95: number | null; samples: number }
  by_endpoint: Record<string, number>
  by_status: Record<string, number>
  by_role: Record<string, number>
  runs_total: number
  runs_24h: number
  runs_by_status: Record<string, number>
  escalations_total: number
  confidence_avg: number | null
  approvals: { pending: number; approved: number; rejected: number }
  evals_latest: {
    run_at: string | null
    total: number
    passed: number
    failed: number
    pass_rate: number | null
  }
}

export interface TimeseriesBucket {
  hour: string
  requests: number
  errors_5xx: number
  instruct: number
  p95_ms: number | null
}

export interface AlertItem {
  id: number
  rule: string
  severity: string
  message: string
  status: string
  details: Record<string, unknown>
  created_at: string | null
  resolved_at: string | null
  resolved_by: number | null
}

export interface MonitoringOverview {
  version: string
  environment: string
  service: string
  database: string
  uptime_seconds: number
  scheduler_running: boolean
  monitoring_alerts_enabled: boolean
  summary: MetricsSummary
  active_alerts: AlertItem[]
  active_alert_count: number
  recent_errors: {
    endpoint: string
    method: string
    status: number
    latency_ms: number
    created_at: string | null
  }[]
  disk: {
    path: string
    total_bytes: number
    used_bytes: number
    free_bytes: number
    used_percent: number | null
    data_dir_bytes: number
  }
}

export interface DailyReportItem {
  name: string
  date: string
  size_bytes: number
  has_json: boolean
}

export async function getMetricsSummary(hours = 24): Promise<MetricsSummary> {
  return request<MetricsSummary>(`/admin/metrics/summary?hours=${hours}`)
}

export async function getMetricsTimeseries(
  hours = 24,
): Promise<{ hours: number; buckets: TimeseriesBucket[] }> {
  return request<{ hours: number; buckets: TimeseriesBucket[] }>(
    `/admin/metrics/timeseries?hours=${hours}`,
  )
}

export async function getMonitoringOverview(): Promise<MonitoringOverview> {
  return request<MonitoringOverview>('/admin/monitoring/overview')
}

export async function listAlerts(status?: string): Promise<{
  alerts: AlertItem[]
  count: number
}> {
  const suffix = status ? `?status=${encodeURIComponent(status)}` : ''
  return request<{ alerts: AlertItem[]; count: number }>(`/admin/alerts${suffix}`)
}

export async function resolveAlert(
  id: number,
  comment?: string,
): Promise<{ alert: AlertItem; note?: string }> {
  return request<{ alert: AlertItem; note?: string }>(
    `/admin/alerts/${id}/resolve`,
    { method: 'POST', body: JSON.stringify({ comment: comment ?? null }) },
  )
}

export async function listDailyReports(): Promise<{
  reports: DailyReportItem[]
  count: number
  latest_markdown: string | null
}> {
  return request<{
    reports: DailyReportItem[]
    count: number
    latest_markdown: string | null
  }>('/admin/monitoring/daily-reports')
}
