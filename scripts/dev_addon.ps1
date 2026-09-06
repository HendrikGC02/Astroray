<#
.SYNOPSIS
    pkg175 - one-command Blender dev loop: build -> package -> guard -> install
    -> (headless smoke | interactive launch).

.DESCRIPTION
    Composes the existing pieces (build_blender_addon.py for engine+staging,
    the verify_pkg*_blender.py headless pattern) and wires in the four
    memory-backed guards (scripts/dev_loop_guards.py) so the known footguns
    are impossible, not merely documented.

    Modes (pick one; -Smoke is the default and is the agent/CI-safe path):
      -Smoke    build+package+install in a disposable profile, then a headless
                liveness smoke render. All Blender user paths are isolated.
                Gates on the printed "PKG175_SMOKE_RESULT PASS" sentinel,
                NOT the exit code (Blender --python swallows tracebacks).
      -Launch   build+package+install, then open interactive Blender with the
                addon enabled and a test .blend (owner-facing).
      -SkipBuild  re-stage the addon Python only (no C++ rebuild); iterate fast.

.EXAMPLE
    # Agent / CI: full loop, headless smoke gate
    pwsh scripts/dev_addon.ps1 -Smoke

.EXAMPLE
    # Owner: build + open Blender with the fresh addon
    pwsh scripts/dev_addon.ps1 -Launch

.EXAMPLE
    # Fast Python-only iteration (reuses the already-built .pyd)
    pwsh scripts/dev_addon.ps1 -Smoke -SkipBuild
#>
[CmdletBinding()]
param(
    [switch]$Smoke,
    [switch]$Launch,
    [switch]$SkipBuild,
    [ValidateSet('cpu', 'cuda', 'tcnn', 'auto')]
    [string]$Backend = 'cuda',
    [string]$Blender = 'C:/Program Files/Blender Foundation/Blender 5.2/blender.exe',
    [string]$Python = 'python',
    [string]$SmokeProfileParent = [System.IO.Path]::GetTempPath()
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$RepoRoot   = Split-Path -Parent $PSScriptRoot
$Guards     = Join-Path $PSScriptRoot 'dev_loop_guards.py'
$BuildAddon = Join-Path $PSScriptRoot 'build/build_blender_addon.py'
$SmokePy    = Join-Path $PSScriptRoot 'verify_pkg175_smoke_blender.py'
$StageDir   = Join-Path $RepoRoot 'dist/astroray'
$TestBlend  = Join-Path $RepoRoot 'blender_addon/Test_scene.blend'

$BuildDirByBackend = @{
    'cpu'  = Join-Path $RepoRoot 'build_blender_addon'
    'cuda' = Join-Path $RepoRoot 'build_blender_addon_cuda'
    'tcnn' = Join-Path $RepoRoot 'build_blender_addon_tcnn'
    'auto' = Join-Path $RepoRoot 'build_blender_addon_cuda'
}
$BuildDir = $BuildDirByBackend[$Backend]

# -Launch wins if both are passed; default is Smoke.
$Mode = if ($Launch) { 'launch' } else { 'smoke' }

function Write-Section($text) {
    Write-Host ''
    Write-Host "=== $text ===" -ForegroundColor Cyan
}

function Invoke-Guard($guardArgs) {
    Write-Host "> python dev_loop_guards.py $($guardArgs -join ' ')" -ForegroundColor DarkGray
    & $Python $Guards @guardArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Guard failed: dev_loop_guards.py $($guardArgs -join ' ')"
    }
}

function Invoke-BlenderSentinel($smokeMode, $addonDir, $token) {
    # Run the headless smoke script and gate on the printed "<token> PASS"
    # string (NOT the exit code - Blender --python exits 0 even on a traceback).
    if (-not (Test-Path $Blender)) {
        throw "Blender not found at: $Blender (pass -Blender <path>)"
    }
    $env:ASTRORAY_SMOKE_MODE = $smokeMode
    $env:ASTRORAY_SMOKE_ADDON_DIR = $addonDir
    Write-Host "> blender --background --factory-startup --python verify_pkg175_smoke_blender.py  (mode=$smokeMode)" -ForegroundColor DarkGray
    # Windows PowerShell turns redirected native stderr into ErrorRecords.
    # Capture warnings as diagnostics, then judge the native exit and sentinel.
    $savedErrorPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $out = & $Blender --background --factory-startup --python $SmokePy 2>&1 | Out-String
        $nativeExit = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $savedErrorPreference
    }
    Write-Host $out
    Write-Host "Blender exit code: $nativeExit"
    if ($out -match "$token FAIL") { throw "$token FAIL (see output above)" }
    if ($nativeExit -ne 0) { throw "Blender exited with code $nativeExit (see output above)" }
    if ($out -notmatch "$token PASS") {
        throw "$token sentinel not found - Blender exited without reaching the PASS line"
    }
    Write-Host "$token PASS" -ForegroundColor Green
}

