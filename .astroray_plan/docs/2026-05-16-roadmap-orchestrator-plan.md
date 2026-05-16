# roadmap-orchestrator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a cron-driven roadmap orchestrator: a pure Python decision engine (unit-tested) plus a `SKILL.md` policy doc that composes existing skills to dispatch packages, dual-gate PRs (CI + serialized local hardware test), auto-merge, and write a daily standup.

**Architecture:** All non-deterministic side effects (spawning implementer/fixer agents, `gh pr merge`, running the hardware build+test) live in `.claude/skills/roadmap-orchestrator/SKILL.md` and are executed by the agent using Claude tools. All deterministic decisions (PR classification, SHA-bound hardware-result ledger, lock staleness, HW queue order, the tick plan, standup rendering) live in `scripts/roadmap_orchestrator/` as pure functions with pytest coverage. The skill runs `python -m roadmap_orchestrator.cli` to get a JSON tick-plan, executes the side effects, then writes ledger updates back. `--dry-run` prints the plan and stops.

**Tech Stack:** Python 3.13, pytest (repo `pytest.ini`, `testpaths=tests`), `gh` CLI, existing skills `dispatch-next`/`pkg-ship`/`verify`/`pr-reviewer`/`gate-failure-reviewer`, `/schedule` cron.

**Spec:** `.astroray_plan/docs/2026-05-16-roadmap-orchestrator-design.md` (authoritative; this plan implements it).

---

## Shared data contracts (referenced by every task — do not redefine)

**PR record** — produced by:
`gh pr list --state open --json number,title,headRefName,headRefOid,isDraft,mergeable,mergeStateStatus,statusCheckRollup,createdAt`

```python
# Example element
{
  "number": 302, "title": "docs(round10): ... pkg94 ...",
  "headRefName": "feat/x", "headRefOid": "abc123…",
  "isDraft": False,
  "mergeable": "MERGEABLE",          # MERGEABLE | CONFLICTING | UNKNOWN
  "mergeStateStatus": "CLEAN",        # CLEAN | BEHIND | BLOCKED | DIRTY | UNSTABLE | UNKNOWN
  "statusCheckRollup": [              # list; entries are CheckRun or StatusContext
     {"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"},
     {"__typename": "StatusContext", "state": "SUCCESS"},
  ],
  "createdAt": "2026-05-15T13:59:17Z",
}
```

**Ledger** — JSON object at `.astroray_plan/.orchestrator-state.json`, keyed by `str(pr_number)`:

```python
{
  "302": {
    "head_sha": "abc123…",
    "last_action": "hw_dispatched",   # free string; used for fixer debounce
    "last_action_ts": "2026-05-16T00:10:00Z",
    "hw_result": "PASS",              # "PASS" | "FAIL" | None
    "hw_numbers": "SSIM 0.981",       # str | None
    "hw_artifact": "tests/.../out.png" # str | None
  }
}
```

**Buckets** — `classify_prs` returns a dict with exactly these keys, each a list of PR numbers (ints), every open non-? PR in exactly one:
`rebase_needed`, `ci_failing`, `hw_failed`, `ready`, `hw_untested`, `in_progress`.

**Classification precedence** (first match wins):
1. `in_progress` if `isDraft` is True.
2. `rebase_needed` if `mergeable == "CONFLICTING"` or `mergeStateStatus == "BEHIND"`.
3. `ci_failing` if `ci_state(pr) == "fail"`.
4. `hw_failed` if ledger entry exists for the PR, its `head_sha == pr["headRefOid"]`, and `hw_result == "FAIL"`.
5. `ready` if `mergeable == "MERGEABLE"` and `ci_state == "pass"` and ledger `head_sha == headRefOid` and `hw_result == "PASS"`.
6. `hw_untested` if `mergeable == "MERGEABLE"` and there is no PASS/FAIL bound to the current `headRefOid` (CI state irrelevant — HW runs concurrently with CI).
7. else `in_progress`.

**`ci_state(pr) -> "pass"|"fail"|"pending"`**: over `statusCheckRollup` — if any entry is a failure → `"fail"`; elif any entry is non-terminal → `"pending"`; elif ≥1 entry and all success → `"pass"`; elif empty list → `"pending"`. Failure = `CheckRun` with `conclusion in {"FAILURE","CANCELLED","TIMED_OUT","ACTION_REQUIRED"}` or `StatusContext` with `state in {"FAILURE","ERROR"}`. Success = `CheckRun conclusion in {"SUCCESS","NEUTRAL","SKIPPED"}` or `StatusContext state == "SUCCESS"`. Anything else = non-terminal.

---

## File Structure

- `scripts/roadmap_orchestrator/__init__.py` — package marker, version.
- `scripts/roadmap_orchestrator/ci.py` — `ci_state(pr)`.
- `scripts/roadmap_orchestrator/classify.py` — `classify_prs(prs, ledger)`.
- `scripts/roadmap_orchestrator/state.py` — ledger load/save, SHA invalidation, closed-PR expiry, record helpers.
- `scripts/roadmap_orchestrator/locks.py` — `acquire_lock`, `release_lock`, `lock_status` (tick lock + GPU lock).
- `scripts/roadmap_orchestrator/priority.py` — `parse_priority(next_stage_report_text) -> list[str]`.
- `scripts/roadmap_orchestrator/queue.py` — `pkg_of(pr, priority)`, `order_hw_queue(hw_untested, prs, priority)`.
- `scripts/roadmap_orchestrator/plan.py` — `build_tick_plan(...)` pure tick-plan object.
- `scripts/roadmap_orchestrator/standup.py` — `render_standup(plan)`, `upsert_standup(dir, date, plan)`, `finalize_previous(dir, date)`.
- `scripts/roadmap_orchestrator/cli.py` — argparse entrypoint; gathers inputs, prints JSON plan; `--dry-run`.
- `.claude/skills/roadmap-orchestrator/SKILL.md` — policy doc the agent executes each tick.
- Tests: `tests/test_roadmap_orchestrator_{ci,classify,state,locks,priority,queue,plan,standup,cli}.py`.

