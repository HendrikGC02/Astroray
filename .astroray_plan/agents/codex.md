# Codex Handbook

**Role:** repo-integrated engineering agent. Codex is best used for fast local
orientation, scoped implementation, GitHub issue/PR triage, CI/debug follow-up,
and preparing handoff specs for Claude Code, Copilot coding agents, or local
model workers.

Codex should complement Claude Code, not replace it:

- Use **Claude Code** for long, core track-A changes where cross-file physics
  invariants must be held in one model's head.
- Use **Codex** for local repo setup, issue shaping, PR review, CI diagnosis,
  targeted fixes, reports, and small-to-medium implementation packages.
- Use **GitHub Copilot coding agents** for narrow plugin-pattern issues with
  exact file scope and machine-checkable acceptance criteria.
- Use **local model workers** for prototypes, mechanical test/doc tasks, and
  overnight queues where a wrong answer can be discarded cheaply.

## Starting A Codex Session

1. Read `AGENTS.md`.
2. Read `.astroray_plan/docs/STATUS.md`.
3. If choosing next work, read `.astroray_plan/docs/ROADMAP.md` and the relevant
   pillar design doc.
4. Check `git status --short --branch`.
5. For coding changes, create a `codex/<topic>` branch unless the user says
   otherwise.

## Default Codex Workflows

### Repo Orientation

- Summarize current status from `.astroray_plan/docs/STATUS.md`.
- Compare docs against live repo state with `pytest --collect-only -q`, `git log`,
  and open GitHub issues/PRs.
- Record stale instructions as doc fixes instead of relying on memory.

### Implementation

- Keep changes narrowly scoped.
- Prefer plugins and tests over edits to `include/raytracer.h`.
- Re-run CMake when adding plugin files because plugin discovery uses CMake globbing.
- Run focused tests first, then the full suite when the change touches shared paths.

### GitHub Handoff

Codex should write issues for other agents in this shape:

```markdown
## Goal
One concrete deliverable.

## Context
Relevant package, closest existing file, and why this is safe for this agent.

## Files Allowed
Exact paths or path globs.

## Acceptance Criteria
- [ ] Machine-checkable result.
- [ ] Focused test.
- [ ] Full test command.

## Non-goals
Explicit files and behaviors not to touch.
```

Use Copilot only for tasks that match an existing plugin/test pattern. Use
Claude Code when the task changes renderer invariants, GR math, integrator
contracts, or build architecture. Use local model workers for disposable
experiments and mechanical queue items.

## Verification Baseline

```bash
cmake -B build -DCMAKE_BUILD_TYPE=Release -DASTRORAY_ENABLE_CUDA=OFF
cmake --build build -j
pytest --collect-only -q
pytest tests/ -v --tb=short
```

On Windows, stale `.pyd` files can shadow the fresh build. Before debugging
surprising behavior, run:

```powershell
Get-ChildItem -Recurse -Filter 'astroray*.pyd'
```

The authoritative test module should normally be under `build/`.

## Current Codex Priorities

1. Keep agent instructions current as the architecture changes.
2. Shape Pillar 3 into small packages before implementation starts.
3. Turn rendering-output observations into explicit tests where possible.
4. Use GitHub issues/PRs as the coordination layer so the user does not have to
   manually shuttle context between agents.