function Assert-PlainPath($path) {
    # Check lexical ancestors before resolving: resolving a junction first
    # would hide that the caller supplied a redirected path.
    if (($path -split '[\\/]') -contains '..') { throw "Parent traversal is forbidden: $path" }
    $full = [System.IO.Path]::GetFullPath($path)
    $ancestor = $full
    while ($ancestor) {
        if (Test-Path -LiteralPath $ancestor) {
            $item = Get-Item -LiteralPath $ancestor -Force
            if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
                throw "Reparse path is forbidden: $ancestor"
            }
        }
        $ancestor = Split-Path -Parent $ancestor
    }
    return $full
}

# Capture the caller environment even in launch mode, where the register
# guard temporarily sets ASTRORAY_SMOKE_* variables.
$profileVariables = @('BLENDER_USER_RESOURCES', 'BLENDER_USER_EXTENSIONS',
    'BLENDER_USER_CONFIG', 'BLENDER_USER_SCRIPTS', 'BLENDER_USER_DATAFILES')
$savedEnvironment = @{}
foreach ($name in $profileVariables) {
    $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
Get-ChildItem Env: | Where-Object { $_.Name -like 'ASTRORAY_SMOKE_*' } | ForEach-Object {
    $savedEnvironment[$_.Name] = $_.Value
}
$ownedProfile = $null
try {
if ($Mode -eq 'smoke') {
    $profileParent = Assert-PlainPath $SmokeProfileParent
    if (-not (Test-Path -LiteralPath $profileParent -PathType Container)) {
        throw "Smoke profile parent must be an existing directory: $profileParent"
    }
    # tempfile creates a fresh child exclusively; the supplied parent is never
    # itself an install or cleanup target.
    $createProfile = 'import sys,tempfile; print(tempfile.mkdtemp(prefix="astroray-smoke-", dir=sys.argv[1]))'
    $ownedProfile = ($createProfile | & $Python - $profileParent | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $ownedProfile) { throw 'Could not create disposable Blender profile' }
    $ownedProfile = Assert-PlainPath $ownedProfile
    Get-ChildItem Env: | Where-Object { $_.Name -like 'ASTRORAY_SMOKE_*' } | ForEach-Object {
        Remove-Item -LiteralPath "Env:$($_.Name)"
    }
    foreach ($name in $profileVariables) {
        $leaf = $name.Substring('BLENDER_USER_'.Length).ToLowerInvariant()
        $directory = Join-Path $ownedProfile $leaf
        [System.IO.Directory]::CreateDirectory($directory) | Out-Null
        [Environment]::SetEnvironmentVariable($name, $directory, 'Process')
    }
    Write-Host "disposable Blender profile: $ownedProfile"
}

# --------------------------------------------------------------------------- #
$total = [System.Diagnostics.Stopwatch]::StartNew()
Write-Host "pkg175 dev loop  mode=$Mode  backend=$Backend  skip-build=$($SkipBuild.IsPresent)"

# Check the per-worktree stage before restaging files or replacing its tree.
$stageCheck = @'
import sys
sys.path.insert(0, sys.argv[1])
import build_blender_addon as b
error = b._validate_target_path(b.STAGE_DIR, b.REPO_ROOT)
if error is None and b.STAGE_DIR.exists():
    error = b._validate_stage_tree(b.STAGE_DIR)
if error:
    raise RuntimeError(error)
'@
$stageCheck | & $Python - (Split-Path -Parent $BuildAddon)
if ($LASTEXITCODE -ne 0) { throw 'Unsafe addon staging path' }

# 1. BUILD + STAGE (engine .pyd with OpenMP OFF, staged into dist/astroray)
$buildSecs = 0.0
if ($SkipBuild) {
    Write-Section "Re-stage addon Python only (-SkipBuild)"
    if (-not (Test-Path (Join-Path $StageDir 'build_report.json'))) {
        throw "No staged build at $StageDir - run a full build once before -SkipBuild"
    }
    # Reuse build_blender_addon's ADDON_FILES / STAGE_DIR / ADDON_SRC so the
    # copied set stays in lockstep with the packaging allow-list.
    $restage = @'
import shutil, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import build_blender_addon as b
for name in b.ADDON_FILES:
    src = b.ADDON_SRC / name
    if src.exists():
        shutil.copy2(src, b.STAGE_DIR / name)
        print("restaged", name)
'@
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $restage | & $Python - (Split-Path -Parent $BuildAddon)
    if ($LASTEXITCODE -ne 0) { throw "re-stage failed" }
    $sw.Stop(); $buildSecs = $sw.Elapsed.TotalSeconds
}
else {
    Write-Section "Build engine + package addon (backend=$Backend)"
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    & $Python $BuildAddon --backend $Backend --blender $Blender
    if ($LASTEXITCODE -ne 0) { throw "build_blender_addon.py failed" }
    $sw.Stop(); $buildSecs = $sw.Elapsed.TotalSeconds
}

# 2. GUARDS a/b/c on the freshly staged artifacts
Write-Section "Guards"
if (-not $SkipBuild) {
    # (a) stale-.pyd: only meaningful right after a build.
    Invoke-Guard @('pyd-fresh', '--build-dir', $BuildDir)
}
else {
    Write-Host "[guard:pyd] skipped (-SkipBuild reuses the prior .pyd)" -ForegroundColor DarkGray
}
# (b) OpenMP off  (c) ADDON_FILES allow-list drift
Invoke-Guard @('openmp', '--staged', $StageDir)
Invoke-Guard @('addon-files', '--addon-dir', (Join-Path $RepoRoot 'blender_addon'))

# 3. GUARD d: register the STAGED dir headless BEFORE copying into Blender
Write-Section "Guard (d): headless register() of the staged addon (pre-install)"
Invoke-BlenderSentinel 'register' $StageDir 'PKG175_REGISTER_RESULT'

# 4. INSTALL staged -> Blender user_default extensions dir (reuses existing code)
Write-Section "Install into Blender"
$installPy = @'
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[3])
import build_blender_addon as b
ok = b.install_to_blender(Path(sys.argv[1]), allowed_root=Path(sys.argv[2]) if sys.argv[2] != "-" else None)
sys.exit(0 if ok else 1)
'@
$installRootArg = if ($ownedProfile) { $ownedProfile } else { '-' }
$installPy | & $Python - $Blender $installRootArg (Split-Path -Parent $BuildAddon)
if ($LASTEXITCODE -ne 0) { throw "install_to_blender failed" }

# 5. SMOKE or LAUNCH
if ($Mode -eq 'smoke') {
    Write-Section "Headless smoke render (liveness gate)"
    # Point the smoke at the installed extension dir so we exercise exactly
    # what Blender will load. An unresolved install is a failure.
    $installPath = @'
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[3])
import build_blender_addon as b
d = b.blender_user_extensions_dir(Path(sys.argv[1]))
if d is None:
    raise RuntimeError("Cannot resolve isolated installation")
target = (d / "astroray").resolve()
if not target.is_relative_to(Path(sys.argv[2]).resolve()) or not target.is_dir():
    raise RuntimeError("Missing or escaped isolated installation: " + str(target))
print(target)
'@
    $installed = ($installPath | & $Python - $Blender $ownedProfile (Split-Path -Parent $BuildAddon) | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $installed) { throw 'Cannot resolve isolated installation' }
    $addonDir = Assert-PlainPath $installed
    Write-Host "smoke addon dir: $addonDir" -ForegroundColor DarkGray
    Invoke-BlenderSentinel 'render' $addonDir 'PKG175_SMOKE_RESULT'
}
else {
    Write-Section "Launch interactive Blender"
    $enable = "import bpy; bpy.ops.preferences.addon_enable(module='bl_ext.user_default.astroray'); bpy.ops.wm.save_userpref()"
    $blendArg = if (Test-Path $TestBlend) { @($TestBlend) } else { @() }
    Write-Host "Opening Blender with the addon enabled..." -ForegroundColor Green
    & $Blender @blendArg --python-expr $enable
}

