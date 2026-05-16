# roadmap-orchestrator — Design Spec

- **Date:** 2026-05-16
- **Status:** approved (brainstorming) — ready for implementation plan
- **Owner decisions baked in:** `/schedule` cron engine; NEXT_STAGE_REPORT §2 readiness-filtered dispatch; full auto-merge gated on **both** GitHub CI **and** a serialized local hardware build+test (run concurrently, both must be green); thin composer over existing skills.

## 1. Purpose

A single project skill that, on each cron tick, advances the Astroray roadmap autonomously: it dispatches ready packages to implementer agents, triages every open PR and routes it to the correct fixer, runs a serialized local hardware build+test gate, auto-merges PRs that are green on **both** CI and hardware, and maintains a daily standup of what shipped, what is blocked, and what needs an owner decision.

It is **policy/orchestration only**. It does not re-implement spec-reading, worktree hygiene, dispatch routing, PR review, or CI-fixing — it composes the skills/agents that already do those.

## 2. Non-goals

- Not a re-implementation of `pkg-ship` / `dispatch-next` / `pr-reviewer` / `gate-failure-reviewer` / `verify`. It calls them.
- Runs the per-PR package hardware build+test as a **strictly serialized** merge gate (exactly one GPU job at a time across the entire orchestrator — memory `cuda_verifier_concurrency`). It does **not** run the full multi-scene closeout sweep — that stays an owner/architect step (memory `ci_has_no_gpu_runtime_blindspot` is addressed *per-PR* here, not deferred to a debt ledger).
- Does not invent priority order. It consumes the human-curated `NEXT_STAGE_REPORT.md` §2 set.
- Not a long-running daemon. Each tick is a bounded, fresh run; recurrence comes from the `/schedule` harness, not from the skill looping internally.

## 3. Execution model

- **Skill:** `.claude/skills/roadmap-orchestrator/` with `SKILL.md` (frontmatter `name: roadmap-orchestrator`, `invocation: /roadmap-orchestrator`).
- **Engine:** a `/schedule` cron routine, every 10 minutes, whose command is `/roadmap-orchestrator`. Survives terminal close; runs unattended.
- **Entry points:**
  - `/roadmap-orchestrator` — run one bounded tick.
  - `/roadmap-orchestrator --dry-run` — print the full plan (would-dispatch, would-merge, would-fix, standup preview); mutate nothing.

Each tick recomputes ground truth from `gh` + `git` every time. The only persisted state between ticks is the lock file, the per-day standup file, and a small debounce state file (§6). The skill is otherwise stateless and idempotent — a missed or doubled tick is safe.

## 4. One tick — ordered sequence

### Step 0 — Guards (reuse `pkg-ship` Step 0)
1. `cd` to the canonical repo path the owner uses; `git rev-parse --show-toplevel` to confirm.
2. `git fetch origin`; confirm current branch is `main` and up to date with `origin/main`.
3. Stale-`.pyd` scan (the `pkg-ship` Step 0 PowerShell scan). Abort the tick on shadow `.pyd` rather than risk a masked build.
4. Acquire `.astroray_plan/.orchestrator.lock` (write PID + ISO timestamp). If a lock exists and its timestamp is < 25 min old, **exit immediately** (a prior tick is still running — no overlap). If the lock is stale (≥ 25 min), reclaim it and log a warning to the standup.
5. Release the lock at end of tick (and on any abort path).

### Step 1 — Dispatch fill (implementer slots)
1. Read `.astroray_plan/docs/NEXT_STAGE_REPORT.md` §2 (recommended deployable set).
2. For each package in priority order, read its spec frontmatter in `.astroray_plan/packages/`. **Eligible** iff: not `Status: research …/not ready`, all `Depends on` packages are merged, no open PR for it, no active worktree for it, and Track is dispatchable.
3. Count current in-flight implementers (active worktrees + running implementer agents). While `in-flight < N` (default **N = 2**), take the next eligible package and route it exactly as `dispatch-next` does:
   - Track E **and** marked Codex-paste-ready → `codex-implementer`.
   - Otherwise → `package-implementer` in its own fresh worktree.
   - Pass the `NEXT_STAGE_REPORT.md` §3 drop-in prompt for that package **verbatim**, plus the spec path and worktree name.
