# PRODUCTION STOP — Al Madar Holding AI Agent (v0.8.0)
#
# Stops the production API (:8100) and production web preview (:3100).
# Dev (same ports) and staging (:8101 / :3101) are NOT touched by this
# script — restart dev afterwards with .\scripts\dev_start.ps1
# (+ dev_start_web.ps1).
#
# Usage:  .\scripts\production_stop.ps1
$ErrorActionPreference = "Continue"
$api = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -match "uvicorn app.main:app --port 8100" }
$api | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
$web = Get-CimInstance Win32_Process -Filter "Name = 'node.exe'" |
    Where-Object { $_.CommandLine -match "vite preview --port 3100" }
$web | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Write-Host "Production processes stopped (if any were running)."
