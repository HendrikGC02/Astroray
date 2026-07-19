# pyd_shadow_guard.ps1
#
# PreToolUse hook for Astroray. Two jobs:
#   1. Block any Edit/Write whose file_path ends in `.pyd` — these are build
#      artifacts and should never be hand-edited.
#   2. When a Bash command runs pytest or imports `astroray` via `python -c`,
#      scan for stale `astroray*.pyd` shadow copies outside the legitimate
#      build output dirs and emit a warning. Does not block — surfaces the
#      list so the model/user notices before chasing a frozen-test ghost.
#
# Hook protocol: receive JSON on stdin with .tool_name / .tool_input.
# Exit 0 = allow.  Exit 2 = block (stderr is shown).  Stderr on exit 0 is
# surfaced as a non-blocking warning.
#
# Background: tests/base_helpers.py inserts the project root into sys.path
# AFTER build/, so any .pyd at the project root, in tests/, or in stray
# Release/ dirs silently shadows fresh builds. See
# .claude/skills/rebuild-pyd/SKILL.md for the recovery procedure.

$ErrorActionPreference = 'Stop'

# Read hook payload
$raw = [Console]::In.ReadToEnd()
if (-not $raw) { exit 0 }

try {
    $payload = $raw | ConvertFrom-Json
} catch {
    exit 0  # Malformed payload — don't block on harness bugs.
}

$tool = [string]$payload.tool_name
$ti   = $payload.tool_input

# Repo root: this script lives at <repo>/.claude/hooks/pyd_shadow_guard.ps1
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path

# --- Job 1: block Edit/Write to .pyd -----------------------------------------
if ($tool -in @('Edit', 'Write', 'NotebookEdit', 'MultiEdit')) {
    $path = [string]$ti.file_path
    if ($path -and $path.ToLower().EndsWith('.pyd')) {
        [Console]::Error.WriteLine(
            "[pyd-shadow-guard] BLOCKED: $tool on '$path'. " +
            "`.pyd` files are build artifacts; rebuild them with /rebuild-pyd instead of editing.")
        exit 2
    }
    exit 0
}

# --- Job 2: warn on shadows before pytest / astroray import ------------------
if ($tool -ne 'Bash') { exit 0 }

$cmd = [string]$ti.command
if (-not $cmd) { exit 0 }

# Only fire on commands that actually load the astroray module.
$triggersImport = (
    $cmd -match '\bpytest\b' -or
    ($cmd -match '\bpython\b' -and $cmd -match 'astroray')
)
if (-not $triggersImport) { exit 0 }

# Legitimate output dirs (anything matching these is NOT a shadow):
$legit = @(
    '\build\',
    '\build_cuda\',
    '\build_tcnn\',
    '\build_blender_addon_tcnn\',
    '\build_blender_addon_cuda\',
    '\build_blender_addon_cpu\',
    '\dist\',
    '\blender_addon\Release\'
) | ForEach-Object { [Regex]::Escape($_) }
$legitPattern = '(' + ($legit -join '|') + ')'

try {
    $all = Get-ChildItem -LiteralPath $repo -Recurse -Filter 'astroray*.pyd' `
              -ErrorAction SilentlyContinue -Force
} catch {
    exit 0
}

$shadows = $all | Where-Object { $_.FullName -notmatch $legitPattern }

if ($shadows -and $shadows.Count -gt 0) {
    # Root-level shadows are the lethal case: they sat ahead of the build
    # dirs on sys.path for every harness run (2026-07-19 pkg55-C3 incident
    # burned hours on a stale root shadow). BLOCK those; warn on the rest.
    $rootShadows = @($shadows | Where-Object { $_.DirectoryName -eq $repo })
    [Console]::Error.WriteLine("[pyd-shadow-guard] WARNING: $($shadows.Count) shadow .pyd file(s) found outside build/ -- these can be loaded instead of the fresh build:")
    foreach ($s in $shadows) {
        $rel = $s.FullName.Substring($repo.Length).TrimStart('\','/')
        [Console]::Error.WriteLine("  $rel  ($([math]::Round($s.Length/1MB,2)) MB, $($s.LastWriteTime.ToString('yyyy-MM-dd HH:mm')))")
    }
    [Console]::Error.WriteLine("[pyd-shadow-guard] Run /rebuild-pyd or delete these before trusting test output.")
    if ($rootShadows.Count -gt 0) {
        [Console]::Error.WriteLine("[pyd-shadow-guard] BLOCKED: shadow .pyd at the repo/worktree ROOT. Delete it (it is gitignored build debris) and rerun.")
        exit 2
    }
}

exit 0
