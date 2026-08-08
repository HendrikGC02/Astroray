<#
  orchestrator_tick.ps1 -- robust launcher for the Astroray-RoadmapOrchestrator
  scheduled task.

  WHY: the task invoked `claude.exe -p /roadmap-orchestrator ...` DIRECTLY and
  returned exit 129 every run (46x), writing no log. Manual launches of the
  exact same command in the interactive session succeed (verified 2026-08-08,
  with and without --dangerously-skip-permissions, with and without stdin), so
  the failure is the Task Scheduler launch ENVIRONMENT, not the command --
  almost certainly a PATH/env entry present in the interactive shell but absent
  from the task's captured environment, aborting claude/Node before it logs.

  This wrapper (1) pins a known-good environment + PATH, (2) cds to the repo,
  (3) captures FULL stdout/stderr + diagnostics to a timestamped log so any
  residual failure is finally visible, then (4) runs the tick.

  Wire the task to:
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<repo>\scripts\orchestrator_tick.ps1"
#>
$ErrorActionPreference = 'Continue'
$Repo   = 'C:\Users\hgcom\OneDrive\Astroray\Astroray_repo\Astroray'
$Claude = 'C:\Users\hgcom\.local\bin\claude.exe'
$LogDir = Join-Path $Repo '.astroray_plan\logs'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
# Timestamp is passed by the OS clock; safe in a real shell (not the sandbox).
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$Log   = Join-Path $LogDir "orchestrator-$stamp.log"

# --- pin the environment the interactive session has and the task may lack ---
# Rebuild PATH from the machine + user registry values (Task Scheduler can
# launch with a stale/narrow PATH), then prepend the claude bin dir.
$machinePath = [Environment]::GetEnvironmentVariable('Path','Machine')
$userPath    = [Environment]::GetEnvironmentVariable('Path','User')
$env:Path = "C:\Users\hgcom\.local\bin;$userPath;$machinePath"

Set-Location $Repo

"=== orchestrator_tick $stamp ==="                     | Out-File $Log
"cwd=$(Get-Location)"                                   | Out-File $Log -Append
"claude=$Claude  exists=$(Test-Path $Claude)"          | Out-File $Log -Append
"PATH=$env:Path"                                        | Out-File $Log -Append
# Prove the CLI is reachable/launchable in THIS environment before the tick.
(& $Claude --version 2>&1)                              | Out-File $Log -Append
"=== tick start ==="                                    | Out-File $Log -Append

# Run the tick; full output (all streams) to the log. PowerShell has no `<`
# input redirection ("reserved for future use"), so stdin is left as the task's
# default (verified 2026-08-08 not to be the exit-129 cause).
& $Claude -p '/roadmap-orchestrator' --model claude-sonnet-5 --dangerously-skip-permissions `
    *>> $Log
$code = $LASTEXITCODE

"=== tick end exit=$code ===" | Out-File $Log -Append
exit $code
