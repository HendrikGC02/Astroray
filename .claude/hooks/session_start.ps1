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

# Stale .pyd check (Windows MSVC build_cuda layout)
$pydCandidates = @(
    "build_cuda\astroray.cp*.pyd",
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
    $age = (Get-Date) - $latestSrc.LastWriteTime
    if ($age.TotalHours -gt 24) {
        Write-Host "`n⚠  STALE .pyd DETECTED: $($latestSrc.Name) is $([int]$age.TotalHours)h old." -ForegroundColor Red
        Write-Host "   Suggest rebuild before running tests." -ForegroundColor Red
    }
} else {
    Write-Host "`nNo .pyd found — CUDA build not present or not built yet." -ForegroundColor DarkYellow
}
