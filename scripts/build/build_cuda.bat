@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" x64
if errorlevel 1 (echo vcvarsall failed & exit /b 1)

REM Prefer the environment's CUDA_PATH so this build uses the SAME toolkit as
REM build_cuda_worktree.bat (which already does this). Hardcoding v12.6 here
REM while worktrees used v12.8 made the two build routes silently diverge —
REM and v12.6 cannot target sm_120 (Blackwell), so the local RTX 5070 Ti ran
REM PTX-JIT instead of native code. Fall back to v12.8 explicitly.
if not defined CUDA_PATH set CUDA_PATH=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8
set NVCC=%CUDA_PATH%\bin\nvcc.exe
if not exist "%NVCC%" (echo ERROR: nvcc not found at %NVCC% & exit /b 1)

REM --- sccache compiler cache, shared across every worktree ------------------
REM SCCACHE_DIR + FETCHCONTENT_BASE_DIR live under %LOCALAPPDATA% (outside the
REM OneDrive tree — no sync churn) and are IDENTICAL for every checkout, so a
REM warm build in one tree seeds cache hits in the next. SCCACHE_BASEDIR is set
REM to THIS checkout's root below so sccache hashes sources by their path
REM RELATIVE to the tree root; without it the differing absolute __FILE__ /
REM include paths per worktree produce near-zero cross-tree hits (sccache #956).
REM /Zi is never emitted here (Release has no debug info), so MSVC PDB caching
REM is a non-issue. FETCHCONTENT_BASE_DIR is shared so pybind11 / tiny-cuda-nn
REM download+build once; warm it serially from ONE checkout first, because
REM concurrent cold configures race on first population.
if not defined SCCACHE_DIR set SCCACHE_DIR=%LOCALAPPDATA%\astroray-cache\sccache
if not defined FETCHCONTENT_BASE_DIR set FETCHCONTENT_BASE_DIR=%LOCALAPPDATA%\astroray-cache\fetchcontent
set SCCACHE_BASEDIR=%CD%
set CCLAUNCH=
where sccache >nul 2>&1 && set CCLAUNCH=sccache
if "%CCLAUNCH%"=="" echo [build_cuda] WARNING: sccache not on PATH; building without compiler cache

mkdir build_cuda 2>nul
cd build_cuda

REM Generator changed NMake -> Ninja 2026-08-06: NMake builds are fully serial
REM (no -j support); Ninja parallelizes object compiles across cores. If this
REM tree was configured with a different generator, CMake hard-errors on the
REM mismatch — wipe the stale cache first (the _deps subbuilds carry their own
REM caches with the old generator too).
if exist CMakeCache.txt (
    findstr /C:"CMAKE_GENERATOR:INTERNAL=Ninja" CMakeCache.txt >nul 2>&1 || (
        echo [build_cuda] Wiping stale-generator CMake cache
        del /q CMakeCache.txt
        rmdir /s /q CMakeFiles 2>nul
        rmdir /s /q _deps 2>nul
    )
)

cmake .. ^
  -G "Ninja" ^
  -DCMAKE_BUILD_TYPE=Release ^
  -DBUILD_PYTHON_MODULE=ON ^
  -DASTRORAY_ENABLE_CUDA=ON ^
  -DASTRORAY_CUDA_ARCHS=native ^
  -DCMAKE_CXX_COMPILER_LAUNCHER=%CCLAUNCH% ^
  -DCMAKE_CUDA_COMPILER_LAUNCHER=%CCLAUNCH% ^
  -DFETCHCONTENT_BASE_DIR="%FETCHCONTENT_BASE_DIR%" ^
  -DCMAKE_CUDA_COMPILER="%NVCC%"

if errorlevel 1 (echo CMake configure failed & exit /b 1)

cmake --build . --config Release --target astroray
if errorlevel 1 (echo Build failed & exit /b 1)

REM astroray_test_helpers is a SEPARATE target not pulled in by astroray;
REM without it the pkg92 RNG/PractRand tests fail with a spurious
REM ModuleNotFoundError (same fix as build_cuda_worktree.bat).
cmake --build . --config Release --target astroray_test_helpers
if errorlevel 1 (echo astroray_test_helpers build failed & exit /b 1)
