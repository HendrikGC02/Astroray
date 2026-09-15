"""Run an arbitrary command under the orchestrator GPU lock (poll, run, release-in-finally).

Usage: python scripts/build/gpu_locked_run.py <who> -- <command...>
The lock is ALWAYS the MAIN checkout's lock file. The command runs in the current
working directory. Never write the lock file yourself (memory
`gpu-lock-lanes-overwrite-lock-file`); this helper only ever acquires/releases
via locks.py, which refuses to remove a lock it does not own.
"""
import os, subprocess, sys, time
MAIN = "C:\Users\hgcom\OneDrive\Astroray\Astroray_repo\Astroray"
sys.path.insert(0, os.path.join(MAIN, "scripts", "roadmap_orchestrator"))
from locks import acquire_lock, release_lock, lock_status
LOCK = os.path.join(MAIN, ".astroray_plan", ".orchestrator.gpu.lock")
args = sys.argv[1:]
if "--" not in args or args.index("--") == 0:
    print(__doc__); sys.exit(2)
who = args[0]; cmd = args[args.index("--") + 1:]
t0 = time.time()
while not acquire_lock(LOCK, 5400, {"who": who, "cmd": " ".join(cmd)[:120]}):
    st = lock_status(LOCK, 5400)
    print(f"[lock] held by {st['meta']}, waiting... ({int(time.time()-t0)}s)", flush=True)
    time.sleep(30)
print(f"[lock] acquired for {who} after {int(time.time()-t0)}s", flush=True)
try:
    r = subprocess.run(cmd)
    print(f"[run] exit {r.returncode} after {int(time.time()-t0)}s", flush=True)
    sys.exit(r.returncode)
finally:
    release_lock(LOCK)
    print("[lock] released", flush=True)
