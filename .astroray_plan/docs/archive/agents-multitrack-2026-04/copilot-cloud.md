# GitHub Copilot Cloud Handbook (Track B)

**Role:** Feature breadth worker. Handles self-contained features that
match an existing pattern — new plugins, well-scoped additions. Runs
inside GitHub Actions as a Copilot coding agent, triggered from a
GitHub issue. Zero cost beyond an Education Premium or Copilot
Enterprise seat.

**What track B is good at:** spinning up five plugins in parallel,
mechanical pattern-matching work, anything with a clear input/output
spec.

**What track B is bad at:** refactors that touch invariants, work
requiring deep context across 20+ files, anything where "doing it
right" isn't obviously derivable from a spec.

---

## One-time setup

### 1. Enable the Copilot coding agent

In your GitHub account:
1. Settings → Copilot → Policies.
2. Enable "Copilot coding agent" for the `Astroray` repository.
3. Confirm the agent appears under the "Assignees" list in issues.

### 2. Add `.github/copilot-instructions.md`

Run `scripts/bootstrap.sh` (one-time). It copies
`.astroray_plan/agents/copilot-instructions.md` to
`.github/copilot-instructions.md`. This file tells the agent how to
build, test, and what not to touch. Never let the agent run without it.

Verify: `cat .github/copilot-instructions.md` — should be the
`copilot-instructions.md` content verbatim.

### 3. Add `.github/workflows/copilot-setup-steps.yml`

Also done by `bootstrap.sh`. This workflow runs `cmake` and `pytest`
in the agent's sandbox so it gets a pre-built environment.

To verify it passes:
```bash
gh workflow run copilot-setup-steps.yml
gh run list --workflow=copilot-setup-steps.yml --limit 5
```

The job must be green before you assign any issue to the agent. A
failing setup step means the agent will guess its environment wrong and
produce unusable code.

---

## Per-issue workflow

### Step 1: Choose the right task

Track B is correct for a task when:
- It matches a pattern already in the codebase (e.g., "add a material
  that works like Disney but only has two parameters").
- All files it will create are listed in a work package.
- The acceptance criteria are machine-verifiable (tests pass,
  registration macro present, etc.).
- The task is bounded to ≤5 files touched.

If the task requires understanding why something is structured the way
it is, or coordinating across multiple subsystems, escalate to track A.

### Step 2: Write the issue

Use the issue template below. Precision here directly determines
output quality. Vague issues produce vague code.

### Step 3: Assign to Copilot

In the issue sidebar: Assignees → select the Copilot agent. It will
open a draft PR within minutes. Do not push anything to the branch
yourself while it's working.

### Step 4: Review the PR

Use the review checklist below. Do not merge without passing every
item.

---

## Issue template

```markdown
## Goal
One sentence. What should exist that doesn't exist now?

## Context
Which work package is this from? (e.g., pkg03)
Which existing plugin is the closest analogue? (e.g., plugins/materials/lambertian.cpp)

## Spec
<!-- Be explicit. The agent will follow this literally. -->

**File to create:** `plugins/<category>/<name>.cpp`

**Constructor parameters (from ParamDict):**
- `"param_name"` → float, default X
- `"param_name2"` → Vec3, default (0, 0, 0)

**Methods to implement:** `eval`, `sample`, `pdf` (for materials).
See `include/raytracer.h` for signatures.

**Registration:** `ASTRORAY_REGISTER_MATERIAL("name", ClassName)`

**Test to add:** `tests/test_materials.py::test_<name>_energy_conservation`
(copy the pattern from `test_lambertian_energy_conservation`).

## Acceptance criteria
- [ ] Plugin file exists at the path above.
- [ ] `ASTRORAY_REGISTER_MATERIAL` (or equivalent) macro present.
- [ ] New test passes.
- [ ] All existing tests still pass (`pytest tests/ -v`).
- [ ] No files outside `plugins/` and `tests/` are modified.

## Non-goals
- Do not modify `include/raytracer.h`.
- Do not add dependencies.
- Do not "improve" adjacent code.
```

---

## When to use track B vs other tracks

| Situation | Use |
|---|---|
| New plugin matching an existing pattern | B |
| Pillar foundation or cross-cutting refactor | A |
| "Does X even work?" exploration | C |
| Test coverage expansion, lint fixes | D |
| Anything that must be correct on first ship | A |

Plugins that fail code review get fixed by track A, not re-assigned to
track B. Do not let the agent iterate endlessly on a complex problem.

---

## Review checklist

Before merging any Copilot PR:

- [ ] **Build is green.** The `copilot-setup-steps` workflow passed.
- [ ] **Tests pass.** `pytest tests/ -v` in the PR checks shows no
      failures.
- [ ] **Files touched.** Only files listed in the issue spec. If the
      agent edited `include/raytracer.h` or `CMakeLists.txt` without
      explicit permission, reject the PR.
- [ ] **Registration macro present.** `grep ASTRORAY_REGISTER_ <file>`
      returns exactly one match.
- [ ] **ParamDict usage correct.** Constructor reads params via
      `getFloat`, `getVec3`, etc. with sensible defaults. No raw
      stringly-typed access beyond what the macro helpers provide.
- [ ] **Simplicity tax.** Is there any abstraction that doesn't have a
      second caller? If yes, ask for it to be inlined.
- [ ] **No physics invariants violated.** Check the invariant list in
      `.astroray_plan/agents/claude-code.md`.

If any item fails: add a review comment describing exactly what to fix.
Copilot will re-push. Do not fix it yourself — that defeats the point.

---

## Common failure modes

### Agent modifies files outside the spec

It sees a "related" issue and fixes it. Reject the PR with: "revert
all changes outside `plugins/<name>.cpp` and `tests/test_<name>.py`."

### Agent produces a class that compiles but evaluates to zero

The `eval` method returns zero whenever the implementation is wrong.
Energy conservation test will flag this. Add a brighter-light smoke
test if the energy test isn't catching it.

### Agent times out or fails setup

Usually a `cmake` error in `copilot-setup-steps.yml`. Check the
Actions tab. Often a missing `#include` in a new file the agent created
before the setup workflow ran.

### Agent opens multiple PRs for one issue

Happens if you accidentally trigger it twice. Close all but one with
"duplicate."

---

## Budget

Track B runs inside GitHub Actions — you pay with Actions minutes, not
API credits. Education Premium includes 2,000 minutes/month; Copilot
Enterprise has more. An average coding agent session takes 15–30
minutes of Actions time.

Target: 2–5 open track B issues at a time during active feature
expansion. More than 5 and you cannot review them fast enough. Fewer
than 2 and you're leaving parallelism on the table.

Review duty: ~30 min/day on weekdays during active sprints. PRs older
than 3 days without review should be closed or merged to avoid drift.
