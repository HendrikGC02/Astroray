@echo off
REM Worktree-parameterized CUDA build wrapper with MSVC bootstrap
REM Usage: build_cuda_worktree.bat <worktree-path> <expected-head-sha>
REM
REM This wrapper:
REM 1. Locates MSVC via vswhere (or falls back to hardcoded path)
REM 2. Initializes vcvars64.bat so cl.exe + nvcc are on PATH
REM 3. Validates the worktree is at the expected SHA
REM 4. Builds the CUDA target in the worktree's own build_cuda directory
REM
REM Exit codes:
REM   0 = build succeeded
REM   1 = missing arguments
REM   2 = MSVC bootstrap failed (cl.exe not on PATH after vcvars)
REM   3 = nvcc not found
REM   4 = worktree HEAD mismatch (contamination guard)
REM   5 = cmake build failed
REM   6 = pkg183 ABI canary failed (freshly built .pyd crashes on a host-only
REM       lambertian capability query = stale-object / ABI-mixed binary; distinct
REM       from a compile/link failure, which uses code 5)

setlocal enabledelayedexpansion

REM Parse arguments
if "%~1"=="" (
    echo ERROR: Missing worktree path argument
    echo Usage: build_cuda_worktree.bat ^<worktree-path^> ^<expected-head-sha^>
    exit /b 1
)
if "%~2"=="" (
    echo ERROR: Missing expected SHA argument
    echo Usage: build_cuda_worktree.bat ^<worktree-path^> ^<expected-head-sha^>
    exit /b 1
)

set "WORKTREE_PATH=%~1"
set "EXPECTED_SHA=%~2"

echo ========================================
echo CUDA Worktree Build
echo ========================================
echo Worktree: %WORKTREE_PATH%
echo Expected SHA: %EXPECTED_SHA%
echo.

REM Phase 1: MSVC bootstrap (idempotent)
echo [Phase 1] MSVC bootstrap...

REM Check if cl.exe is already on PATH (fast-path for dev shells)
where cl.exe >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo cl.exe already on PATH ^(dev shell^) - skipping vcvars init
    goto :check_nvcc
)

REM Locate MSVC via vswhere
set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if not exist "%VSWHERE%" goto :fallback_vcvars

echo Locating MSVC installation via vswhere...
for /f "usebackq tokens=*" %%i in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do (
    set "VS_INSTALL_PATH=%%i"
)

if not defined VS_INSTALL_PATH goto :fallback_vcvars
goto :have_vs_install

:fallback_vcvars
echo Falling back to hardcoded BuildTools path...
set "VCVARS_PATH=C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
goto :call_vcvars

:have_vs_install

set "VCVARS_PATH=%VS_INSTALL_PATH%\VC\Auxiliary\Build\vcvars64.bat"
echo Found MSVC at: %VS_INSTALL_PATH%

:call_vcvars
if not exist "!VCVARS_PATH!" (
    echo ERROR: vcvars64.bat not found at: !VCVARS_PATH!
    echo MSVC bootstrap failed - cannot locate vcvars64.bat
    exit /b 2
)

echo Calling: %VCVARS_PATH%
call "%VCVARS_PATH%"
if %ERRORLEVEL% neq 0 (
    echo ERROR: vcvars64.bat exited with code %ERRORLEVEL%
    exit /b 2
)

REM Verify cl.exe is now on PATH
where cl.exe >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo ERROR: MSVC bootstrap failed - cl.exe not on PATH after vcvars64
    exit /b 2
)
echo cl.exe located:
where cl.exe

:check_nvcc
REM Verify nvcc is on PATH
where nvcc.exe >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo ERROR: nvcc not found on PATH
    exit /b 3
)
echo nvcc located:
where nvcc.exe
echo.

REM Phase 2: Worktree validation and build
echo [Phase 2] Worktree validation...