Run all suite tests with: `python -m pytest tests/test_roadmap_orchestrator_*.py -v`

---

## Task 1: Package skeleton + `ci_state`

**Files:**
- Create: `scripts/roadmap_orchestrator/__init__.py`
- Create: `scripts/roadmap_orchestrator/ci.py`
- Test: `tests/test_roadmap_orchestrator_ci.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_roadmap_orchestrator_ci.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from roadmap_orchestrator.ci import ci_state

def _cr(concl): return {"__typename": "CheckRun", "status": "COMPLETED", "conclusion": concl}
def _sc(state): return {"__typename": "StatusContext", "state": state}

def test_all_success_is_pass():
    assert ci_state({"statusCheckRollup": [_cr("SUCCESS"), _sc("SUCCESS")]}) == "pass"

def test_any_failure_is_fail():
    assert ci_state({"statusCheckRollup": [_cr("SUCCESS"), _cr("FAILURE")]}) == "fail"

def test_pending_when_non_terminal():
    assert ci_state({"statusCheckRollup": [{"__typename": "CheckRun", "status": "IN_PROGRESS", "conclusion": None}]}) == "pending"

def test_empty_rollup_is_pending():
    assert ci_state({"statusCheckRollup": []}) == "pending"

def test_skipped_and_neutral_count_as_success():
    assert ci_state({"statusCheckRollup": [_cr("SKIPPED"), _cr("NEUTRAL")]}) == "pass"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_roadmap_orchestrator_ci.py -v`
Expected: FAIL — `ModuleNotFoundError: roadmap_orchestrator`

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/roadmap_orchestrator/__init__.py
__version__ = "0.1.0"
```

```python
# scripts/roadmap_orchestrator/ci.py
"""Reduce a GitHub statusCheckRollup to pass | fail | pending."""

_CR_FAIL = {"FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED"}
_CR_OK = {"SUCCESS", "NEUTRAL", "SKIPPED"}
_SC_FAIL = {"FAILURE", "ERROR"}


def ci_state(pr: dict) -> str:
    rollup = pr.get("statusCheckRollup") or []
    if not rollup:
        return "pending"
    any_nonterminal = False
    saw_ok = False
    for e in rollup:
        if e.get("__typename") == "CheckRun":
            concl = e.get("conclusion")
            if e.get("status") != "COMPLETED" or concl is None:
                any_nonterminal = True
            elif concl in _CR_FAIL:
                return "fail"
            elif concl in _CR_OK:
                saw_ok = True
            else:
                any_nonterminal = True
        else:  # StatusContext
            state = e.get("state")
            if state in _SC_FAIL:
                return "fail"
            elif state == "SUCCESS":
                saw_ok = True
            else:
                any_nonterminal = True
    if any_nonterminal:
        return "pending"
    return "pass" if saw_ok else "pending"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_roadmap_orchestrator_ci.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/roadmap_orchestrator/__init__.py scripts/roadmap_orchestrator/ci.py tests/test_roadmap_orchestrator_ci.py
git commit -m "feat(orchestrator): ci_state rollup reducer + package skeleton"
```

---

## Task 2: `classify_prs`

**Files:**
- Create: `scripts/roadmap_orchestrator/classify.py`
- Test: `tests/test_roadmap_orchestrator_classify.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_roadmap_orchestrator_classify.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from roadmap_orchestrator.classify import classify_prs

