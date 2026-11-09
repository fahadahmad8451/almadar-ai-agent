# Start the backend API (dev, :8100). Local-first, no Docker.
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path) | Out-Null
Set-Location ..
if (-not (Test-Path .venv)) {
  python -m venv .venv
}
.venv\Scripts\pip install -q -r backend\requirements.txt
.venv\Scripts\uvicorn app.main:app --port 8100 --app-dir backend
