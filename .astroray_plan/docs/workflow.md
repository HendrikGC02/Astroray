# Astroray Workflow — quick reference

This is the short version of how to use the autonomous dev loop. For
the design rationale behind it, see the conversation that produced
the agent definitions in `.claude/agents/` and skill files in
`.claude/skills/`.

The principle: **direction-setting is yours; execution is the loop's.**

---

## Your three modes

### 1. Passive — most of the time

Open the laptop, glance at the dashboard (Sheets tracker), read any
push notifications that arrived. Often nothing's required of you.
That's the loop working. Move on with your day.

### 2. Architect calls you — periodic planning beats

A push notification: *"strategy review fired"* or *"decision required:
c1-vs-c2 fork"*. Open the CLI. Architect speaks first with framing +
a short open question. You answer free-form. It pushes back if it
disagrees. You converge. It writes the PR. **~5–30 min.**

### 3. You have a new goal — whenever

`/architect "I want a render of a [thing]"` — vague is fine.
Architect researches, comes back with N options + tradeoffs, dialogue,
picks, files specs, dispatches implementation.

---

## Command reference — when to use which

| You see / want | Run |
|---|---|
| **New idea or desire** (vague to specific) | `/architect "<goal>"` |
| **Feel lost about direction** OR end of a round and curious | `/strategy-review` |
| **A round looks done** in the dashboard (deployable set all green) and the pulse hasn't fired yet | `/close-round` |
| **Want to fire the next package manually** (pulse off, or impatient) | `/dispatch-next` |
| **Want to inspect a render** ad hoc | `/visual-check <path> [<ref>]` |
| **A package needs a hardware re-verify** (rare; PRs are usually auto-labeled) | `/verify <pkg>` |
| **You spotted something out-of-scope** while reading a PR or render | `/file-followup "<reason>"` |

### Commands the agents fire (you generally won't)

These get spawned by other agents and skills — only run them manually
if something gets stuck:

- `cite-algorithm` — implementer agents auto-invoke before any
  non-trivial physics/sampling/numerical algorithm
- `commit-commands:commit-push-pr` — agents fire this after work
- `superpowers:*` — wrapped into custom agents (`package-implementer`
  uses `executor`, `pr-reviewer` uses `critic`, etc.)
- `verify` — `pr-reviewer` labels PRs needing hardware verification
  and the pulse dispatches the verifier automatically

---

## The five-minute weekly rhythm

| When | What |
|---|---|
| Morning, while coffee brews | Glance at the Sheets tracker. KPI band tells you everything in one view. |
| Phone buzz | Push notification — read it. Decision-required → open CLI. Direction signal (round closed, gate fell, new spec filed) → acknowledge and move on. |
| End of a round (every 1–2 weeks) | Architect probably auto-fires a state+refine. ~5 min. |
| When you have a new aesthetic target / curiosity / "what if" | `/architect "<thing>"` |
| Every 3rd round (or auto-triggered by 3+ deferred packages, or by a measurement-vs-spec divergence event) | Deep strategy review with architect. **~30 min. Where direction actually gets set.** |

---

## What the loop is doing while you're not looking

- **Implementer agents** ship packages in worktrees (`package-implementer`).
- **pr-reviewer** auto-merges clean PRs per the trust-boundary rules.
- **hardware-verifier** runs gate tests + visual inspection on
  RTX-needed PRs; appends measured numbers to spec Lessons sections.
- **gate-failure-reviewer** escalates when a fix PR doesn't clear a
  gate — checks upstream AND downstream (the pkg73 two-bug-masking
  pattern).
- **docs-updater** regenerates STATUS / ROADMAP / NEXT_STAGE_REPORT
  at round close.
- **architect** runs idle scan once a week (background research on
  Cycles changelogs, recent papers, OIDN/OptiX/tcnn releases) — pings
  you with "have you thought about X" when something surfaces.
- **Pulse** (if enabled) fires `/dispatch-next` and `/close-round`
  when conditions hit.

Pretty pictures land in `test_results/` and the showcase HTML. The
architect surfaces them when relevant.

---

## Trust boundaries — what auto-merges vs asks

| PR type | Auto-merge? |
|---|---|
| Doc-only (touches only `*.md` and `.astroray_plan/`) | ✅ |
| Verifier PR (only spec Lessons + ≤1 one-line test parameter change, with measured numbers) | ✅ |
| Feature PR with green CI + reviewer subagent green + all spec acceptance criteria addressed | ✅ |
| Touches `CMakeLists.txt`, build presets, or a new public Python binding | ❌ — pings you |
| Changes a gate floor or removes a test | ❌ — pings you |
| Suspected CLAUDE.md §6 violation (uncited algorithm, GPL borrow) | 🛑 — halts, files an issue |

---

## How direction gets set (vs. how execution happens)

| | Set by | When |
|---|---|---|
| **Direction** (what to build, what to park, what to refocus) | You + architect dialogue | Round close, every 3rd round deep, or when you fire `/architect "<goal>"` |
| **Execution** (writing code, running tests, opening PRs, merging) | Agent loop (mostly autonomous) | Continuously, paced by the pulse if enabled |

The two never collapse into each other. Mixing them gives you either
a survey ("what do you want?") or a runaway agent ("here's 30 PRs you
didn't ask for"). Keeping them separate is the whole point.

---

## Related docs

- [`ROADMAP.md`](ROADMAP.md) — the five pillars + strategic gate state
- [`STATUS.md`](STATUS.md) — current package board + pillar percentages + changelog
- [`NEXT_STAGE_REPORT.md`](NEXT_STAGE_REPORT.md) — the current round's deployable set + drop-in prompts (regenerated by `docs-updater` at every round close)
- [`tracker/README.md`](../tracker/README.md) — Sheets dashboard recovery + maintenance
- `CLAUDE.md` (project root) — the §1–§6 discipline rules every agent enforces
