$ErrorActionPreference = "Stop"

$Root = if ($env:ROLL_ROOT) { $env:ROLL_ROOT } else { "C:\Roll" }
$Python = "$Root\python-embed\App\Python\python.exe"
$Cloudflared = "$Root\cloudflare\cloudflared.exe"
$ConfigPath = "$Root\config\config.local.json"

$Config = Get-Content $ConfigPath -Raw | ConvertFrom-Json

if ($Config.server_name -eq "eu-wheel") {
    Write-Host "Starting Global Collector"
    Start-Process "$Root\python-embed\App\Python\python.exe" `
        -ArgumentList "$Root\global\collector.py" `
        -WorkingDirectory "$Root"
}