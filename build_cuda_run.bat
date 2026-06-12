@echo off
cd /d "%~dp0"
cmake --build build_cuda --config Release --target astroray
