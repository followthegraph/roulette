$ErrorActionPreference = "Stop"

$Root = if ($env:ROLL_ROOT) { $env:ROLL_ROOT } else { "C:\Roll" }
$Python = "$Root\python-embed\App\Python\python.exe"
$Cloudflared = "$Root\cloudflare\cloudflared.exe"
$ConfigPath = "$Root\config\config.local.json"

$Config = Get-Content $ConfigPath -Raw | ConvertFrom-Json

if ($Config.cloudflare_tunnel_name -and $Config.cloudflare_config_path) {
    Write-Host "Starting Cloudflare tunnel: $($Config.cloudflare_tunnel_name)"

    Start-Process $Cloudflared `
        -ArgumentList "tunnel --protocol http2 --config `"$($Config.cloudflare_config_path)`" run $($Config.cloudflare_tunnel_name)" `
        -WorkingDirectory "$Root\cloudflare"

    Start-Sleep -Seconds 3
} else {
    Write-Host "Cloudflare tunnel skipped."
}