@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
cd /d "C:\Users\hgcom\OneDrive\Astroray\Astroray_repo\Astroray\..Astroray-vndf"
rmdir /s /q build_cuda
cmake -S . -B build_cuda -G Ninja -DCMAKE_BUILD_TYPE=Release -DASTRORAY_ENABLE_CUDA=ON -DASTRORAY_ENABLE_OIDN=ON -DASTRORAY_ENABLE_OPTIX=AUTO -DBUILD_PYTHON_MODULE=ON -DBUILD_TESTS=ON
cmake --build build_cuda --target astroray