4. **No-main-writes enforcement (hard):**
   - Spawn each implementer with an explicit, isolated worktree path.
   - If an isolated worktree cannot be created for a package, **abort that dispatch** and record it as blocked — never fall back to dispatching against `main` (memory `parallel_agent_worktree_contamination`).
   - Post-dispatch audit: re-read `git rev-parse main`; it MUST be unchanged from Step 0. If it moved unexpectedly, halt all further dispatch this tick and write a `CONTAMINATION` alert to the standup.

### Step 2 — PR triage + dual gate
1. `gh pr list --state open --json number,title,headRefName,isDraft,mergeable,mergeStateStatus,statusCheckRollup`.
2. Classify each open PR and route (debounced — see §6). A PR auto-merges only when **both** gates are green: GitHub CI rollup all-pass **and** the local hardware build+test recorded `PASS` for the PR's current head SHA.
   | State | Condition | Action |
   |---|---|---|
   | **Rebase-needed** | `mergeable=CONFLICTING` or behind base | Dispatch a rebase-fixer on that PR's branch in its own worktree (rebase/merge `origin/main`, push). Invalidates any prior hardware result for that PR (head SHA will change). |
   | **CI-failing** | rollup has `FAILURE` | Dispatch `gate-failure-reviewer` to diagnose, then a `pkg-ship` CI-fix pass on that branch worktree. |
   | **HW-untested** | not draft, `mergeable=MERGEABLE`, no `PASS` recorded for current head SHA | Enqueue for the hardware gate (Step 2a). Do **not** wait on CI to enqueue — CI runs concurrently on GitHub. |
   | **HW-failed** | hardware build+test recorded `FAIL` for current head SHA | Do not merge. Dispatch `gate-failure-reviewer` on the local failure artifacts; flag in standup **Action items**. |
   | **Ready** | not draft, `mergeable=MERGEABLE`, CI rollup all-pass, hardware `PASS` for current head SHA | Auto-merge via `pr-reviewer` agent (its checklist self-escalates and **stops** on gate/license problems instead of merging). |
   | **In progress** | draft, or CI rollup `PENDING` with hardware not yet run | Report only; CI may still be running — hardware may run in parallel if otherwise eligible. |
3. Fixers obey a separate cap (default **1** concurrent fixer). Rebase/CI fixers and implementers do CPU build/test freely (subject to the implementer cap); any job that **executes CUDA on the RTX** must hold the single GPU lock (Step 2a).

### Step 2a — Hardware gate (strictly serialized)
1. The orchestrator holds exactly **one** GPU slot, guarded by `.astroray_plan/.orchestrator.gpu.lock` (PID + head SHA + ISO ts). At most one CUDA-executing job runs at any time across the whole orchestrator (memory `cuda_verifier_concurrency`).
2. Each tick: if the GPU lock is free and the HW-untested queue is non-empty, take the front PR (queue ordered by: `NEXT_STAGE_REPORT.md` §2 package priority first, then oldest PR `createdAt` as tiebreak), acquire the GPU lock, and dispatch the local hardware build+test via the existing `verify` skill / `hardware-verifier` agent against that PR's branch worktree: build the `.pyd` on the RTX (stale-`.pyd` hygiene per `pkg-ship` Step 0), run the package's acceptance render/test, capture measured numbers + the rendered PNG path.
3. Record the outcome in `.orchestrator-state.json` keyed by **PR number + head SHA**: `PASS` / `FAIL` + measured numbers + artifact paths. Release the GPU lock.
4. A recorded result is bound to the head SHA — any new push (including a rebase-fixer) invalidates it and re-queues the PR. If the GPU lock is held by a stale entry (≥ 90 min, generous because a CUDA build+render is slow), reclaim it and log a warning.
5. The hardware build+test never runs concurrently with another CUDA job, never blocks the rest of the tick (it is dispatched and its result is read on a later tick), and is never run against a branch already being rebased/CI-fixed (its SHA is about to move).

### Step 3 — Standup
Upsert `.astroray_plan/docs/standup/YYYY-MM-DD.md` (one file per local day). Sections:
- **Shipped today** — PRs merged this day (number, pkg, "CI-green + hardware-PASS", measured numbers).
- **In-flight** — package · worktree · agent · dispatched-at.
- **Blocked** — deps-unsatisfied / research-not-ready / subagent-escalated, with reason.
- **Hardware gate** — current GPU-lock holder; HW-untested queue (oldest first); recent `PASS`/`FAIL` with measured numbers + PNG path. No "debt ledger" — nothing merges without a hardware `PASS`, so there is no post-merge GPU debt.
- **CI under repair** — failing PRs with a fixer dispatched, and the diagnosis link.
- **Action items** — anything requiring an owner decision: HW-failed PRs, escalations, contamination alerts, stale locks (tick or GPU).

