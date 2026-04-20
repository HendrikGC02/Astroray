# Overseer Handbook (Coordination)

**Role:** Weekly 15-minute session on claude.ai (not Claude Code).
Produces a ≤400-word briefing that tells you what to focus on this
week across all four tracks. Has no code authority. Does not open PRs,
does not write code, does not modify work packages.

**Why claude.ai and not Claude Code:** the overseer session is a
thinking exercise, not a coding session. Claude Code's strength is
multi-file coherent changes; the overseer just needs to read a few
status files and produce a plan.

---

## When to run

Monday morning, before you open VS Code. Takes 15 minutes.

If you skip a week: run it the next Monday anyway. The briefing is
based on current status, not last week's briefing.

---

## Input collection checklist

Before pasting the prompt, gather these inputs manually:

1. **`docs/STATUS.md`** — current state. Copy the full content.
2. **`scripts/ralph_queue.txt`** — what's in the queue. Copy the
   first 20 lines.
3. **`scripts/ralph_graduated.txt`** — tasks Ralph failed. Copy if
   non-empty.
4. **Open PRs** — run `gh pr list --state open` and copy the output.
5. **This week's calendar pressure** — are there any constraints on
   your time? (Optional one-liner: "I have ≤8 hours this week.")

---

## The exact prompt

Paste this into claude.ai with the gathered inputs substituted:

```
You are the overseer for Astroray development. Your job is to produce
a ≤400-word weekly briefing that tells the developer what to focus on
this week across four tracks. You have no code authority — do not
suggest writing code, do not reference specific implementations, do
not suggest changing the architecture.

Current status (from docs/STATUS.md):
---
STATUS_CONTENT
---

Ralph queue (first 20 lines of ralph_queue.txt):
---
QUEUE_CONTENT
---

Ralph graduated tasks (ralph_graduated.txt, if any):
---
GRADUATED_CONTENT
---

Open PRs:
---
PR_LIST
---

Calendar constraint (if any): CALENDAR_NOTE

Produce a briefing with this structure:
1. Last week — 2 sentences on what landed.
2. This week's focus — one thing per track (A/B/C/D). Be specific
   about which package or task. If a track should idle, say so.
3. Blockers — any dependency that is holding up progress.
4. Ralph queue — is the queue healthy? Should any graduated tasks be
   rewritten or escalated?
5. One risk to watch.

Keep it under 400 words. No code. No implementation suggestions.
Plain prose.
```

---

## Expected briefing shape

A well-formed briefing looks like this:

```
**Last week:** pkg02 (Lambertian migration) landed on track A.
Ralph added 4 tests. No track B issues merged.

**This week:**
- Track A: pkg03 (remaining materials migration). Estimated 2 sessions.
- Track B: Issue #12 (Metal plugin) — spec is ready, assign now.
- Track C: Prototype tiny-cuda-nn build alongside Astroray CUDA.
- Track D: Let Ralph run; queue has 14 tasks. No changes needed.

**Blockers:** pkg04 cannot start until pkg03 passes tests. pkg03
depends on the ParamDict design from pkg01, which is done.

**Ralph queue:** Healthy. One graduated task ("Add doc comment to
GRIntegrator") failed because the class was renamed. Rewrite to
reference the new name `BoyerLindquistIntegrator`.

**Risk to watch:** If pkg03 material migrations reveal issues with the
ParamDict default values, pkg04 will need a stop-and-fix before
proceeding. Watch for test failures on Dielectric refraction.
```

If the briefing is longer than 400 words or starts suggesting code,
discard it and re-run with the instruction "shorter, no implementation
details."

---

## What the overseer is forbidden from doing

- Opening or closing GitHub issues.
- Writing code or pseudocode in the briefing.
- Suggesting that a package's design should change.
- Modifying `docs/STATUS.md` — that is your job after the session.
- Assigning tasks to specific days ("do this Tuesday"). It coordinates
  tracks, not your schedule.

These constraints exist because the overseer has only a summary of
the state, not the full context. Architectural and design decisions
require that full context; the overseer does not have it.

---

## After the briefing

1. Update `docs/STATUS.md` based on what the briefing says landed last
   week.
2. Assign the track B issue(s) to the Copilot agent.
3. Start the track A Claude Code session with the specified package.
4. Start Ralph with the current queue (`bash scripts/ralph_loop.sh &`).
5. File the briefing nowhere. It is ephemeral. The source of truth is
   `STATUS.md` and the package files.
