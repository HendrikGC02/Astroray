"""Read-only tick-plan emitter. Side effects belong to SKILL.md, never here."""
import argparse, json, subprocess, sys
from roadmap_orchestrator.state import load_ledger
from roadmap_orchestrator.priority import parse_priority
from roadmap_orchestrator.plan import build_tick_plan
from roadmap_orchestrator.standup import render_standup

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
    ap.add_argument("--gpu-lock-free", action="store_true", default=True)
    a = ap.parse_args(argv)

    prs = json.load(open(a.prs_json, encoding="utf-8")) if a.prs_json else _gh_prs()
    ledger = load_ledger(a.ledger)
    priority = parse_priority(open(a.next_stage_report, encoding="utf-8").read())
    eligible = [p for p in a.eligible.split(",") if p]

    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    plan = build_tick_plan(prs, ledger, priority, eligible, a.in_flight,
                           IMPL_CAP, FIXER_CAP, a.gpu_lock_free,
                           FIXER_DEBOUNCE, now_iso)
    out = {"plan": plan,
           "standup_md": render_standup(plan, gpu_holder=None,
                                        hw_queue=plan["buckets"]["hw_untested"]),
           "dry_run": bool(a.dry_run)}
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
