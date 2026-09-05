# WARDOGS TOOLS — автозапуск бота при входе в Windows (Task Scheduler).
# Запуск от админа: powershell -ExecutionPolicy Bypass -File install_autostart.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path (Split-Path $MyInvocation.MyCommand.Path -Parent) -Parent
$bat = Join-Path $root "ops\run_bot.bat"
$task = "WARDOGS-TOOLS-Bot"
$action = New-ScheduledTaskAction -Execute $bat -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
try { Unregister-ScheduledTask -TaskName $task -Confirm:$false -ErrorAction SilentlyContinue } catch {}
Register-ScheduledTask -TaskName $task -Action $action -Trigger $trigger -Settings $settings -Description "WARDOGS TOOLS Discord bot (autorestart loop)" | Out-Null
Write-Output "OK: task '$task' installed -> $bat"
