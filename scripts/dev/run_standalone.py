#!/usr/bin/env python
"""Run the Astroray standalone binary with repo-local runtime paths.

On Windows, the CUDA/OIDN standalone executable needs dependent DLL directories
on PATH. Tests already configure those paths through tests/runtime_setup.py;
this launcher applies the same setup before forwarding arguments to raytracer.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = ROOT / "tests"
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from runtime_setup import configure_test_imports, find_standalone_executable  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run build_cuda/build standalone raytracer with DLL paths configured.",
        add_help=False,
    )
    parser.add_argument("--build-dir", help="Specific CMake build directory to use.")
    parser.add_argument("--print-exe", action="store_true", help="Print selected executable path.")
    known, passthrough = parser.parse_known_args(argv)

    configure_test_imports()
    exe = find_standalone_executable(known.build_dir)
    if exe is None:
        print("error: raytracer executable not found. Build first with:", file=sys.stderr)
        print("  cmake --build --preset windows-cuda-vs-release", file=sys.stderr)
        return 2

    if known.print_exe:
        print(exe)

    completed = subprocess.run([exe, *passthrough], cwd=ROOT, env=os.environ.copy())
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
