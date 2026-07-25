@echo off
setlocal

set "WORKTREE_DIR=%~dp0"
cd /d "%WORKTREE_DIR%"

echo Configuring CMake with VS 2022 generator...
cmake -B build_cuda -G "Visual Studio 17 2022" -A x64 -DCMAKE_BUILD_TYPE=Release -DASTRORAY_USE_CUDA=ON
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
