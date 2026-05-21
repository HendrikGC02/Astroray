"""Render and upsert the daily standup markdown. No GPU-debt ledger by design."""
import os, glob, subprocess, json
from datetime import datetime, timezone


def _get_merged_today() -> list:
    """Query gh for PRs merged in the current local day."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        # Query all merged PRs (gh pr list defaults to open; use --state merged)
        raw = subprocess.check_output(
            ["gh", "pr", "list", "--state", "merged", "--json",
             "number,title,mergedAt,headRefName"],
            text=True, stderr=subprocess.DEVNULL
        )
        prs = json.loads(raw)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return []

    # Filter to PRs merged today (local day boundary)
    merged_today = []
    for pr in prs:
        merged_at_str = pr.get("mergedAt")
        if not merged_at_str:
            continue
        # Parse ISO 8601 timestamp
        merged_at = datetime.fromisoformat(merged_at_str.replace("Z", "+00:00"))
        if merged_at >= today_start:
            merged_today.append(pr["number"])
    return merged_today


def render_standup(plan: dict, gpu_holder, hw_queue: list, merged_today=None, gc_report=None, ledger: dict = None) -> str:
    """Render standup markdown.

    merged_today: list of PR numbers merged today (defaults to gh query).
    gc_report: dict with {"removed": [...], "escalations": [...]} from gc_merged_worktrees.
    ledger: optional; used to surface independent-review verdicts.
    """
    b = plan["buckets"]
    if merged_today is None:
        merged_today = _get_merged_today()
    ledger = ledger or {}

    L = []
    L.append("# Standup")
    L.append("
## Shipped today")
    L += [f"- #{n} � CI-green + hardware-PASS" for n in merged_today] or ["- (none)"]
    L.append("
## In-flight")
    L += [f"- dispatch: {p}" for p in plan["dispatch"]] or ["- (none)"]
    L.append("
## Blocked")
    L += [f"- #{n} in progress" for n in b["in_progress"]] or ["- (none)"]
    L.append("
## Hardware gate")
    L.append(f"- GPU lock holder: {gpu_holder or '(free)'}")
    L.append(f"- HW-untested queue: {hw_queue or '(empty)'}")
    L.append("\n## CI under repair")
    for f in plan["fixers"]:
        n = f['pr']
        e = ledger.get(str(n), {})
        last_action = e.get("last_action", "")
        if last_action.startswith("indep_review:"):
            verdict = last_action.split(":", 1)[1]
            L.append(f"- #{n} ({f['kind']}) — independent review: {verdict}")
        else:
            L.append(f"- #{n} ({f['kind']})")
    if not plan["fixers"]:
        L.append("- (none)")
    L.append("
## Action items")
    for n in plan["hw_failed"]:
        e = ledger.get(str(n), {})
        last_action = e.get("last_action", "")
        if last_action == "indep_review:BLOCK":
            L.append(f"- #{n} HARDWARE FAILED + independent review BLOCKED fix — owner attention")
        else:
            L.append(f"- #{n} HARDWARE FAILED — owner attention")
    if not plan["hw_failed"]:
    if gc_report and gc_report.get("escalations"):
        L += [f"- Worktree GC: {msg}" for msg in gc_report["escalations"]]
    if not (plan["hw_failed"] or (gc_report and gc_report.get("escalations"))):
        L.append("- (none)")
    return "
".join(L) + "
"


def upsert_standup(directory: str, date: str, plan: dict, gpu_holder, hw_queue,
                   merged_today=None, gc_report=None, ledger: dict = None) -> str:
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{date}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(render_standup(plan, gpu_holder, hw_queue, merged_today, gc_report, ledger))
    return path


def finalize_previous(directory: str, today: str) -> None:
    for path in sorted(glob.glob(os.path.join(directory, "*.md"))):
        name = os.path.basename(path)[:-3]
        if name >= today:
            continue
        with open(path, "r", encoding="utf-8") as f:
            txt = f.read()
        if "<!-- finalized -->" not in txt:
            with open(path, "a", encoding="utf-8") as f:
                f.write("\n<!-- finalized -->\n")
