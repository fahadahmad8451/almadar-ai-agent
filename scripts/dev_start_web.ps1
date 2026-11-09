# Start the frontend web app (dev, :3100). Local-first, no Docker.
Set-Location (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "..\frontend")
if (-not (Test-Path node_modules)) {
  npm install
}
npm run dev
