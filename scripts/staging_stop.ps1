# STAGING STOP — Al Madar Holding AI Agent (v0.5)
#
# Stops the staging API (:8101) and staging web preview (:3101).
# Dev (:8100 / :3100) is NOT touched.
#
# Usage:  .\scripts\staging_stop.ps1
$ErrorActionPreference = "Continue"
$api = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -match "uvicorn app.main:app --port 8101" }
$api | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
$web = Get-CimInstance Win32_Process -Filter "Name = 'node.exe'" |
    Where-Object { $_.CommandLine -match "vite preview --port 3101" }
$web | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Write-Host "Staging processes stopped (if any were running)."
