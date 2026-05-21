"""Read-only tick-plan emitter. Side effects belong to SKILL.md, never here."""
import argparse, json, subprocess, sys
from datetime import datetime, timezone
from roadmap_orchestrator.state import load_ledger
from roadmap_orchestrator.priority import parse_priority
from roadmap_orchestrator.plan import build_tick_plan
from roadmap_orchestrator.standup import render_standup

# Canonical stale thresholds (seconds) passed by SKILL.md to locks.lock_status; not used by this read-only CLI.
TICK_LOCK_STALE = 1500   # 25 min
GPU_LOCK_STALE = 5400    # 90 min
IMPL_CAP = 2
FIXER_CAP = 1
FIXER_DEBOUNCE = 3600


def _gh_prs() -> list:
    fields = ("number,title,headRefName,headRefOid,isDraft,mergeable,"
              "mergeStateStatus,statusCheckRollup,createdAt")
    raw = subprocess.check_output(
        ["gh", "pr", "list", "--state", "open", "--json", fields], text=True)
    return json.loads(raw)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="roadmap_orchestrator.cli")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--prs-json")
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--next-stage-report", required=True)
    ap.add_argument("--eligible", default="")
    ap.add_argument("--in-flight", type=int, default=0)
    ap.add_argument("--gpu-lock-free", action="store_true", default=False)
    a = ap.parse_args(argv)

    if a.prs_json:
        with open(a.prs_json, encoding="utf-8") as f:
            prs = json.load(f)
    else:
        prs = _gh_prs()
    ledger = load_ledger(a.ledger)
    with open(a.next_stage_report, encoding="utf-8") as f:
        priority = parse_priority(f.read())
    eligible = [p for p in a.eligible.split(",") if p]

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    plan = build_tick_plan(prs, ledger, priority, eligible, a.in_flight,
                           IMPL_CAP, FIXER_CAP, a.gpu_lock_free,
                           FIXER_DEBOUNCE, now_iso)
    # Query merged-today for standup (Phase 2: pkg97 fix)
    from roadmap_orchestrator.standup import _get_merged_today
    merged_today = _get_merged_today()
    out = {"plan": plan,
           "standup_md": render_standup(plan, gpu_holder=None,
                                        hw_queue=plan["buckets"]["hw_untested"],
                                        merged_today=merged_today,
                                        ledger=ledger),
           "dry_run": bool(a.dry_run)}
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
