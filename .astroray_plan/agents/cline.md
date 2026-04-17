# Cline Handbook (Track C)

**Role:** Local prototype and experimentation worker. Runs in VS Code
with the Cline extension and a local model (Qwen 3.5-35b or similar
via Ollama). Zero API cost — uses your RTX 5070 Ti. Code produced here
is not production-bound until track A promotes it.

**What track C is good at:** answering "does this even work?" quickly,
binding a new library against the codebase, building throwaway proofs
of concept, exploring algorithmic options before committing to one.

**What track C is bad at:** sustained correctness over multi-file
refactors, work where the first approach must be right, anything
touching invariants.

**The rule:** every file produced by Cline that reaches `main` must
first be reviewed and owned by a track A session. Cline is a drafting
tool, not a shipping tool.

---

## One-time setup

### Local model

```bash
# Install Ollama
winget install Ollama.Ollama   # or download from ollama.com

# Pull a capable code model (≥30B for decent C++ output)
ollama pull qwen2.5-coder:32b
# or
ollama pull deepseek-coder-v2:16b   # lighter, still reasonable
```

Confirm it works: `ollama run qwen2.5-coder:32b "Write hello world in C++"`.

### Cline in VS Code

1. Install the Cline extension from the VS Code marketplace.
2. Open VS Code settings → Cline → Provider: `Ollama`.
3. Set model name to match your `ollama pull` above.
4. Confirm the status bar shows the model name and no error.

### `.clinerules`

Create `.clinerules` in the Astroray repo root. This file is Cline's
equivalent of `copilot-instructions.md` — it constrains its behavior
per-project.

```
# Astroray Cline rules

## This is a prototype track. Nothing here ships without track A review.

## Build
cmake -B build && cmake --build build -j
pytest tests/ -v

## Simplicity tax
Do not add abstractions. Do not add dependencies without asking. Do not
modify files outside the prototype scope described in the task.

## Physics invariants (read-only; never alter)
- GR capture threshold: r < 2.5M
- Double precision in GR integrator, float elsewhere
- Dormand-Prince coefficients match Python reference exactly

## What not to touch
- include/raytracer.h (unless the task explicitly says so)
- Any file with "validated" in a nearby comment
- CMakeLists.txt (propose changes, do not make them unilaterally)
```

---

## Plan/Act workflow

Cline has two modes: Plan and Act. Use them in order, every time.

### Plan mode (≤10 min)

Before Cline writes a single line:

1. Describe the prototype goal in one paragraph. Be explicit about the
   question you are answering: "Does tiny-cuda-nn build alongside
   Astroray's existing CUDA setup?" or "Can we sample an MLP for
   indirect radiance in 2 ms at 1080p on this GPU?"
2. Cline outlines a plan: what files it will create, what it will not
   touch, what the success check is.
3. You review and approve. If the plan looks like it will touch
   invariant files, stop and redirect.

### Act mode

Cline executes the plan. Watch for scope creep — it may start "fixing"
things that aren't broken. Interrupt with: "stay in scope, don't touch
`include/raytracer.h`."

### After Act

Run the build and tests yourself:
```bash
cmake --build build -j && pytest tests/ -v
```

If tests break, the prototype has damaged something. Revert and narrow
the task.

---

## When to graduate a prototype to track A

A Cline prototype is ready for track A promotion when:

- The core question is answered ("yes, tiny-cuda-nn builds and returns
  sensible output").
- The prototype produces clearly correct output on at least one test
  scene (visual or numeric).
- The prototype does not break any existing tests.
- The approach is simple enough that track A can understand it without
  asking questions.

Write up what you learned in the relevant work package's "Progress"
section before handing off. Track A's job is to take the core idea and
make it production-quality — not to reverse-engineer what you were
trying to do.

A prototype that fails 3 times to produce correct output should be
abandoned. Write a "learned: this approach doesn't work because..."
note in the package, then either redesign or escalate to track A with
a problem statement.

---

## When Cline is faster than Claude Code

| Use case | Faster with |
|---|---|
| Binding tiny-cuda-nn and running a dummy inference | Cline (iterate freely, no API cost) |
| Pillar 1 registry skeleton | Claude Code (must be right) |
| Prototyping a new accretion disk emission formula | Cline (throw-away math) |
| Migrating all materials to the registry | Claude Code (invariants) |
| Checking if Qwen can write passable CUDA | Cline (experiment) |
| Any PR that will land on `main` | Claude Code review required |

If you are not sure which track to use: ask whether a wrong answer has
lasting consequences. If yes, track A. If the prototype can be deleted
without loss, track C.

---

## Prototype-only discipline

Track C produces drafts. The discipline is enforced socially, not
technically. Some concrete rules:

- Never push a Cline-produced branch directly to `main`. It goes
  through a track A review session or it does not go.
- Do not reference Cline prototype code in track B issues ("just copy
  what Cline did"). Track B must be spec'd from the work package, not
  from a prototype.
- Delete prototype branches after track A has incorporated what's
  useful. Stale Cline branches create noise.
- Keep prototype work in a branch named `proto/<topic>` so it's
  clearly not production work.

---

## Common failure modes

### Cline edits `include/raytracer.h`

It will sometimes reason that the cleanest fix is to modify the core
header. Stop it immediately, revert, and re-scope the task to avoid
needing that change. The track A package that properly handles core
header changes is the right vehicle.

### The model picks a wrong algorithm

Local models are less reliable than Claude Code on physics-adjacent
math. Always sanity-check spectral or GR formulas against the papers
in `docs/external-references.md`. A plausible-looking but wrong
Doppler boost factor will not be caught by tests.

### Prototype grows to 30 files

Scope creep. Stop. Delete. Rewrite the task to answer a single
question. A 30-file prototype is not a prototype.

### Ollama is too slow for CUDA code generation

Qwen-32b at 4-bit needs ~4 GB VRAM for inference, which competes with
the CUDA build. Either quantize further (`q4_0`) or prototype without
CUDA compilation in the loop (write code, then build separately).
