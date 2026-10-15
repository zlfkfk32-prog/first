# Run manually only after Microsoft 365 app permission and local .env are ready.
# Registers a task for the current Windows user. The PC must be on and logged in.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
$runFile = Join-Path $projectRoot 'run.py'
if (-not (Test-Path $pythonExe)) { throw 'Create .venv and install requirements first.' }
if (-not (Test-Path (Join-Path $projectRoot '.env'))) { throw 'Configure .env before scheduling.' }
$action = New-ScheduledTaskAction -Execute $pythonExe -Argument ('"' + $runFile + '" --send-email') -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -Daily -At '08:00'
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName 'RealEstateDailyNews' -Action $action -Trigger $trigger -Settings $settings -Description 'Generate real estate daily news and submit mail to Microsoft 365; local timezone applies.'
Write-Output 'Task registered for 08:00 local Windows time. Use Asia/Seoul timezone. The PC must remain available.'
