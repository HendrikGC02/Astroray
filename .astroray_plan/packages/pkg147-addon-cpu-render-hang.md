# pkg147 — Blender addon CPU render hangs at any resolution > 16px

**Pillar:** 5 (Blender addon reliability)
**Track:** A
**Codex-paste-ready:** no (Blender-in-the-loop debugging; needs headless Blender 5.1 + build access)
**Status:** open — dispatchable, but **NOT for the 2026-07-23 overnight run** (needs interactive Blender-in-the-loop debugging, not a fire-and-forget gate)
**Estimated effort:** S–M (diagnosis-first; the fix is likely a build/threading flag or a glue-loop bug, not new features)
**Depends on:** none

**Origin:** pkg146 investigation (PR #514). Never hit before because every prior
oracle ran `device_mode='gpu'`.

---

## Repro (measured, PR #514)

Addon `render()` with `device_mode='cpu'` inside Blender:

- **16×16 completes in 0.01 s.**
- **32×32 freezes indefinitely** — CPU time pinned for 12+ min, no progress, no error.
- **Direct Python bindings** (same build, outside Blender) render 64×64 CPU scenes
  instantly — the engine's CPU path is fine; the defect is specific to the
  **addon/Blender render glue**.

Repro artifacts: `Astroray-pkg146` worktree,
`test_results/pkg146_oracle/cpu_render_hang_repro/`.
Findings doc: `.astroray_plan/docs/pkg146-equal-wattage-findings.md` (PR #514).

## Suspected layer

Addon render glue and/or an OpenMP/threading interaction inside Blender. This
smells like the known precedent (memory `mingw_openmp_blender_deadlock`, later
generalized to MSVC/vcomp in the pkg115 diagnosis, PR #471): **any addon-use
`.pyd` must be built with `-DASTRORAY_DISABLE_OPENMP=ON`** — an OpenMP-enabled
build deadlocks inside Blender on the CPU path while the GPU path (no OpenMP
loops) masks it. First diagnostic step: confirm which `.pyd` the failing repro
loaded (`astroray.__file__`) and whether it was an OpenMP-enabled build. If the
OpenMP-free addon build still hangs, bisect the glue: tile/chunk loop, progress
callback, GIL interaction, or a threads-vs-Blender-job conflict in
`blender_addon/` render dispatch. The 16px-works/32px-hangs threshold suggests a
thread-count or tiling boundary (e.g. work splitting kicks in above one tile).

## Acceptance gate

- A 32×32 **and** a 256×256 CPU addon render (`device_mode='cpu'`, headless
  Blender 5.1) complete within a sane walltime bound (seconds, not minutes),
  verified in the repro harness; root cause written up.
- GPU addon path and direct-bindings CPU path unchanged (regression suite green).
- If the root cause is the OpenMP build flag: the guard becomes structural
  (build-time check or runtime assert in the addon), not tribal knowledge.

## Non-goals

- No CPU-path performance work beyond un-hanging it.
- Does not block pkg146 — its oracle runs GPU.
