# -*- coding: utf-8 -*-
"""pkg264-cont — GPU-lock-guarded regression suite against the worktree build."""
import os
import subprocess
import sys
import time

WT = "C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray-pkg264"
LOCK = "C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray/.astroray_plan/.orchestrator.gpu.lock"
sys.path.insert(0, "C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray/scripts")
from roadmap_orchestrator.locks import acquire_lock, release_lock, lock_status  # noqa: E402

TESTS = [
    "tests/test_pkg264_glass_cycles_parity.py",
    "tests/test_dielectric_glass_furnace.py",
    "tests/test_disney_rough_glass_furnace.py",
    "tests/test_disney_energy_conservation.py",
    "tests/test_glass_sphere_caustic.py",
    "tests/test_pkg178_principled_gpu_furnace.py",
    "tests/test_rough_glass.py",
]


def main():
    deadline = time.time() + 40 * 60
    while not acquire_lock(LOCK, 5400, {"job": "pkg264cont", "what": "regression suite"}):
        if time.time() > deadline:
            raise SystemExit("gpu lock wait timeout: " + str(lock_status(LOCK, 5400)))
        time.sleep(30)
    try:
        bd = os.path.join(WT, "build_cuda")
        env = dict(os.environ, ASTRORAY_BUILD_DIR=bd)
        cmd = [sys.executable, os.path.join(WT, "scripts/dev/run_tests.py"),
               "--build-dir", bd] + [os.path.join(WT, t) for t in TESTS] + ["-q", "--no-header"]
        r = subprocess.run(cmd, cwd=WT, env=env)
        print("regression rc:", r.returncode)
        sys.exit(r.returncode)
    finally:
        release_lock(LOCK)


if __name__ == "__main__":
    main()
