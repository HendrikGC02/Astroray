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
4. `acquire_lock(.astroray_plan/.orchestrator.lock, 1500)`. If it returns "held & fresh", **exit now**.
   On `--dry-run`, skip lock acquisition entirely.

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

## Step 2 — Execute side effects (live only)
In this order, respecting caps already applied by the engine:

1. **Dispatch** each pkg in `plan.dispatch` via `dispatch-next` routing (Track E →
   `codex-implementer`; else `package-implementer` in its own fresh worktree) with the
   NEXT_STAGE_REPORT §3 drop-in prompt verbatim. **If an isolated worktree cannot be
   created, abort that dispatch** and note it blocked — never fall back to `main`
   (memory `parallel_agent_worktree_contamination`). After spawning, re-check
   `git rev-parse main` == Step-0 value; if it moved, halt dispatch and write a
   `CONTAMINATION` Action item.
2. **Fixers** — for each `plan.fixers`: `kind=="rebase"` → rebase-fixer on that PR's
   branch worktree (rebase `origin/main`, push); `kind=="ci"` → `gate-failure-reviewer`
   then a `pkg-ship` CI-fix pass on that branch. Record `record_action(ledger, pr,
   "rebase_dispatched"|"ci_dispatched")`.
3. **Hardware gate** — if `plan.hw_dispatch` is not null:
   `acquire_lock(.orchestrator.gpu.lock, 5400, meta={"sha": <headRefOid>})`. If acquired,
   run the local hardware build+test via the `verify` skill / `hardware-verifier` on
   that PR's branch worktree (build `.pyd` on the RTX with `pkg-ship` Step-0 hygiene,
   run the package acceptance render/test). On completion `record_hw_result(ledger, pr,
   sha, "PASS"|"FAIL", numbers, png_path)` and `release_lock(.orchestrator.gpu.lock)`.
   **Exactly one GPU job ever** — never start a second CUDA job while this lock is held
   (memory `cuda_verifier_concurrency`). Never auto-run the full closeout sweep.
4. **Merges** — for each `plan.merges`: invoke the `pr-reviewer` agent (its checklist
   self-escalates and STOPS on gate/license problems). It only auto-merges a PR that is
   `mergeable` + CI all-pass; the engine already confirmed hardware `PASS` bound to the
   current head SHA.
5. **HW-failed / Action items** — for each `plan.hw_failed`: dispatch
   `gate-failure-reviewer` on the local failure artifacts; never override a HW `FAIL`.

## Step 3 — Standup + close out
1. `finalize_previous(.astroray_plan/docs/standup, <today>)`.
2. `upsert_standup(.astroray_plan/docs/standup, <today>, plan, gpu_holder, hw_queue)`.
3. `expire_closed(ledger, {open PR numbers})`; `save_ledger(.astroray_plan/.orchestrator-state.json, ledger)`.
4. `release_lock(.astroray_plan/.orchestrator.lock)` (also release on every abort path).

## Safety rails (non-negotiable — see design spec §5)
- One tick at a time (tick lock); one CUDA job at a time (GPU lock).
- Per-package isolated worktree or abort — never `main`. `main` mutated only by `pr-reviewer`.
- Implementer cap 2 / fixer cap 1 (enforced in the engine).
- Auto-merge requires BOTH CI all-pass AND head-SHA-bound hardware `PASS`. A HW `FAIL` blocks merge + escalates.
- `--dry-run` = zero side effects.

## /schedule wiring (one-time owner setup — see Task 11)
