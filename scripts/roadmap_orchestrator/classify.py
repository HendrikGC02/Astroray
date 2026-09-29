"""Classify open PRs into action buckets. See plan §Shared data contracts."""
import functools
import json
import re
import subprocess
from pathlib import Path
from roadmap_orchestrator.ci import ci_state

BUCKETS = ("rebase_needed", "ci_failing", "hw_failed", "ready", "hw_untested", "in_progress")


def _hw_for_current_sha(pr: dict, ledger: dict):
    e = ledger.get(str(pr["number"]))
    if not e or e.get("head_sha") != pr.get("headRefOid"):
        return None
    return e.get("hw_result")


_REPO_ROOT = Path(__file__).resolve().parents[2]
_INCLUDE_RE = re.compile(r'^\s*#\s*include\s+"([^"]+)"', re.MULTILINE)


@functools.lru_cache(maxsize=None)
def _cuda_reachable_files(repo_root: Path = _REPO_ROOT) -> frozenset:
    """Repo-relative posix paths of every file reachable from a CUDA TU.

    Seeds are src/gpu/**/*.cu and *.cuh; `#include "..."` is followed
    transitively, resolving against the including file's dir, <repo>/include
    and <repo>. A change to any such header (e.g. include/astroray/gpu_materials.h,
    also included by CPU code) can alter GPU kernels, so it is not CPU-only.
    """
    gpu = repo_root / "src" / "gpu"
    seen, stack = set(), [p for pat in ("*.cu", "*.cuh") for p in gpu.rglob(pat)]
    while stack:
        f = stack.pop()
        if f in seen or not f.is_file():
            continue
        seen.add(f)
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for inc in _INCLUDE_RE.findall(text):
            for base in (f.parent, repo_root / "include", repo_root):
                cand = (base / inc).resolve()
                if cand.is_file():
                    stack.append(cand)
                    break
    root = repo_root.resolve()
    return frozenset(p.resolve().relative_to(root).as_posix()
                     for p in seen if root in p.resolve().parents)


def _is_cpu_only_pr(pr: dict) -> bool:
    """
    Detect CPU-only PRs (no CUDA artifacts in the diff).

    Per pkg90 spec Phase 2.5: a PR whose diff touches no CUDA artifact (and
    whose Track/spec carries no GPU-port binding) is CPU-only for gating
    purposes. For such PRs, CI green == acceptance (the CPU↔CPU bit-identity
    / pytest tests/ gate is the real and sufficient gate — pkg55-B-prime
    L277). They are routed to CI-only gate, never the CUDA HW-untested queue.

    Source of file list (in priority order):
      1. pr["files"] — pre-fetched by cli.py for live PRs; also lets unit
         tests inject a synthetic file list without hitting gh.
      2. Live `gh pr diff` — fallback for callers that didn't enrich.

    Returns True if the PR is CPU-only: no .cu/.cuh/CUDA build paths, no
    CMakeLists.txt / cmake/**, and no header reachable from a CUDA TU.
    """
    files = pr.get("files")
    if files is None:
        n = pr["number"]
        try:
            # Verify the live PR's head SHA matches what the caller passed in.
            # If not, we're being handed synthetic / replay data (e.g. unit
            # tests with fake SHAs colliding with real PR numbers); fall back
            # to the conservative "route to HW gate" answer.
            head = subprocess.check_output(
                ["gh", "pr", "view", str(n), "--json", "headRefOid"],
                text=True, stderr=subprocess.DEVNULL,
            )
            if json.loads(head).get("headRefOid") != pr.get("headRefOid"):
                return False
            files = subprocess.check_output(
                ["gh", "pr", "diff", str(n), "--name-only"],
                text=True
            ).splitlines()
        except (subprocess.CalledProcessError, FileNotFoundError):
            # gh unavailable or PR not on GitHub (e.g. synthetic test PR):
            # conservatively treat as non-CPU-only — route to HW gate.
            return False

    cuda_extensions = {".cu", ".cuh"}
    cuda_paths = {"build_cuda", "cuda", "nvcc"}

    cuda_reachable = _cuda_reachable_files()
    for f in files:
        if any(f.endswith(ext) for ext in cuda_extensions):
            return False
        if f == "CMakeLists.txt" or f.endswith("/CMakeLists.txt") or f.startswith("cmake/"):
            return False
        if f in cuda_reachable:
            return False
        f_lower = f.lower()
        if any(cuda_path in f_lower for cuda_path in cuda_paths):
            return False

    return True


def classify_prs(prs: list, ledger: dict) -> dict:
    out = {k: [] for k in BUCKETS}
    for pr in prs:
        n = pr["number"]
        if pr.get("isDraft"):
            out["in_progress"].append(n); continue
        if pr.get("mergeable") == "CONFLICTING" or pr.get("mergeStateStatus") == "BEHIND":
            out["rebase_needed"].append(n); continue
        if ci_state(pr) == "fail":
            out["ci_failing"].append(n); continue
        hw = _hw_for_current_sha(pr, ledger)
        # PARTIAL = verifier ran but some acceptance gates were inert / not
        # exercised (e.g. probe-harness landed without full input plumbing).
        # Route via the same fix-implementer path as FAIL; do not merge.
        if hw in ("FAIL", "PARTIAL"):
            out["hw_failed"].append(n); continue
        if pr.get("mergeable") == "MERGEABLE" and ci_state(pr) == "pass" and hw == "PASS":
            out["ready"].append(n); continue
        # CPU-only carve-out (pkg90 Phase 2.5): CI-green + CPU-only → Ready (bypass HW-untested)
        if pr.get("mergeable") == "MERGEABLE" and ci_state(pr) == "pass" and hw is None and _is_cpu_only_pr(pr):
            out["ready"].append(n); continue
        if pr.get("mergeable") == "MERGEABLE" and hw is None:
            out["hw_untested"].append(n); continue
        out["in_progress"].append(n)
    return out
