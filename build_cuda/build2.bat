@echo off
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat" x64
cd /d "C:\Users\hgcom\OneDrive\Astroray\Astroray_repo\Astroray\build_cuda"
nmake
