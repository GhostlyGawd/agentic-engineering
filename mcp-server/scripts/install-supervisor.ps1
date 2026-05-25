# Register the agentic supervisor with Windows Task Scheduler so it starts at
# logon and is restarted if it dies. Run with -Print to see the action without
# registering anything.
param(
    [switch]$Print
)

$ErrorActionPreference = "Stop"

$taskName = "AgenticSupervisor"
$exe = (Get-Command "agentic-supervisor" -ErrorAction SilentlyContinue).Source
if (-not $exe) {
    Write-Host "agentic-supervisor not found on PATH. Install the package first:"
    Write-Host "  pip install -e mcp-server"
    if (-not $Print) { exit 1 }
    $exe = "agentic-supervisor"
}

$action = New-ScheduledTaskAction -Execute $exe
$atLogon = New-ScheduledTaskTrigger -AtLogOn
# Ensure-running heartbeat: re-trigger every 5 minutes (no-op if already up).
$ensure = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 5)
$settings = New-ScheduledTaskSettingsSet -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable

if ($Print) {
    Write-Host "Would register scheduled task '$taskName':"
    Write-Host "  Execute : $exe"
    Write-Host "  Triggers: AtLogOn + every 5 minutes ensure-running"
    Write-Host "  Settings: RestartCount=3, RestartInterval=1m, StartWhenAvailable"
    exit 0
}

Register-ScheduledTask -TaskName $taskName -Action $action `
    -Trigger @($atLogon, $ensure) -Settings $settings -Force
Write-Host "Registered scheduled task '$taskName'."
