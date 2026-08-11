# Ralph Loop Handbook (Track D)

**Role:** Background grind worker. Runs `scripts/ralph_loop.sh`
unattended — typically overnight or during idle time. Picks tasks from
`scripts/ralph_queue.txt`, runs a local model session per task,
commits successes, logs everything, and kicks failures up the chain.
Zero API cost.

**Named after Geoffrey Huntley's "naive persistence" pattern:** a
simple loop that picks up a task, tries it, commits or fails, moves
on. No memory between tasks. No grand plan. Just grind.

**What Ralph is good at:** test expansion, adding doc comments to
public API headers, fixing clang-tidy warnings, adding missing
`ASTRORAY_REGISTER_*` checks, formatting passes, updating
`CHANGELOG.md`, regenerating stale reference renders.

**What Ralph is bad at:** anything requiring judgment, physics
knowledge, multi-file refactors, or understanding why something is
structured the way it is.

---

## The loop concept

Geoffrey Huntley (https://github.com/snarktank/ralph) demonstrates
that a naive "pick task, attempt, commit, repeat" loop produces
surprising amounts of useful mechanical work. The key properties:

1. **Stateless.** Each iteration starts with a fresh context. Ralph
   does not carry lessons from one task to the next.
2. **Atomic.** One task = one commit attempt. Partial success is not
   committed.
3. **Self-limiting.** Tasks that fail 3 times are removed from the
   queue and written to a graduation log. A human (or track A) handles
   them.
4. **Auditable.** Every iteration produces a log entry. You can see
   exactly what was attempted, what the model did, and whether it
   succeeded.

---

## Queue format (`scripts/ralph_queue.txt`)

One task per line. Blank lines are ignored. `#` lines are comments.

A task line has three fields separated by ` | `:
```
<priority> | <category> | <description>
```

- `priority`: `P1` (do next) or `P2` (do whenever).
- `category`: `test`, `doc`, `lint`, `format`, `misc`.
- `description`: plain English imperative. Be specific.

Example:
```
P1 | test | Add energy-conservation test for Metal material (copy from test_lambertian_energy_conservation)
P2 | doc  | Add doc comment to Registry::create explaining what happens when the name is unknown
P2 | lint | Fix clang-tidy modernize-use-nullptr warnings in src/renderer.cpp
```

The loop script reads the first non-blank, non-comment line, attempts
it, removes it on success, increments its fail count on failure.
After 3 failures, the line is moved to `scripts/ralph_graduated.txt`
with a note.

---

## Prompt template

For each task, Ralph uses this prompt. The script substitutes `TASK`
and `CATEGORY` from the queue entry.

```
You are working on Astroray, a C++/CUDA path tracer.

Your task category is: CATEGORY
Your task is: TASK

Rules:
1. Do only what the task says. Nothing else.
2. Run `cmake --build build -j && pytest tests/ -v` after your change.
   If either fails, revert all changes and stop.
3. Do not modify files outside the scope of the task.
4. Do not add abstractions or refactor adjacent code.
5. Commit your changes with message: "ralph: TASK"
6. If you are not confident the change is correct, stop without
   committing and output: "RALPH_FAIL: <reason>"

Physics invariants (never alter):
- GR capture threshold: r < 2.5M
- Dormand-Prince coefficients match Python reference exactly
- Double precision in GR integrator, float elsewhere
```

---

## What counts as a Ralph task

**Good Ralph tasks:**
- Adding a test that copies an existing pattern exactly.
- Adding a doc comment to a function that has none.
- Renaming a variable to match the naming convention everywhere in one
  file.
- Updating a `CHANGELOG.md` entry with information from a recent
  commit.
- Fixing a `clang-tidy` warning that has a mechanical fix (e.g.,
  `modernize-use-nullptr`).
- Verifying that every `plugins/*.cpp` file contains exactly one
  `ASTRORAY_REGISTER_*` macro.

**Not Ralph tasks (graduate to another track):**
- Anything requiring understanding of the physics.
- Any test that cannot be written by cloning an existing test.
- Any warning fix that requires understanding the algorithm.
- Cross-file refactors.
- Tasks where "looks right" isn't the same as "is right."

When in doubt: if you would be comfortable telling a junior developer
"just copy the pattern from this other file," it's a Ralph task.

---

## Log output format

Each iteration writes to `logs/ralph-YYYYMMDD-HHMMSS.md`:

```markdown
# Ralph run 2026-04-17 22:00:00

## Task
P1 | test | Add energy-conservation test for Metal material

## Action
Copied test_lambertian_energy_conservation, substituted Metal.
Added to tests/test_materials.py lines 87-110.

## Result
PASS

## Build output
(truncated cmake --build output)
(truncated pytest output — 67 passed, 0 failed)

## Commit
ralph: Add energy-conservation test for Metal material
SHA: abc1234
```

On failure:
```markdown
## Result
FAIL (attempt 1/3)

## Reason
RALPH_FAIL: Could not find Metal constructor signature; class may have
changed since task was written.

## Action taken
No commit. Task attempt count incremented.
```

---

## Graduation loop

When a task fails 3 times, `ralph_loop.sh`:

1. Appends the task to `scripts/ralph_graduated.txt` with the failure
   reasons from all three logs.
2. Removes the task from `ralph_queue.txt`.
3. Logs: `GRADUATED: <task> — 3 failures, needs human or track A`.

Check `ralph_graduated.txt` on Friday as part of the weekly rhythm.
Typically, graduated tasks need either a rewritten spec (the
description was too vague) or track A work (the scope was wrong for
Ralph).

---

## Common failure modes

### Ralph keeps failing the same test task

Usually the test class it was told to copy has been renamed or moved.
Update the queue entry with the correct filename/function.

### Ralph commits broken code

The build check should prevent this. If it happens anyway, the loop
script did not run the build correctly. Check `scripts/ralph_loop.sh`
for the `set -e` guard. Revert the bad commit with `git revert <sha>`.

### Ralph graduates every task it touches

The queue entries are too vague. Rewrite them to be more explicit:
name the exact file, the exact pattern to copy, the exact output to
verify.

### Ralph uses too much VRAM

`ralph_loop.sh` runs Ollama with the same model as track C. If you're
using your GPU for something else, kill the loop with Ctrl-C. The
queue is durable — nothing is lost.

---

## Budget

Track D has zero API cost. Your practical budget is GPU time and
electricity. Rough figures on RTX 5070 Ti at 4-bit Qwen-32b:

- ~2 min/task for simple test additions.
- ~5 min/task for multi-step lint fixes.
- Overnight run (8 h) ≈ 96–240 tasks attempted.
- Success rate for well-written queue entries: ~70–80%.

Run Ralph on weeknights. Friday morning: review the logs and the
graduated list. Update the queue for next week.
