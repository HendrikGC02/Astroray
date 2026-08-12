@echo off
setlocal

set "WORKTREE_DIR=%~dp0"
cd /d "%WORKTREE_DIR%"

echo Configuring CMake with VS 2022 generator...
REM ASTRORAY_ENABLE_CUDA (not ASTRORAY_USE_CUDA, which is not a real option) enables the
REM GPU backend; ASTRORAY_CUDA_ARCHS=native pins the local GPU arch. Under the VS
REM generator the arch MUST be resolved to a numeric value (CMakeLists does this via
REM nvidia-smi) -- passing the bare "native" keyword leaves .vcxproj CodeGeneration
REM empty and nvcc defaults to sm_52 (the 2026-08-12 stale-arch incident).
cmake -B build_cuda -G "Visual Studio 17 2022" -A x64 -DCMAKE_BUILD_TYPE=Release -DASTRORAY_ENABLE_CUDA=ON -DASTRORAY_CUDA_ARCHS=native
if %ERRORLEVEL% neq 0 (
    echo CMake configuration failed
    exit /b 1
)

echo Building astroray target...
cmake --build build_cuda --config Release --target astroray
if %ERRORLEVEL% neq 0 (
    echo Build failed
    exit /b 1
)

echo Building astroray_test_helpers target...
cmake --build build_cuda --config Release --target astroray_test_helpers
if %ERRORLEVEL% neq 0 (
    echo Test-helpers build failed
    exit /b 1
)

echo Build succeeded
