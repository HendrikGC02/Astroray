<#
  weekly_local_bench.ps1 -- local replacement for the retired GitHub Actions
  self-hosted-runner workflows .github/workflows/cycles-parity.yml and
  .github/workflows/showcase.yml (both deleted; this repo's self-hosted
  runner does not have GPU coverage worth a scheduled CI job, so these ran
  on hand-triggered cron instead). Runs the same two benchmarks locally:

    1. scripts/run_parity.py            (full scene x engine matrix, no
                                          --scene/--engine filters, mirroring
                                          cycles-parity.yml's non-issue_comment
                                          default) + scripts/summarize_parity.py
                                          on the freshest resulting CSV.
    2. benchmarks/showcase/runner.py     (quick mode, --output-dir
                                          benchmarks/showcase/output, mirroring
                                          showcase.yml's
                                          `render_showcase.py --quick
                                          --output-dir benchmarks/showcase/output`
                                          invocation; runner.py is the current
                                          canonical showcase script per
                                          scripts/README.md, so it replaces
                                          render_showcase.py here).

  This script NEVER runs git commit/push. It only renders and logs. Intended
  to be run manually (or later wired to a Windows Scheduled Task by the lead
  after a manual validation run -- not done by this script).

  Usage:
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\benchmarks\weekly_local_bench.ps1
#>

$ErrorActionPreference = 'Continue'
$Repo = 'C:\Users\hgcom\OneDrive\Astroray\Astroray_repo\Astroray'
Set-Location $Repo

$LogDir = Join-Path $env:LOCALAPPDATA 'astroray'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd'
$Log = Join-Path $LogDir "weekly_bench_$stamp.log"

"=== weekly_local_bench $stamp ===" | Out-File $Log -Encoding ascii
"cwd=$(Get-Location)" | Out-File $Log -Append -Encoding ascii

"=== cycles-parity: historical scripts/run_parity.py ===" | Out-File $Log -Append -Encoding ascii
& python scripts/run_parity.py --scene cornell --scene textured_plane --scene glass_sphere *>> $Log
$parityCode = $LASTEXITCODE
"run_parity.py exit=$parityCode" | Out-File $Log -Append -Encoding ascii

$CorpusScenes = @('camera_lens', 'camera_lens_ortho', 'geometry_zoo', 'lighting_studio', 'materials_hall',
    'render_settings', 'textures_mapping', 'volumes_smoke', 'world_sky_hdri', 'world_sky_sky',
    # pkg284 corpus v2 (Phase 1 lists the ids; Phase 3 wires the v2 gate rows)
    'v2_camera_geometry', 'v2_dispersion_caustics', 'v2_light_tree', 'v2_media', 'v2_sky_sun',
    'v2_textures_opvm', 'v2_thin_film_metals', 'v2_viewport',
    # pkg296 volumes_mesh (mesh-bounded volumes; gated by tests/test_pkg296_mesh_volume_boundary.py)
    'vm_camera_inside', 'vm_glass_shell', 'vm_icosphere', 'vm_icosphere_empty', 'vm_nested',
    'vm_overlap', 'vm_suzanne')
$CorpusParityArgs = @()
foreach ($CorpusScene in $CorpusScenes) {
    $CorpusParityArgs += '--scene'
    $CorpusParityArgs += $CorpusScene
}
"=== cycles-parity: corpus scripts/run_parity.py ===" | Out-File $Log -Append -Encoding ascii
& python scripts/run_parity.py @CorpusParityArgs *>> $Log
$corpusParityCode = $LASTEXITCODE
"corpus run_parity.py exit=$corpusParityCode" | Out-File $Log -Append -Encoding ascii

"=== gate-c corpus F12 evidence ===" | Out-File $Log -Append -Encoding ascii
if ([string]::IsNullOrWhiteSpace($env:ASTRORAY_GATE_C_MODULE_SHA256)) {
    "gate-c skipped: ASTRORAY_GATE_C_MODULE_SHA256 is required" | Out-File $Log -Append -Encoding ascii
    $gateCCode = 1
} else {
    & python scripts/run_parity.py --gate-c --gate-c-build-id $env:ASTRORAY_GATE_C_BUILD_ID --gate-c-module-sha256 $env:ASTRORAY_GATE_C_MODULE_SHA256 *>> $Log
    $gateCCode = $LASTEXITCODE
}
"gate-c exit=$gateCCode" | Out-File $Log -Append -Encoding ascii

if ($parityCode -eq 0) {
    $latestCsv = Get-ChildItem -Path (Join-Path $Repo 'benchmarks\cycles-parity') -Filter '*.csv' -File |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($latestCsv) {
        "=== cycles-parity: scripts/summarize_parity.py $($latestCsv.FullName) ===" | Out-File $Log -Append -Encoding ascii
        $mdOut = [System.IO.Path]::ChangeExtension($latestCsv.FullName, '.md')
        & python scripts/summarize_parity.py $latestCsv.FullName --output $mdOut *>> $Log
        "summarize_parity.py exit=$LASTEXITCODE" | Out-File $Log -Append -Encoding ascii
    } else {
        "no cycles-parity CSV found to summarize" | Out-File $Log -Append -Encoding ascii
    }
}

"=== showcase: benchmarks/showcase/runner.py ===" | Out-File $Log -Append -Encoding ascii
& python -m benchmarks.showcase.runner --quick --output-dir benchmarks/showcase/output *>> $Log
$showcaseCode = $LASTEXITCODE
"runner.py exit=$showcaseCode" | Out-File $Log -Append -Encoding ascii

# pkg307 noise-per-time benchmark, quick weekly slice: GPU legs (Astroray vs Cycles OptiX) on two corpus scenes, 10 s
# per-frame budget. The full 8-scene x 4-leg run is hand-triggered (hours): see scripts/README.md and
# test_results/integrator/noise-per-time. Output stays under LOCALAPPDATA; this script never commits.
"=== noise-bench (quick): mc_tolerance.py --noise-bench ===" | Out-File $Log -Append -Encoding ascii
$NoiseWork = Join-Path $LogDir "noise_bench_$stamp"
& python scripts/build/gpu_locked_run.py weekly-noise-bench -- python benchmarks/reference_corpus/mc_tolerance.py --noise-bench --scenes v2_light_tree v2_camera_geometry --nb-legs cycles_gpu gpu --budgets 10 --spps 64 --work-dir $NoiseWork *>> $Log
$noiseCode = $LASTEXITCODE
"noise-bench exit=$noiseCode" | Out-File $Log -Append -Encoding ascii

"=== weekly_local_bench done ===" | Out-File $Log -Append -Encoding ascii
Write-Host "Log written to $Log"

if ($parityCode -ne 0 -or $corpusParityCode -ne 0 -or $gateCCode -ne 0 -or $showcaseCode -ne 0 -or $noiseCode -ne 0) {
    exit 1
}
exit 0
