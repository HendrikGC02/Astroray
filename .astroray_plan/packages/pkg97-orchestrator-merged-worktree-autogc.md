# pkg97 — Orchestrator safe post-merge worktree auto-GC

**Pillar:** 5
**Track:** A (engine/Python + git plumbing — no GPU, no physics, no CUDA)
**Codex-paste-ready:** yes
**Status:** done (PR #331, 2026-05-21 — three-gate safety: PR MERGED + content-in-main + clean worktree; squash-aware mergeCommit ancestry; OneDrive footgun handled; "Shipped today" fix; 47 tests pass)
**Estimated effort:** ~½ day (~4 h)
**Depends on:** roadmap-orchestrator design spec (2026-05-16) — the engine/skill this extends; pkg94 (the most recent ship that exposed the stall)

---

## Goal

**Before:** The roadmap-orchestrator counts `git worktree list`
entries toward `in_flight` against `IMPL_CAP` (2). It **never
auto-removes a merged package's worktree** — that was deliberately
left out of a bounded tick's scope as destructive, so the engine
only escalates a standup Action item. Result: every shipped package
leaves `.claude/worktrees/pkgNN` behind, and after **2 ships** the
engine silently stalls — `free=0`, `dispatch=[]`, every subsequent
tick a no-op until the owner manually runs `git worktree remove`.

Observed repeatedly 2026-05-16/17: pkg87 (stale, pre-merged; blocked
pkg94), pkg94 (merged via #304 squash `cc64e11`; worktree
`.claude/worktrees/pkg94` @ `1ffad42` still present after merge), and
the pkg55-s5 cycle. This is structural, not incidental — it WILL
recur on every package. See memory
`orchestrator-merged-worktree-impl-cap-stall`.

A second, co-located defect on the same close-out code path: the
daily standup **"Shipped today" stays `(none)`** even after a
successful merge — `upsert_standup`/`finalize_previous` is not
recording shipped PRs.

**After:** A subsequent tick, after `pr-reviewer` confirms a PR
merged, **safely** removes that PR's worktree + local branch — but
**only** when provably safe (all three conditions below). Anything
not provably safe is escalated as a standup Action item and never
force-deleted. The standup "Shipped today" section correctly lists
PRs merged that day. The engine no longer stalls within ≤2 ships.

---

## Context — why this matters now

The orchestrator is the project's autonomous advance engine. A
stall every ≤2 ships means it does roughly one useful burst of work
per owner intervention, defeating the "survives terminal close;
runs unattended" design goal (design spec §3). The cost is not a
slow tick — it is a *silent* full stop with a green-looking standup.

The naive fix ("delete stale-looking worktrees/branches") is a
**data-loss trap**. The inverse case was hit 2026-05-17: branch
`pkg93` had an **unmerged commit but NO worktree** — a
staleness-heuristic GC would have destroyed unmerged work. The
package must therefore reason about **merged-ness**, never about
staleness/age. Squash-merge makes this subtle: after a squash, the
branch tip is **not** an ancestor of `main`, so `git branch
--merged` alone reports the branch as un-merged even though its
content shipped. Detection must use GitHub's merge state, not git
ancestry alone.

This is engine/git-plumbing only — no GPU, no physics, no CUDA — so
it does not contend for the serialized hardware slot and is safe to
ship while hardware-gated packages are in flight.

---

## Reference

### Internal

- [`.astroray_plan/docs/2026-05-16-roadmap-orchestrator-design.md`](../docs/2026-05-16-roadmap-orchestrator-design.md)
  — §5 safety rails (worktree/`main` invariants), §3 execution
  model (worktree counts toward `in_flight`), Step 2/3.
- [`.claude/skills/roadmap-orchestrator/SKILL.md`](../../.claude/skills/roadmap-orchestrator/SKILL.md)
  — Step 1 (`in_flight` = active worktrees + running implementers),
  Step 2 (merges via `pr-reviewer`), Step 3 (`finalize_previous` /
  `upsert_standup` close-out), Safety rails.
- `roadmap_orchestrator/` Python package — `cli.py` (plan engine,
  zero side effects), `state.py` (`record_action`,
  `record_hw_result`, `expire_closed`, `save_ledger`),
  `standup.py` (`finalize_previous`, `upsert_standup`) — the
  modules this package extends. *(Locate exact module paths during
  Phase 0; the SKILL invokes `python -m roadmap_orchestrator.cli`.)*
- Memory `orchestrator-merged-worktree-impl-cap-stall` — the
  observed stall + the OneDrive permission-denied tactic (a `git
  worktree remove` that fails on the physical dir can still
  de-register the worktree; verify via `git worktree list`, not by
  checking the dir is gone).
- Memory `parallel_agent_worktree_contamination` and
  `harness_worktree_isolation_eexist` — why worktree ops are
  handled explicitly and carefully.
- Memory `stale_pyd_locations` — the OneDrive read-only/locked-dir
  footgun on `git worktree remove`.

### External (read for understanding only — no code mirrored)

- `gh pr view --json state,mergeCommit,mergedAt,headRefName,headRefOid`
  — GitHub CLI: authoritative merged-state + squash merge-commit.
  This is the cited source of truth for "merged", not git ancestry.
- `git worktree remove` / `git worktree prune` / `git branch -d`
  (safe delete; refuses un-merged) vs `git branch -D` (force;
  **never used by this package**) — Git documentation.

---

## Specification

### Phase 0 — locate the code path (~½ h)

Identify, in the `roadmap_orchestrator` package, exactly:
1. Where `in_flight` is computed from `git worktree list` (the
   counter that stalls).
2. Where the post-merge close-out runs after `pr-reviewer` reports a
   merge (Step 2 merges → Step 3 standup).
3. Where `upsert_standup` builds the "Shipped today" section, and
   why merged PRs are not landing in it.

Record the file:line of each in the PR description. **No behaviour
change in Phase 0** — read-only mapping.

### Phase 1 — safe merged-worktree auto-GC

Add a single, well-scoped routine (e.g.
`gc_merged_worktrees(ledger, gh_pr_json)`), invoked once per tick on
the **live** path only (never under `--dry-run`), **after** the
Step 2 merge step and **before** the Step 1 dispatch-fill `in_flight`
count is consumed on the *next* tick (i.e. it runs at close-out so
the next tick sees freed slots).

For each registered worktree under `.claude/worktrees/` with an
associated package branch, remove the worktree **and** its local
branch **iff ALL** of:

- **(a) PR is MERGED.** `gh pr view <branch> --json state,mergeCommit,mergedAt`
  reports `state == "MERGED"` with a non-null `mergeCommit`. If
  there is no PR for the branch, condition (a) fails → escalate, do
  not delete (covers the `pkg93` "unmerged commit, no PR" trap —
  though that case has no worktree, the branch-delete arm must apply
  the same gate).
- **(b) Content is in `main`, squash-aware.** Satisfied if **either**
  the branch tip is an ancestor of `origin/main`
  (`git merge-base --is-ancestor <tip> origin/main`) **or** the PR's
  `mergeCommit` from (a) exists in `origin/main`'s history
  (`git merge-base --is-ancestor <mergeCommit> origin/main`). The
  second arm is the squash-merge case: after a squash the branch tip
  is **not** an ancestor, so ancestry alone is insufficient and the
  `mergeCommit` check is the authoritative signal.
- **(c) Zero uncommitted AND zero unpushed changes** in the
  worktree. `git -C <wt> status --porcelain` is empty **and** `git
  -C <wt> log --oneline @{upstream}..HEAD` is empty (no commits
  ahead of the pushed branch). If the branch has no upstream, treat
  as **unsafe** → escalate.

Removal procedure when (a)∧(b)∧(c) hold:
1. `git worktree remove <wt>` (NOT `--force`).
2. If step 1 fails with a permission/lock error (OneDrive footgun)
   but `git worktree list` no longer lists `<wt>`, treat the
   **de-registration as success** (memory
   `orchestrator-merged-worktree-impl-cap-stall`); record the
   physical-dir cleanup as a standup Action item for the owner.
3. `git branch -d <branch>` (safe delete; **never** `-D`). If
   `branch -d` refuses (git still thinks it is unmerged — expected
   after squash), and condition (b) was satisfied via the
   `mergeCommit` arm, `git branch -D <branch>` is permitted **only
   in this exact narrowed case** (PR `state == "MERGED"` AND
   `mergeCommit` in `origin/main`); log the forced delete explicitly
   in the standup with the merge commit SHA as justification.
4. After removal, `git worktree prune`.

If **any** of (a)/(b)/(c) is not provably true, **do not touch the
worktree or branch**. Add a standup Action item naming the
worktree, the branch, and which condition failed.

**Hard invariant:** the routine must NEVER remove a worktree or
branch that is live or unmerged. There is no age/staleness input to
this routine at all — only merged-ness. A worktree whose PR is open,
draft, closed-without-merge, or absent is always escalated, never
deleted.

### Phase 2 — fix "Shipped today" recording

In the standup close-out path, ensure a PR merged during the current
local day is upserted into the **"Shipped today"** section (number,
pkg, "CI-green + hardware-PASS", measured numbers when available).
The source of merged PRs for the day is the same `gh pr list`/`gh
pr view` data already fetched in the tick (filter by `mergedAt`
within the local day). This is a write-path bug in
`upsert_standup`/`finalize_previous` — fix the recording, do not
restructure the standup format.

### Files to modify

| File | Change |
|---|---|
| `roadmap_orchestrator/` (the module owning worktree GC / close-out — confirmed in Phase 0) | Add `gc_merged_worktrees(...)` implementing the (a)∧(b)∧(c) gate + escalation. Pure git/`gh` plumbing; no new deps. |
| `roadmap_orchestrator/` standup module | Fix the "Shipped today" upsert so day-local merged PRs are recorded. |
| `.claude/skills/roadmap-orchestrator/SKILL.md` | In Step 3 close-out, add the one-line invocation of the safe auto-GC (live path only; explicitly NOT under `--dry-run`). Update the Safety-rails block to state the merged-only, never-force, escalate-on-doubt invariant. |
| `tests/test_orchestrator_worktree_gc.py` *(new)* | Unit tests with mocked `gh`/`git` outputs (no real worktrees, no network) for every gate branch below. |

### Acceptance criteria

- [ ] Squash-merge case: PR `MERGED`, branch tip NOT an ancestor of
      `main`, `mergeCommit` IS in `main`, clean worktree → worktree
      **and** branch removed; freed slot reflected in next-tick
      `in_flight`.
- [ ] Normal-merge case: PR `MERGED`, branch tip IS ancestor of
      `main`, clean → removed.
- [ ] Open-PR case: PR `OPEN` → worktree/branch untouched; standup
      Action item written.
- [ ] No-PR-for-branch case (the `pkg93` inverse trap): branch with
      a commit but no PR → untouched; escalated. Asserts no `branch
      -D` is ever issued here.
- [ ] Dirty-worktree case: `MERGED` + in `main` but `git status
      --porcelain` non-empty OR unpushed commits → untouched;
      escalated.
- [ ] Permission-denied-but-deregistered case: `git worktree
      remove` errors yet `git worktree list` no longer shows it →
      treated as success; physical-dir cleanup raised as Action
      item.
- [ ] `--dry-run` performs **zero** worktree/branch deletions and
      zero `gh`/`git` mutations (regression guard on design spec §5).
- [ ] "Shipped today" lists a PR merged earlier the same local day
      (was previously `(none)` — Phase 2 regression test).
- [ ] Existing orchestrator test suite stays green
      (`pytest tests/test_orchestrator*.py` or the project's
      orchestrator test path).
- [ ] Call-site sweep: `gc_merged_worktrees` and any changed
      standup signature grepped repo-wide; SKILL.md + tests updated.

### Hard non-goals

- **No staleness/age heuristic.** Merged-ness is the *only* signal.
  No "older than N hours" input anywhere in this routine.
- **No `git branch -D` outside the one narrowed squash case**
  (PR `state == "MERGED"` AND `mergeCommit` in `origin/main`). Never
  force-delete on doubt.
- **No touching unmerged or live worktrees/branches**, ever — escalate.
- **No new persisted state.** Reuse the existing ledger / `gh` /
  `git` ground truth recomputed each tick (design spec §6). No new
  lock files.
- **No standup format restructuring.** Phase 2 fixes the recording
  bug only; section layout is unchanged.
- **No owner-side automation / scheduler change.** The fix lives
  inside the bounded tick close-out, not a separate cron.
- **No retroactive cleanup tooling** for already-orphaned worktrees
  beyond what the normal per-tick gate naturally collects.

---

## Why this matters

This is the difference between an autonomous engine that advances
the roadmap unattended and one that needs an owner unblock every
~2 ships. The package also encodes a permanent invariant — *"GC by
proven merged-ness, never by staleness"* — that protects every
future worktree the orchestrator creates from the data-loss trap
that the `pkg93` inverse case demonstrated. The squash-aware
detection is the load-bearing subtlety: the project squash-merges,
so any merged-ness check that relies on git ancestry alone is wrong
by construction.

---

## Lessons (filled in on completion)
