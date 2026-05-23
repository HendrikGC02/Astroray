# pkg55-B' Session N+4 worktree build script
param(
    [string]$ExpectedSHA = "45b3429"
)

Write-Host "[build_worktree] Worktree build for pkg55-B' Session N+4"

# Verify we're in the worktree
$actualSHA = (git rev-parse HEAD).Substring(0, 7)
if ($actualSHA -ne $ExpectedSHA.Substring(0, 7)) {
    Write-Error "Git SHA mismatch. Expected $ExpectedSHA, got $actualSHA"
    exit 1
}

Write-Host "[build_worktree] Git SHA verified: $actualSHA"

# Source vcvarsall
Write-Host "[build_worktree] Sourcing vcvarsall..."
cmd /c "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" x64 "&&" set 2>&1 | ForEach-Object {
    if ($_ -match "^([^=]+)=(.*)$") {
        [System.Environment]::SetEnvironmentVariable($matches[1], $matches[2])
    }
}

$env:CUDA_PATH = "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.6"
$env:NVCC = "$env:CUDA_PATH\bin\nvcc.exe"

# Create build directory
if (!(Test-Path build_cuda)) {
    New-Item -ItemType Directory -Path build_cuda | Out-Null
}
Set-Location build_cuda

# Configure CMake
Write-Host "[build_worktree] Configuring CMake..."
cmake .. `
  -G "NMake Makefiles" `
  -DCMAKE_BUILD_TYPE=Release `
  -DBUILD_PYTHON_MODULE=ON `
  -DASTRORAY_ENABLE_CUDA=ON `
  -DASTRORAY_WAVEFRONT_CUDA_N3=ON `
  -DCMAKE_CUDA_COMPILER="$env:NVCC"

if ($LASTEXITCODE -ne 0) {
    Write-Error "CMake configure failed"
    exit 1
}

# Build
Write-Host "[build_worktree] Building..."
cmake --build . --target astroray

if ($LASTEXITCODE -ne 0) {
    Write-Error "Build failed"
    exit 1
}

Write-Host "[build_worktree] Build succeeded"
exit 0
