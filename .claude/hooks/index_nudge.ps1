# index_nudge.ps1
#
# PreToolUse hook (Grep | Glob | Bash). Owner directive 2026-09-22: the project
# index (scripts/project_index.py) is under-used; agents grep .astroray_plan/
# and scripts/ blind and waste tokens on things the SQLite index answers in one
# line. This hook NUDGES (non-blocking, exit 0 + stderr) at most 3 times per
# session when a Grep/Glob targets .astroray_plan/, scripts/, or a pkgNNN
# pattern, and goes quiet for the session once any Bash command runs
# project_index.py.
#
# Hook protocol: JSON on stdin (.tool_name / .tool_input / .session_id).
# Exit 0 = allow; stderr on exit 0 is surfaced as a non-blocking warning.

$ErrorActionPreference = 'Stop'
$raw = [Console]::In.ReadToEnd()
if (-not $raw) { exit 0 }
try { $payload = $raw | ConvertFrom-Json } catch { exit 0 }

$tool = [string]$payload.tool_name
$ti   = $payload.tool_input
$sid  = [string]$payload.session_id
if (-not $sid) { $sid = 'nosession' }
$state = Join-Path $env:TEMP ("astroray_index_nudge_" + $sid + ".txt")

if ($tool -eq 'Bash') {
    $cmd = [string]$ti.command
    if ($cmd -and $cmd -match 'project_index\.py') { Set-Content -Path $state -Value 'used' }
    exit 0
}
if ($tool -notin @('Grep', 'Glob')) { exit 0 }

$target = ([string]$ti.path) + ' ' + ([string]$ti.pattern) + ' ' + ([string]$ti.glob)
$hit = ($target -match 'astroray_plan') -or ($target -match '(^|[\/ ])scripts([\/ ]|$)') -or ($target -match 'pkg\d{2,3}')
if (-not $hit) { exit 0 }

$count = 0
if (Test-Path $state) {
    $v = (Get-Content -Path $state -Raw).Trim()
    if ($v -eq 'used') { exit 0 }
    [int]::TryParse($v, [ref]$count) | Out-Null
}
if ($count -ge 3) { exit 0 }
Set-Content -Path $state -Value ([string]($count + 1))

[Console]::Error.WriteLine("[index-nudge] Use the project index before grepping .astroray_plan/ or scripts/ (owner 2026-09-22):")
[Console]::Error.WriteLine("  python scripts/project_index.py query <term>   # packages/docs/tests by title, body, file path")
[Console]::Error.WriteLine("  python scripts/project_index.py owns <path>    # which package owns a file, what landed")
[Console]::Error.WriteLine("  python scripts/project_index.py whatis pkgNNN  # one-card summary; deps pkgNNN for dependencies")
[Console]::Error.WriteLine("  python scripts/project_index.py script <task>  # canonical script for a task (scripts/README.md)")
[Console]::Error.WriteLine("  Any project_index.py call silences this nudge for the session.")
exit 0
