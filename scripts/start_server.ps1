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

Start-Sleep -Seconds 3

if ($Config.cloudflare_tunnel_name -and $Config.cloudflare_config_path) {
    Write-Host "Starting Cloudflare tunnel: $($Config.cloudflare_tunnel_name)"

    Start-Process $Cloudflared `
        -ArgumentList "tunnel --protocol http2 --config `"$($Config.cloudflare_config_path)`" run $($Config.cloudflare_tunnel_name)" `
        -WorkingDirectory "$Root\cloudflare"

    Start-Sleep -Seconds 3
} else {
    Write-Host "Cloudflare tunnel skipped."
}

Write-Host "Starting session persistence..."

Start-Process $Python `
    -ArgumentList "$Root\app\session_persistence.py" `
    -WorkingDirectory $Root

Write-Host "Start complete."