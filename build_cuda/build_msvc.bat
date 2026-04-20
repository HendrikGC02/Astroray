@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" x64
cd /d "C:\Users\hgcom\OneDrive\Astroray\Astroray_repo\Astroray\build_cuda"
nmake
echo NMAKE_EXIT=%ERRORLEVEL%
