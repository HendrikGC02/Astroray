"""Render and upsert the daily standup markdown. No GPU-debt ledger by design."""
import os, glob


def render_standup(plan: dict, gpu_holder, hw_queue: list) -> str:
    b = plan["buckets"]
    L = []
    L.append("# Standup")
    L.append("\n## Shipped today")
    L += [f"- #{n} — CI-green + hardware-PASS" for n in plan["merges"]] or ["- (none)"]
    L.append("\n## In-flight")
    L += [f"- dispatch: {p}" for p in plan["dispatch"]] or ["- (none)"]
    L.append("\n## Blocked")
    L += [f"- #{n} in progress" for n in b["in_progress"]] or ["- (none)"]
    L.append("\n## Hardware gate")
    L.append(f"- GPU lock holder: {gpu_holder or '(free)'}")
    L.append(f"- HW-untested queue: {hw_queue or '(empty)'}")
    L.append("\n## CI under repair")
    L += [f"- #{f['pr']} ({f['kind']})" for f in plan["fixers"]] or ["- (none)"]
    L.append("\n## Action items")
    L += [f"- #{n} HARDWARE FAILED — owner attention" for n in plan["hw_failed"]] or ["- (none)"]
    return "\n".join(L) + "\n"


def upsert_standup(directory: str, date: str, plan: dict, gpu_holder, hw_queue) -> str:
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{date}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(render_standup(plan, gpu_holder, hw_queue))
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
