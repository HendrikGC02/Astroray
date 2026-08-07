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
      -Smoke    build+package+install, then a headless liveness smoke render.
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
    [string]$Blender = 'C:/Program Files/Blender Foundation/Blender 5.1/blender.exe',
    [string]$Python = 'python'
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
    'auto' = Join-Path $RepoRoot 'build_blender_addon_tcnn'
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
    $out = & $Blender --background --factory-startup --python $SmokePy 2>&1 | Out-String
    Write-Host $out
    if ($out -match "$token FAIL") { throw "$token FAIL (see output above)" }
    if ($out -notmatch "$token PASS") {
        throw "$token sentinel not found - Blender exited without reaching the PASS line"
    }
    Write-Host "$token PASS" -ForegroundColor Green
}

# --------------------------------------------------------------------------- #
$total = [System.Diagnostics.Stopwatch]::StartNew()
Write-Host "pkg175 dev loop  mode=$Mode  backend=$Backend  skip-build=$($SkipBuild.IsPresent)"

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
sys.path.insert(0, r"{0}")
import build_blender_addon as b
for name in b.ADDON_FILES:
    src = b.ADDON_SRC / name
    if src.exists():
        shutil.copy2(src, b.STAGE_DIR / name)
        print("restaged", name)
'@ -f (Split-Path -Parent $BuildAddon)
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $restage | & $Python -
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
sys.path.insert(0, r"{0}")
import build_blender_addon as b
ok = b.install_to_blender(Path(r"{1}"))
sys.exit(0 if ok else 1)
'@ -f (Split-Path -Parent $BuildAddon), $Blender
$installPy | & $Python -
if ($LASTEXITCODE -ne 0) { throw "install_to_blender failed" }

# 5. SMOKE or LAUNCH
if ($Mode -eq 'smoke') {
    Write-Section "Headless smoke render (liveness gate)"
    # Point the smoke at the installed extension dir so we exercise exactly
    # what Blender will load. Fall back to the staged dir if the ext dir
    # cannot be resolved.
    $installPath = @'
import sys
from pathlib import Path
sys.path.insert(0, r"{0}")
import build_blender_addon as b
d = b.blender_user_extensions_dir(Path(r"{1}"))
print((d / "astroray") if d else "")
'@ -f (Split-Path -Parent $BuildAddon), $Blender
    $installed = ($installPath | & $Python -).Trim()
    $addonDir = if ($installed -and (Test-Path $installed)) { $installed } else { $StageDir }
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
