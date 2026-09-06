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

"=== cycles-parity: scripts/run_parity.py ===" | Out-File $Log -Append -Encoding ascii
& python scripts/run_parity.py *>> $Log
$parityCode = $LASTEXITCODE
"run_parity.py exit=$parityCode" | Out-File $Log -Append -Encoding ascii

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
& python benchmarks/showcase/runner.py --quick --output-dir benchmarks/showcase/output *>> $Log
$showcaseCode = $LASTEXITCODE
"runner.py exit=$showcaseCode" | Out-File $Log -Append -Encoding ascii

"=== weekly_local_bench done ===" | Out-File $Log -Append -Encoding ascii
Write-Host "Log written to $Log"

if ($parityCode -ne 0 -or $showcaseCode -ne 0) {
    exit 1
}
exit 0
