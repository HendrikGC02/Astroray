# roadmap-orchestrator — Design Spec

- **Date:** 2026-05-16
- **Status:** approved (brainstorming) — ready for implementation plan
- **Owner decisions baked in:** `/schedule` cron engine; NEXT_STAGE_REPORT §2 readiness-filtered dispatch; full auto-merge; thin composer over existing skills.

## 1. Purpose

A single project skill that, on each cron tick, advances the Astroray roadmap autonomously: it dispatches ready packages to implementer agents, triages every open PR and routes it to the correct fixer (or auto-merges it), and maintains a daily standup of what shipped, what is blocked, and what still owes the owner a hardware verification.

It is **policy/orchestration only**. It does not re-implement spec-reading, worktree hygiene, dispatch routing, PR review, or CI-fixing — it composes the skills/agents that already do those.

## 2. Non-goals

- Not a re-implementation of `pkg-ship` / `dispatch-next` / `pr-reviewer` / `gate-failure-reviewer` / `verify`. It calls them.
- Does **not** run GPU/hardware verification. Ever. (CI has no GPU; two concurrent CUDA verifiers crash the RTX. Hardware verification stays human-gated and serial — memories `ci_has_no_gpu_runtime_blindspot`, `cuda_verifier_concurrency`.)
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

### Step 2 — PR triage
1. `gh pr list --state open --json number,title,headRefName,isDraft,mergeable,mergeStateStatus,statusCheckRollup`.
2. Classify each open PR and route (debounced — see §6):
   | State | Condition | Action |
   |---|---|---|
   | **Ready** | not draft, `mergeable=MERGEABLE`, rollup all-pass | Auto-merge via `pr-reviewer` agent (its checklist self-escalates and **stops** on gate/license problems instead of merging). On success → append GPU-verification-debt ledger entry. |
   | **Rebase-needed** | `mergeable=CONFLICTING` or behind base | Dispatch a rebase-fixer on that PR's branch in its own worktree (rebase/merge `origin/main`, push). |
   | **CI-failing** | rollup has `FAILURE` | Dispatch `gate-failure-reviewer` to diagnose, then a `pkg-ship` CI-fix pass on that branch worktree. |
   | **In progress** | draft, or rollup `PENDING` | Report only; no action. |
3. Fixers obey a separate cap (default **1** concurrent fixer). A rebase/CI fixer is never dispatched against a branch that has a hardware-verification in progress. No GPU work is ever auto-run.

### Step 3 — Standup
Upsert `.astroray_plan/docs/standup/YYYY-MM-DD.md` (one file per local day). Sections:
- **Shipped today** — PRs merged this day (number, pkg, "MERGED on CI-green only — GPU sweep owed").
- **In-flight** — package · worktree · agent · dispatched-at.
- **Blocked** — deps-unsatisfied / research-not-ready / subagent-escalated, with reason.
- **Needs YOUR hardware verification** — the GPU-verification-debt ledger: every auto-merged PR awaiting a manual RTX sweep, oldest first.
- **CI under repair** — failing PRs with a fixer dispatched, and the diagnosis link.
- **Action items** — anything requiring an owner decision (escalations, contamination alerts, stale locks).

On the first tick of a new local day, finalize the previous day's file (write a one-line summary footer) before starting the new one.

## 5. Safety rails (explicit, non-negotiable)

- Lock file prevents overlapping ticks.
- Every implementer/fixer runs in its own isolated worktree, or the dispatch is aborted — never main.
- `main` is mutated **only** by the `pr-reviewer` auto-merge path; post-dispatch audit catches any unexpected `main` movement and raises a `CONTAMINATION` alert.
- Implementer cap (default 2); fixer cap (default 1).
- Hardware/GPU verification is never auto-run and never parallelized — only flagged in the standup ledger.
- Every auto-merge writes a GPU-verification-debt ledger entry (CI-green ≠ GPU-correct on this project — memory `ci_has_no_gpu_runtime_blindspot`).
- `--dry-run` performs zero side effects (no spawn, no merge, no file writes except an in-memory plan printed to stdout).

## 6. State & idempotency

Persisted between ticks (all under `.astroray_plan/`):
- `.orchestrator.lock` — overlap guard (PID + ISO ts).
- `docs/standup/YYYY-MM-DD.md` — the human-facing output.
- `.orchestrator-state.json` — debounce ledger: `{ pr_number: { last_action, last_action_ts } }` so a rebase/CI fixer is not re-spawned every 10 min for a PR already under repair. Entries expire when the PR closes.

Everything else is recomputed from `gh`/`git` each tick. No tick trusts prior in-memory state.

## 7. Testing & acceptance

1. **Primary:** `/roadmap-orchestrator --dry-run` against the current `NEXT_STAGE_REPORT.md` §2 set (Round-10: pkg94 → pkg95 ∥ pkg96) prints the routing decisions, PR triage classification, and a standup preview, and makes **zero** side effects (verified: no new worktrees, `main` unmoved, no PR state change, no files written).
2. **Classifier check:** a captured `gh pr list --json` fixture is classified into the four buckets correctly (Ready / Rebase-needed / CI-failing / In-progress).
3. **Guard test:** simulate "isolated worktree cannot be created" → the tick aborts that dispatch and records it blocked; `main` is provably untouched (no fallback path exists).
4. **Acceptance:** the dry-run output for the Round-10 set shows pkg94 dispatched first (no deps), pkg95/pkg96 gated until pkg94 merges, the pkg55-B-prime gate package classified per its Track, and the standup preview lists the GPU-debt ledger section.

## 8. Out of scope / future

- Auto-running the hardware verifier (deliberately excluded — human-gated).
- Cross-round priority re-planning (that is the architect's job, not the orchestrator's).
- Multi-repo orchestration.
