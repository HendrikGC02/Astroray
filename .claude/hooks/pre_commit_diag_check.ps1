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

# Only act on Bash tool calls that invoke git commit
$command = ""
if ($inputJson -and $inputJson.command) {
    $command = $inputJson.command
} elseif ($inputJson -and $inputJson.input -and $inputJson.input.command) {
    $command = $inputJson.input.command
}

if ($command -notmatch "git\s+commit") {
    exit 0
}

# Check staged changes for diagnostic markers
Set-Location $env:CLAUDE_PROJECT_DIR

$markerPatterns = @(
    '\[pkg\d+-diag\]',
    'REMOVE AFTER',
    'XXX DEBUG',
    'printf.*pkg.*diag',
    '// \[diag\]'
)

$diff = git diff --cached 2>$null
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
    Write-Host "BLOCKED: Diagnostic markers found in staged changes:" -ForegroundColor Red
    $offendingLines | Select-Object -Unique | ForEach-Object {
        Write-Host "  $_" -ForegroundColor Yellow
    }
    Write-Host "Remove all [pkg##-diag] markers and 'REMOVE AFTER' comments before committing." -ForegroundColor Red
    exit 1
}

exit 0
