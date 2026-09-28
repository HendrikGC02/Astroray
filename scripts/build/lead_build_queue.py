"""Lead-only serial CUDA / addon build queue for multi-worktree sessions.

Usage (one build per background task, so each completion notifies):
    python scripts/build/lead_build_queue.py <lane>[:addon-cpu|:addon-cuda|:addon-cpu-clean]

<lane> is "main" (this checkout) or a sibling worktree suffix: "batchZ" builds
../Astroray-batchZ. CUDA builds go through scripts/build/build_cuda_worktree.bat
without the sccache launcher (it drops >10 min stage_advance.cu compiles).

- Own lock (.astroray_plan/.lead.build.lock), not the GPU lock, so lane test runs
  are not blocked; nvcc builds never overlap (two sm_120 -rdc builds kill each other).
- FIFO tickets: only the oldest live requester takes the lock.
- The worktree SHA is read after the lock is taken, so commits made while queued
  are built.
- A lock whose holder process is dead (e.g. after a reset or a stopped task) is
  cleared.
Logs and tickets: %LOCALAPPDATA%\\astroray-lead-builds\\.
"""
import ctypes
import os
import subprocess
import sys
import time

MAIN = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(MAIN, "scripts", "roadmap_orchestrator"))
from locks import acquire_lock, release_lock  # noqa: E402

LOCK = os.path.join(MAIN, ".astroray_plan", ".lead.build.lock")
WORK = os.path.join(os.environ["LOCALAPPDATA"], "astroray-lead-builds")
TICKETS = os.path.join(WORK, "tickets")
os.makedirs(TICKETS, exist_ok=True)
# Shared FetchContent cache: an uncached pybind11 git clone hung a build for 8+ min.
os.environ.setdefault("FETCHCONTENT_BASE_DIR",
                      os.path.join(os.environ["LOCALAPPDATA"], "astroray-cache", "fetchcontent"))


def _alive(pid):
    h = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if h:
        ctypes.windll.kernel32.CloseHandle(h)
        return True
    return False


def _oldest_live():
    for t in sorted(os.listdir(TICKETS)):
        if _alive(int(t.split("_")[1])):
            return t
        os.remove(os.path.join(TICKETS, t))  # dead waiter
    return None


def _cuda_cmd(wt, sha):
    ninja = os.path.join(os.environ["LOCALAPPDATA"], "Microsoft", "WinGet", "Packages",
                         "Ninja-build.Ninja_Microsoft.Winget.Source_8wekyb3d8bbwe")
    links = os.path.join(os.environ["LOCALAPPDATA"], "Microsoft", "WinGet", "Links")
    env = dict(os.environ)
    env["PATH"] = ninja + ";" + env["PATH"].replace(links + ";", "")  # no sccache shim
    bat = os.path.join(MAIN, "scripts", "build", "build_cuda_worktree.bat")
    return ["cmd", "/c", bat, wt, sha], env


for item in sys.argv[1:]:
    lane, _, kind = item.partition(":")
    wt = MAIN if lane == "main" else os.path.join(os.path.dirname(MAIN), f"Astroray-{lane}")
    ticket = os.path.join(TICKETS, f"{time.time_ns()}_{os.getpid()}_{lane}_{kind or 'cuda'}")
    open(ticket, "w").close()
    no_nvcc = kind.startswith("addon-cpu")  # MinGW-only build: safe beside a CUDA build
    while not no_nvcc:
        if _oldest_live() == os.path.basename(ticket) and acquire_lock(LOCK, meta={"who": f"lead-{lane}"}):
            break
        time.sleep(20)
    os.remove(ticket)
    sha = subprocess.run(["git", "-C", wt, "rev-parse", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    t0 = time.time()
    try:
        env = None
        if kind.startswith("addon"):
            log = os.path.join(WORK, f"build_{lane}_{kind}.log")
            cmd = [sys.executable, os.path.join(wt, "scripts", "build", "build_blender_addon.py"),
                   "--backend", kind.split("-")[1]] + (["--clean"] if kind.endswith("-clean") else [])
        else:
            log = os.path.join(WORK, f"build_{lane}.log")
            cmd, env = _cuda_cmd(wt, sha)
        with open(log, "w", encoding="utf-8", errors="replace") as lf:
            r = subprocess.run(cmd, cwd=wt, stdout=lf, stderr=subprocess.STDOUT, env=env)
        print(f"[{lane}{':' + kind if kind else ''}] exit {r.returncode} sha {sha} "
              f"{int(time.time() - t0)}s log {log}", flush=True)
    finally:
        if not no_nvcc:
            release_lock(LOCK)
