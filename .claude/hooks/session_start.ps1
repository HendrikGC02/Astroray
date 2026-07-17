#!/usr/bin/env pwsh
# SessionStart hook: surface git + PR state, warn on stale .pyd

Set-Location $env:CLAUDE_PROJECT_DIR

Write-Host "=== Astroray session start ===" -ForegroundColor Cyan

# Git state
git fetch --quiet 2>$null
$status = git status --short
if ($status) {
    Write-Host "Git status:" -ForegroundColor Yellow
    Write-Host $status
} else {
    Write-Host "Working tree clean." -ForegroundColor Green
}

# Open PRs
Write-Host "`nOpen PRs:" -ForegroundColor Cyan
gh pr list --state open --limit 10 2>$null

# Stale .pyd check — every dir the test harness can load a pyd from
# (mirror runtime_setup.candidate_build_dirs)
$pydCandidates = @(
    "build_cuda\Release\astroray.cp*.pyd",
    "build_cuda\astroray.cp*.pyd",
    "build_tcnn\Release\astroray.cp*.pyd",
    "build_tcnn\astroray.cp*.pyd",
    "build\astroray.cp*.pyd",
    "build\Release\astroray.cp*.pyd"
)

$latestSrc = $null
foreach ($pattern in $pydCandidates) {
    $matches = Get-ChildItem -Path (Join-Path $env:CLAUDE_PROJECT_DIR $pattern) -ErrorAction SilentlyContinue
    if ($matches) {
        $candidate = $matches | Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($null -eq $latestSrc -or $candidate.LastWriteTime -gt $latestSrc.LastWriteTime) {
            $latestSrc = $candidate
        }
    }
}

if ($latestSrc) {
    # The CLAUDE.md rule: a pyd older than HEAD's commit time is stale.
    $headEpoch = git log -1 --format=%ct HEAD 2>$null
    if ($headEpoch) {
        $headTime = [DateTimeOffset]::FromUnixTimeSeconds([long]$headEpoch).LocalDateTime
        if ($latestSrc.LastWriteTime -lt $headTime) {
            Write-Host "`nWARN: STALE .pyd DETECTED: $($latestSrc.FullName) ($($latestSrc.LastWriteTime)) predates HEAD ($headTime)." -ForegroundColor Red
            Write-Host "   Rebuild before trusting any GPU result." -ForegroundColor Red
        }
    }
} else {
    Write-Host "`nNo .pyd found - CUDA build not present or not built yet." -ForegroundColor DarkYellow
}
