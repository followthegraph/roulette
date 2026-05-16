param(
    [Parameter(Mandatory=$true)]
    [ValidateSet(
        "status",
        "start_app",
        "stop_app",
        "restart_app",
        "start_tunnel",
        "stop_tunnel",
        "restart_tunnel",
        "restart_all",
        "update",
        "update_and_restart",
        "kill_processes"
    )]
    [string]$Action
)

$ErrorActionPreference = "Stop"

$Root = if ($env:ROLL_ROOT) { $env:ROLL_ROOT } else { "C:\Roll" }
$Python = "$Root\python-embed\App\Python\python.exe"
$Cloudflared = "$Root\cloudflare\cloudflared.exe"
$ConfigPath = "$Root\config\config.local.json"
$Scripts = "$Root\scripts"

function Show-Status {
    Write-Host "=== Roll Status ==="
    Write-Host "Root: $Root"

    Write-Host "`nPython:"
    Get-Process python -ErrorAction SilentlyContinue | Select-Object Id, ProcessName, StartTime

    Write-Host "`nCloudflared:"
    Get-Process cloudflared -ErrorAction SilentlyContinue | Select-Object Id, ProcessName, StartTime

    Write-Host "`nLocal health:"
    try {
        $Config = Get-Content $ConfigPath -Raw | ConvertFrom-Json
        $Port = $Config.flask_port
        Invoke-RestMethod "http://127.0.0.1:$Port/health" -TimeoutSec 5 | ConvertTo-Json -Depth 5
    } catch {
        Write-Host "Health check failed: $($_.Exception.Message)"
    }
}

function Stop-App {
    Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
}

function Stop-Tunnel {
    Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force
}

function Start-App {
    Start-Process -FilePath $Python -ArgumentList "$Root\app\app.py" -WorkingDirectory $Root
}

function Start-Tunnel {
    $Config = Get-Content $ConfigPath -Raw | ConvertFrom-Json
    $TunnelConfig = $Config.cloudflare_config_path

    Start-Process -FilePath $Cloudflared -ArgumentList "tunnel --config `"$TunnelConfig`" run" -WorkingDirectory $Root
}

switch ($Action) {
    "status" {
        Show-Status
    }

    "stop_app" {
        Stop-App
        Write-Host "Stopped app."
    }

    "start_app" {
        Start-App
        Write-Host "Started app."
    }

    "restart_app" {
        Stop-App
        Start-Sleep -Seconds 2
        Start-App
        Write-Host "Restarted app."
    }

    "stop_tunnel" {
        Stop-Tunnel
        Write-Host "Stopped tunnel."
    }

    "start_tunnel" {
        Start-Tunnel
        Write-Host "Started tunnel."
    }

    "restart_tunnel" {
        Stop-Tunnel
        Start-Sleep -Seconds 2
        Start-Tunnel
        Write-Host "Restarted tunnel."
    }

    "restart_all" {
        Stop-App
        Stop-Tunnel
        Start-Sleep -Seconds 2
        Start-App
        Start-Sleep -Seconds 2
        Start-Tunnel
        Write-Host "Restarted app and tunnel."
    }

    "update" {
        Push-Location $Root
        git pull
        Pop-Location
        Write-Host "Updated repo."
    }

    "update_and_restart" {
        Push-Location $Root
        git pull
        Pop-Location
        Stop-App
        Stop-Tunnel
        Start-Sleep -Seconds 2
        Start-App
        Start-Sleep -Seconds 2
        Start-Tunnel
        Write-Host "Updated and restarted app/tunnel."
    }

    "kill_processes" {
        Stop-App
        Stop-Tunnel
        Get-Process chrome -ErrorAction SilentlyContinue | Stop-Process -Force
        Write-Host "Killed python, cloudflared, and chrome."
    }
}