---
name: team-overnight
description: Stand up a persistent agent team for an unattended overnight Astroray run — architect researches and writes specs, orchestrator ticks dispatch implementation, hardware-verifier visually checks renders, docs-scribe writes the morning standup. Time-bounded; ships whatever lands cleanly.
invocation: /team-overnight
---

# /team-overnight

Unattended multi-hour run. The owner kicks this off, walks away, and reads the
morning standup. **Time-bounded** — no fixed deliverable; ship what lands cleanly
with HW verification.

## Preconditions (verify before TeamCreate)

1. `git status` clean on `main`; `git fetch origin`; up to date.
2. `.astroray_plan/.orchestrator.lock` not held (`Get-Content` to check meta; if held by a dead PID, release).
3. `.astroray_plan/.orchestrator.gpu.lock` not held.
4. `git worktree list` — no leftover merged worktrees (orchestrator will GC, but a clean start avoids first-tick noise).
5. `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` in `.claude/settings.json` (already set).
6. **The Task Scheduler `Astroray-RoadmapOrchestrator` task must be DISABLED for the duration of the team run.** The team-lead drives the tick loop itself (see Loop below); two engines running in parallel would double-dispatch even though locks would prevent corruption. `Disable-ScheduledTask -TaskName 'Astroray-RoadmapOrchestrator'`. Re-enable on team shutdown if you want the scheduled tick to resume after the run.
7. Recent `.pyd` built (mtime within ~24h of HEAD on `main`). If stale, run `/rebuild-pyd` first.

## Team topology

```
TeamCreate team_name="astroray-overnight"
```

Persistent members (spawned via Agent with team_name + name):

| Name             | Subagent type        | Role                                                                  |
|------------------|----------------------|-----------------------------------------------------------------------|
| `team-lead`      | (this session)       | Boots team, runs kickoff, monitors, calls last-call + shutdown        |
| `architect`      | general-purpose      | Strategy review, research, spec writing, follow-up filing             |
| `pr-merger`      | pr-reviewer          | Reviews and merges PRs that pass CI + HW gates                        |
| `docs-scribe`    | docs-updater         | Updates STATUS / ROADMAP / NEXT_STAGE_REPORT; finalizes daily standup |

Ephemerals (spawned per tick by the orchestrator, NOT persistent):

- `package-implementer` per dispatched package, each in its own isolated worktree.
- `hardware-verifier` per HW gate, **serialized by the GPU lock** (see below).
- `gate-failure-reviewer` per failure.
- `codex-implementer` for Track-E codex-paste-ready specs.

## Hardware mutex (non-negotiable)

`memory/cuda_verifier_concurrency.md` — two CUDA-heavy verifiers on this RTX
produce false-positive illegal-access crashes. The orchestrator already
serializes via `.astroray_plan/.orchestrator.gpu.lock`. **Nothing in this team
ever bypasses that lock.** If a team member wants to run a render or HW check
outside the orchestrator's dispatch, it MUST `acquire_lock` first and release on
exit.

## Kickoff (team-lead executes once at boot)

1. `TeamCreate` (`astroray-overnight`).
2. Spawn `architect`, `pr-merger`, `docs-scribe` as **persistent team members**.

   ⚠️ **CRITICAL — they MUST be spawned with `team_name` AND `name` params, not as bare `Agent` calls.** A bare `Agent` call runs the prompt and exits; the agent never joins the team and never goes idle waiting for messages. `SendMessage` to a non-joined name silently fails (message routes nowhere). Verified failure mode 2026-05-24 overnight run — the entire persistent-specialists topology was a ghost layer.

   Correct invocation per teammate (run all three in parallel):
   ```
   Agent(
     subagent_type: "general-purpose"   (or pr-reviewer / docs-updater)
     team_name:     "astroray-overnight"
     name:          "architect"          (or pr-merger / docs-scribe)
     prompt:        "<role brief; ends with `Join the team and go idle when done with the boot task. Wake on messages from team-lead.`>"
   )
   ```

   After spawning, **verify** they joined: read `<user-home>\.claude\teams\astroray-overnight\config.json` — the `members` array should list four entries (team-lead + the three persistent). If only team-lead is there, the spawn didn't join and `SendMessage` to those names will go to /dev/null. Re-spawn with the correct params before kickoff Step 3.
3. Send `architect` this task: *"Run `/strategy-review`. Survey STATUS.md / ROADMAP.md / NEXT_STAGE_REPORT.md / open PRs / recent standups. Identify the next 2–4 highest-leverage deployable packages for tonight's run. If any need a spec written or refreshed before they're dispatchable, write it now via `/file-followup` or by editing the existing spec under `.astroray_plan/packages/`. Do NOT implement; your output is research + specs ready for the orchestrator to pick up. When done, message team-lead with the list of packages you've made dispatchable and any research notes saved under `.astroray_plan/docs/`."*
4. Wait for `architect` to report back. Confirm the named specs exist and `Status:` lines are set so the orchestrator's eligibility check passes (see `memory/orchestrator-next-stage-report-stale.md`).
5. Confirm `Astroray-RoadmapOrchestrator` Task Scheduler task is **Disabled** (preconditions §6). The team-lead — not the scheduler — drives the loop.

