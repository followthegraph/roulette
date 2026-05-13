$ErrorActionPreference = "Continue"

Write-Host "Stopping roulette app processes..."

Get-Process python -ErrorAction SilentlyContinue |
    Stop-Process -Force -ErrorAction SilentlyContinue

Get-Process cloudflared -ErrorAction SilentlyContinue |
    Stop-Process -Force -ErrorAction SilentlyContinue

Write-Host "Stop complete."