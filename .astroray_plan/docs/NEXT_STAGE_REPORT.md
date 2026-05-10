# Astroray Next Stage Report

**Date:** 2026-05-10 (post-Round-2 — pkg64-1, pkg56-A, pkg74-1, pkg70 verify, pkg72/73/75 specs all landed)
**Prepared by:** Claude (Anthropic Code, Sonnet 4.5 in Max 5x)
**Scope:** prompts for Round 3, to be launched once the in-flight Codex
pkg71-canonical-baseline PR lands. Round 3 focuses on closing the
denoiser story (pkg75 normal-guide fix, then pkg72 motion vectors
unlocking pkg73 OptiX temporal mode), keeping pkg64 + pkg74 + pkg56
moving through their phases, and re-baselining pkg68/pkg70 once
pkg75 corrects the AOV-mode floor.

> Strategic gate (unchanged): Pillar 4 (astrophysics) remains parked.
> Focus is locking in Blender integration + measured parity + perf.
> Strategy in [`ROADMAP.md`](ROADMAP.md), status in [`STATUS.md`](STATUS.md).

---

## 1. Current state (one screen)

**Done since the previous report:**

- pkg70 OptiX denoiser verified on RTX 5070 Ti + OptiX 9.1.0 — 5.31×
  synthetic-noise reduction at 256×256, 1.86× faster than OIDN-CUDA
  at 1080p, SSIM 0.9987 vs OIDN. PR #216.
- pkg64 Phase 1 (SMS skeleton) shipped — Mitsuba 2 BSD-3 reference
  ported as opt-in `sms_caustic_path_tracer` integrator. Phase 2
  (spectral wavelength-Newton from Hanika 2015) and Phase 3 (default-
  integrator fold) are queued. PR #212.
- pkg56 Phase A (viewport sync instrumentation) shipped — measured
  baseline 129.92 ms/frame on a 100k-tri scene (geometry 77.68 ms,
  render 51.73 ms). Phase B and C will optimize against these
  numbers. PR #210.
- pkg74 Phase 1 (engine showcase framework) shipped — material zoo
  + convergence grid + RMSE-vs-spp curve + HTML index. Phase 2
  (full stat coverage) and Phase 3 (CI integration) queued. PR #214.
- pkg72 (motion vector AOV) + pkg73 (OptiX temporal denoiser) specs
  filed — implementation pickups ready. PR #209.
- pkg75 (first-hit normal-buffer population for AOV guides) spec
  filed during pkg70 verification. **The defect is real and is the
  priority pickup of Round 3** — both pkg68 (OIDN AOV) and pkg70
  (OptiX AOV) silently degrade to HDR+albedo without it.
