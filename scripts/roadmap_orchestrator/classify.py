"""Classify open PRs into action buckets. See plan §Shared data contracts."""
from roadmap_orchestrator.ci import ci_state

BUCKETS = ("rebase_needed", "ci_failing", "hw_failed", "ready", "hw_untested", "in_progress")


def _hw_for_current_sha(pr: dict, ledger: dict):
    e = ledger.get(str(pr["number"]))
    if not e or e.get("head_sha") != pr.get("headRefOid"):
        return None
    return e.get("hw_result")


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
        if hw == "FAIL":
            out["hw_failed"].append(n); continue
        if pr.get("mergeable") == "MERGEABLE" and ci_state(pr) == "pass" and hw == "PASS":
            out["ready"].append(n); continue
        if pr.get("mergeable") == "MERGEABLE" and hw is None:
            out["hw_untested"].append(n); continue
        out["in_progress"].append(n)
    return out
