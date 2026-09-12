"""Run a CUDA build .bat under the orchestrator GPU lock (poll, run, release-in-finally)."""
import os, subprocess, sys, time
repo = sys.argv[1]; bat = sys.argv[2]; who = sys.argv[3] if len(sys.argv) > 3 else "lead-build"
sys.path.insert(0, os.path.join(repo, "scripts", "roadmap_orchestrator"))
from locks import acquire_lock, release_lock, lock_status
# ALWAYS the MAIN checkout's lock, regardless of which worktree is being built —
# a worktree-relative lock is invisible to every other lane (bitten 2026-09-09, pkg262).
LOCK = os.path.join("C:\\Users\\hgcom\\OneDrive\\Astroray\\Astroray_repo\\Astroray",
                    ".astroray_plan", ".orchestrator.gpu.lock")
sha = subprocess.run(["git", "-C", repo, "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
t0 = time.time()
while not acquire_lock(LOCK, 5400, {"who": who, "sha": sha, "bat": bat}):
    st = lock_status(LOCK, 5400)
    print(f"[lock] held by {st['meta']}, waiting... ({int(time.time()-t0)}s)", flush=True)
    time.sleep(30)
print(f"[lock] acquired for {who} @ {sha} after {int(time.time()-t0)}s", flush=True)
try:
    r = subprocess.run(["cmd", "/c", bat], cwd=repo)
    print(f"[build] exit {r.returncode} after {int(time.time()-t0)}s", flush=True)
    sys.exit(r.returncode)
finally:
    release_lock(LOCK)
    print("[lock] released", flush=True)
