"""Classify open PRs into action buckets. See plan §Shared data contracts."""
import subprocess
import json
from roadmap_orchestrator.ci import ci_state

BUCKETS = ("rebase_needed", "ci_failing", "hw_failed", "ready", "hw_untested", "in_progress")


def _hw_for_current_sha(pr: dict, ledger: dict):
    e = ledger.get(str(pr["number"]))
    if not e or e.get("head_sha") != pr.get("headRefOid"):
        return None
    return e.get("hw_result")


def _is_cpu_only_pr(pr: dict) -> bool:
    """
    Detect CPU-only PRs (no CUDA artifacts in the diff).

    Per pkg90 spec Phase 2.5: a PR whose diff touches no CUDA artifact (and
    whose Track/spec carries no GPU-port binding) is CPU-only for gating
    purposes. For such PRs, CI green == acceptance (the CPU↔CPU bit-identity
    / pytest tests/ gate is the real and sufficient gate — pkg55-B-prime
    L277). They are routed to CI-only gate, never the CUDA HW-untested queue.

    Returns True if the PR is CPU-only (no .cu/.cuh/CUDA build paths in diff).
    """
    n = pr["number"]
    try:
        # Get the PR's base ref (usually main)
        pr_info = subprocess.check_output(
            ["gh", "pr", "view", str(n), "--json", "baseRefName"],
            text=True
        )
        base_ref = json.loads(pr_info)["baseRefName"]

        # Get the diff file list
        files = subprocess.check_output(
            ["gh", "pr", "diff", str(n), "--name-only"],
            text=True
        ).splitlines()

        # Check if any file is a CUDA artifact
        cuda_extensions = {".cu", ".cuh"}
        cuda_paths = {"build_cuda", "cuda", "nvcc"}

        for f in files:
            # Check extension
            if any(f.endswith(ext) for ext in cuda_extensions):
                return False
            # Check path components (case-insensitive on Windows)
            f_lower = f.lower()
            if any(cuda_path in f_lower for cuda_path in cuda_paths):
                return False

        # No CUDA artifacts found
        return True
    except subprocess.CalledProcessError:
        # On error (e.g., gh unavailable), conservatively treat as non-CPU-only
        # (route to HW gate — safer to over-test than under-test)
        return False


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