$total.Stop()
Write-Section "Done"
Write-Host ("build/stage: {0:N1}s   total: {1:N1}s" -f $buildSecs, $total.Elapsed.TotalSeconds)
}
finally {
    Get-ChildItem Env: | Where-Object { $_.Name -like 'ASTRORAY_SMOKE_*' } | ForEach-Object {
        Remove-Item -LiteralPath "Env:$($_.Name)"
    }
    foreach ($entry in $savedEnvironment.GetEnumerator()) {
        if ($null -eq $entry.Value) {
            Remove-Item -LiteralPath "Env:$($entry.Key)" -ErrorAction SilentlyContinue
        }
        else {
            [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, 'Process')
        }
    }
    if ($ownedProfile) {
        try {
            $cleanupPath = Assert-PlainPath $ownedProfile
            if ((Split-Path -Parent $cleanupPath).TrimEnd([char[]]'\/') -ne $profileParent.TrimEnd([char[]]'\/') -or
                (Split-Path -Leaf $cleanupPath) -notlike 'astroray-smoke-*') {
                throw 'Disposable profile ownership check failed'
            }
            # Never follow a directory introduced by Blender/addon code during
            # cleanup. Retain the owned profile if its topology changed.
            Get-ChildItem -LiteralPath $cleanupPath -Recurse -Force | ForEach-Object {
                if ($_.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
                    throw "Reparse entry in disposable profile: $($_.FullName)"
                }
            }
            Remove-Item -LiteralPath $cleanupPath -Recurse -Force
        }
        catch {
            throw "Disposable profile cleanup failed; recovery retained at $ownedProfile : $_"
        }
    }
}
