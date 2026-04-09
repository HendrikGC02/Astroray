@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" x64
if errorlevel 1 (echo vcvarsall failed & exit /b 1)

set CUDA_PATH=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.6
set NVCC=%CUDA_PATH%\bin\nvcc.exe

mkdir build_cuda 2>nul
cd build_cuda

cmake .. ^
  -G "NMake Makefiles" ^
  -DCMAKE_BUILD_TYPE=Release ^
  -DBUILD_PYTHON_MODULE=ON ^
  -DASTRORAY_ENABLE_CUDA=ON ^
  -DCMAKE_CUDA_COMPILER="%NVCC%"

if errorlevel 1 (echo CMake configure failed & exit /b 1)

cmake --build . --target astroray