REM Change to worktree
if not exist "%WORKTREE_PATH%" (
    echo ERROR: Worktree path does not exist: %WORKTREE_PATH%
    exit /b 4
)
cd /d "%WORKTREE_PATH%"
if %ERRORLEVEL% neq 0 (
    echo ERROR: Failed to cd to worktree: %WORKTREE_PATH%
    exit /b 4
)
echo Current directory: %CD%

REM Verify HEAD SHA
for /f "tokens=*" %%i in ('git rev-parse HEAD') do set "ACTUAL_SHA=%%i"
if not "%ACTUAL_SHA%"=="%EXPECTED_SHA%" (
    echo ERROR: Worktree HEAD mismatch - refusing to build stale/contaminated tree
    echo   Expected: %EXPECTED_SHA%
    echo   Actual:   %ACTUAL_SHA%
    exit /b 4
)
echo HEAD SHA verified: %ACTUAL_SHA%
echo.

REM Phase 3: Build
REM --config Release is REQUIRED: with a VS multi-config generator tree
REM (configure_and_build.bat / windows-cuda-vs preset) omitting it builds
REM Debug and dies with /RTC1 + /O2 -> D8016 on every .cu file. Same fix as
REM scripts/build/build_cuda_worktree.bat; see memory
REM build-cuda-worktree-debug-config.
echo [Phase 3] CUDA build...

REM --- pkg183 incremental-build staleness guard ------------------------------
REM This OneDrive tree defeats mtime-based staleness detection, so crossing a
REM layout-changing commit boundary can leave objects compiled against an old
REM struct layout to be linked with fresh ones (ABI-mixed binary -> host-side
REM access violations). Compare a hash of the layout-critical headers against
REM the last build's stamp; on mismatch force a full object clean (correctness
REM over speed) instead of trusting mtimes.
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [pkg183] WARNING: python not on PATH; skipping staleness guard
) else (
    set "GUARD_DECISION=OK"
    for /f "usebackq delims=" %%g in (`python "%CD%\scripts\build\build_guard.py" check --repo-root "%CD%" --build-dir "%CD%\build_cuda"`) do set "GUARD_DECISION=%%g"
    if "!GUARD_DECISION!"=="WIPE" (
        echo [pkg183] layout-critical headers changed since last build -- force-cleaning objects
        cmake --build build_cuda --config Release --target clean
    )
)

echo Running: cmake --build build_cuda --config Release --target astroray
cmake --build build_cuda --config Release --target astroray
if %ERRORLEVEL% neq 0 (
    echo ERROR: cmake build failed with code %ERRORLEVEL%
    exit /b 5
)

REM astroray_test_helpers is a separate target not pulled in by astroray;
REM gate tests (test_pkg92_*) import it and fail with a spurious
REM ModuleNotFoundError without this step.
echo Running: cmake --build build_cuda --config Release --target astroray_test_helpers
cmake --build build_cuda --config Release --target astroray_test_helpers
if %ERRORLEVEL% neq 0 (
    echo ERROR: astroray_test_helpers build failed with code %ERRORLEVEL%
    exit /b 5
)

REM --- pkg183 build stamp + host-only ABI canary -----------------------------
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [pkg183] WARNING: python not on PATH; skipping build stamp + ABI canary
) else (
    python "%CD%\scripts\build\build_guard.py" write --repo-root "%CD%" --build-dir "%CD%\build_cuda" --sha %ACTUAL_SHA%
    echo [pkg183] running host-only ABI canary ^(no GPU^)...
    python "%CD%\scripts\build\build_guard.py" canary --repo-root "%CD%" --build-dir "%CD%\build_cuda"
    if !ERRORLEVEL! neq 0 (
        echo ====================================================================
        echo ERROR [pkg183]: ABI CANARY FAILED -- this is NOT a compile/link error.
        echo The freshly built astroray.pyd crashed on a host-only lambertian
        echo capability query -- the stale-object / ABI-mixed-binary signature.
        echo The binary is NOT trustworthy. Remedy: rmdir /s /q build_cuda then rebuild.
        echo ====================================================================
        exit /b 6
    )
)

echo.
echo ========================================
echo Build succeeded
echo ========================================
exit /b 0
