$ErrorActionPreference = 'Continue'
$sw = [System.Diagnostics.Stopwatch]::StartNew()
cmake --build build_cuda --config Release -j 2>&1 | Tee-Object -FilePath build_cuda_build_log.txt | Out-Null
$code = $LASTEXITCODE
$sw.Stop()
Write-Output ("BUILD_EXIT_CODE=" + $code)
Write-Output ("BUILD_ELAPSED_SECONDS=" + [int]$sw.Elapsed.TotalSeconds)
