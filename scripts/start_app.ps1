$ErrorActionPreference = "Stop"

$Root = if ($env:ROLL_ROOT) { $env:ROLL_ROOT } else { "C:\Roll" }
$Python = "$Root\python-embed\App\Python\python.exe"
$Cloudflared = "$Root\cloudflare\cloudflared.exe"
$ConfigPath = "$Root\config\config.local.json"

$Config = Get-Content $ConfigPath -Raw | ConvertFrom-Json

Write-Host "Starting server: $($Config.server_name)"

Start-Process $Python `
    -ArgumentList "$Root\app\app.py" `
    -WorkingDirectory $Root
