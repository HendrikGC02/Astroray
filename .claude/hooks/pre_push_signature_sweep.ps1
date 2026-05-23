# pre_push_signature_sweep.ps1
#
# PreToolUse hook. Fires when Claude is about to `git push` or `gh pr create`.
# Computes function/class signatures that changed on this branch vs origin/main,
# then greps the repo for each name and surfaces call sites NOT touched on the
# branch — i.e. likely-stale callers that will break CI.
#
# Non-blocking: emits a warning on stderr (exit 0). The model sees the warning
# and decides whether to update the call sites before pushing.
#
# Implements the "list every changed function/class signature, grep the repo for
# each name, show call sites NOT updated" discipline from CLAUDE.md § Build &
# Verification, and the insights-report friction pattern of CI-rescue commits.

$ErrorActionPreference = 'Stop'

$raw = [Console]::In.ReadToEnd()
if (-not $raw) { exit 0 }

try { $payload = $raw | ConvertFrom-Json } catch { exit 0 }

$tool = [string]$payload.tool_name
if ($tool -ne 'Bash') { exit 0 }

$cmd = [string]$payload.tool_input.command
if (-not $cmd) { exit 0 }

# Only fire on git push or gh pr create.
$isPush  = $cmd -match '\bgit\s+push\b'
$isPrNew = $cmd -match '\bgh\s+pr\s+create\b'
if (-not ($isPush -or $isPrNew)) { exit 0 }

Set-Location $env:CLAUDE_PROJECT_DIR

# Determine the merge base with origin/main. If origin/main is unreachable, bail quietly.
$base = git merge-base HEAD origin/main 2>$null
if (-not $base) { exit 0 }

# Diff vs base, restrict to source files where signature changes matter.
$changedFiles = git diff --name-only $base..HEAD -- '*.py' '*.cpp' '*.hpp' '*.h' '*.cu' '*.cuh' 2>$null
if (-not $changedFiles) { exit 0 }

# Collect added/removed signature lines on this branch.
$diff = git diff -U0 $base..HEAD -- '*.py' '*.cpp' '*.hpp' '*.h' '*.cu' '*.cuh' 2>$null
if (-not $diff) { exit 0 }

# Regexes that catch the *name* part of a function/class/method signature.
# Python:  def foo(...  /  class Foo(...
# C++:     ReturnType  foo(...   /  class Foo  /  struct Foo
# We extract the bare identifier; the grep step finds call sites by name.
$names = New-Object System.Collections.Generic.HashSet[string]
foreach ($line in ($diff -split "`n")) {
    if ($line -notmatch '^[+-](?![+-])') { continue }   # only +/- lines, not +++/---
    $body = $line.Substring(1)

    # Python def/class
    if ($body -match '^\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(') {
        [void]$names.Add($Matches[1])
    } elseif ($body -match '^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\b') {
        [void]$names.Add($Matches[1])
    }
    # C++ class/struct
    elseif ($body -match '^\s*(?:template\s*<[^>]*>\s*)?(?:class|struct)\s+([A-Za-z_][A-Za-z0-9_]*)\b') {
        [void]$names.Add($Matches[1])
    }
    # C++ free / member function: crude — "Type  name(" near start of line
    elseif ($body -match '^\s*(?:[A-Za-z_][A-Za-z0-9_:<>\*\&\s]*\s)([A-Za-z_][A-Za-z0-9_]+)\s*\([^;]*\)\s*(?:const)?\s*(?:override)?\s*[{;]?\s*$') {
        $n = $Matches[1]
        # Skip obvious keywords / control flow
        if ($n -notin @('if','for','while','switch','return','sizeof','static_cast','reinterpret_cast','const_cast','dynamic_cast')) {
            [void]$names.Add($n)
        }
    }
}

if ($names.Count -eq 0) { exit 0 }

# For each touched name, grep the repo and see if any hit lives in a file NOT
# changed on this branch. Those are the likely-stale callers.
$changedSet = New-Object System.Collections.Generic.HashSet[string]
foreach ($f in $changedFiles) { [void]$changedSet.Add($f.Replace('/','\').ToLower()) }

$stale = @{}   # name -> list of file paths
foreach ($name in $names) {
    # Skip very short / very common names to avoid noise.
    if ($name.Length -lt 4) { continue }

    try {
        $hits = git grep -l -w --untracked -- $name 2>$null
    } catch { continue }
    if (-not $hits) { continue }

    foreach ($h in ($hits -split "`n")) {
        if (-not $h) { continue }
        $norm = $h.Replace('/','\').ToLower()
        if ($changedSet.Contains($norm)) { continue }
        # Skip build artifacts and vendored dirs
        if ($norm -match '\\(build|build_cuda|build_tcnn|node_modules|\.git|__pycache__|dist|out)\\') { continue }
        if (-not $stale.ContainsKey($name)) { $stale[$name] = New-Object System.Collections.Generic.List[string] }
        if (-not $stale[$name].Contains($h)) { $stale[$name].Add($h) }
    }
}

if ($stale.Count -eq 0) { exit 0 }

[Console]::Error.WriteLine("[signature-sweep] $($stale.Count) changed name(s) have call sites in files NOT touched on this branch — likely-stale callers:")
foreach ($k in ($stale.Keys | Sort-Object)) {
    [Console]::Error.WriteLine("  $k :")
    foreach ($f in ($stale[$k] | Select-Object -First 8)) {
        [Console]::Error.WriteLine("    $f")
    }
    if ($stale[$k].Count -gt 8) {
        [Console]::Error.WriteLine("    ... ($($stale[$k].Count - 8) more)")
    }
}
[Console]::Error.WriteLine("[signature-sweep] Verify each is genuinely unaffected before pushing — this is the CI-rescue pattern the insights report flagged.")

exit 0
