#!/usr/bin/env pwsh
# PreToolUse hook: lint staged/unstaged package specs against TEMPLATE v2
# before a git commit is allowed to proceed.

# Read the tool input JSON from stdin to check if this is a git commit call
$inputJson = $null
try {
    $rawInput = [Console]::In.ReadToEnd()
    if ($rawInput) {
        $inputJson = $rawInput | ConvertFrom-Json -ErrorAction SilentlyContinue
    }
} catch {}

# Only act on Bash tool calls that invoke git commit. The current
# PreToolUse payload nests the command at .tool_input.command; the other
# two shapes are kept for parity with the sibling diag-check hook.
$command = ""
if ($inputJson -and $inputJson.tool_input -and $inputJson.tool_input.command) {
    $command = $inputJson.tool_input.command
} elseif ($inputJson -and $inputJson.command) {
    $command = $inputJson.command
} elseif ($inputJson -and $inputJson.input -and $inputJson.input.command) {
    $command = $inputJson.input.command
}

if ($command -notmatch "git\s+(-C\s+(?:'[^']*'|`"[^`"]*`"|\S+)\s+)?commit\b") {
    exit 0
}

# Resolve which repo checkout to check: a `git -C <path>` or `cd <path> &&`
# commit may target a linked worktree, not the main checkout.
. "$PSScriptRoot\_resolve_repo.ps1"
$repoPath = Resolve-HookRepoPath -Command $command -PayloadCwd $inputJson.cwd

Set-Location $repoPath

# Collect staged AND unstaged package-spec paths: a combined "git add ... &&
# git commit" stages files after this hook runs, so --cached alone misses
# them. TEMPLATE.md itself is not linted.
$staged = @(git diff --cached --name-only 2>$null)
$unstaged = @(git diff --name-only 2>$null)
# @(...) around the whole pipeline is load-bearing: PowerShell collapses a
# single-match pipeline result to a scalar string, and splatting a scalar
# string with "@specs" below would explode it into one argument per
# character instead of passing it as one path.
$specs = @(
    @($staged + $unstaged) |
        Where-Object { $_ -like ".astroray_plan/packages/*.md" -and $_ -notlike "*TEMPLATE.md" } |
        Sort-Object -Unique |
        Where-Object { Test-Path $_ }
)

if ($specs.Count -eq 0) {
    exit 0
}

$lintOutput = & python scripts/project_index.py lint @specs 2>&1
$exitCode = $LASTEXITCODE

if ($exitCode -ne 0) {
    # Hook protocol: only exit 2 + stderr blocks a PreToolUse call.
    [Console]::Error.WriteLine("BLOCKED: package spec lint failed")
    $lintOutput | ForEach-Object { [Console]::Error.WriteLine($_) }
    [Console]::Error.WriteLine("Fix the findings above, or add the file to scripts/spec_lint_baseline.txt only if it is a pre-existing legacy spec.")
    exit 2
}

exit 0
