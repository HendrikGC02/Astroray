#!/usr/bin/env python
"""Rebuild Astroray with MSVC toolchain."""
import subprocess
import sys
from pathlib import Path

repo_root = Path(__file__).parent.resolve()
build_dir = repo_root / "build_cuda"

# Call vcvars64 and then cmake/ninja
vcvars = r"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"

# Configure if needed
if not (build_dir / "build.ninja").exists():
    cmd_configure = f'"{vcvars}" >nul && cmake -B build_cuda -G Ninja -DCMAKE_BUILD_TYPE=Release -DASTRORAY_ENABLE_CUDA=ON -DASTRORAY_ENABLE_HARDWARE_VERIFIER_TESTS=OFF'
    print(f"Configuring... {cmd_configure}")
    result = subprocess.run(cmd_configure, shell=True, cwd=repo_root)
    if result.returncode != 0:
        print(f"Configure failed with {result.returncode}")
        sys.exit(1)

# Build
cmd_build = f'"{vcvars}" >nul && cmake --build build_cuda --config Release -j 8'
print(f"Building... {cmd_build}")
result = subprocess.run(cmd_build, shell=True, cwd=repo_root)
sys.exit(result.returncode)