- Build hygiene fixes: pkg70 NOMINMAX guard + FindOptiX glob for
  OptiX 9.x via PR #215. README + QUICKSTART + CMake configure log
  all now document OptiX as an optional GPU prerequisite (PR #213).

**In flight (do NOT spawn Round 3 sessions until this lands):**

- **Codex pkg71-canonical-baseline** — running on
  `codex/pkg71-first-canonical-baseline`. The big multi-fix PR per
  the previous direction: NOMINMAX (already separately landed via
  #215), OIDN DLL bootstrap on Windows, harness parity (Cycles EXR
  reference vs Astroray EXR output, not gamma'd PNG vs HDR EXR), and
  the canonical first-baseline CSV across all 5 scenes. Slow because
  it's actually rendering a 5-scene × 4-engine × 3-runs matrix. May
  take hours. Will land as a single PR.

**Open Pillar 5 (the Round 3 + Round 4 pickup pool):**

| Pkg | Title | Effort | Status |
|---|---|---|---|
| **pkg75** | First-hit normal buffer for AOV guides | 2–3 days | Spec filed; **highest priority of Round 3** |
| **pkg72** | Motion vector AOV | ~3 days | Spec filed; standalone; unblocks pkg73 |
| **pkg73** | OptiX temporal denoiser (AOV+motion) | ~3–4 days | Spec filed; depends on pkg72 |
| **pkg64** Phase 2 | Spectral wavelength-Newton (Hanika 2015) | ~1.5 weeks | Phase 1 landed |
| **pkg64** Phase 3 | Fold SMS into default path_tracer | ~½ week | Phase 2 first |
| **pkg56** Phase B | uploadScene split into incremental uploaders | ~2 weeks | Phase A baseline measured |
| **pkg56** Phase C | depsgraph-driven dispatch | ~2–3 weeks | Phase B first |
| **pkg74** Phase 2 | Full stat coverage (BVH, GPU, integrator-specific) | ~1 week | Phase 1 framework in place |
| **pkg74** Phase 3 | Interactive HTML dashboard + weekly CI | ~3 days | Phase 2 first |
| pkg55 | Wavefront SoA GPU refactor | 8–12 weeks (3 phases) | Deferred until pkg56 + pkg64 land for measured baselines |

---

## 2. Recommended next deployable set (Round 3, post-Codex-pkg71)

Five sessions, all parallel-safe:

| # | Agent | Worktree / location | Package | Effort |
|---|---|---|---|---|
| 1 | Claude tech | `pkg75-normal-buffer` (new) | pkg75 — fix the AOV normal-guide defect that silently degrades pkg68 + pkg70 | 2–3 days |
| 2 | Codex | main directory | pkg72 motion vector AOV | ~3 days |
| 3 | Claude tech | `pkg64-phase-2` (new) | pkg64 Phase 2 — spectral wavelength-Newton (Hanika 2015) on top of Phase 1 SMS skeleton | ~1.5 weeks |
| 4 | Claude tech | `pkg74-phase-2` (new) | pkg74 Phase 2 — full stat coverage (BVH stats, GPU rows, integrator-specific stats) on top of Phase 1 framework | ~1 week |
| 5 | CUDA verifier | hardware (after #1 lands) | re-run pkg68 + pkg70 baselines to capture the AOV-mode improvement that pkg75 unlocks | ~½ day |

Session 5 only spawns AFTER session 1 lands (pkg75 is its prerequisite).
Sessions 1–4 all spawn at once. Session 5 may be batched with the next
round's verifier work; not a blocker.

After Round 3 lands:

- **Round 4** can pick up pkg73 (depends on pkg72), pkg56 Phase B,
  pkg64 Phase 3, pkg74 Phase 3 — at which point Pillar 5 is mostly
  done.
- Then pkg55 wavefront refactor (the big architectural pivot) and
  Pillar 4 thaws.

---

## 3. Drop-in prompts per agent

### 3.1 Claude tech (worktree `pkg75-normal-buffer`) — fix the AOV normal-guide defect

```
You are Claude Code in worktree .claude/worktrees/pkg75-normal-buffer,
branched from current main. Implement pkg75 end to end.

Read first:
  - .astroray_plan/packages/pkg75-integrator-normal-guide-aov.md
    (the spec)
  - include/raytracer.h — search for `Camera::albedoBuffer` (the
    correct precedent). normalBuffer is allocated alongside it
    around line 1653-1654 but never written by the default render
    loop. The one in-tree write site is around line 2451-2452 in
    a spectral integrator branch that the canonical color path
    doesn't reach.
  - plugins/passes/normal_aov.cpp — confirm what shape it expects
    in the buffer (world-space vs shading vs camera-space normals)
  - plugins/passes/oidn_denoiser.cpp — confirm how OIDN AOV mode
    binds the normal guide buffer. Same for plugins/passes/optix_denoiser.cpp.

Why this matters: pkg70 verification 2026-05-10 found that
fb.hasBuffer("normal") returns true so both OIDN AOV mode and OptiX
AOV mode bind the buffer as a guide image — but the data they
upload is all-zeros. AOV mode is silently degrading to HDR+albedo
on every scene at every resolution. Fixing this lifts the floor on
pkg68 (measured 2.57× speedup is conservative) and pkg70 (5.31×
synthetic-noise reduction is conservative).

Implementation:

  1. Find the canonical write site for albedoBuffer in the default
     render loop — probably around the same point where the
     primary-ray hit record produces albedo (raytracer.h render
     dispatch). The write should happen for every primary ray
     that hits geometry.

  2. Add the matching normalBuffer write at the same point. Use
     the SHADING normal (world-space) by default — that's what
     OIDN's docs recommend and what Cycles uses for its
     PASS_NORMAL output. Cite Cycles' intern/cycles/integrator/pass.cpp
     PASS_NORMAL semantics in a code comment per CLAUDE.md §6.

     For pixels that miss all geometry (env hit), write Vec3(0)
     or the env-direction as the normal? Check what OIDN expects
     for misses. If it expects 0, that matches today's behavior;
     if it expects something else, document the choice.

  3. Verify the normal_aov pass plugin still produces correct
     output (no regression — the pass just exposes the buffer
     to Blender). If normal_aov was the existing populator in
     a different code path, refactor so the population happens
     in one place and normal_aov reads it.

Tests:

  - tests/test_normal_buffer_populated.py — new test:
    render a Cornell scene, assert get_normal_buffer() at every
    geometry-hit pixel has |normal| ≈ 1.0 within 0.01. At
    background pixels assert the documented choice (0 or
    env-direction).

  - tests/test_oidn_denoiser_aov_uses_guides.py — new test (or
    extend test_oidn_denoiser_persistence.py): render the
    same scene WITHOUT pkg75 normals (use a synthetic zero
    buffer override if exposed via test hook, otherwise
    compare to previous-baseline numbers) and WITH pkg75
    normals. The OIDN-with-real-normals output should have
    visibly tighter noise reduction than OIDN-with-zero-normals.

  - Re-run tests/test_optix_denoiser.py at 256×256 — confirm
    the synthetic noise reduction ratio improves from the
    pkg70-verified 5.31× to something measurably higher.
    Record both numbers in pkg75 Lessons.

  - tests/test_aov_passes.py — make sure the existing normal
    AOV pass still exposes the correct values to Blender.
    No regression.

Constraints:
  - CLAUDE.md sections 2, 3, 6.
  - Surgical: ONLY the canonical render loop's normal-buffer
    write + tests. Do NOT touch denoiser plugins, do NOT
    refactor the Camera buffer ABI.
  - Cite Cycles PASS_NORMAL semantics in the new code site.
  - You probably will not have CUDA at the implementation
    site; the OptiX/OIDN-CUDA improvement gates will skip
    cleanly. Mark in PR body: "CUDA + OptiX improvement
    re-baselines pending verifier session 3.5."

When done:
  - pkg75 spec status -> done.
  - STATUS.md: pkg75 row updated.
  - Add brief note to pkg68 Lessons: "AOV normals now live
    courtesy of pkg75; the 2.57× speedup baseline can be
    re-measured."
  - Add brief note to pkg70 Lessons: same shape, plus the
    new synthetic-noise reduction number once the test gives
    it.
  - Commit on this branch:
      feat(pkg75): populate first-hit normal buffer for AOV
      denoiser guides — restores AOV mode for OIDN + OptiX
  - PR. DO NOT merge.
```

### 3.2 Codex (main directory) — pkg72 motion vector AOV

```
The Codex pkg71-canonical-baseline session must be done before
spawning this. Implement pkg72 motion vectors end to end.

Read first:
  - .astroray_plan/packages/pkg72-motion-vectors.md (the spec)
  - .astroray_plan/docs/motion-vectors-research.md (the research
    note that backs the spec)
  - include/raytracer.h — find the Camera class and the render
    loop. You will add a Camera::motionBuffer alongside
    albedoBuffer + normalBuffer (which after pkg75 will both
    be populated correctly).
  - plugins/passes/normal_aov.cpp — the AOV plugin pattern
    you mirror for motion_vector_aov.

Why this matters: pkg73 OptiX temporal denoiser depends on per-
pixel motion vectors. Without them, the denoiser cannot upgrade
to OPTIX_DENOISER_MODEL_KIND_TEMPORAL_AOV mode and viewport
animation continues to suffer from frame-to-frame boiling.
pkg72 unblocks pkg73.

Reference (Apache-2.0, mirrorable patterns):
  - Cycles PASS_MOTION + PASS_MOTION_WEIGHT in
    intern/cycles/integrator/pass.cpp — the per-pixel motion
    vector layout (float2: previous→current screen-space
    pixel offset).
  - PBRT v4 motion vectors in src/pbrt/film.cpp.

The math: given a hit point P (world space) and the previous-
frame camera transform C_prev, compute
  P_prev_screen = projectToScreen(P, C_prev)
  P_curr_screen = projectToScreen(P, C_curr)
  motion = P_prev_screen - P_curr_screen   # float2 per pixel

For pixels that miss all geometry (env hit), motion = (0, 0).
For the first frame of a render (no previous camera), motion
= (0, 0).

Implementation outline (subject to spec):
  1. Camera::motionBuffer added alongside albedoBuffer/normalBuffer
     (raytracer.h:1653-1654). Sized unconditionally (matches
     pkg68's audit pattern).
  2. Renderer holds a copy of the previous frame's camera
     transform. Update on every render call. First call uses
     identity (returns zero motion).
  3. Render loop populates motionBuffer for every primary ray
     hit using the math above. One additional matrix-multiply
     per pixel; cheap.
  4. plugins/passes/motion_vector_aov.cpp — new plugin
     mirroring normal_aov.cpp's shape; exposes the buffer
     to Blender.
  5. module/blender_module.cpp — Renderer.get_motion_buffer()
     binding returning a numpy float32[H, W, 2].
  6. tests/test_motion_vector_aov.py — synthetic camera-pan
     test produces non-zero motion on every static-geometry
     pixel; static-camera test produces zero motion within
     float epsilon; first-frame produces zero motion.

Constraints:
  - CLAUDE.md sections 2, 3, 6.
  - Camera-only motion. Animated geometry (moving objects)
    is OUT of scope per spec — that needs per-vertex previous
    transforms which we don't have. Document this in pkg72
    Lessons.
  - Surgical: stay in raytracer.h render dispatch, new plugin
    file, blender_module binding, new test, pkg72 spec, STATUS.
  - Cite Cycles file + line in code comments.

When done:
  - pkg72 spec status -> done.
  - STATUS.md updated.
  - Commit on a fresh branch:
      feat(pkg72): per-pixel motion vector AOV (camera-only)
  - PR. DO NOT merge.
```

### 3.3 Claude tech (worktree `pkg64-phase-2`) — spectral wavelength-Newton

```
You are Claude Code in worktree .claude/worktrees/pkg64-phase-2,
branched from current main. Implement pkg64 Phase 2 only.
Phase 1 (RGB SMS skeleton) just landed (PR #212); Phase 3
(default-integrator fold) is a separate package on its own
branch.

Read first:
  - .astroray_plan/packages/pkg64-spectral-caustics.md (the spec —
    look for the Phase 2 section)
  - .astroray_plan/docs/caustics-research.md (the signed-off
    research, especially the Hanika 2015 MNEE wavelength-Newton
    section)
  - plugins/integrators/sms_caustic_path_tracer.cpp (the Phase 1
    RGB SMS skeleton — Phase 2 extends this)
  - include/astroray/manifold/half_vector_constraint.h +
    newton_iterate.h (Phase 1 helpers)
  - plugins/integrators/spectral_path_tracer.cpp +
    plugins/integrators/spectral_dielectric_*.cpp — search for
    Sellmeier dispersion (this is what produces wavelength-
    dependent IOR which the Hanika 2015 wavelength-Newton needs)

Phase 2 goal: extend the Phase 1 RGB SMS implementation to do
per-wavelength Newton iteration on the half-vector constraint,
producing prism-accurate spectral caustics.

Reference (paper):
  - Hanika, Droske, Manakov, "Manifold Next Event Estimation",
    EGSR 2015 (DOI 10.1111/cgf.12681). The paper is the math
    source — the spectral residual derivation is in §4.
  - Mitsuba 2 SMS reference (BSD-3, mirrored via citation in
    Phase 1) does NOT include spectral extension; we do this
    ourselves from the paper.
  - Cycles' MNEE source is GPL-2.0+ — DO NOT consult it for
    code patterns (license fence per caustics-research.md).

Implementation outline (subject to spec):

  1. Convert the Newton residual + Jacobian in
     sms_caustic_path_tracer.cpp from "use the material's
     scalar IOR" to "evaluate IOR at the hero wavelength
     λ_hero". Use the existing Sellmeier dispersion path
     (via SpectralDielectric::iorAt(λ)).

  2. For each spectral chain bounce, evaluate the constraint
     residual at the hero wavelength only (the math from
     Hanika 2015 §4 — the residual decouples per-wavelength
     because the half-vector constraint is linear in cosθ).

  3. Acceptance:
     - Existing tests/test_sms_caustic_validation.py still passes
       (RGB SMS regression baseline unchanged for monochromatic
       light).
     - New tests/test_sms_caustic_spectral.py: Cornell with
       refractive sphere under broad-spectrum light produces a
       visible chromatic spread in the caustic (red focuses
       differently from blue). Acceptance: PSNR(spectral SMS,
       hi-spp ground truth) − PSNR(RGB-only SMS, ground truth)
       ≥ 3 dB at equal sample count on the prism scene.
     - Performance: per-bounce cost increase ≤ 2× vs Phase 1
       (one Newton solve per spectral sample, not per RGB
       channel). Document the actual ratio in Lessons.

NOT in Phase 2:
  - Folding into the default path_tracer (Phase 3).
  - GPU port (separate package after Phase 2).
  - Triangle-mesh refraction (still spheres only — Phase 1
    constraint).

Constraints:
  - CLAUDE.md sections 2, 3, 6.
  - Cite Hanika 2015 §4 in code comments at the spectral
    residual implementation site.
  - DO NOT consult Cycles MNEE source.
  - Multi-session work — Max 5x makes Phase 2 doable in one
    focused push (~1.5 weeks of Claude time across the
    Newton math, validation scene, and spectral test).

When done:
  - pkg64 Phase 2 checklist items checked; Phase 3 (default-
    integrator fold) remains open.
  - STATUS.md: pkg64 noted as "Phases 1+2 done (RGB + spectral
    SMS); Phase 3 open".
  - Commit on this branch:
      feat(pkg64-2): spectral wavelength-Newton on top of
      Phase 1 SMS — prism-accurate caustics
  - PR. DO NOT merge.
```

### 3.4 Claude tech (worktree `pkg74-phase-2`) — full stat coverage

```
You are Claude Code in worktree .claude/worktrees/pkg74-phase-2,
branched from current main. Implement pkg74 Phase 2 only.
Phase 1 framework just landed (PR #214); Phase 3 (interactive
HTML + weekly CI) is a separate package.

Read first:
  - .astroray_plan/packages/pkg74-engine-benchmark-showcase.md
    (the spec — Phase 2 section)
  - .astroray_plan/docs/engine-benchmark-research.md (the
    research note's §2 stats catalog — that's the gold list
    to implement against)
  - benchmarks/showcase/ — the Phase 1 framework. Phase 2
    extends, doesn't replace.

Phase 2 goal: expand the stats catalog from Phase 1's basic
set (image stats + render time + peak RSS + integrator-stats
round-trip) to the full stats catalog from the research note:

  - Geometry: BVH stats (tris, nodes, max depth), prim counts,
    leaf utilization
  - Sampling: rays/pixel (camera, shadow, scattered),
    samples/light (NEE), Russian-roulette termination rate
  - Memory: peak per-allocator (CUDA pool, OIDN buffers,
    Framebuffer, BVH)
  - Timing: per-bounce cost, per-material-type cost, per-
    pass cost
  - Quality: pixel variance histogram, firefly count,
    convergence rate
  - Spectral: hero-wavelength selection histogram, sampled-
    wavelength coverage
  - Integrator-specific: NRC training loss curve, ReSTIR
    reservoir-reuse rate (when active)
  - GPU rows: same scenes rendered with set_use_gpu(True),
    appended to the same CSV

This is a lot. Bite it off as:

  Phase 2a (~3 days): Geometry + Memory + Timing categories
  Phase 2b (~2 days): Sampling + Quality categories
  Phase 2c (~2 days): Spectral + Integrator-specific + GPU rows

Land all three sub-phases on the same PR if they fit in one
focused push, or split into 2a+2b+2c on the same branch
with clear commits.

Implementation:

  1. Most stats already exist somewhere — they're just not
     all surfaced through Renderer.get_integrator_stats()
     or equivalent. Inventory: search for `printf` / log
     lines in src/, plugins/, include/. Many will already
     be measured but not exposed. Add Python bindings to
     pull them out.

  2. Some stats need a small bit of integrator instrumentation
     (e.g. ray-counters per type). Mirror the pkg56-A
     ring-buffer pattern from blender_module.cpp.

  3. Update benchmarks/showcase/runner.py to call into
     each new stat source per (scene, integrator) row.
     The CSV gets wider, not deeper.

  4. Add a "stats categories" section to the HTML index
     so viewers can collapse/expand each category.

  5. tests/test_benchmark_showcase_phase2.py — confirm
     each new category produces non-zero output on the
     Cornell scene.

Constraints:
  - CLAUDE.md sections 2, 3, 6.
  - DO NOT add new integrators or denoisers; this is
    measurement only.
  - Phase 3 (interactive HTML + CI) is OUT of scope for
    this PR.
  - Multi-session work — expect 1 week of Claude time.

When done:
  - pkg74 Phase 2 checklist items checked; Phase 3 still open.
  - STATUS.md: pkg74 noted as "Phases 1+2 done; Phase 3 open".
  - Commit on this branch:
      feat(pkg74-2): full stat coverage (geometry, sampling,
      memory, timing, quality, spectral, integrator-specific,
      GPU rows)
  - PR. DO NOT merge.
```

### 3.5 CUDA verifier — re-baseline pkg68 + pkg70 after pkg75 lands

```
You are a CUDA verification session on the user's RTX 5070 Ti
Windows workstation. Spawn this AFTER pkg75 (PR from §3.1) is
merged to main. Goal: capture the AOV-mode improvement that
pkg75 unlocks for both pkg68 (OIDN) and pkg70 (OptiX).

Step 1: pull main, confirm pkg75 is present.
  git fetch origin && git checkout main && git pull --ff-only
  grep "pkg75" .astroray_plan/docs/STATUS.md   # confirm "done"

Step 2: clean build + run all denoiser tests.
  Remove build_cuda dir entirely (don't trust cached object
  files after a buffer-population change).
  scripts\build\build_cuda.bat
  python scripts\dev\run_tests.py --build-dir build_cuda --
    tests/test_oidn_denoiser_persistence.py
    tests/test_oidn_denoiser.py
    tests/test_optix_denoiser.py
    tests/test_aov_passes.py
    tests/test_normal_buffer_populated.py     # new from pkg75
    tests/test_oidn_denoiser_aov_uses_guides.py  # new from pkg75
  -v --tb=short

  All green expected.

Step 3: re-measure pkg68 OIDN A/B baseline.
  Same harness as the 2026-05-10 baseline (Cornell, 256×256,
  spp=2, max_depth=3, N=100, warmup=3, persistent Renderer):

  Build at the pkg75-merged main HEAD: time 100 frames OIDN-on,
  100 frames OIDN-off. Record post-pkg75 OIDN-on ms/frame.

  Compare against the recorded post-pkg68 numbers in pkg68
  Lessons (50.67 ms/frame OIDN-on). The expected delta is
  EITHER lower per-frame cost (OIDN converges faster with real
  normal guides) OR same ms/frame with cleaner output (OIDN
  uses the saved budget for tighter denoising). Either is a win.

  Append to pkg68 Lessons:
    "Post-pkg75 OIDN A/B baseline (RTX 5070 Ti, same harness
    as 2026-05-10): OIDN-on X ms/frame, OIDN-off Y ms/frame.
    Comparison with the 2026-05-10 baseline shows
    [LOWER PER-FRAME COST | CLEANER OUTPUT AT SAME COST | both]."

Step 4: re-measure pkg70 OptiX synthetic-noise gate.
  Re-run tests/test_optix_denoiser.py at 256×256 (the post-
  fixture-bump size). Record the new noise-reduction ratio.

  Compare against the recorded pkg70-verification number
  (5.31× OptiX, 5.58× OIDN). Expected: BOTH numbers improve
  measurably, since both denoisers were running degraded-AOV
  before pkg75.

  Append to pkg70 Lessons:
    "Post-pkg75 synthetic noise gate re-measurement:
    OptiX X.XX× (was 5.31× pre-pkg75), OIDN Y.YY× (was 5.58×).
    Confirms the floor-not-ceiling reading of the original
    verification."

Step 5: re-measure pkg70 OptiX vs OIDN-CUDA timing.
  1080p parity scene, spp=2, max_depth=3, N=10, warmup=2.
  Compare against pre-pkg75 numbers (OptiX 728.94 ms,
  OIDN-CUDA 1356.09 ms, ratio 1.86×). Document any change.

Step 6: commit on a verify branch.
  Title: verify(pkg75): post-pkg75 pkg68/pkg70 re-baseline
  Body: include all four numbers with before/after table.

  Push, open PR, do NOT merge.

Constraints:
  - Do NOT modify implementation code (test fixture stays at
    256×256; pkg70 test docstring may be updated to reflect
    the post-pkg75 numbers).
  - Do NOT promote pkg75 yourself — this verifier session
    only re-baselines pkg68/pkg70 numbers in their Lessons;
    pkg75's own promotion happened at its merge.
  - If any number REGRESSES (gets worse than pre-pkg75),
    stop and ask. Regression would mean pkg75 broke
    something rather than improving the floor.
```

---

## 4. Coordination

**File-touching map** (zero hard collisions):

| Session | Files |
|---|---|
| pkg75 normal-buffer | `include/raytracer.h` (render loop normal-buffer write), maybe `plugins/passes/normal_aov.cpp` (refactor), new tests, pkg75 spec, STATUS.md, brief Lessons appends to pkg68/pkg70 specs |
| Codex pkg72 motion vectors | `include/raytracer.h` (Camera::motionBuffer + render loop motion-vector population), new `plugins/passes/motion_vector_aov.cpp`, `module/blender_module.cpp` (binding), new test, pkg72 spec, STATUS.md |
| pkg64 Phase 2 | `plugins/integrators/sms_caustic_path_tracer.cpp`, `include/astroray/manifold/` headers, new test, pkg64 spec, STATUS.md |
| pkg74 Phase 2 | `benchmarks/showcase/runner.py`, possibly new `benchmarks/showcase/stats/` dir, `module/blender_module.cpp` (new stat bindings), new test, pkg74 spec, STATUS.md |
| Verifier (post-pkg75) | only verify-branch commits + pkg68/pkg70 Lessons appends |

**Two real conflict points to watch:**

1. **`include/raytracer.h`** — pkg75 writes normalBuffer in the render
   loop; pkg72 writes motionBuffer in the same loop. Different lines
   but same file. **Mitigation:** pkg75 lands first (Round 3 priority
   ordering). pkg72 rebases over it; the write-site is a 3-line
   addition next to pkg75's normal-write — trivial three-way merge.

2. **`module/blender_module.cpp`** — pkg72 + pkg74 Phase 2 both add
   new bindings. Different binding sets, same file. Trivial merge.

**Recommended merge order** (when PRs land): verifier (smallest) →
pkg72 (depends on pkg75 only via shared raytracer.h, can land second
once the rebase is clean) → pkg64 Phase 2 → pkg74 Phase 2 → pkg75 first
(actually pkg75 should land FIRST so others can rebase off it; revise
order to: pkg75 → pkg72 → pkg64 Phase 2 → pkg74 Phase 2 → verifier).

STATUS.md squash-merge race protection: same as last round — if rows
go missing after the merges, file a small docs PR to restore.

---

## 5. After Round 3 lands

When this round lands:

- pkg75 → AOV mode actually works for both denoisers; pkg68 + pkg70
  numbers are no longer floors.
- pkg72 → motion vectors available; unblocks pkg73.
- pkg64 → Phase 2 (spectral SMS) done; only Phase 3 (default-integrator
  fold) and GPU port remain for caustics.
- pkg74 → Phase 2 (full stat coverage) done; only Phase 3 (interactive
  HTML + CI) remains for the showcase framework.
- Verifier session → pkg68 and pkg70 Lessons document the post-pkg75
  numbers, confirming the original measurements were conservative
  floors.

Then **Round 4** picks up:

- pkg73 OptiX temporal denoiser (now unblocked by pkg72) — ~3-4 days,
  Claude tech.
- pkg56 Phase B uploadScene split — ~2 weeks, Claude tech.
- pkg64 Phase 3 default-integrator fold — ~½ week, Claude tech.
- pkg74 Phase 3 HTML + CI — ~3 days, Codex.
- Re-baseline pkg54a/b parity scene through the showcase framework
  to show the cumulative pkg54+pkg68+pkg70+pkg75 visual quality story.

Then **Round 5**:

- pkg56 Phase C depsgraph-driven dispatch — ~2-3 weeks, Claude tech.
- pkg55 wavefront SoA refactor Phase A (instrument current megakernel
  perf) — ~1 week, Claude tech. The 3-phase wavefront work begins.
- pkg74 Phase 3 if not already landed.

When pkg56 Phases B+C land AND pkg64 Phase 3 lands, **Pillar 5 is
essentially feature-complete**. At that point Pillar 4 thaws; the
Codex-paste-ready specs for pkg41/pkg42/pkg43/pkg44/pkg47/pkg48/pkg49
are waiting; pkg40 Kerr metric already landed.

Bump this report when pkg75 lands or when Round 3 verification
returns numbers — that's the next major queue movement.
