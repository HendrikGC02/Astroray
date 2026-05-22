@echo off
REM Simple worktree build script
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
cd /d "%~dp0"

if not exist build_cuda (
    echo Configuring CMake...
    cmake -B build_cuda -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_COMPILER=cl -DCMAKE_CXX_COMPILER=cl -DCMAKE_CUDA_COMPILER=nvcc -DASTRORAY_USE_CUDA=ON
    if %ERRORLEVEL% neq 0 (
        echo CMake configure failed
        exit /b 1
    )
)

echo Building...
cmake --build build_cuda --target astroray
if %ERRORLEVEL% neq 0 (
    echo Build failed
    exit /b 1
)

echo Build succeeded
