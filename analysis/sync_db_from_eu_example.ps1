param(
    [string]$EuDbPath = "\\EU-SERVER-NAME\Roll\global\global_rolls.sqlite",
    [string]$LocalFolder = "C:\projects\roulette_dist\global_analysis"
)

$ErrorActionPreference = "Stop"

if (!(Test-Path $LocalFolder)) {
    New-Item -ItemType Directory -Path $LocalFolder | Out-Null
}

$LocalDb = Join-Path $LocalFolder "global_rolls.sqlite"

Write-Host "Copying SQLite DB from: $EuDbPath"
Write-Host "To: $LocalDb"

Copy-Item -Path $EuDbPath -Destination $LocalDb -Force

Write-Host "Done."
Write-Host "Run analysis with:"
Write-Host "python analyze_crossfire.py --db `"$LocalDb`" --config crossfire_all_strategies_config.json"
