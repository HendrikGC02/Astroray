# Astroray Development Plan

**Self-contained.** Everything you (or any AI agent) needs to push Astroray
toward being the best open-source physically-based astrophysical rendering
engine is in this folder. Drop it into the repo root as `.astroray_plan/`.

## Start here

1. **[`docs/ROADMAP.md`](docs/ROADMAP.md)** — master roadmap. Agent tracks,
   five pillars, 12-week view. Read first.
2. **[`docs/STATUS.md`](docs/STATUS.md)** — current state. Updated weekly.
3. **[`docs/NEXT_STAGE_REPORT.md`](docs/NEXT_STAGE_REPORT.md)** — current
   Codex orientation report and recommended next work.
4. Pick a package from **[`packages/`](packages/)** and go.

## Structure

```
.astroray_plan/
├── README.md                      ← this file
├── docs/                          ← design documentation
│   ├── ROADMAP.md                ← start here
│   ├── STATUS.md                 ← current state
│   ├── NEXT_STAGE_REPORT.md      ← Codex orientation + next-stage report
│   ├── local-agent-integration.md← local model integration plan
│   ├── plugin-architecture.md    ← Pillar 1 design
│   ├── spectral-core.md          ← Pillar 2 design
│   ├── light-transport.md        ← Pillar 3 design
│   ├── astrophysics.md           ← Pillar 4 design
│   ├── production.md             ← Pillar 5 design
│   └── external-references.md    ← libraries, data, papers
├── agents/                        ← per-agent handbooks
│   ├── claude-code.md            ← track A
│   ├── codex.md                  ← Codex repo/GitHub/coordination workflow
│   ├── copilot-cloud.md          ← track B
│   ├── copilot-instructions.md   ← copy to .github/copilot-instructions.md
│   ├── copilot-setup-steps.yml   ← copy to .github/workflows/
│   ├── cline.md                  ← track C
│   ├── ralph-loop.md             ← track D
│   └── overseer.md               ← coordination
├── packages/                      ← work packages (one per PR/session)
│   ├── TEMPLATE.md
│   ├── pkg01-registry-skeleton.md
│   ├── pkg02-migrate-lambertian.md
│   ├── pkg03-migrate-remaining-materials.md
│   ├── pkg04-migrate-textures-shapes.md
│   ├── pkg05-integrator-interface.md
│   └── pkg06-pass-registry.md
├── scripts/
│   ├── ralph_loop.sh             ← background grind worker
│   ├── ralph_queue.txt           ← Ralph's task queue
│   └── bootstrap.sh              ← one-time setup
├── examples/                      ← (future) example plugins
└── logs/                          ← auto-generated Ralph reports
```

## The agent tracks at a glance

| Track | What it is | When to use | Cost |
|---|---|---|---|
| **A. Claude Code** (local) | Multi-file refactors, core work | Pillar foundations; anything touching invariants | Anthropic API session |
| **B. Copilot cloud** | Self-contained features | New plugins matching an existing pattern | Education Premium |
| **C. Cline + local model** | Prototype and experimentation | "Does X even work?" exploration | Free (your RTX 5070 Ti) |
| **D. Ralph loop** | Background grind (tests, docs) | Small, mechanical, verifiable tasks | Free (your GPU, idle time) |
| **E. Codex** | Repo setup, PR/issue orchestration, targeted fixes, reviews | Handoffs, CI/debug, scoped implementation, next-step reports | ChatGPT/Codex plan or local mode |

## Weekly rhythm

**Monday morning (15 min):** Run an overseer session on claude.ai. Get a
briefing. Update `docs/STATUS.md`. Know what you're doing this week.

**During the week:** Launch Claude Code sessions (track A) 1-2 times on
the current pillar's foundation work. Assign 2-5 Copilot cloud issues
(track B). Let Ralph (track D) run overnight.

**Friday (15 min):** Review and merge what landed. Update the Ralph
queue for next week. Close completed packages.

Rinse, repeat.

## One-time setup

Run `scripts/bootstrap.sh` to copy the Copilot files into `.github/` and
verify the GitHub Actions workflow. After that, start on pkg01.
