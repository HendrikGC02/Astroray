#!/usr/bin/env python3
"""Model evaluation bench — compare open-weight models on Astroray's actual
task classes (repo navigation, tool-calling, retrieval), so tier assignment is
backed by measured gate/cost/latency numbers rather than vendor claims.

Read-only by design: the default tasks mutate nothing, so the bench is safe to
re-run and cheap (a fixed, short prompt set per model). Run it when re-ranking
the delegate tiers (quarterly, or when a primary underperforms twice).

Usage:
  python scripts/model_bench.py                # run default models x tasks
  python scripts/model_bench.py --models opencode-go/deepseek-v4-pro,opencode-go/hy3
  python scripts/model_bench.py --dry-run      # print what would run
  python scripts/model_bench.py --timeout 600

Evidence note: this records finish_reason/tool_calls/tokens/cost, NOT quality.
It answers "does the model stay on the rails and finish cleanly?" — a
precondition for tier fit. Implementation-quality gating still needs
build+pytest+lint (delegate.py / gates), never a bench number alone.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_MODELS = [
    "opencode-go/deepseek-v4-pro",
    "opencode-go/deepseek-v4-flash",
    "opencode-go/glm-5.3",
    "opencode-go/kimi-k2.7-code",
    "opencode-go/qwen3.7-plus",
    "opencode-go/mimo-v2.5",
    "opencode-go/hy3",
    "opencode-go/minimax-m3",
    "opencode-go/muse-spark-1.2-contributor",
]

DEFAULT_TASKS = [
    {
        "id": "retrieve",
        "prompt": ("Using scripts/project_index.py, find which package(s) the package "
                   "pkg203 depends on, and the single most relevant research doc for it. "
                   "Reply with a compact list. Do not modify anything."),
    },
    {
        "id": "navigate",
        "prompt": ("Find the C++ function that applies gamma correction in this repo and "
                   "report its exact file:line and the exponent it uses. Cite the file:line. "
                   "Do not modify anything."),
    },
    {
        "id": "summarize",
        "prompt": ("Read AGENTS.md and KNOWLEDGE.md, then list the 3 most load-bearing "
                   "invariants an implementer must not break. Be specific. "
                   "Do not modify anything."),
    },
]


def _opencode_cmd(args):
    exe = shutil.which("opencode")
    if exe is None:
        sys.exit("model_bench.py: opencode not found on PATH")
    if sys.platform == "win32" and exe.lower().endswith((".cmd", ".bat", ".ps1")):
        cmd_shim = str(Path(exe).with_suffix(".cmd"))
        if Path(cmd_shim).exists():
            return ["cmd", "/c", cmd_shim, *args]
        return ["cmd", "/c", exe, *args]
    return [exe, *args]


def _run_one(model: str, task: dict, timeout: int, workdir: str) -> dict:
    oc_args = ["run", "-m", model, "--format", "json", task["prompt"]]
    t0 = time.monotonic()
    status, exit_code = "completed", None
    out = ""
    try:
        r = subprocess.run(_opencode_cmd(oc_args), cwd=workdir, capture_output=True,
                           text=True, timeout=timeout, encoding="utf-8", errors="replace")
        exit_code = r.returncode
        out = r.stdout
    except subprocess.TimeoutExpired:
        status = "timeout"
        return {"model": model, "task": task["id"], "status": status, "wall_s": round(time.monotonic() - t0, 1)}

    tokens = cost = finish_reason = None
    tool_calls = 0
    errors = []
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        et = ev.get("type")
        part = ev.get("part", {})
        if et == "tool_use":
            tool_calls += 1
        elif et == "step_finish":
            tokens = part.get("tokens", tokens)
            cost = part.get("cost", cost)
            finish_reason = part.get("reason", finish_reason)
        elif et == "error":
            errors.append(str(ev.get("error", {}))[:120])
    if errors:
        status = "errored"
    elif status == "completed" and finish_reason != "stop":
        status = "no_clean_finish"
    return {
        "model": model, "task": task["id"], "status": status,
        "wall_s": round(time.monotonic() - t0, 1), "exit_code": exit_code,
        "finish_reason": finish_reason, "tool_calls": tool_calls,
        "tokens": tokens, "cost": cost, "errors": errors[:1],
    }


def main() -> None:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", help="comma-separated provider/model ids")
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    models = [m.strip() for m in (args.models or ",".join(DEFAULT_MODELS)).split(",") if m.strip()]
    workdir = str(ROOT)

    if args.dry_run:
        for m in models:
            for t in DEFAULT_TASKS:
                print(f"would run: opencode run -m {m} --format json '{t['id']}'")
        print(f"total {len(models) * len(DEFAULT_TASKS)} runs")
        return

    results = []
    for m in models:
        for t in DEFAULT_TASKS:
            print(f"[{m}] {t['id']} ...", flush=True)
            r = _run_one(m, t, args.timeout, workdir)
            results.append(r)
            print(f"    {r['status']} wall={r['wall_s']}s tool_calls={r.get('tool_calls')} "
                  f"cost={r.get('cost')}", flush=True)

    out = ROOT / ".astroray_plan" / "docs" / "model-bench-results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")

    print("\n== summary (clean-finish rate) ==")
    from collections import defaultdict
    by_model = defaultdict(lambda: {"ok": 0, "n": 0, "cost": 0.0, "wall": 0.0})
    for r in results:
        d = by_model[r["model"]]
        d["n"] += 1
        d["ok"] += 1 if r["status"] == "completed" else 0
        d["cost"] += r.get("cost") or 0.0
        d["wall"] += r.get("wall_s") or 0
    print(f"{'model':<45} {'clean':>6} {'cost$':>8} {'wall_s':>8}")
    for m, d in sorted(by_model.items(), key=lambda kv: -kv[1]["ok"] / kv[1]["n"]):
        print(f"{m:<45} {d['ok']}/{d['n']:<4} {d['cost']:>8.4f} {d['wall']:>8.1f}")


if __name__ == "__main__":
    main()