OK = [{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"}]
FAILED = [{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "FAILURE"}]
PENDING = [{"__typename": "CheckRun", "status": "IN_PROGRESS", "conclusion": None}]

def _pr(n, **kw):
    base = {"number": n, "headRefOid": f"sha{n}", "isDraft": False,
            "mergeable": "MERGEABLE", "mergeStateStatus": "CLEAN",
            "statusCheckRollup": OK, "createdAt": "2026-05-15T00:00:00Z"}
    base.update(kw); return base

def test_draft_is_in_progress():
    b = classify_prs([_pr(1, isDraft=True)], {})
    assert b["in_progress"] == [1]

def test_conflicting_is_rebase_needed():
    b = classify_prs([_pr(2, mergeable="CONFLICTING")], {})
    assert b["rebase_needed"] == [2]

def test_behind_is_rebase_needed():
    b = classify_prs([_pr(3, mergeStateStatus="BEHIND")], {})
    assert b["rebase_needed"] == [3]

def test_ci_failure_is_ci_failing():
    b = classify_prs([_pr(4, statusCheckRollup=FAILED)], {})
    assert b["ci_failing"] == [4]

def test_hw_fail_for_current_sha_is_hw_failed():
    led = {"5": {"head_sha": "sha5", "hw_result": "FAIL"}}
    b = classify_prs([_pr(5)], led)
    assert b["hw_failed"] == [5]

def test_ready_requires_ci_pass_and_hw_pass():
    led = {"6": {"head_sha": "sha6", "hw_result": "PASS"}}
    b = classify_prs([_pr(6)], led)
    assert b["ready"] == [6]

def test_hw_untested_when_no_result_even_if_ci_pending():
    b = classify_prs([_pr(7, statusCheckRollup=PENDING)], {})
    assert b["hw_untested"] == [7]

def test_stale_hw_result_for_old_sha_is_requeued():
    led = {"8": {"head_sha": "OLDsha", "hw_result": "PASS"}}
    b = classify_prs([_pr(8)], led)  # current sha is sha8 != OLDsha
    assert b["hw_untested"] == [8]
    assert b["ready"] == []

def test_every_pr_in_exactly_one_bucket():
    prs = [_pr(1, isDraft=True), _pr(2, mergeable="CONFLICTING"),
           _pr(4, statusCheckRollup=FAILED), _pr(7, statusCheckRollup=PENDING)]
    b = classify_prs(prs, {})
    flat = [n for v in b.values() for n in v]
    assert sorted(flat) == [1, 2, 4, 7]
    assert len(flat) == len(set(flat))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_roadmap_orchestrator_classify.py -v`
Expected: FAIL — `ModuleNotFoundError: roadmap_orchestrator.classify`

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/roadmap_orchestrator/classify.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_roadmap_orchestrator_classify.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/roadmap_orchestrator/classify.py tests/test_roadmap_orchestrator_classify.py
git commit -m "feat(orchestrator): PR classifier with SHA-bound hardware gate"
```

---

## Task 3: Ledger state (`state.py`)

**Files:**
- Create: `scripts/roadmap_orchestrator/state.py`
- Test: `tests/test_roadmap_orchestrator_state.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_roadmap_orchestrator_state.py
import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from roadmap_orchestrator.state import (
    load_ledger, save_ledger, record_hw_result, record_action, expire_closed)

def test_load_missing_returns_empty(tmp_path):
    assert load_ledger(str(tmp_path / "nope.json")) == {}

def test_save_then_load_roundtrip(tmp_path):
    p = str(tmp_path / "led.json")
    save_ledger(p, {"1": {"head_sha": "a"}})
    assert load_ledger(p) == {"1": {"head_sha": "a"}}

def test_record_hw_result_binds_sha():
    led = {}
    record_hw_result(led, 5, "sha5", "PASS", "SSIM 0.98", "out.png")
    assert led["5"]["head_sha"] == "sha5"
    assert led["5"]["hw_result"] == "PASS"
    assert led["5"]["hw_numbers"] == "SSIM 0.98"

def test_record_action_sets_timestamp():
    led = {}
    record_action(led, 5, "rebase_dispatched")
    assert led["5"]["last_action"] == "rebase_dispatched"
    assert led["5"]["last_action_ts"].endswith("Z")

def test_expire_closed_drops_absent_prs():
    led = {"1": {}, "2": {}, "3": {}}
    expire_closed(led, open_numbers={2})
    assert set(led.keys()) == {"2"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_roadmap_orchestrator_state.py -v`
Expected: FAIL — `ModuleNotFoundError: roadmap_orchestrator.state`

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/roadmap_orchestrator/state.py
"""Persisted debounce + SHA-bound hardware-result ledger."""
import json, os
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_ledger(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_ledger(path: str, ledger: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(ledger, f, indent=2, sort_keys=True)
    os.replace(tmp, path)


def _entry(ledger: dict, number: int) -> dict:
    return ledger.setdefault(str(number), {})


def record_hw_result(ledger, number, head_sha, result, numbers, artifact):
    e = _entry(ledger, number)
    e.update(head_sha=head_sha, hw_result=result, hw_numbers=numbers,
             hw_artifact=artifact, last_action="hw_recorded", last_action_ts=_now())


def record_action(ledger, number, action):
    e = _entry(ledger, number)
    e.update(last_action=action, last_action_ts=_now())


def expire_closed(ledger: dict, open_numbers: set) -> None:
    for k in [k for k in ledger if int(k) not in open_numbers]:
        del ledger[k]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_roadmap_orchestrator_state.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/roadmap_orchestrator/state.py tests/test_roadmap_orchestrator_state.py
git commit -m "feat(orchestrator): SHA-bound hardware-result + debounce ledger"
```

---

## Task 4: Locks (`locks.py`)

**Files:**
- Create: `scripts/roadmap_orchestrator/locks.py`
- Test: `tests/test_roadmap_orchestrator_locks.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_roadmap_orchestrator_locks.py
import os, sys, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from roadmap_orchestrator.locks import acquire_lock, release_lock, lock_status

def test_acquire_when_free(tmp_path):
    p = str(tmp_path / "t.lock")
    assert acquire_lock(p, stale_seconds=1500, meta={"sha": "x"}) is True
    assert os.path.exists(p)

def test_acquire_blocked_when_fresh(tmp_path):
    p = str(tmp_path / "t.lock")
    acquire_lock(p, stale_seconds=1500)
    assert acquire_lock(p, stale_seconds=1500) is False  # held & fresh

def test_acquire_reclaims_when_stale(tmp_path):
    p = str(tmp_path / "t.lock")
    with open(p, "w") as f:
        json.dump({"pid": 1, "ts": "2000-01-01T00:00:00Z"}, f)
    assert acquire_lock(p, stale_seconds=10) is True  # old ts -> reclaim

def test_release_removes(tmp_path):
    p = str(tmp_path / "t.lock")
    acquire_lock(p, stale_seconds=1500)
    release_lock(p)
    assert not os.path.exists(p)

def test_lock_status_reports_held_and_meta(tmp_path):
    p = str(tmp_path / "t.lock")
    acquire_lock(p, stale_seconds=1500, meta={"sha": "abc"})
    st = lock_status(p, stale_seconds=1500)
    assert st["held"] is True and st["stale"] is False and st["meta"]["sha"] == "abc"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_roadmap_orchestrator_locks.py -v`
Expected: FAIL — `ModuleNotFoundError: roadmap_orchestrator.locks`

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/roadmap_orchestrator/locks.py
"""File-based locks: tick-overlap guard and single-GPU-slot guard."""
import json, os
from datetime import datetime, timezone


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def lock_status(path: str, stale_seconds: int) -> dict:
    if not os.path.exists(path):
        return {"held": False, "stale": False, "meta": None}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        age = (_now() - _parse_ts(data["ts"])).total_seconds()
    except (ValueError, KeyError, OSError):
        return {"held": True, "stale": True, "meta": None}
    return {"held": True, "stale": age >= stale_seconds, "meta": data.get("meta")}


def acquire_lock(path: str, stale_seconds: int, meta: dict = None) -> bool:
    st = lock_status(path, stale_seconds)
    if st["held"] and not st["stale"]:
        return False
    payload = {"pid": os.getpid(),
               "ts": _now().strftime("%Y-%m-%dT%H:%M:%SZ"),
               "meta": meta or {}}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    os.replace(tmp, path)
    return True


def release_lock(path: str) -> None:
    if os.path.exists(path):
        os.remove(path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_roadmap_orchestrator_locks.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/roadmap_orchestrator/locks.py tests/test_roadmap_orchestrator_locks.py
git commit -m "feat(orchestrator): tick + GPU file locks with stale reclaim"
```

---

## Task 5: Priority parsing (`priority.py`)

**Files:**
- Create: `scripts/roadmap_orchestrator/priority.py`
- Test: `tests/test_roadmap_orchestrator_priority.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_roadmap_orchestrator_priority.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from roadmap_orchestrator.priority import parse_priority

SAMPLE = """
## 1. Something
pkg00 should be ignored (before section 2)

## 2. Recommended next deployable set
1. pkg94 — addon build-integrity guard (first)
2. pkg95 ∥ pkg96 — concurrent after pkg94
3. pkg55-B-prime-cuda-gate-derivation — doc-only

## 3. Drop-in prompts
pkg99 ignored (after section 2)
"""

def test_extracts_section2_packages_in_order():
    assert parse_priority(SAMPLE) == ["pkg94", "pkg95", "pkg96", "pkg55-B-prime-cuda-gate-derivation"]

def test_missing_section_returns_empty():
    assert parse_priority("no sections here") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_roadmap_orchestrator_priority.py -v`
Expected: FAIL — `ModuleNotFoundError: roadmap_orchestrator.priority`

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/roadmap_orchestrator/priority.py
"""Parse the ordered package list from NEXT_STAGE_REPORT.md section 2."""
import re

_PKG = re.compile(r"pkg[0-9]+[A-Za-z0-9\-]*")


def parse_priority(text: str) -> list:
    lines = text.splitlines()
    start = end = None
    for i, ln in enumerate(lines):
        if start is None and re.match(r"^##\s*2[.)]", ln.strip()):
            start = i + 1
        elif start is not None and re.match(r"^##\s*3[.)]", ln.strip()):
            end = i
            break
    if start is None:
        return []
    body = "\n".join(lines[start:end if end is not None else len(lines)])
    seen, out = set(), []
    for m in _PKG.findall(body):
        if m not in seen:
            seen.add(m); out.append(m)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_roadmap_orchestrator_priority.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/roadmap_orchestrator/priority.py tests/test_roadmap_orchestrator_priority.py
git commit -m "feat(orchestrator): parse NEXT_STAGE_REPORT section-2 priority"
```

---

## Task 6: HW queue ordering (`queue.py`)

**Files:**
- Create: `scripts/roadmap_orchestrator/queue.py`
- Test: `tests/test_roadmap_orchestrator_queue.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_roadmap_orchestrator_queue.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from roadmap_orchestrator.queue import pkg_of, order_hw_queue

PRIORITY = ["pkg94", "pkg95", "pkg96"]

def _pr(n, title, created):
    return {"number": n, "title": title, "headRefName": "b", "createdAt": created}

def test_pkg_of_matches_title_token():
    assert pkg_of(_pr(1, "feat: pkg95 camera", "x"), PRIORITY) == "pkg95"

def test_pkg_of_none_when_unknown():
    assert pkg_of(_pr(2, "chore: tidy", "x"), PRIORITY) is None

def test_order_by_priority_then_created():
    prs = {
        1: _pr(1, "pkg96 work", "2026-01-01T00:00:00Z"),
        2: _pr(2, "pkg94 work", "2026-01-03T00:00:00Z"),
        3: _pr(3, "unknown",    "2026-01-02T00:00:00Z"),
        4: _pr(4, "pkg94 also", "2026-01-01T00:00:00Z"),
    }
    # pkg94 (idx0) before pkg96 (idx2) before unknown; within pkg94 older createdAt first
    assert order_hw_queue([1, 2, 3, 4], prs, PRIORITY) == [4, 2, 1, 3]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_roadmap_orchestrator_queue.py -v`
Expected: FAIL — `ModuleNotFoundError: roadmap_orchestrator.queue`

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/roadmap_orchestrator/queue.py
"""Order the HW-untested queue: NEXT_STAGE_REPORT priority, then oldest PR."""


def pkg_of(pr: dict, priority: list):
    hay = f"{pr.get('title','')} {pr.get('headRefName','')}"
    for pkg in priority:
        if pkg in hay:
            return pkg
    return None


def order_hw_queue(numbers: list, prs_by_number: dict, priority: list) -> list:
    idx = {p: i for i, p in enumerate(priority)}

    def key(n):
        pr = prs_by_number[n]
        pkg = pkg_of(pr, priority)
        prio = idx.get(pkg, len(priority))  # unknown sorts last
        return (prio, pr.get("createdAt", ""), n)

    return sorted(numbers, key=key)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_roadmap_orchestrator_queue.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/roadmap_orchestrator/queue.py tests/test_roadmap_orchestrator_queue.py
git commit -m "feat(orchestrator): HW-untested queue ordering"
```

---

## Task 7: Tick plan (`plan.py`)

**Files:**
- Create: `scripts/roadmap_orchestrator/plan.py`
- Test: `tests/test_roadmap_orchestrator_plan.py`

`build_tick_plan` is pure. Inputs are already-computed primitives (the SKILL.md gathers them); the function only decides. Signature:

```python
build_tick_plan(prs, ledger, priority, eligible_packages, in_flight_count,
                impl_cap, fixer_cap, gpu_lock_free, fixer_debounce_secs, now_iso) -> dict
```

Returns:
```python
{
  "dispatch":   [pkg, ...],            # ≤ impl_cap - in_flight_count, from eligible_packages
  "fixers":     [{"pr": n, "kind": "rebase"|"ci"}, ...],  # ≤ fixer_cap, debounced
  "hw_dispatch": n | None,             # one PR, only if gpu_lock_free
  "merges":     [n, ...],              # ready bucket
  "hw_failed":  [n, ...],
  "buckets":    {...},                 # raw classify output
}
```

Debounce rule: a PR already in `fixers` is skipped if its ledger `last_action` is one of `{"rebase_dispatched","ci_dispatched"}` **and** `last_action_ts` is within `fixer_debounce_secs` of `now_iso`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_roadmap_orchestrator_plan.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from roadmap_orchestrator.plan import build_tick_plan

OK = [{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"}]
FAILED = [{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "FAILURE"}]

def _pr(n, **kw):
    b = {"number": n, "title": f"pkg9{n}", "headRefName": "b", "headRefOid": f"s{n}",
         "isDraft": False, "mergeable": "MERGEABLE", "mergeStateStatus": "CLEAN",
         "statusCheckRollup": OK, "createdAt": "2026-01-0%dT00:00:00Z" % n}
    b.update(kw); return b

def test_dispatch_respects_cap_minus_inflight():
    p = build_tick_plan([], {}, ["pkg94","pkg95","pkg96"],
                         eligible_packages=["pkg94","pkg95","pkg96"],
                         in_flight_count=1, impl_cap=2, fixer_cap=1,
                         gpu_lock_free=True, fixer_debounce_secs=3600,
                         now_iso="2026-05-16T00:00:00Z")
    assert p["dispatch"] == ["pkg94"]            # only 1 free slot

def test_ready_pr_is_merged():
    led = {"1": {"head_sha": "s1", "hw_result": "PASS"}}
    p = build_tick_plan([_pr(1)], led, [], [], 0, 2, 1, True, 3600, "2026-05-16T00:00:00Z")
    assert p["merges"] == [1]

def test_hw_dispatch_only_when_gpu_free():
    p_busy = build_tick_plan([_pr(2)], {}, ["pkg92"], [], 0, 2, 1,
                             gpu_lock_free=False, fixer_debounce_secs=3600,
                             now_iso="2026-05-16T00:00:00Z")
    assert p_busy["hw_dispatch"] is None
    p_free = build_tick_plan([_pr(2)], {}, ["pkg92"], [], 0, 2, 1,
                             gpu_lock_free=True, fixer_debounce_secs=3600,
                             now_iso="2026-05-16T00:00:00Z")
    assert p_free["hw_dispatch"] == 2

def test_fixer_debounced_within_window():
    led = {"3": {"last_action": "rebase_dispatched", "last_action_ts": "2026-05-16T00:00:30Z"}}
    p = build_tick_plan([_pr(3, mergeable="CONFLICTING")], led, [], [], 0, 2, 1,
                        True, fixer_debounce_secs=3600, now_iso="2026-05-16T00:01:00Z")
    assert p["fixers"] == []          # 30s < 3600s debounce

def test_ci_failing_becomes_ci_fixer():
    p = build_tick_plan([_pr(4, statusCheckRollup=FAILED)], {}, [], [], 0, 2, 1,
                        True, 3600, "2026-05-16T00:00:00Z")
    assert p["fixers"] == [{"pr": 4, "kind": "ci"}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_roadmap_orchestrator_plan.py -v`
Expected: FAIL — `ModuleNotFoundError: roadmap_orchestrator.plan`

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/roadmap_orchestrator/plan.py
"""Pure tick-plan builder. Decides; never acts. See design spec Step 1/2/2a."""
from datetime import datetime, timezone
from roadmap_orchestrator.classify import classify_prs
from roadmap_orchestrator.queue import order_hw_queue

_DEBOUNCE_ACTIONS = {"rebase_dispatched", "ci_dispatched"}


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
        hw_dispatch = order_hw_queue(buckets["hw_untested"], prs_by_n, priority)[0]

    return {
        "dispatch": dispatch,
        "fixers": fixers,
        "hw_dispatch": hw_dispatch,
        "merges": list(buckets["ready"]),
        "hw_failed": list(buckets["hw_failed"]),
        "buckets": buckets,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_roadmap_orchestrator_plan.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/roadmap_orchestrator/plan.py tests/test_roadmap_orchestrator_plan.py
git commit -m "feat(orchestrator): pure tick-plan builder"
```

---

## Task 8: Standup rendering (`standup.py`)

**Files:**
- Create: `scripts/roadmap_orchestrator/standup.py`
- Test: `tests/test_roadmap_orchestrator_standup.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_roadmap_orchestrator_standup.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from roadmap_orchestrator.standup import render_standup, upsert_standup, finalize_previous

PLAN = {"dispatch": ["pkg94"], "fixers": [{"pr": 5, "kind": "ci"}],
        "hw_dispatch": 7, "merges": [3], "hw_failed": [9],
        "buckets": {"in_progress": [11], "rebase_needed": [], "ci_failing": [5],
                    "hw_untested": [7], "hw_failed": [9], "ready": [3]}}

def test_render_contains_all_sections():
    md = render_standup(PLAN, gpu_holder=None, hw_queue=[7])
    for h in ["Shipped today", "In-flight", "Blocked", "Hardware gate",
              "CI under repair", "Action items"]:
        assert h in md
    assert "pkg94" in md and "#3" in md and "#9" in md
    assert "debt ledger" not in md.lower()

def test_upsert_writes_dated_file(tmp_path):
    upsert_standup(str(tmp_path), "2026-05-16", PLAN, gpu_holder=None, hw_queue=[])
    f = tmp_path / "2026-05-16.md"
    assert f.exists() and "Hardware gate" in f.read_text(encoding="utf-8")

def test_upsert_is_idempotent_overwrite(tmp_path):
    upsert_standup(str(tmp_path), "2026-05-16", PLAN, None, [])
    upsert_standup(str(tmp_path), "2026-05-16", PLAN, None, [])
    assert (tmp_path / "2026-05-16.md").read_text(encoding="utf-8").count("# Standup") == 1

def test_finalize_previous_appends_footer_once(tmp_path):
    (tmp_path / "2026-05-15.md").write_text("# Standup 2026-05-15\n", encoding="utf-8")
    finalize_previous(str(tmp_path), "2026-05-16")
    txt = (tmp_path / "2026-05-15.md").read_text(encoding="utf-8")
    assert "<!-- finalized -->" in txt
    finalize_previous(str(tmp_path), "2026-05-16")  # second call no-ops
    assert (tmp_path / "2026-05-15.md").read_text(encoding="utf-8").count("<!-- finalized -->") == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_roadmap_orchestrator_standup.py -v`
Expected: FAIL — `ModuleNotFoundError: roadmap_orchestrator.standup`

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/roadmap_orchestrator/standup.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_roadmap_orchestrator_standup.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/roadmap_orchestrator/standup.py tests/test_roadmap_orchestrator_standup.py
git commit -m "feat(orchestrator): daily standup renderer (no debt ledger)"
```

---

## Task 9: CLI (`cli.py`)

**Files:**
- Create: `scripts/roadmap_orchestrator/cli.py`
- Test: `tests/test_roadmap_orchestrator_cli.py`

The CLI is read-only: it gathers inputs and prints the tick plan + standup markdown as JSON to stdout. It NEVER spawns agents or merges (the skill does that). `--prs-json PATH` injects PR data for tests/determinism; without it the CLI shells out to `gh`. `--dry-run` is the default-safe behavior (print only); the flag exists for explicitness and to assert "no side effects" semantics in the skill.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_roadmap_orchestrator_cli.py
import os, sys, json, subprocess

ROOT = os.path.join(os.path.dirname(__file__), "..")

def test_cli_emits_plan_json(tmp_path):
    prs = [{"number": 1, "title": "pkg94 x", "headRefName": "b", "headRefOid": "s1",
            "isDraft": False, "mergeable": "MERGEABLE", "mergeStateStatus": "CLEAN",
            "statusCheckRollup": [{"__typename": "CheckRun", "status": "COMPLETED",
                                   "conclusion": "SUCCESS"}],
            "createdAt": "2026-05-15T00:00:00Z"}]
    pj = tmp_path / "prs.json"; pj.write_text(json.dumps(prs), encoding="utf-8")
    nsr = tmp_path / "nsr.md"
    nsr.write_text("## 2. set\n1. pkg94\n## 3. prompts\n", encoding="utf-8")
    led = tmp_path / "led.json"; led.write_text("{}", encoding="utf-8")
    out = subprocess.check_output(
        [sys.executable, "-m", "roadmap_orchestrator.cli", "--dry-run",
         "--gpu-lock-free",
         "--prs-json", str(pj), "--ledger", str(led),
         "--next-stage-report", str(nsr),
         "--eligible", "pkg94", "--in-flight", "0"],
        cwd=os.path.join(ROOT, "scripts"), text=True)
    plan = json.loads(out)
    assert plan["plan"]["hw_dispatch"] == 1
    assert "Hardware gate" in plan["standup_md"]
    # dry-run must not have created/modified the ledger content
    assert led.read_text(encoding="utf-8") == "{}"
    assert plan["dry_run"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_roadmap_orchestrator_cli.py -v`
Expected: FAIL — `No module named roadmap_orchestrator.cli`

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/roadmap_orchestrator/cli.py
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
    ap.add_argument("--gpu-lock-free", action="store_true", default=False)
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_roadmap_orchestrator_cli.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Run the whole suite green**

Run: `python -m pytest tests/test_roadmap_orchestrator_*.py -v`
Expected: PASS (all tasks' tests; ~34 passed)

- [ ] **Step 6: Commit**

```bash
git add scripts/roadmap_orchestrator/cli.py tests/test_roadmap_orchestrator_cli.py
git commit -m "feat(orchestrator): read-only tick-plan CLI"
```

---

## Task 10: `SKILL.md` policy doc

**Files:**
- Create: `.claude/skills/roadmap-orchestrator/SKILL.md`

No automated test (prose policy). It must encode the design spec's Step 0 → Step 3 and safety rails, and delegate side effects to existing skills/agents. It calls the CLI for every decision.

- [ ] **Step 1: Write the skill**

````markdown
---
name: roadmap-orchestrator
description: One bounded roadmap-advance tick — dispatch ready packages, dual-gate PRs (CI + serialized local hardware test), auto-merge, write the daily standup. Cron-driven via /schedule.
invocation: /roadmap-orchestrator
---

# /roadmap-orchestrator [--dry-run]

Implements `.astroray_plan/docs/2026-05-16-roadmap-orchestrator-design.md`. One
invocation = one bounded tick. Recurrence comes from a `/schedule` cron routine,
never from looping in-session.

## Step 0 — Guards
1. `cd` to the canonical repo path; `git rev-parse --show-toplevel` to confirm.
2. `git fetch origin`; confirm on `main`, up to date.
3. Stale-`.pyd` scan (reuse `pkg-ship` Step 0 PowerShell scan). Abort tick on shadow `.pyd`.
4. Acquire the tick lock: `acquire_lock(".astroray_plan/.orchestrator.lock", 1500)` returns `True` if the lock was acquired (proceed) or `False` if a live (non-stale) lock is already held by a running tick. **If it returns `False`, exit now** — do not run an overlapping tick. On `--dry-run`, skip lock acquisition entirely.

## Step 1 — Compute the tick plan (decision engine)
Determine `eligible_packages`: from `NEXT_STAGE_REPORT.md` §2, the ready packages
(not research-only, deps merged, no open PR, no active worktree, dispatchable Track) —
this is exactly `dispatch-next`'s eligibility logic; reuse it. Count `in_flight`
(active worktrees + running implementer agents).

Run:
```
python -m roadmap_orchestrator.cli \
  --ledger .astroray_plan/.orchestrator-state.json \
  --next-stage-report .astroray_plan/docs/NEXT_STAGE_REPORT.md \
  --eligible <comma-joined eligible_packages> --in-flight <n> \
  [--dry-run]   (pass --gpu-lock-free only if the GPU lock is free)
```
GPU-lock-free is decided via `lock_status(.astroray_plan/.orchestrator.gpu.lock, 5400)`.
Parse the JSON: `plan.dispatch`, `plan.fixers`, `plan.hw_dispatch`, `plan.merges`,
`plan.hw_failed`, `standup_md`.

**If `--dry-run`:** print the plan + `standup_md`, do nothing else, exit. (No lock,
no spawn, no merge, no build, no file write.)

Note: `cli.py` always emits the plan JSON and performs **no** side effects itself; the `--dry-run` flag is only echoed back as `dry_run: true` in the JSON and is the SKILL's own signal to stop after printing. All side effects (Step 2/3) are performed by this SKILL, never by the CLI.

## Step 2 — Execute side effects (live only)
In this order, respecting caps already applied by the engine:

1. **Dispatch** each pkg in `plan.dispatch` via `dispatch-next` routing (Track E →
   `codex-implementer`; else `package-implementer` in its own fresh worktree) with the
   NEXT_STAGE_REPORT §3 drop-in prompt verbatim. **If an isolated worktree cannot be
   created, abort that dispatch** and note it blocked — never fall back to `main`
   (memory `parallel_agent_worktree_contamination`). After spawning, re-check
   `git rev-parse main` == Step-0 value; if it moved, halt dispatch and write a
   `CONTAMINATION` Action item.
2. **Fixers** — for each `plan.fixers` (each is `{"pr": n, "kind": "rebase"|"ci"}`): `kind=="rebase"` → rebase-fixer on that PR's branch worktree (rebase `origin/main`, push); `kind=="ci"` → `gate-failure-reviewer` then a `pkg-ship` CI-fix pass on that branch. Then `record_action(ledger, <pr number>, "rebase_dispatched"|"ci_dispatched")` (signature: `state.record_action(ledger, number, action)`).
3. **Hardware gate (strictly serialized, asynchronous across ticks — design spec §2a).** `plan.hw_dispatch` is either `null` or a single **PR number** (int), not a dict.
   a. **Read back a finished result first.** Check `lock_status(".astroray_plan/.orchestrator.gpu.lock", 5400)`. If the GPU lock is held and its dispatched `hardware-verifier` job for that PR has finished, call `record_hw_result(ledger, <pr number>, <head_sha>, "PASS"|"FAIL", <numbers>, <artifact path>)` (signature: `state.record_hw_result(ledger, number, head_sha, result, numbers, artifact)`), then `release_lock(".astroray_plan/.orchestrator.gpu.lock")`.
   b. **Dispatch a new job only if the slot is free.** If `plan.hw_dispatch` is not `null` AND the GPU lock is free: look up that PR's `headRefOid` from the `gh pr list` JSON using `plan.hw_dispatch` (the PR number) as the key; `acquire_lock(".astroray_plan/.orchestrator.gpu.lock", 5400, meta={"sha": <headRefOid>})`; if acquired, dispatch the local hardware build+test via the `verify` skill / `hardware-verifier` on that PR's branch worktree **as a background job — do NOT block the rest of this tick waiting for it** (a CUDA build+render runs far longer than the 10-min tick cadence; its result is read back by a later tick via step (a)). The job builds the `.pyd` on the RTX with `pkg-ship` Step-0 hygiene and runs the package acceptance render/test. **Exactly one GPU/CUDA job ever** — never start a second while this lock is held (memory `cuda_verifier_concurrency`). Never auto-run the full closeout sweep.
4. **Merges** — for each `plan.merges`: invoke the `pr-reviewer` agent (its checklist
   self-escalates and STOPS on gate/license problems). It only auto-merges a PR that is
   `mergeable` + CI all-pass; the engine already confirmed hardware `PASS` bound to the
   current head SHA.
5. **HW-failed / Action items** — for each `plan.hw_failed`: dispatch
   `gate-failure-reviewer` on the local failure artifacts; never override a HW `FAIL`.

## Step 3 — Standup + close out
1. `finalize_previous(.astroray_plan/docs/standup, <today>)`.
2. `upsert_standup(.astroray_plan/docs/standup, <today>, plan, gpu_holder, hw_queue)`.
3. `expire_closed(ledger, open_numbers)` where `open_numbers` is a Python `set` of int PR numbers from the `gh pr list`; then `save_ledger(".astroray_plan/.orchestrator-state.json", ledger)`.
4. `release_lock(.astroray_plan/.orchestrator.lock)` (also release on every abort path).

## Safety rails (non-negotiable — see design spec §5)
- One tick at a time (tick lock); one CUDA job at a time (GPU lock).
- Per-package isolated worktree or abort — never `main`. `main` mutated only by `pr-reviewer`.
- Implementer cap 2 / fixer cap 1 (enforced in the engine).
- Auto-merge requires BOTH CI all-pass AND head-SHA-bound hardware `PASS`. A HW `FAIL` blocks merge + escalates.
- `--dry-run` = zero side effects.

## /schedule wiring (one-time owner setup — see Task 11)
````

- [ ] **Step 2: Sanity-check the skill loads**

Run: `python -c "import yaml,sys; print('frontmatter ok')"` then manually confirm the
frontmatter block parses (name/description/invocation present). Confirm the file is at
`.claude/skills/roadmap-orchestrator/SKILL.md`.

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/roadmap-orchestrator/SKILL.md
git commit -m "feat(orchestrator): SKILL.md policy doc composing existing skills"
```

---

## Task 11: `/schedule` wiring + dry-run acceptance

**Files:**
- Modify: `.claude/skills/roadmap-orchestrator/SKILL.md` (fill the final section)

- [ ] **Step 1: Document the cron wiring**

Append under "## /schedule wiring" in `SKILL.md`:

```markdown
Run once by the owner to start the engine (every 10 minutes):

    /schedule create --name roadmap-orchestrator --cron "*/10 * * * *" \
      --command "/roadmap-orchestrator"

Pause/stop: `/schedule list` then `/schedule delete roadmap-orchestrator`.
The standup is updated every tick and finalized on day rollover — no separate
daily cron is needed.
```

- [ ] **Step 2: Dry-run acceptance against the current §2 set**

Determine eligible packages from `NEXT_STAGE_REPORT.md` §2 (currently Round-10:
`pkg94`, then `pkg95`,`pkg96`; `pkg55-B-prime-cuda-gate-derivation`). Run:

```bash
python -m roadmap_orchestrator.cli --dry-run \
  --ledger .astroray_plan/.orchestrator-state.json \
  --next-stage-report .astroray_plan/docs/NEXT_STAGE_REPORT.md \
  --eligible pkg94 --in-flight 0
```
(run from `scripts/`; `.orchestrator-state.json` may not exist — engine treats missing
ledger as `{}`)

Expected: prints JSON with `plan.dispatch == ["pkg94"]` (no deps, slot free),
`plan.merges == []` and `plan.hw_dispatch == null` (no open PRs right now),
`standup_md` containing the "Hardware gate" section and **no** "debt ledger" text;
zero side effects (no new files: confirm `git status` shows only the plan/skill files,
no `.orchestrator*` written).

- [ ] **Step 3: Verify no side effects**

Run: `git status --porcelain`
Expected: no `.astroray_plan/.orchestrator.lock`, no `.orchestrator-state.json`, no
`docs/standup/` created by the dry-run. Only the committed source files differ.

- [ ] **Step 4: Commit**

```bash
git add .claude/skills/roadmap-orchestrator/SKILL.md
git commit -m "docs(orchestrator): /schedule wiring + dry-run acceptance recorded"
```

---

## Self-Review (completed by plan author)

**Spec coverage:** Step 0 guards → Task 10 SKILL §Step 0. Step 1 dispatch fill → Task 7
(`build_tick_plan.dispatch`) + Task 10 §Step 2.1. Step 2 triage/dual-gate → Tasks 1,2,7.
Step 2a serialized HW gate → Tasks 4 (GPU lock), 7 (`hw_dispatch` only if free), 10 §Step 2.3.
Step 3 standup → Task 8 + Task 10 §Step 3. §5 safety rails → Tasks 4,7,10. §6 state →
Tasks 3,4. §7 testing → Tasks 1–9 unit suites + Task 11 dry-run acceptance + classifier/
SHA-invalidation (Task 2 `test_stale_hw_result_for_old_sha_is_requeued`) + guard tests
(Task 7 `test_hw_dispatch_only_when_gpu_free`, Task 10 worktree-abort prose). No gaps.

**Placeholder scan:** no TBD/TODO; every code step has complete code; every test has real
assertions; SKILL.md is full prose, not stubs.

**Type consistency:** `classify_prs` bucket keys (`BUCKETS`) are identical across Tasks
2/7/8. `build_tick_plan` return shape matches Task 8 `render_standup` input and Task 9 CLI
consumption. `acquire_lock/release_lock/lock_status` signatures consistent across Tasks 4/9/10.
Ledger schema (`head_sha`,`hw_result`,`last_action`,`last_action_ts`) identical across Tasks
2/3/7. `now_iso` format `%Y-%m-%dT%H:%M:%SZ` consistent in state/locks/plan.

No issues found.
