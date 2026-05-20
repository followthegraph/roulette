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
        "kill_processes",
        "json_status",
        "restart_all_clean"
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

function Get-RollJsonStatus {
    $root = "C:\Roll"

    $configPath = Join-Path $root "config\config.local.json"
    $config = Get-Content $configPath -Raw | ConvertFrom-Json

    $serverName = $config.server_name
    $wheelId = $config.wheel_id
    $port = $config.flask_port
    $collectorExpected = $config.run_global_collector -eq $true

    $procs = Get-CimInstance Win32_Process | Where-Object {
        $_.Name -in @(
            "python.exe",
            "cloudflared.exe",
            "chrome.exe",
            "chromium.exe",
            "msedge.exe"
        )
    }

    $appProc = $procs | Where-Object {
        $_.CommandLine -match "app\.py"
    }

    $persistenceProc = $procs | Where-Object {
        $_.CommandLine -match "session_persistence"
    }

    $collectorProc = $procs | Where-Object {
        $_.CommandLine -match "collector\.py"
    }

    $tunnelProc = $procs | Where-Object {
        $_.Name -eq "cloudflared.exe"
    }

    $browserProc = $procs | Where-Object {
        $_.Name -in @("chrome.exe", "chromium.exe", "msedge.exe")
    }

    $healthOk = $false
    $health = $null

    try {
        $health = Invoke-RestMethod "http://127.0.0.1:$port/health" -TimeoutSec 3
        $healthOk = $health.status -eq "ok"
    } catch {}

    [pscustomobject]@{
        server_name = $serverName
        wheel_id = $wheelId
        port = $port
        checked_at = (Get-Date).ToString("s")

        app = @{
            running = [bool]$appProc
            count = @($appProc).Count
        }

        tunnel = @{
            running = [bool]$tunnelProc
            count = @($tunnelProc).Count
        }

        persistence = @{
            running = [bool]$persistenceProc
            count = @($persistenceProc).Count
        }

        browser = @{
            running = [bool]$browserProc
            count = @($browserProc).Count
        }

        collector = @{
            expected = $collectorExpected
            running = [bool]$collectorProc
            count = @($collectorProc).Count
        }

        health = @{
            ok = $healthOk
            raw = $health
        }
    } | ConvertTo-Json -Depth 10
}

function Stop-App {
    Get-CimInstance Win32_Process |
        Where-Object { $_.Name -eq "python.exe" -and $_.CommandLine -match "app\.py" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

function Stop-Tunnel {
    Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force
}

function Stop-Persistence {
    Get-CimInstance Win32_Process |
        Where-Object { $_.Name -eq "python.exe" -and $_.CommandLine -match "session_persistence" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

function Stop-Collector {
    Get-CimInstance Win32_Process |
        Where-Object { $_.Name -eq "python.exe" -and $_.CommandLine -match "collector\.py" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

function Stop-Browser {
    Get-Process chrome, chromium, msedge -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue
}

function Start-Persistence {
    Start-Process -FilePath $Python -ArgumentList "$Root\app\session_persistence.py" -WorkingDirectory $Root
}

function Start-Collector {
    $Config = Get-Content $ConfigPath -Raw | ConvertFrom-Json

    if ($Config.run_global_collector -eq $true) {
        Start-Process -FilePath $Python -ArgumentList "$Root\global\collector.py" -WorkingDirectory "$Root\global"
    }
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

    "json_status" {
        Get-RollJsonStatus
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
        Stop-Persistence
        Stop-Collector
        Stop-App
        Stop-Tunnel
        Stop-Browser

        Start-Sleep -Seconds 3

        powershell.exe -ExecutionPolicy Bypass -File "C:\Roll\scripts\roulette.ps1" start

        Write-Host "Restarted all services."
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

    "restart_all_clean" {
        Stop-Persistence
        Stop-Collector
        Stop-App
        Stop-Tunnel
        Stop-Browser

        Start-Sleep -Seconds 3

        Start-ScheduledTask -TaskName "RouletteStart"

        Write-Host "Clean restart task triggered."
    }
}