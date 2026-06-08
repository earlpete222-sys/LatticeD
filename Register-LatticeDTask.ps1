#Requires -Version 5.1
<#
.SYNOPSIS
    Register-LatticeDTask.ps1 - Register LatticeD as a Windows scheduled task

.DESCRIPTION
    Creates a Task Scheduler entry that launches LatticeD automatically
    when you log in. Runs in watchdog mode so it auto-restarts on crash.

    To remove the task later:
        Unregister-ScheduledTask -TaskName "LatticeD" -Confirm:$false

.NOTES
    Run this script ONCE to register. After that, LatticeD starts automatically at login.
#>

$TaskName   = "LatticeD"
# Path resolution: $env:LATTICED_HOME if set, otherwise this script's own folder
$LATTICED_ROOT = if ($env:LATTICED_HOME) { $env:LATTICED_HOME } else { $PSScriptRoot }
$ScriptPath = Join-Path $LATTICED_ROOT "Start-LatticeD.ps1"
$WorkDir    = Join-Path $LATTICED_ROOT "latticed"
$PwshExe    = (Get-Command pwsh -ErrorAction SilentlyContinue)?.Source
if (-not $PwshExe) { $PwshExe = "powershell.exe" }   # fall back to Windows PowerShell 5.1

# Remove existing task if present
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed existing task: $TaskName"
}

$action  = New-ScheduledTaskAction `
    -Execute $PwshExe `
    -Argument "-NonInteractive -WindowStyle Hidden -File `"$ScriptPath`" -Watch" `
    -WorkingDirectory $WorkDir

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable `
    -DontStopOnIdleEnd

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action   $action `
    -Trigger  $trigger `
    -Settings $settings `
    -RunLevel Highest `
    -Description "LatticeD AI Agent — auto-start with Ollama parallel inference" | Out-Null

Write-Host "`nTask registered: '$TaskName'" -ForegroundColor Green
Write-Host "LatticeD will now start automatically at login."
Write-Host "`nTo start it manually right now:"
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'" -ForegroundColor Cyan
Write-Host "`nTo remove the task:"
Write-Host "  Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false" -ForegroundColor Cyan
