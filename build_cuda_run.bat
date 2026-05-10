@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
cd /d "C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray"
cmake --build build_cuda --target astroray
