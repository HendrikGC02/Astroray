@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" x64
if errorlevel 1 exit /b 1
set CUDA_PATH=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8
set FETCHCONTENT_BASE_DIR=%LOCALAPPDATA%\astroray-cache\fetchcontent
set "REPO_ROOT=%CD%"
cd build_cuda
cmake .. -G Ninja -DCMAKE_BUILD_TYPE=Release -DBUILD_PYTHON_MODULE=ON -DASTRORAY_ENABLE_CUDA=ON -DASTRORAY_CUDA_ARCHS=native -DCMAKE_CXX_COMPILER_LAUNCHER= -DCMAKE_CUDA_COMPILER_LAUNCHER= -DFETCHCONTENT_BASE_DIR="%FETCHCONTENT_BASE_DIR%" -DCMAKE_CUDA_COMPILER="%CUDA_PATH%\bin\nvcc.exe"
if errorlevel 1 (echo CMake configure failed & exit /b 1)
cmake --build . --config Release --target astroray
if errorlevel 1 (echo Build failed & exit /b 1)
cmake --build . --config Release --target astroray_test_helpers
if errorlevel 1 (echo helpers build failed & exit /b 1)
for /f %%i in ('git -C "%REPO_ROOT%" rev-parse HEAD') do set HEAD_SHA=%%i
python "%REPO_ROOT%\scripts\build\build_guard.py" write --repo-root "%REPO_ROOT%" --build-dir "%CD%" --sha %HEAD_SHA%
python "%REPO_ROOT%\scripts\build\build_guard.py" arch-verify --pyd-dir "%CD%"
if errorlevel 1 (echo ARCH GATE FAILED & exit /b 7)
python "%REPO_ROOT%\scripts\build\build_guard.py" canary --repo-root "%REPO_ROOT%" --build-dir "%CD%"
if errorlevel 1 (echo CANARY FAILED & exit /b 6)
echo BUILD OK