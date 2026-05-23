@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >/dev/null 2>&1
cd /d "C:\Users\hgcom\OneDrive\Astroray\Astroray_repo\Astroray-pkg64-gpu-sellmeier-upload"
echo Starting CMake build...
cmake --build build_cuda --target astroray
echo Build complete with exit code: %ERRORLEVEL%
