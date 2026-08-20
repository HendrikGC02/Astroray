<#
  orchestrator_tick_opencode.ps1 -- opencode launcher for the
  Astroray-RoadmapOrchestrator scheduled task (opencode is now the primary driver).

  WHY a wrapper (same reason as orchestrator_tick.ps1 for claude): Task Scheduler
  launches with a stale/narrow PATH and lacks the interactive shell's env, which
  aborts the CLI before it logs. This wrapper (1) pins a known-good env + PATH,
  (2) cds to the repo, (3) captures FULL output to a timestamped log, then
  (4) runs one roadmap-orchestrator tick via `opencode run`.

  Wire the task to:
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<repo>\scripts\orchestrator_tick_opencode.ps1"
  Pass -DryRun to run the roadmap-orchestrator skill with --dry-run (zero side effects).
#>
param([switch]$DryRun)

$ErrorActionPreference = 'Continue'
$Repo     = 'C:\Users\hgcom\OneDrive\Astroray\Astroray_repo\Astroray'
$Opencode = 'C:\Users\hgcom\AppData\Roaming\npm\opencode.cmd'
if (-not (Test-Path $Opencode)) { $Opencode = (Get-Command opencode.cmd -ErrorAction SilentlyContinue).Source }
if (-not $Opencode) { Write-Error 'opencode not found on PATH'; exit 1 }
$Model   = 'opencode-go/deepseek-v4-pro'
$LogDir  = Join-Path $Repo '.astroray_plan\logs'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$Log   = Join-Path $LogDir "orchestrator-opencode-$stamp.log"

# Rebuild PATH from machine + user registry (Task Scheduler can launch with a
# stale/narrow PATH), then prepend the user bin dir (claude.exe, uv, uvx live there).
$machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
$userPath    = [Environment]::GetEnvironmentVariable('Path', 'User')
$env:Path = "C:\Users\hgcom\.local\bin;$userPath;$machinePath"

Set-Location $Repo

if ($DryRun) {
    $Prompt = 'Load the roadmap-orchestrator skill and execute one tick in --dry-run mode (zero side effects: no lock, no dispatch, no merge, no write), following its SKILL.md.'
} else {
    $Prompt = 'Load the roadmap-orchestrator skill and execute exactly one bounded tick, following its SKILL.md steps end to end.'
}

"=== orchestrator_tick_opencode $stamp dryrun=$DryRun ===" | Out-File $Log -Encoding utf8
"cwd=$(Get-Location)"                                      | Out-File $Log -Append -Encoding utf8
"opencode=$Opencode exists=$(Test-Path $Opencode)"         | Out-File $Log -Append -Encoding utf8
"=== tick start ==="                                       | Out-File $Log -Append -Encoding utf8

& $Opencode run -m $Model $Prompt *>> $Log
$code = $LASTEXITCODE

"=== tick end exit=$code ===" | Out-File $Log -Append -Encoding utf8
exit $code
