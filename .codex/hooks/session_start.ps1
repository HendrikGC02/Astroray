#!/usr/bin/env pwsh
# Concise Codex session context. This hook never fetches or mutates git state.

$ErrorActionPreference = 'Stop'

try {
    $repo = (git rev-parse --show-toplevel 2>$null).Trim()
    if (-not $repo) { exit 0 }
    Set-Location -LiteralPath $repo
    $branch = (git branch --show-current 2>$null).Trim()
    $head = (git rev-parse --short HEAD 2>$null).Trim()
    $status = @(git status --short 2>$null)
    $state = if ($status.Count) { "$($status.Count) changed file(s): " + ($status -join '; ') } else { 'working tree clean' }

    $pyd = Get-ChildItem -LiteralPath $repo -Recurse -Filter 'astroray*.pyd' -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match '[\\/](build|build_cuda|build_tcnn)[\\/]' } |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    $pydNote = 'no module build found'
    if ($pyd) {
        $headEpoch = (git log -1 --format=%ct HEAD 2>$null).Trim()
        $headTime = [DateTimeOffset]::FromUnixTimeSeconds([long]$headEpoch).LocalDateTime
        $pydNote = if ($pyd.LastWriteTime -lt $headTime) { 'WARNING: newest module build predates HEAD' } else { 'module build is newer than HEAD' }
    }

    $context = "Astroray: branch=$branch head=$head; $state; $pydNote. Before work, use STATUS.md, NEXT_STAGE_REPORT.md, ROADMAP.md, and scripts/project_index.py."
    @{ hookSpecificOutput = @{ hookEventName = 'SessionStart'; additionalContext = $context } } | ConvertTo-Json -Compress
} catch {
    exit 0
}