## Loop (team-lead drives, runs unattended until last-call)

The team-lead session runs `/roadmap-orchestrator` itself on a ~10-minute
cadence (use `/loop 10m /roadmap-orchestrator` or self-pace via
`ScheduleWakeup`). Each tick is self-contained: guards → dispatch → fixers →
HW gate → merges → standup upsert → GC → release lock. Between ticks, the
team's persistent members work asynchronously on messaged tasks:

- **`pr-merger`** wakes when the orchestrator posts a "ready-to-merge" PR. Runs the `pr-reviewer` checklist (CI all-pass, HW PASS bound to head SHA, no license issues). Merges or escalates with reason.
- **`docs-scribe`** wakes on ship events: updates STATUS/ROADMAP and appends to today's standup. Finalizes yesterday's standup at day-roll.
- **`architect`** is dormant between explicit asks. If the orchestrator emits a `BLOCK` verdict or a `gate-failure-reviewer` requests deeper research, team-lead routes it to `architect`.
- **`hardware-verifier`** (ephemeral) runs after dispatch, holds the GPU lock, builds via `scripts/build_cuda_worktree.bat <worktree> <sha>`, runs gate tests, then performs `/visual-check` on rendered PNGs against any reference. Reports PASS/FAIL with measured numbers; result is bound to the PR's head SHA (`record_hw_result`).

## Visual-inspection protocol (every HW verify)

After every gate that produces an image (`pkg54*`, `pkg63`, `pkg64`, `pkg70`,
`pkg72`, `pkg74`, `pkg76`, `pkg87d`, prism/HDRI/envmap work), the
`hardware-verifier` follows with `/visual-check` reading the PNG via Claude's
multimodal capability. Logs a short qualitative note alongside the numeric
result. CI green + numeric PASS but visual fail → mark `hw_failed` and route to
`gate-failure-reviewer` (per `memory/gr-emission-model-wiring-checklist.md`).

## Last-call + shutdown (team-lead, near morning)

About 45 minutes before the run ends:

1. Stop dispatching new packages: message `architect` to file any out-of-scope findings to specs (do not start new implementation).
2. Let in-flight ticks finish (worktrees drain via merge or revert; HW lock releases naturally).
3. Once `git worktree list` shows only `main`, ask `docs-scribe` to finalize today's standup with:
   - Shipped today (merged PRs)
   - HW verifications and visual notes
   - Blocked / escalated items needing owner attention
   - Specs updated / created
4. `SendMessage {type: shutdown_request}` to each persistent teammate.
5. Optionally `Enable-ScheduledTask -TaskName 'Astroray-RoadmapOrchestrator'` to restore the scheduled-tick fallback.
6. Final message to owner: link to the standup file + summary of any standup `Action:` items.

## Safety rails (lifted from /roadmap-orchestrator SKILL)

- One tick at a time (orchestrator tick lock).
- **One CUDA job at a time, ever** (`orchestrator.gpu.lock`).
- Implementer cap 2, fixer cap 1.
- Per-package isolated worktree or abort — never write to `main`.
- Auto-merge requires CI all-pass AND HW `PASS` bound to head SHA AND (for non-HW-gated PRs) different-model `SIGN-OFF`.
- A HW `FAIL` is never overridden automatically.
- Destructive git ops (`worktree remove`, `branch -D`) only via the orchestrator's safe `gc_merged_worktrees`, which requires MERGED + content-in-`origin/main` + clean worktree.

## What to do if things go wrong

| Symptom                                  | Action                                                                                |
|------------------------------------------|---------------------------------------------------------------------------------------|
| Team-lead loop missed a tick             | Re-issue `/loop 10m /roadmap-orchestrator`; if the team-lead session itself died, re-enable the Task Scheduler task as the resilient fallback and re-kickoff. |
| GPU lock stuck > 90 min                  | The verifier crashed. Inspect `.astroray_plan/.orchestrator.gpu.lock` meta, release.  |
| Worktree contamination on `main`         | Halt all dispatch; `git status` on main, isolate, file an Action item for owner.      |
| Persistent CI-rescue commits on same PR  | Route to `gate-failure-reviewer` for root-cause; do not let an implementer thrash.    |
| Repeated `BLOCK` on same fix             | Stop pushing; escalate to architect for design review.                                |
| Two HW jobs requested in same tick       | Bug — orchestrator should never emit this. Halt, file an Action item.                 |
| `architect` proposing new algorithm      | Enforce `/cite-algorithm` (CLAUDE.md §6); no invented algorithms.                     |

## Why this is safe to leave unattended

Every destructive boundary has a lock or a gate:
- Branch isolation via per-package worktrees.
- HW serialization via `gpu.lock`.
- Merge gating via CI + HW + independent review.
- Worktree GC is merged-only, never force-delete.
- The signature-sweep PreToolUse hook surfaces stale call sites before any push.
- The `pyd_shadow_guard` PreToolUse hook blocks tests that would load shadow `.pyd` copies.

If any rail trips, the affected tick no-ops and the next tick re-evaluates from
ledger state. The owner's morning standup will list anything that escalated.
