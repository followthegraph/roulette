$ErrorActionPreference = "Stop"

$Root = if ($env:ROLL_ROOT) { $env:ROLL_ROOT } else { "C:\Roll" }

Write-Host "Updating repo..."

cd $Root
git pull

Write-Host "Update complete."