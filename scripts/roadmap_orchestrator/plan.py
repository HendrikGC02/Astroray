"""Pure tick-plan builder. Decides; never acts. See design spec Step 1/2/2a."""
from datetime import datetime, timezone
from roadmap_orchestrator.classify import classify_prs
from roadmap_orchestrator.queue import order_hw_queue

# Actions that suppress re-dispatching a CI/rebase fixer or gate-failure-reviewer.
# gate_review_dispatched prevents re-firing the reviewer on every tick (pattern #2).
# ci_failing_hold_for_owner_bias is the owner-held CI state: do NOT auto-re-dispatch
# a fixer while the owner is holding the PR for review (2026-08-20).
_DEBOUNCE_ACTIONS = {
    "rebase_dispatched",
    "ci_dispatched",
    "gate_review_dispatched",
    "ci_failing_hold_for_owner_bias",
}

# Actions that suppress re-dispatching the HW verifier for a PR.
# hw_blocked_buildenv covers MSVC/CUDA env absent in remote contexts (pattern #7).
_HW_DEBOUNCE_ACTIONS = {"hw_dispatched", "hw_blocked_buildenv"}

_HW_DEBOUNCE_SECS = 86400  # 24 h — build env changes slowly


def _age_secs(then_iso: str, now_iso: str) -> float:
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    t = datetime.strptime(then_iso, fmt).replace(tzinfo=timezone.utc)
    n = datetime.strptime(now_iso, fmt).replace(tzinfo=timezone.utc)
    return (n - t).total_seconds()


def _debounced(ledger, n, now_iso, secs):
    e = ledger.get(str(n))
    if not e or e.get("last_action") not in _DEBOUNCE_ACTIONS:
        return False
    ts = e.get("last_action_ts")
    return bool(ts) and _age_secs(ts, now_iso) < secs


def _hw_debounced(ledger, n, now_iso):
    e = ledger.get(str(n))
    if not e or e.get("last_action") not in _HW_DEBOUNCE_ACTIONS:
        return False
    ts = e.get("last_action_ts")
    return bool(ts) and _age_secs(ts, now_iso) < _HW_DEBOUNCE_SECS


def build_tick_plan(prs, ledger, priority, eligible_packages, in_flight_count,
                    impl_cap, fixer_cap, gpu_lock_free, fixer_debounce_secs, now_iso):
    buckets = classify_prs(prs, ledger)
    prs_by_n = {p["number"]: p for p in prs}

    free = max(0, impl_cap - in_flight_count)
    dispatch = list(eligible_packages)[:free]

    fixers = []
    for n in buckets["rebase_needed"]:
        if len(fixers) < fixer_cap and not _debounced(ledger, n, now_iso, fixer_debounce_secs):
            fixers.append({"pr": n, "kind": "rebase"})
    for n in buckets["ci_failing"]:
        if len(fixers) < fixer_cap and not _debounced(ledger, n, now_iso, fixer_debounce_secs):
            fixers.append({"pr": n, "kind": "ci"})

    hw_dispatch = None
    if gpu_lock_free and buckets["hw_untested"]:
        candidates = [
            n for n in order_hw_queue(buckets["hw_untested"], prs_by_n, priority)
            if not _hw_debounced(ledger, n, now_iso)
        ]
        hw_dispatch = candidates[0] if candidates else None

    # Debounce gate-failure-reviewer for hw_failed PRs (pattern #2): skip if
    # gate_review_dispatched was recorded within fixer_debounce_secs.
    hw_failed = [
        n for n in buckets["hw_failed"]
        if not _debounced(ledger, n, now_iso, fixer_debounce_secs)
    ]

    return {
        "dispatch": dispatch,
        "fixers": fixers,
        "hw_dispatch": hw_dispatch,
        "merges": list(buckets["ready"]),
        "hw_failed": hw_failed,
        "buckets": buckets,
    }
