$ErrorActionPreference = "Stop"

$Root = if ($env:ROLL_ROOT) { $env:ROLL_ROOT } else { "C:\Roll" }
$Python = "$Root\python-embed\App\Python\python.exe"
$Cloudflared = "$Root\cloudflare\cloudflared.exe"
$ConfigPath = "$Root\config\config.local.json"

Write-Host "Loading config from $ConfigPath"
$Config = Get-Content $ConfigPath -Raw | ConvertFrom-Json

$TunnelName = $Config.cloudflare_tunnel_name
$CloudflareConfigPath = $Config.cloudflare_config_path

Write-Host "Server: $($Config.server_name)"
Write-Host "Tunnel: $TunnelName"
Write-Host "Cloudflare config: $CloudflareConfigPath"

cd $Root

Write-Host "Pulling latest code..."
git pull

Write-Host "Stopping existing processes..."
taskkill /IM python.exe /F 2>$null
taskkill /IM cloudflared.exe /F 2>$null

Start-Sleep -Seconds 3

Write-Host "Starting Flask app..."
Start-Process $Python -ArgumentList "$Root\app\app.py" -WorkingDirectory $Root

Start-Sleep -Seconds 3

Write-Host "Starting Cloudflare tunnel..."
Start-Process $Cloudflared -ArgumentList "tunnel --config `"$CloudflareConfigPath`" run $TunnelName" -WorkingDirectory "$Root\cloudflare"

Start-Sleep -Seconds 3

Write-Host "Starting session persistence..."
Start-Process $Python -ArgumentList "$Root\app\session_persistence.py" -WorkingDirectory $Root

Write-Host "Update and restart complete."