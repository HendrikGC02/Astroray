# -*- coding: utf-8 -*-
"""pkg264-cont — acquire the GPU lock, build the worktree (launcher-free), then
run the CPU+GPU furnace gates against the freshly-built .pyd. Foreground, logged.
"""
import os
import subprocess
import sys
import time

WT = "C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray-pkg264"
LOCK = "C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray/.astroray_plan/.orchestrator.gpu.lock"
LOG = os.path.join(WT, "test_results/2026-09-08-pkg264cont/build.log")
sys.path.insert(0, "C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray/scripts")
from roadmap_orchestrator.locks import acquire_lock, release_lock, lock_status  # noqa: E402


def run(cmd, **kw):
    print(">>>", cmd, flush=True)
    return subprocess.run(cmd, **kw)


def main():
    deadline = time.time() + 45 * 60
    while not acquire_lock(LOCK, 5400, {"job": "pkg264cont", "what": "cuda build + furnace"}):
        if time.time() > deadline:
            raise SystemExit("gpu lock wait timeout: " + str(lock_status(LOCK, 5400)))
        print("waiting for gpu lock...", lock_status(LOCK, 5400), flush=True)
        time.sleep(30)
    try:
        t0 = time.time()
        with open(LOG, "w") as f:
            p = subprocess.run(["cmd", "/c", os.path.join(WT, "build_nosccache.bat")],
                               cwd=WT, stdout=f, stderr=subprocess.STDOUT, text=True)
        tail = open(LOG, encoding="utf-8", errors="replace").read().splitlines()[-8:]
        print(f"\n=== build rc={p.returncode}  ({(time.time()-t0)/60:.1f} min) ===")
        print("\n".join(tail))
        if p.returncode != 0:
            raise SystemExit("BUILD FAILED rc=" + str(p.returncode))

        # CPU + GPU furnace gates against the worktree build.
        bd = os.path.join(WT, "build_cuda")
        env = dict(os.environ, ASTRORAY_BUILD_DIR=bd)
        r = run([sys.executable, os.path.join(WT, "scripts/dev/run_tests.py"),
                 "--build-dir", bd,
                 os.path.join(WT, "tests/test_pkg264_glass_cycles_parity.py"),
                 "-v"], cwd=WT, env=env)
        print("furnace gate rc:", r.returncode)
    finally:
        release_lock(LOCK)


if __name__ == "__main__":
    main()
