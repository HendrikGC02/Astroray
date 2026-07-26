@echo off
REM pkg55-B' worktree CUDA build helper
REM Usage: build_cuda_worktree.bat <worktree-path> <git-commit-sha>
REM Example: build_cuda_worktree.bat C:\path\to\worktree abc1234

if "%1"=="" (
    echo Usage: build_cuda_worktree.bat ^<worktree-path^> ^<git-commit-sha^>
    exit /b 1
)
if "%2"=="" (
    echo Usage: build_cuda_worktree.bat ^<worktree-path^> ^<git-commit-sha^>
    exit /b 1
)

set WORKTREE=%1
set EXPECTED_SHA=%2

echo [build_cuda_worktree] Worktree: %WORKTREE%
echo [build_cuda_worktree] Expected SHA: %EXPECTED_SHA%

REM Verify worktree exists
if not exist "%WORKTREE%" (
    echo ERROR: Worktree does not exist: %WORKTREE%
    exit /b 1
)

REM Change to worktree
cd /d "%WORKTREE%"
if errorlevel 1 (
    echo ERROR: Failed to cd into worktree
    exit /b 1
)

REM Verify git SHA
for /f %%i in ('git rev-parse HEAD') do set ACTUAL_SHA=%%i
if not "%ACTUAL_SHA:~0,7%"=="%EXPECTED_SHA:~0,7%" (
    echo ERROR: Worktree HEAD mismatch. Expected %EXPECTED_SHA%, got %ACTUAL_SHA%
    exit /b 1
)

echo [build_cuda_worktree] Git SHA verified: %ACTUAL_SHA:~0,7%

REM Source vcvarsall
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" x64
if errorlevel 1 (
    echo ERROR: vcvarsall failed
    exit /b 1
)

REM Prefer the environment's CUDA_PATH so worktree builds use the SAME toolkit as
REM main-checkout builds (configure_and_build.bat inherits it). This script used
REM to hardcode v12.6 while CUDA_PATH/PATH resolve to v12.8, so the two build
REM routes silently used different compilers -- and register allocation is
REM compiler-version sensitive, which is a live confound for pkg155's
REM register-count bisect. Fall back to an explicit v12.8 only if unset.
if not defined CUDA_PATH set CUDA_PATH=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8
set NVCC=%CUDA_PATH%\bin\nvcc.exe
echo [build_cuda_worktree] CUDA_PATH: %CUDA_PATH%
if not exist "%NVCC%" (
    echo ERROR: nvcc not found at %NVCC%
    exit /b 1
)

REM Create build directory
mkdir build_cuda 2>nul
cd build_cuda

REM Configure CMake
cmake .. ^
  -G "NMake Makefiles" ^
  -DCMAKE_BUILD_TYPE=Release ^
  -DBUILD_PYTHON_MODULE=ON ^
  -DASTRORAY_ENABLE_CUDA=ON ^
  -DASTRORAY_WAVEFRONT_CUDA_N3=ON ^
  -DCMAKE_CUDA_COMPILER="%NVCC%"

if errorlevel 1 (
    echo ERROR: CMake configure failed
    exit /b 1
)

REM Build
REM --config Release is REQUIRED and must not be dropped. It is a no-op for the
REM single-config NMake generator configured above, but if this build_cuda/ tree
REM was previously configured by configure_and_build.bat (Visual Studio =
REM multi-config generator), an un---config'd build silently resolves to Debug
REM and dies with /RTC1 + /O2 -> D8016. Bit the pkg152 verifier 2026-07-25;
REM see memory build-cuda-worktree-debug-config.
cmake --build . --config Release --target astroray
if errorlevel 1 (
    echo ERROR: Build failed
    exit /b 1
)

REM astroray_test_helpers is a SEPARATE CMake target and is not pulled in by the
REM astroray target. tests/test_pkg92_wavefront_rng.py and
REM test_pkg92_practrand_gate.py import it; without this step they fail with a
REM spurious ModuleNotFoundError that looks like a code regression.
cmake --build . --config Release --target astroray_test_helpers
if errorlevel 1 (
    echo ERROR: astroray_test_helpers build failed
    exit /b 1
)

echo [build_cuda_worktree] Build succeeded
exit /b 0
