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
1. **Safe merged-worktree auto-GC (live path only; never under `--dry-run`).**
   Call `gc_merged_worktrees(".claude/worktrees", ledger)` (signature: `state.gc_merged_worktrees(worktrees_dir, ledger) -> dict`).
   Returns `{"removed": [...], "escalations": [...]}`.
   This safely removes worktrees + branches for PRs that are (a) MERGED on GitHub, (b) content in `origin/main` (squash-aware), (c) zero uncommitted/unpushed changes.
   Anything not provably safe is escalated, never force-deleted. Design: pkg97 § Phase 1.
2. `finalize_previous(.astroray_plan/docs/standup, <today>)`.
3. `upsert_standup(.astroray_plan/docs/standup, <today>, plan, gpu_holder, hw_queue, merged_today, gc_report)` where `merged_today` is the list of PR numbers merged today (from `_get_merged_today()`) and `gc_report` is the GC report from step 1.
4. `expire_closed(ledger, open_numbers)` where `open_numbers` is a Python `set` of int PR numbers from the `gh pr list`; then `save_ledger(".astroray_plan/.orchestrator-state.json", ledger)`.
5. `release_lock(.astroray_plan/.orchestrator.lock)` (also release on every abort path).

## Safety rails (non-negotiable — see design spec §5)
- One tick at a time (tick lock); one CUDA job at a time (GPU lock).
- Per-package isolated worktree or abort — never `main`. `main` mutated only by `pr-reviewer`.
- Implementer cap 2 / fixer cap 1 (enforced in the engine).
- Auto-merge requires BOTH CI all-pass AND head-SHA-bound hardware `PASS`. A HW `FAIL` blocks merge + escalates.
- `--dry-run` = zero side effects.
- **Worktree/branch GC is merged-only, never force-delete on doubt.** Only PRs with `state == "MERGED"` AND content in `origin/main` (squash-aware) AND clean worktree are removed. No staleness/age heuristic. Escalate all ambiguous cases as Action items (pkg97 § Phase 1 hard invariant).

## /schedule wiring (one-time owner setup — see Task 11)

Run once by the owner to start the engine. The `/schedule` skill is a
natural-language front-end to the cron tools — describe the job in prose,
do NOT use CLI flags (there is no `create`/`--name`/`--command` syntax).
Say, verbatim intent:

> /schedule Run `/roadmap-orchestrator` every 10 minutes, durably — it
> must survive Claude restarts.

This schedules a recurring job (cron `*/10 * * * *`; an off-:00/:30 minute
offset such as `3-53/10 * * * *` is equally fine and slightly preferred
for fleet hygiene since the tick cadence is approximate) with
**`durable: true`** so it is written to `.claude/scheduled_tasks.json` and
survives restarts. Without `durable`, the job is in-memory only and dies
when this Claude session ends — the engine would silently stop. The tick
lock makes exact firing time immaterial, so jitter/offset is harmless.

**7-day auto-expiry (important):** the harness auto-expires recurring cron
jobs after 7 days — it fires one final time, then deletes the job. The
engine will silently stop after a week. Re-arm it weekly (re-issue the
same `/schedule` request); keep a standing reminder to do so.

**Pause/stop:** `/schedule list` to see the job and its **job ID**, then
`/schedule delete <job-id>`. Deletion is by the ID returned at creation,
not by name.

The standup is updated every tick and finalized on day rollover, so no
separate daily cron is needed.
