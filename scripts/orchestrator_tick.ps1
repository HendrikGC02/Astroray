<#
  orchestrator_tick.ps1 -- robust launcher for the Astroray-RoadmapOrchestrator
  scheduled task. Supports both CLI drivers via -Driver.

  WHY a wrapper: Task Scheduler launches with a stale/narrow PATH and lacks
  the interactive shell's env, which aborts the CLI before it logs (originally
  diagnosed for `claude.exe -p /roadmap-orchestrator ...`, which returned exit
  129 every run (46x) with no log; manual launches of the exact same command
  in the interactive session succeeded, 2026-08-08). This wrapper (1) pins a
  known-good environment + PATH, (2) cds to the repo, (3) captures FULL
  stdout/stderr + diagnostics to a timestamped log, then (4) runs one tick
  via the selected driver.

  Wire the task to:
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<repo>\scripts\orchestrator_tick.ps1" -Driver claude
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<repo>\scripts\orchestrator_tick.ps1" -Driver opencode

  -DryRun (opencode driver only) runs the roadmap-orchestrator skill with
  --dry-run (zero side effects: no lock, no dispatch, no merge, no write).
#>
param(
    [ValidateSet('claude', 'opencode')]
    [string]$Driver = 'claude',
    [switch]$DryRun
)

$ErrorActionPreference = 'Continue'
$Repo   = 'C:\Users\hgcom\OneDrive\Astroray\Astroray_repo\Astroray'
$LogDir = Join-Path $Repo '.astroray_plan\logs'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
# Timestamp is passed by the OS clock; safe in a real shell (not the sandbox).
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$Log   = Join-Path $LogDir "orchestrator-$Driver-$stamp.log"

# --- pin the environment the interactive session has and the task may lack ---
# Rebuild PATH from the machine + user registry values (Task Scheduler can
# launch with a stale/narrow PATH), then prepend the user bin dir (claude.exe,
# uv, uvx live there).
$machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
$userPath    = [Environment]::GetEnvironmentVariable('Path', 'User')
$env:Path = "C:\Users\hgcom\.local\bin;$userPath;$machinePath"

Set-Location $Repo

if ($Driver -eq 'claude') {
    $Claude = 'C:\Users\hgcom\.local\bin\claude.exe'

    "=== orchestrator_tick $stamp driver=claude ===" | Out-File $Log
    "cwd=$(Get-Location)"                             | Out-File $Log -Append
    "claude=$Claude  exists=$(Test-Path $Claude)"     | Out-File $Log -Append
    "PATH=$env:Path"                                  | Out-File $Log -Append
    # Prove the CLI is reachable/launchable in THIS environment before the tick.
    (& $Claude --version 2>&1)                        | Out-File $Log -Append
    "=== tick start ==="                              | Out-File $Log -Append

    # Run the tick; full output (all streams) to the log. PowerShell has no `<`
    # input redirection ("reserved for future use"), so stdin is left as the
    # task's default (verified 2026-08-08 not to be the exit-129 cause).
    & $Claude -p '/roadmap-orchestrator' --model claude-sonnet-5 --dangerously-skip-permissions `
        *>> $Log
    $code = $LASTEXITCODE
} else {
    $Opencode = 'C:\Users\hgcom\AppData\Roaming\npm\opencode.cmd'
    if (-not (Test-Path $Opencode)) { $Opencode = (Get-Command opencode.cmd -ErrorAction SilentlyContinue).Source }
    if (-not $Opencode) { Write-Error 'opencode not found on PATH'; exit 1 }
    $Model = 'opencode-go/deepseek-v4-pro'

    # Background subagents: let the orchestrator dispatch implementers without
    # blocking the tick (otherwise each dispatch tick waits 30-60 min on the
    # implementer and the 10-min cadence collapses). Experimental flag.
    $env:OPENCODE_EXPERIMENTAL_BACKGROUND_SUBAGENTS = "true"

    if ($DryRun) {
        $Prompt = 'Load the roadmap-orchestrator skill and execute one tick in --dry-run mode (zero side effects: no lock, no dispatch, no merge, no write), following its SKILL.md.'
    } else {
        $Prompt = 'Load the roadmap-orchestrator skill and execute exactly one bounded tick, following its SKILL.md steps end to end.'
    }

    "=== orchestrator_tick $stamp driver=opencode dryrun=$DryRun ===" | Out-File $Log -Encoding utf8
    "cwd=$(Get-Location)"                                             | Out-File $Log -Append -Encoding utf8
    "opencode=$Opencode exists=$(Test-Path $Opencode)"                | Out-File $Log -Append -Encoding utf8
    "=== tick start ==="                                              | Out-File $Log -Append -Encoding utf8

    & $Opencode run -m $Model $Prompt *>> $Log
    $code = $LASTEXITCODE
}

"=== tick end exit=$code ===" | Out-File $Log -Append
exit $code
