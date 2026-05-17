param(
    [ValidateSet("start", "stop", "restart", "update", "kill", "app", "tunnel", "persistence", "collector")]
    [string]$Action = "start"
)

$ErrorActionPreference = "Stop"

$Root = if ($env:ROLL_ROOT) { $env:ROLL_ROOT } else { "C:\Roll" }

if ($Root -like "C:\projects\roulette_dist*") {
    $Python = "C:\Python\python.exe"
} else {
    $Python = "$Root\python-embed\App\Python\python.exe"
}

$Cloudflared = "$Root\cloudflare\cloudflared.exe"
$ConfigPath = "$Root\config\config.local.json"

if (!(Test-Path $ConfigPath)) {
    throw "Missing config file: $ConfigPath"
}

$Config = Get-Content $ConfigPath -Raw | ConvertFrom-Json

$TunnelName = $Config.cloudflare_tunnel_name
$CloudflareConfigPath = $Config.cloudflare_config_path
$RunCollector = $Config.run_global_collector -eq $true

function Start-App {
    Write-Host "Starting Flask app..."
    Start-Process $Python -ArgumentList "$Root\app\app.py" -WorkingDirectory $Root
}

function Start-Tunnel {
    if (!$TunnelName -or !$CloudflareConfigPath) {
        Write-Host "Cloudflare tunnel skipped."
        return
    }

    Write-Host "Starting Cloudflare tunnel: $TunnelName"
    Start-Process $Cloudflared `
        -ArgumentList "tunnel --protocol http2 --config `"$CloudflareConfigPath`" run $TunnelName" `
        -WorkingDirectory "$Root\cloudflare"
}

function Start-Persistence {
    Write-Host "Starting session persistence..."
    Start-Process $Python -ArgumentList "$Root\app\session_persistence.py" -WorkingDirectory $Root
}

function Start-Collector {
    if (!$RunCollector) {
        Write-Host "Global collector skipped."
        return
    }

    Write-Host "Starting global collector..."
    Start-Process $Python -ArgumentList "$Root\global\collector.py" -WorkingDirectory "$Root\global"
}

function Stop-Processes {
    Write-Host "Stopping roulette processes..."

    Get-Process python -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue

    Get-Process cloudflared -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue

    Get-Process chrome -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue

    Get-Process chromium -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue

    Start-Sleep -Seconds 3
}

function Update-Code {
    Write-Host "Pulling latest code..."
    cd $Root
    git pull
}

function Start-All {
    Start-Collector
    Start-Sleep -Seconds 2

    Start-App
    Start-Sleep -Seconds 3

    Start-Tunnel
    Start-Sleep -Seconds 3

    Start-Persistence

    Write-Host "Start complete."
}

switch ($Action) {
    "start"       { Start-All }
    "stop"        { Stop-Processes }
    "kill"        { Stop-Processes }
    "update"      { Update-Code }
    "restart"     { Stop-Processes; Update-Code; Start-All }
    "app"         { Start-App }
    "tunnel"      { Start-Tunnel }
    "persistence" { Start-Persistence }
    "collector"   { Start-Collector }
}