$TaskUser = "bp\bp"
$Root = "C:\Roll"
$Scripts = "$Root\scripts"
$Roulette = "$Scripts\roulette.ps1"

$Tasks = @{
    "RouletteStartApp"         = "app"
    "RouletteStartTunnel"      = "tunnel"
    "RouletteStartPersistence" = "persistence"
    "RouletteStartCollector"   = "collector"
    "RouletteStartAll"         = "start"
}

foreach ($task in $Tasks.GetEnumerator()) {
    $taskName = $task.Key
    $actionArg = $task.Value

    $Action = New-ScheduledTaskAction `
        -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Roulette`" $actionArg"

    $Trigger = New-ScheduledTaskTrigger -Once -At "12:00AM"

    Register-ScheduledTask `
        -TaskName $taskName `
        -Action $Action `
        -Trigger $Trigger `
        -User $TaskUser `
        -RunLevel Highest `
        -Force

    Write-Host "Created/updated task: $taskName -> roulette.ps1 $actionArg"
}