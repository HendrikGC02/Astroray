# Claude Code Handbook (Track A)

**Role:** The surgeon. Handles multi-file refactors, pillar foundations,
anything touching project-wide invariants. Runs locally (on your RTX
5070 Ti machine) using the `claude` CLI. Paid per session via Anthropic
API.

**What Claude Code is good at:** cross-cutting refactors, physics
correctness, architectural decisions, code that has to be right the
first time. Will read 20 files before making a change, will reject its
own first approach if it sees a better one.

**What Claude Code is bad at:** spinning up 5 parallel plugin
implementations (that's track B's job), or running for hours
unattended (that's track D's job).

**Why it matters:** the pillars are hard, load-bearing work. Get them
wrong and everything downstream cracks. Claude Code is the right tool.

---

## One-time setup

1. Install Claude Code: https://docs.claude.com/en/docs/claude-code/overview
2. `cd` into the Astroray repo.
3. Confirm you have an API key set: `claude auth status`.
4. Create `AGENTS.md` in the repo root. See template below.

### AGENTS.md template

```markdown
# Astroray Agent Context

You are working on Astroray, a C++/CUDA physically-based path tracer
with a Blender 5.1 addon. The project is simpler than it looks — the
primary design goal is pluggability via registries, not abstraction.

## Build
- Build: `cmake -B build && cmake --build build -j`
- Tests: `pytest tests/ -v`
- Render test: `cd build && ./bin/astroray --scene 1 --samples 32 --out /tmp/smoke.ppm`

## Simplicity tax
Every abstraction must have a concrete caller today. No "framework for
future flexibility." A veteran engineer reading your diff should say
"yeah that's how I'd do it," not "clever."

## Plan location
The current plan is in `.astroray_plan/`. Read
`.astroray_plan/docs/ROADMAP.md` first. Work packages are in
`.astroray_plan/packages/`. Pick the one marked as your assigned
package; do not wander.

## Physics invariants
- GR capture threshold is `r < 2.5M` — validated, do not change.
- Dormand-Prince Butcher tableau coefficients are ported exactly from
  the Python reference — do not "clean up" the numbers.
- Double precision in the GR integrator, float elsewhere.
- Auto-exposure uses 99th-percentile luminance scaled to 0.8.

## What not to touch
- Never alter `include/raytracer.h` unless your package explicitly
  says so.
- Never add a new dependency without checking with the user first.
- Never rewrite tests to make them pass.
```

---

## Per-session workflow

### Before starting

1. Open `docs/STATUS.md`. Which package is the active track A target?
2. Open that package file (`packages/pkgNN-name.md`). Read the whole
   thing, including acceptance criteria and non-goals.
3. Confirm dependencies (earlier packages done) and build is green.
4. If not, fix that in a micro-session first (≤10 min).

### Launch prompt template

```
You are working on Astroray. Read AGENTS.md and
.astroray_plan/packages/pkgNN-name.md in full before doing anything
else.

Goal: complete the package. Your work is done when every acceptance
criterion is met and all existing tests still pass.

Constraints:
- Follow every "Non-goal" in the package. These are hard stops.
- Do not start a new package. If this one is already done, say so and
  stop.
- If you hit a genuine ambiguity in the spec, stop and ask — do not
  guess.
- Run tests before you declare done.

Start by running `cmake --build build` and `pytest tests/` to confirm
the baseline is green.
```

### End-of-session ritual

Before ending the session, Claude Code should:

1. Run the full test suite. No regressions allowed.
2. Run the Cornell box standalone render at 32 spp. Compare to a
   known-good PNG (stored in `tests/reference/cornell_32spp.png`).
   Visually flag any change.
3. Update the "Progress" section in the package file.
4. Write a PR description summarizing the change.

---

## Common failure modes

### "It refactors things it wasn't asked to"

Tell it: "only change files listed in the package. If you think
another file needs changing, stop and surface that — don't fix it
inline."

### "It adds a framework layer"

Trigger the simplicity tax: "does this new abstraction have a second
caller today? If not, delete it and inline."

### "It gets stuck on a build error"

The model may not know about a platform quirk. Paste the full error
into the chat and let it read the context. If still stuck, paste the
relevant file headers.

### "The test passes but the output looks wrong"

The test was too weak. Open the test file, strengthen the assertion,
re-run. Record the pattern in `docs/agent-context/lessons-learned.md`
(create if it doesn't exist).

---

## Budget

Before spending a session:

- **Is this actually track-A work?** If a Copilot cloud agent can do
  it with a well-specified issue, use track B instead.
- **Is this a 10-minute fix?** Fix it yourself. Don't spin up an agent
  for a typo.
- **Is the package well-specified?** If not, write the package first
  (see `../packages/TEMPLATE.md`). A 30-min investment in
  specification saves a 3-hour agent session that goes off the rails.

Target: two Claude Code sessions per week on average during active
development. More when a pillar is cresting; fewer during
consolidation.
