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

REM --- sccache compiler cache, shared across every worktree ------------------
REM SCCACHE_DIR + FETCHCONTENT_BASE_DIR live under %LOCALAPPDATA% (outside the
REM OneDrive tree — no sync churn) and are IDENTICAL for every checkout, so a
REM warm build in one tree seeds cache hits here. SCCACHE_BASEDIR = this
REM worktree's root (%CD% after the cd above) so sccache hashes sources by their
REM path RELATIVE to the tree root; without it the per-worktree absolute
REM __FILE__ / include paths yield near-zero cross-tree hits (sccache #956).
REM Release emits no /Zi, so MSVC PDB caching is a non-issue. Warm the shared
REM FETCHCONTENT_BASE_DIR serially from ONE checkout first — concurrent cold
REM configures race on first population.
if not defined SCCACHE_DIR set SCCACHE_DIR=%LOCALAPPDATA%\astroray-cache\sccache
if not defined FETCHCONTENT_BASE_DIR set FETCHCONTENT_BASE_DIR=%LOCALAPPDATA%\astroray-cache\fetchcontent
set SCCACHE_BASEDIR=%CD%
set CCLAUNCH=
where sccache >nul 2>&1 && set CCLAUNCH=sccache
if "%CCLAUNCH%"=="" echo [build_cuda_worktree] WARNING: sccache not on PATH; building without compiler cache

REM pkg183: repo root captured BEFORE cd build_cuda for the staleness guard.
set "REPO_ROOT=%CD%"

REM Create build directory
mkdir build_cuda 2>nul
cd build_cuda

REM Generator changed NMake -> Ninja 2026-08-06 (NMake is fully serial; Ninja
REM parallelizes). Worktree build_cuda dirs may carry a cache from the old
REM generator — CMake hard-errors on the mismatch, so wipe stale caches
REM (including _deps subbuild caches) before configuring.
if exist CMakeCache.txt (
    findstr /C:"CMAKE_GENERATOR:INTERNAL=Ninja" CMakeCache.txt >nul 2>&1 || (
        echo [build_cuda_worktree] Wiping stale-generator CMake cache
        del /q CMakeCache.txt
        rmdir /s /q CMakeFiles 2>nul
        rmdir /s /q _deps 2>nul
    )
)

REM Configure CMake. ASTRORAY_CUDA_ARCHS=native: worktree builds only ever run
REM on this machine's GPU (hardware verify), so compile one native arch
REM (sm_120) instead of the 3-arch broad-compat list — ~3x less device
REM compile work and no PTX-JIT at test time.
cmake .. ^
  -G "Ninja" ^
  -DCMAKE_BUILD_TYPE=Release ^
  -DBUILD_PYTHON_MODULE=ON ^
  -DASTRORAY_ENABLE_CUDA=ON ^
  -DASTRORAY_WAVEFRONT_CUDA_N3=ON ^
  -DASTRORAY_CUDA_ARCHS=native ^
  -DCMAKE_CXX_COMPILER_LAUNCHER=%CCLAUNCH% ^
  -DCMAKE_CUDA_COMPILER_LAUNCHER=%CCLAUNCH% ^
  -DFETCHCONTENT_BASE_DIR="%FETCHCONTENT_BASE_DIR%" ^
  -DCMAKE_CUDA_COMPILER="%NVCC%"

if errorlevel 1 (
    echo ERROR: CMake configure failed
    exit /b 1
)

REM --- pkg183 incremental-build staleness guard ------------------------------
REM Ninja's mtime-based staleness detection is unreliable on this OneDrive tree,
REM so crossing a layout-changing commit boundary can leave objects compiled
REM against an old struct layout to be linked with fresh ones (ABI-mixed binary
REM -> host-side access violations). Compare a hash of the layout-critical
REM headers against the last build's stamp; on mismatch force a full object
REM clean (correctness over speed) instead of trusting mtimes.
where python >nul 2>&1 || goto :pkg183_guard_skip
set GUARD_DECISION=OK
for /f "usebackq delims=" %%g in (`python "%REPO_ROOT%\scripts\build\build_guard.py" check --repo-root "%REPO_ROOT%" --build-dir "%CD%"`) do set GUARD_DECISION=%%g
if "%GUARD_DECISION%"=="WIPE" (
    echo [build_cuda_worktree] pkg183: layout-critical headers changed since last build -- force-cleaning objects
    cmake --build . --config Release --target clean
)
goto :pkg183_guard_done
:pkg183_guard_skip
echo [build_cuda_worktree] WARNING: python not on PATH; skipping pkg183 staleness guard
:pkg183_guard_done

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

REM --- pkg183 build stamp + host-only ABI canary -----------------------------
where python >nul 2>&1 || goto :pkg183_post_skip
python "%REPO_ROOT%\scripts\build\build_guard.py" write --repo-root "%REPO_ROOT%" --build-dir "%CD%" --sha %ACTUAL_SHA%
echo [build_cuda_worktree] pkg183: running host-only ABI canary (no GPU)...
python "%REPO_ROOT%\scripts\build\build_guard.py" canary --repo-root "%REPO_ROOT%" --build-dir "%CD%"
if errorlevel 1 (
    echo ====================================================================
    echo ERROR [pkg183]: ABI CANARY FAILED -- this is NOT a compile/link error.
    echo The freshly built astroray.pyd crashed on a host-only lambertian
    echo capability query -- the stale-object / ABI-mixed-binary signature.
    echo The binary is NOT trustworthy. Remedy: rmdir /s /q build_cuda ^&^& rebuild.
    echo ====================================================================
    exit /b 6
)
:pkg183_post_skip

echo [build_cuda_worktree] Build succeeded
exit /b 0
