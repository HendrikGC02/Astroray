#!/usr/bin/env pwsh
# PreToolUse hook: block git commits that contain diagnostic markers

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
# two shapes are kept as fallbacks for parity with the sibling spec-lint hook.
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

# Check staged changes for diagnostic markers
Set-Location $repoPath

$markerPatterns = @(
    '\[pkg\d+-diag\]',
    'REMOVE AFTER',
    'XXX DEBUG',
    'printf.*pkg.*diag',
    '// \[diag\]'
)

# Scan staged AND unstaged changes: a combined "git add ... && git commit"
# stages the files after this hook runs, so --cached alone misses them.
$diff = @(git diff --cached 2>$null) + @(git diff 2>$null)
if (-not $diff) {
    exit 0
}

$offendingLines = @()
foreach ($pattern in $markerPatterns) {
    $found = $diff | Select-String -Pattern $pattern
    if ($found) {
        $offendingLines += $found | ForEach-Object { $_.Line.Trim() }
    }
}

if ($offendingLines.Count -gt 0) {
    # Hook protocol: only exit 2 + stderr blocks a PreToolUse call.
    [Console]::Error.WriteLine("BLOCKED: Diagnostic markers found in staged/unstaged changes:")
    $offendingLines | Select-Object -Unique | ForEach-Object {
        [Console]::Error.WriteLine("  $_")
    }
    [Console]::Error.WriteLine("Remove all [pkg##-diag] markers and 'REMOVE AFTER' comments before committing.")
    exit 2
}

exit 0