On the first tick of a new local day, finalize the previous day's file (write a one-line summary footer) before starting the new one.

## 5. Safety rails (explicit, non-negotiable)

- Lock file prevents overlapping ticks.
- Every implementer/fixer runs in its own isolated worktree, or the dispatch is aborted — never main.
- `main` is mutated **only** by the `pr-reviewer` auto-merge path; post-dispatch audit catches any unexpected `main` movement and raises a `CONTAMINATION` alert.
- Implementer cap (default 2); fixer cap (default 1).
- **Exactly one** CUDA-executing job at any time across the whole orchestrator, guarded by `.orchestrator.gpu.lock` — never parallelized (memory `cuda_verifier_concurrency`). The hardware build+test is auto-run but only ever serially.
- Auto-merge requires **both** GitHub CI all-pass **and** a local hardware `PASS` bound to the PR's current head SHA — CI catches Linux/GCC divergence the local box can't (memory `mingw_local_vs_gcc_ci_divergence`); the hardware test catches GPU-correctness CI can't (memory `ci_has_no_gpu_runtime_blindspot`). Neither substitutes for the other; they run concurrently.
- A hardware `FAIL` blocks merge and escalates to owner — it is never overridden automatically.
- `--dry-run` performs zero side effects (no spawn, no merge, no build, no GPU work, no file writes except an in-memory plan printed to stdout).

## 6. State & idempotency

Persisted between ticks (all under `.astroray_plan/`):
- `.orchestrator.lock` — tick-overlap guard (PID + ISO ts; stale ≥ 25 min).
- `.orchestrator.gpu.lock` — single-GPU-slot guard (PID + head SHA + ISO ts; stale ≥ 90 min).
- `docs/standup/YYYY-MM-DD.md` — the human-facing output.
- `.orchestrator-state.json` — debounce + hardware-result ledger: `{ pr_number: { head_sha, last_action, last_action_ts, hw_result, hw_numbers, hw_artifact } }` so (a) a rebase/CI fixer is not re-spawned every 10 min for a PR already under repair, and (b) a hardware `PASS`/`FAIL` is remembered per head SHA and invalidated on any new push. Entries expire when the PR closes.

Everything else is recomputed from `gh`/`git` each tick. No tick trusts prior in-memory state.

## 7. Testing & acceptance

1. **Primary:** `/roadmap-orchestrator --dry-run` against the current `NEXT_STAGE_REPORT.md` §2 set (Round-10: pkg94 → pkg95 ∥ pkg96) prints the routing decisions, PR triage classification, the hardware-gate plan (which PR would take the GPU slot, queue order), and a standup preview, and makes **zero** side effects (verified: no new worktrees, no build, no GPU work, `main` unmoved, no PR state change, no files written).
2. **Classifier check:** a captured `gh pr list --json` fixture plus a synthetic `.orchestrator-state.json` is classified into the correct buckets (Rebase-needed / CI-failing / HW-untested / HW-failed / Ready / In-progress), including the head-SHA invalidation case (recorded `PASS` for an old SHA → re-queued).
3. **Guard tests:** (a) "isolated worktree cannot be created" → tick aborts that dispatch and records it blocked; `main` provably untouched. (b) GPU lock held → no second CUDA job is dispatched this tick (serialization holds). (c) hardware `FAIL` recorded → PR is not merged even with CI green; it appears under Action items.
4. **Acceptance:** the dry-run for the Round-10 set shows pkg94 dispatched first (no deps), pkg95/pkg96 gated until pkg94 merges, the pkg55-B-prime gate package classified per its Track, and the standup preview shows the Hardware-gate section (GPU-lock holder + HW-untested queue) and **no** "debt ledger".

## 8. Out of scope / future

- The full multi-scene closeout sweep (the orchestrator runs the *per-PR* package acceptance test, not the round-closeout gallery sweep — that stays an owner/architect step).
- Parallel hardware testing / multi-GPU (single serialized GPU slot is intentional; hardware throughput is the accepted bottleneck — memory `cuda_verifier_concurrency`).
- Cross-round priority re-planning (that is the architect's job, not the orchestrator's).
- Multi-repo orchestration.
