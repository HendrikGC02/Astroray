# Astroray Next Stage Report

**Date:** 2026-05-10 (post-pkg54c/68 verified, pkg70/57/71 just landed)
**Prepared by:** Claude (Anthropic Code, Sonnet 4.5 in Max 5x)
**Scope:** prompts for the round AFTER pkg70 OptiX, pkg57 native shader
nodes, and pkg71 benchmark-framework all just merged. This is the next
deployable parallel set.

> Strategic gate (unchanged): Pillar 4 (astrophysics) remains parked.
> Focus is locking in Blender integration + measured parity + perf.
> Strategy in [`ROADMAP.md`](ROADMAP.md), status in [`STATUS.md`](STATUS.md).

---

## 1. Current state (one screen)

**Done since the previous report:**

- pkg54c verified end-to-end on RTX 5070 Ti — visible-band SSIM hits
  the 0.999 gate at 0.999263 (spp=8192). The GPU `gpu_rgbSpectrumAt`
  ILLUMINANT renormalization bug was caught and fixed during
  verification. Frame-time regression vs pkg54b is +0.45% — pkg54e
  not needed.
- pkg68 verified with measured **2.57× viewport speedup**
  (130.01 → 50.67 ms/frame on RTX 5070 Ti at 256×256 spp=2). PR #206
  merged the verify branch with A/B numbers in Lessons.
- pkg57 native Astroray shader nodes landed (PR #204) — 5 ShaderNode
  subclasses + 2 NodeSocket subclasses + AstrorayMaterialSettings
  PropertyGroup; engine-switch survival via Cycles' Apache-2.0
  PointerProperty pattern; engine bl_idname kept as
  `CUSTOM_RAYTRACER` (surgical per CLAUDE.md §3).
- pkg70 OptiX denoiser landed (PR #203) — co-equal with OIDN; persistent
  OptixDeviceContext, lazy init, HDR/AOV model selection by guide
  presence; `gpu_optix_available()` Python probe; addon
  `denoiser_backend` Auto/OptiX/OIDN dropdown.
- pkg71 Cycles parity benchmark framework landed (PR #205) — full
  scripts + scene manifest + CC-BY attribution + Victor defence-in-depth
  + weekly self-hosted CI workflow. Local smoke run revealed Astroray
  invocations failing with Windows DLL init error (0xC0000142) — the
  framework is correct; the canonical baseline waits on the self-hosted
  CUDA runner with the DLL issue debugged.
- ReSTIR explicitly parked as an artefact (per owner decision). The
  pkg20–24 packages stay marked "implemented"; restir-di remains an
  opt-in plugin with no auto-selection.

**Pending verification:**

- pkg70 + pkg57 → CUDA hardware + live-Blender 5.1 verification.
- pkg71 → first canonical baseline CSV from a CUDA + Cycles 4.x runner
  (separately: debug the 0xC0000142 Astroray DLL load issue).

**Open Pillar 5 (the queue after this round):**

| Pkg | Title | Effort | Status |
|---|---|---|---|
| pkg56 | Incremental scene sync (depsgraph diff) | 5–7 weeks (3 phases) | Spec + research signed off (#192) |
| pkg64 | Spectral caustics (SMS + spectral MNEE) | 3–4 weeks | Research signed off; flagship visual fidelity |
| pkg55 | Wavefront SoA GPU refactor | 8–12 weeks (3 phases) | Spec + research signed off (#189); architectural |
| pkg72 (new spec) | Motion-vector AOV pass | 3 days | TBD — needs spec |
| pkg73 (new spec) | OptiX temporal denoiser (depends on pkg72) | 3–4 days | TBD — needs spec |
| pkg74 (new spec) | Comprehensive engine benchmark + visual showcase | 1.5 weeks | TBD — needs spec + starter impl |

---

## 2. Recommended next deployable set

Six sessions, all parallel-safe:

| # | Agent | Worktree / location | Package | Effort |
|---|---|---|---|---|
| 1 | CUDA verifier | hardware | pkg70 + pkg57 verification | ~½ day |
| 2 | Codex | main directory | pkg71 first baseline run + commit CSVs | ~½ day |
| 3 | Claude tech | `pkg56-phase-a` (new) | pkg56 Phase A: instrument current sync path | 1 week |
| 4 | Claude tech | `pkg64-sms-skeleton` (new) | pkg64 Phase 1: port Mitsuba 2 SMS skeleton (BSD-3) | 1 week |
| 5 | Claude research | `research-temporal-denoise` (new) | spec pkg72 (motion vectors) + pkg73 (OptiX temporal) | ~½ day |
| 6 | Claude research+impl | `pkg74-bench-showcase` (new) | pkg74 comprehensive engine benchmark + visual showcase (research → spec → starter impl) | 1.5 weeks |

The pkg56 + pkg64 sessions are the multi-week flagship work; they'll
spawn follow-up packages of their own (pkg56 Phase B / Phase C; pkg64
spectral MNEE extension) once Phase 1 of each lands.

---

## 3. Drop-in prompts per agent

### 3.1 CUDA verifier — pkg70 + pkg57 verification

```
You are a CUDA verification session on the user's RTX 5070 Ti
Windows workstation. Two packages need verification together
(both just merged to main).

Step 1: pull latest main.
  git fetch origin && git checkout main && git pull --ff-only

Step 2: pkg70 OptiX denoiser verification.
  scripts\build\build_cuda.bat
  python scripts\dev\run_tests.py --build-dir build_cuda --
    tests/test_optix_denoiser.py
    tests/test_oidn_denoiser.py
    tests/test_oidn_denoiser_persistence.py
    tests/test_aov_passes.py
  -v --tb=short

  Report:
  - First "[OptiX] Using <device>" line.
  - All pkg70 tests green; existing OIDN tests still green
    (no regression).
  - Synthetic noise gate: noise floor ≥5x lower than input
    on the speckle test image.
  - Timing: pkg70 OptiX vs pkg68 OIDN-CUDA on the pkg54a/b
    parity scene at 1080p. Acceptance is "OptiX ≥ 1.5× faster
    than OIDN-CUDA". Record both numbers.
  - SSIM between OptiX-denoised and OIDN-denoised outputs.
    Acceptance is ≥0.95.

Step 3: pkg57 native shader nodes verification.
  Open Blender 5.1 with the addon installed. Manually verify:
  - All 5 Astroray shader nodes appear in the Add menu when
    engine == CUSTOM_RAYTRACER (Spectral Profile, Sellmeier Glass,
    IR/UV Response, NRC Hint, Astroray Output).
  - Same nodes are absent from the Add menu when engine
    switches to Cycles.
  - An existing Cycles BsdfPrincipled scene (use the Cornell
    box from tests/) renders identically before and after
    switching engine to Astroray (modulo Monte Carlo noise).
  - A scene using AstrorayOutputNode + SellmeierGlass produces
    visible chromatic dispersion in a prism scene (test
    against tests/scenes/prism_*.py if present).
  - Switching back to Cycles preserves the Astroray nodes
    (inert in Cycles' graph) and keeps the BsdfPrincipled
    wired so Cycles still renders.

  python scripts\dev\run_tests.py -- tests/test_blender_native_nodes.py -v

  Report whether each manual check passes; report the pytest
  results.

Step 4: promotion + commit.
  - If both packages pass their acceptance gates:
      pkg70 spec status -> done; STATUS.md updated.
      pkg57 spec was already promoted in PR #204 — confirm only.
  - Commit on a verify branch:
      verify(pkg70, pkg57): CUDA + Blender 5.1 gates green
  - Push and open PR.

Constraints:
  - Do NOT modify implementation code.
  - Do NOT relax any gate.
  - Close-but-not-quite gates: report numbers + ask, don't promote.
```

### 3.2 Codex — pkg71 first baseline run

```
The pkg71 framework just merged. Produce the first canonical
baseline CSV from this Windows + RTX 5070 Ti workstation.

Read first:
  - .astroray_plan/packages/pkg71-cycles-parity-benchmark.md
  - benchmarks/cycles-parity/scenes/scripts/fetch_scenes.py
  - scripts/run_parity.py
  - scripts/summarize_parity.py
  - The previous local-smoke CSV at
    benchmarks/cycles-parity/2026-05-10-local-smoke-d614e03.csv
    — Astroray rows skipped with `exit:3221225781`
    (0xC0000142, Windows DLL init failure). Debug this first
    before producing the canonical baseline.

Steps:
  0. Debug the Astroray DLL load issue. The .pyd is at
     build_cuda/lib/Release/ (or wherever scripts/dev/run_tests.py
     points). The harness subprocess-invokes the .pyd via
     `python -c "import astroray; ..."` — replicate the failing
     command verbatim, then trace which DLL is missing
     (Dependency Walker / dumpbin / ldd-equivalent). Common
     causes on Windows: cudart64_*.dll not on PATH, MSVC
     redistributable mismatch, OIDN DLL missing.

  1. Verify Blender 4.x or later is on PATH (the harness
     subprocess-invokes `blender --background --python`).
     If not, install or set BLENDER_EXECUTABLE env var.

  2. Run the scene fetcher:
       python benchmarks\cycles-parity\scenes\scripts\fetch_scenes.py
     Confirm Classroom + Monster (CC-0) downloaded;
     confirm Junkshop + BMW27 (CC-BY) downloaded with
     attribution files; confirm Victor (CC-BY-NC) is
     refused by defence-in-depth assertion.

  3. Run the parity harness:
       python scripts\run_parity.py
     This will be slow — 5 scenes × 4 engines × 3 runs each,
     plus the SSIM-vs-Cycles-EXR computation. Expect 1–4 hours
     depending on scene complexity.

  4. The output CSV lands at:
       benchmarks\cycles-parity\<date>-<machine>.csv

  5. Generate the Markdown summary:
       python scripts\summarize_parity.py \
         benchmarks\cycles-parity\<date>-<machine>.csv

  6. Commit ONLY the CSV + the generated Markdown summary
     (NOT the cached scene files):
       git add benchmarks\cycles-parity\<date>-<machine>.csv
       git add benchmarks\cycles-parity\<date>-<machine>.md
       git commit -m "benchmark(pkg71): first canonical parity baseline on RTX 5070 Ti"

  7. Open PR. Body should embed the Markdown summary table
     verbatim.

Acceptance:
  - SSIM gate ≥ 0.95 on every (scene, engine) row WHERE
    Astroray and Cycles both produced output. Skipped rows
    are reported but don't fail the gate.
    If any row fails the SSIM gate by a small margin
    (e.g. 0.92-0.95), report and ask before relaxing.
    Big failures (< 0.85) are real bugs to investigate.
  - Perf numbers are recorded but NOT gated this round.

Constraints:
  - Do NOT commit cached scene files.
  - Do NOT relax SSIM gates.
  - DO commit attribution files for CC-BY scenes.
```

### 3.3 Claude tech (worktree `pkg56-phase-a`) — instrument current sync path

```
You are Claude Code in worktree .claude/worktrees/pkg56-phase-a,
branched from current main. Implement pkg56 Phase A only.

Read first:
  - .astroray_plan/packages/pkg56-incremental-scene-sync.md
    (the spec, broken into 3 phases — implement Phase A only,
    Phase B and C are separate packages on this branch)
  - .astroray_plan/docs/blender-depsgraph-sync-research.md
    (the Cycles BlenderSync reference reading, signed off in
    PR #192)
  - blender_addon/__init__.py — find _sync_viewport_scene
    (the per-frame upload entry point) and the upload* C++
    bindings it calls
  - module/blender_module.cpp — find uploadScene + upload*
    helpers

Phase A goal: instrument the current sync path with timers
and publish a measured no-change-frame baseline. NO behaviour
change. Just measurement.

Implementation:
  1. Add per-stage timers in blender_addon/__init__.py around:
     - Geometry upload (BVH build + transforms)
     - Material upload
     - Light upload
     - Environment upload
     - Render dispatch
     Record cumulative ms per stage per frame in a ring buffer
     (last 100 frames).
  2. Add `astroray.viewport_perf_stats()` Python API that
     returns the ring buffer as a dict[stage, mean_ms].
  3. Expose in the addon's render-stats overlay (pkg62-style).
  4. tests/test_viewport_perf_stats.py — unit-tests that the
     ring buffer rolls correctly, mean ms is monotonic vs
     scene complexity (small scene < big scene).
  5. Document baseline numbers from a 100k-tri reference
     scene in pkg56 Lessons (Phase A): per-stage ms + total.
     This is the "before" number that Phase C optimises against.

Acceptance:
  - tests/test_viewport_perf_stats.py green.
  - Render-stats overlay shows per-stage timings during
    viewport interaction.
  - pkg56 Phase A checklist items checked.
  - Spec updated with the actual baseline numbers in Lessons.
  - Phase B + Phase C remain explicitly future work — do NOT
    start them on this branch.

Constraints:
  - CLAUDE.md sections 2, 3.
  - NO behaviour change. Pure measurement.
  - Surgical: stay in blender_addon/, module/ (one binding),
    new test file, pkg56 spec updates, STATUS.md.

When done:
  - pkg56 Phase A entry in spec marked done; Phase B/C still
    open.
  - STATUS.md: pkg56 noted as "Phase A done, B+C open".
  - Commit on this branch:
      feat(pkg56-A): instrument viewport sync path with
      per-stage timers + ring buffer
  - PR. DO NOT merge.
```

### 3.4 Claude tech (worktree `pkg64-sms-skeleton`) — pkg64 Phase 1: SMS skeleton

```
You are Claude Code in worktree .claude/worktrees/pkg64-sms-skeleton,
branched from current main. This is the flagship visual-fidelity
package. Phase 1 only — port the Mitsuba 2 SMS skeleton; the
spectral MNEE extension is Phase 2.

Read first:
  - .astroray_plan/packages/pkg64-spectral-caustics.md (the spec)
  - .astroray_plan/docs/caustics-research.md (the signed-off
    research: SMS skeleton from Mitsuba 2 BSD-3, spectral MNEE
    from Hanika 2015 paper, Cycles GPL incompatible — DO NOT
    mirror Cycles MNEE source)
  - plugins/integrators/caustic_path_tracer.cpp (the existing
    CPU caustic-aware path tracer — pkg64 augments this, does
    not replace it)
  - tests/test_caustic_validation.py + tests/scenes/caustic_validation.py
    (the regression baseline — Phase 1 must not regress these)

Phase 1 goal: port the SMS algorithm from Mitsuba 2 reference
implementation as an opt-in pass on top of caustic_path_tracer.
RGB-only; spectral extension is Phase 2.

Reference implementation (BSD-3-Clause, mirroring permitted):
  - https://github.com/tizian/specular-manifold-sampling
  - Read src/integrators/sms.cpp (the integrator) and
    src/libcore/manifold.cpp (the geometric Newton iteration)
  - Cite the commit SHA in code comments per CLAUDE.md §6

Implementation outline:
  1. plugins/integrators/sms_caustic_path_tracer.cpp — new
     integrator registered as "sms_caustic_path_tracer".
     Augments the existing caustic_path_tracer's NEE with an
     SMS connection attempt for specular chains.
  2. include/astroray/manifold/ (new dir):
     - half_vector_constraint.h — the geometric constraint
       formulation from Zeltner 2020 §4.2
     - newton_iterate.h — the Newton iteration solver
  3. tests/test_sms_caustic_validation.py — regression scene
     (single sphere on glass under area light) where SMS-on
     produces a measurable caustic that SMS-off misses.
     Acceptance gate: PSNR improvement ≥ 6 dB at equal sample
     count vs caustic_path_tracer baseline.
  4. NO change to default integrator selection — sms_caustic
     is opt-in via r.set_integrator("sms_caustic_path_tracer").

NOT in Phase 1 (Phase 2 / Phase 3):
  - Spectral wavelength-Newton iteration (Hanika 2015) — Phase 2.
  - Folding SMS into the default path_tracer — Phase 3.
  - GPU port — separate package after Phase 1+2 land on CPU.

Constraints:
  - CLAUDE.md sections 2, 3, 6.
  - License fence: Mitsuba 2 SMS is BSD-3 (mirror with attribution).
    Cycles' MNEE source is GPL-2.0+ — DO NOT read it for code
    patterns. Hanika 2015 is a paper (math is not copyrightable,
    cite the paper).
  - Multi-session work — Phase 1 alone is ~1 week of focused
    Claude time.

When done:
  - pkg64 Phase 1 checklist items checked; Phase 2 (spectral)
    and Phase 3 (default-integrator integration) remain open.
  - STATUS.md: pkg64 noted as "Phase 1 done (RGB SMS); Phases 2+3
    open".
  - Commit on this branch:
      feat(pkg64-1): SMS skeleton from Mitsuba 2 ported as
      opt-in caustic integrator
  - PR. DO NOT merge.
```

### 3.5 Claude research (worktree `research-temporal-denoise`) — pkg72 + pkg73 specs

```
You are Claude Code in worktree .claude/worktrees/research-temporal-denoise,
branched from current main. RESEARCH + SPEC session — no
implementation code. Two deliverables in .astroray_plan/.

Why this matters: pkg70's OptiX denoiser explicitly excluded
temporal mode because the integrator emits no motion vectors.
That left the strongest viewport-stability story on the table.
Fixing it cleanly needs two packages: motion-vector generation
in the integrator (pkg72), and OptiX temporal-mode wiring on
top (pkg73). This session writes both specs.

Deliverable 1: .astroray_plan/packages/pkg72-motion-vectors.md
Deliverable 2: .astroray_plan/packages/pkg73-optix-temporal-denoiser.md

Required reading:

Motion vectors (pkg72):
  - Cycles motion vector pass:
    https://projects.blender.org/blender/blender/src/branch/main/intern/cycles/integrator/pass.cpp
    Search for PASS_MOTION + PASS_MOTION_WEIGHT. Apache-2.0.
  - PBRT v4's motion vectors:
    https://github.com/mmp/pbrt-v4/blob/master/src/pbrt/film.cpp
    Search for "motion". Apache-2.0.
  - The math: given a hit point P and the previous-frame camera
    transform, compute the previous-frame pixel coordinate
    P_prev = projectToScreen(P, camera_prev). Motion vector =
    P_prev - P_current. Per-pixel float2.

OptiX temporal mode (pkg73):
  - https://raytracing-docs.nvidia.com/optix8/guide/index.html#ai_denoiser
    Specifically the OPTIX_DENOISER_MODEL_KIND_TEMPORAL section.
  - Cycles' OptiX temporal denoiser:
    intern/cycles/device/optix/ — search for "Temporal".
    Apache-2.0.

Spec content (each package):

pkg72 (motion vectors):
  - Goal / Before / After.
  - Spec: new MotionVector AOV pass (plugins/passes/motion_vector_aov.cpp);
    new buffer "motion" in Framebuffer; integrator populates from
    previous-frame camera transform; Python binding
    Renderer.get_motion_buffer().
  - Acceptance: synthetic camera-pan test produces non-zero motion
    on every pixel hit by static geometry; static-camera test
    produces zero motion within float epsilon.
  - Effort: ~3 days.

pkg73 (OptiX temporal):
  - Goal / Before / After.
  - Spec: extend pkg70's OptiXDenoiser to optionally upgrade to
    OPTIX_DENOISER_MODEL_KIND_TEMPORAL when motion buffer is
    present. Add previous-frame color buffer caching.
  - Depends on: pkg70 (OptiX denoiser) + pkg72 (motion vectors).
  - Acceptance: viewport camera-pan test shows ≥30% reduction
    in inter-frame pixel variance vs pkg70's HDR/AOV mode.
  - Effort: ~3-4 days.

Both specs:
  - Front-matter: Pillar 5, Track A, Status open.
  - Reference Implementations table per CLAUDE.md §6.
  - Non-goals.
  - Progress checklist.

When done:
  - Commit on this branch:
      docs(pkg72, pkg73): motion vectors + OptiX temporal denoiser
      specs (closes pkg70 temporal-mode follow-up gap)
  - PR against main with the two-line summary of each package.
    DO NOT merge.

Constraints:
  - CLAUDE.md section 6 (cite, borrow, verify).
  - No source code changes.
  - License-fence: Cycles is Apache-2.0 (mirror OK with citation);
    PBRT-v4 is Apache-2.0; NVIDIA OptiX SDK headers NOT
    redistributable.
```

### 3.6 Claude research+impl (worktree `pkg74-bench-showcase`) — comprehensive engine benchmark + visual showcase

```
You are Claude Code in worktree .claude/worktrees/pkg74-bench-showcase,
branched from current main. RESEARCH → SPEC → STARTER IMPLEMENTATION
session. End state: a new package pkg74 filed AND a runnable
benchmark+visualisation framework checked in.

Why this is distinct from pkg71:
  - pkg71 is narrow: Astroray vs Cycles head-to-head on a fixed scene
    set, CSV output, perf+SSIM gates, CI integration.
  - pkg74 is broad: Astroray-internal showcase across every dimension
    we care about (materials, integrators, edge cases, convergence
    behaviour, memory, sample efficiency), with VISUAL output (contact
    sheets) and STATISTICAL output (graphs). Used for paper figures,
    release blog posts, regression spotting at a glance, and showing
    the engine off honestly.
  - The two are complementary: pkg71 tracks parity numbers in CI;
    pkg74 produces the qualitative + visual artefacts you'd put in a
    talk or a README.

DO NOT duplicate pkg71's scene set or CSV layout. pkg74 outputs are
different artefacts (PNG contact sheets, matplotlib graphs, HTML index
page) and live under benchmarks/showcase/ not benchmarks/cycles-parity/.

---

PHASE 0: research note (~½ day, do this FIRST)

Write .astroray_plan/docs/engine-benchmark-research.md (~5 pages).

Required reading (use WebFetch — fetch specific files, don't clone):

PBRT v4 stats system (Apache-2.0, mirrorable patterns):
  - https://github.com/mmp/pbrt-v4 — read src/pbrt/util/stats.h and
    src/pbrt/util/stats.cpp. The STAT_* macros + reporting framework
    are the canonical "what stats matter" reference.
  - Their stats categories: ray counts (camera/shadow/scattered),
    BVH (intersection tests, leaves visited), memory (per-allocator),
    timing (per-stage), image (samples/pixel, splat counts),
    light sampling (selections, MIS weights).

Mitsuba 3 statistics + logging:
  - https://github.com/mitsuba-renderer/mitsuba3 — src/core/profiler.cpp,
    src/core/logger.cpp. BSD-3, mirrorable.

Cycles' debug + stats panel (Apache-2.0):
  - intern/cycles/util/stats.h, intern/cycles/util/stats.cpp,
    intern/cycles/blender/addon/ui.py (search "Statistics").
  - The "Cycles Stats" panel in Blender's properties shows: scene
    geometry counts, render time per pass, peak memory, sample
    counts. Mirror this idea.

Blender opendata visualisation (CC-BY, look-and-feel reference only):
  - https://opendata.blender.org/ — how they present cross-machine
    benchmark results. Box plots, scene-grid contact sheets, hardware
    matrices.

Render-engine paper figures (look at SIGGRAPH papers for inspiration):
  - PBRT 4th edition has standard benchmark figure layouts:
    convergence curves (RMSE vs sample count log-log), variance
    decomposition (direct vs indirect noise), material zoo contact
    sheets, scene gallery.
  - Disney's "Production Volume Rendering" (2017) chapters have good
    contact-sheet patterns for material parameter sweeps.

Existing Astroray stuff to inventory and NOT duplicate:
  - scripts/benchmark_caustic_transport.py
  - scripts/benchmark_light_transport.py
  - scripts/benchmark_showcase.py — this exists; READ IT, then decide
    whether pkg74 supersedes it or extends it.
  - scripts/diagnostics/material_contact_sheet.py — referenced in
    pkg66 deferred entry; check if it's there.
  - .astroray_plan/packages/pkg32-visual-diagnostics.md — the prior
    visual-diagnostics package; what's done vs what's still missing.

Required H2 sections in engine-benchmark-research.md:

  1. What is comprehensive engine benchmarking — distinguish from
     parity benchmarking (pkg71). Quote 3-4 paragraphs of justification
     for why both exist.
  2. Statistics catalog — enumerate every stat worth tracking,
     grouped: Geometry (BVH stats, prim counts), Sampling (rays/pixel,
     samples/light, RR termination), Memory (peak, per-allocator),
     Timing (per-stage, per-bounce, per-material-type), Quality
     (variance, convergence rate, firefly count), Spectral (wavelength
     coverage, hero-wavelength selection), Integrator-specific
     (NRC training loss, ReSTIR reservoir-reuse rate).
  3. Visual outputs catalog — contact sheets (material zoo, integrator
     comparison, scene gallery, convergence-vs-spp grid), statistical
     graphs (convergence curves, variance decomposition, perf scaling
     vs scene complexity, memory profile per scene), HTML/dashboard
     output for browseability.
  4. Reproducibility constraints — fixed seeds, deterministic scene
     geometry, machine-tagging in output filenames, version-tagging
     (commit SHA + Astroray + Cycles + Blender + driver versions in
     output metadata).
  5. Recommended starter scope for the package — what Phase 1 of the
     implementation should produce; what Phase 2 / Phase 3 are.
  6. License + reference matrix per source consulted.

Length: ~5 pages.

---

PHASE 1: write the package spec (~½ day)

Create .astroray_plan/packages/pkg74-engine-benchmark-showcase.md
following the format of pkg71-cycles-parity-benchmark.md:

  - Pillar: 5
  - Track: A
  - Status: open (this PR will move it to "Phase 1 implemented")
  - Estimated effort: 1.5 weeks initial; recurring use thereafter
  - Depends on: nothing hard; pkg71 framework is a soft dep (shared
    helpers possible)
  - Goal / Before / After.
  - Reference Implementations table.
  - Specification broken into Phase 1 (starter framework + 1 contact
    sheet + 1 graph + driver), Phase 2 (full coverage), Phase 3
    (HTML dashboard + CI integration).
  - Acceptance per phase.
  - Non-goals (e.g., NOT a perf-regression CI gate — that's pkg71;
    NOT a Blender-integration test — that's existing pytest suite).

---

PHASE 2: starter implementation (~1 week)

Create benchmarks/showcase/ with at minimum:

  benchmarks/showcase/
    __init__.py
    config.py                 # default scene set, sample counts, etc.
    runner.py                 # driver — runs all benchmarks, captures
                              # both stats CSV and rendered PNGs
    scenes/                   # benchmark scene library (Python builders
                              # using astroray.Renderer API directly)
      material_zoo.py         # one sphere per material plugin under
                              # uniform lighting
      integrator_compare.py   # same scene, every registered
                              # integrator
      convergence_grid.py     # one scene, geometric spp series
                              # (1,4,16,64,256,1024) for convergence
                              # visualisation
      cornell_variants.py     # Cornell box with material swaps
    contact_sheets.py         # PIL/Pillow grid composer
    graphs.py                 # matplotlib convergence curves +
                              # variance plots + perf scaling
    html_index.py             # static HTML index pointing at the
                              # generated artefacts
    README.md                 # how to run, what each output means

Acceptance for the starter implementation (Phase 1):

  - `python benchmarks/showcase/runner.py --quick` produces:
    1. material_zoo_contact_sheet.png — N×M grid of per-material
       sphere renders with labels.
    2. convergence_grid_contact_sheet.png — same scene at increasing
       spp, side by side.
    3. convergence_curve.png — RMSE vs sample count log-log plot
       for one reference scene against a converged ground truth.
    4. stats_summary.csv — per-(scene, integrator) row of every
       stat from research note §2.
    5. index.html — browsable static page linking everything.
  - Outputs land in benchmarks/showcase/output/<date>-<machine>/.
  - Outputs are NOT committed to the repo (gitignore the output/
    subdirectory). Only the framework + scene builders + scripts
    are committed.
  - One end-to-end pytest:
    tests/test_benchmark_showcase_runs.py — runs `--quick` mode
    (small spp, small image size), asserts all five output files
    are produced and are non-trivial (file size > 0, PNG is parseable,
    CSV has > 0 rows).

  Phase 2 (full coverage), Phase 3 (HTML dashboard polish + CI hook
  for weekly run) explicitly out of scope for this PR.

---

When done with all three phases:

  - pkg74 spec status -> "Phase 1 implemented; Phase 2/3 open".
  - STATUS.md: pkg74 entry under Pillar 5.
  - Commit on this branch:
      feat(pkg74-1): engine benchmark + visual showcase framework
      (material zoo, convergence grid, stats CSV, HTML index)
  - PR against main. Body should embed one example contact sheet
    inline (use markdown image link to a temp upload OR commit one
    representative example PNG into a docs/ subfolder if small).
    DO NOT merge.

Constraints:
  - CLAUDE.md sections 2, 3, 6.
  - DO NOT duplicate pkg71's CSV format or scene set; pkg74 is
    showcase + visualisation, not parity tracking.
  - DO NOT modify existing scripts/benchmark_*.py — pkg74 is
    additive. Note in the research doc which existing scripts
    pkg74 supersedes; deletion of superseded scripts is a
    separate PR.
  - License-fence per CLAUDE.md §6: PBRT v4 (Apache-2.0, mirrorable),
    Mitsuba 3 (BSD-3, mirrorable), Cycles (Apache-2.0, mirrorable),
    matplotlib (PSF/BSD-compatible, dependency only), Pillow
    (HPND, dependency only). No GPL deps.
  - This is the most ambitious single session in the round
    (~1.5 weeks of focused Claude time across research +
    spec + impl). Take it in chunks; commit between phases on
    the same branch.
```

---

## 4. Coordination

**File-touching map** (zero hard collisions):

| Session | Files |
|---|---|
| Verifier (pkg70+pkg57) | only verify-branch commits + spec promotions |
| Codex pkg71 baseline | `benchmarks/cycles-parity/<date>-<machine>.csv` + `.md` (new) |
| pkg56 Phase A | `blender_addon/__init__.py`, `module/blender_module.cpp` (one binding), new test, pkg56 spec, STATUS.md |
| pkg64 Phase 1 | new `plugins/integrators/sms_caustic_path_tracer.cpp`, new `include/astroray/manifold/`, new test, pkg64 spec, STATUS.md |
| Research pkg72+73 | only `.astroray_plan/packages/pkg72-*.md` + `pkg73-*.md` (new) |
| pkg74 bench showcase | new `benchmarks/showcase/`, new `.astroray_plan/docs/engine-benchmark-research.md`, new `.astroray_plan/packages/pkg74-*.md`, new test, STATUS.md, possibly one small example PNG in `docs/` |

Three sessions touch STATUS.md. Trivial three-way merge. (Watch for the
squash-merge race we hit on pkg57/70/71 — when STATUS.md sees concurrent
table-row additions, the squash collapse can drop rows. Mitigation: do a
quick post-round STATUS.md sweep PR if needed, like #207 was.)

Two sessions touch `module/blender_module.cpp` (pkg56 + the verifier
might if pkg70 verification needs a binding tweak — unlikely). Small
delta, trivial merge.

**Recommended merge order:** verifier (small, independent) → research
specs (docs only) → Codex baseline (new files) → pkg74 bench showcase
(new dir, no collisions) → pkg56 Phase A → pkg64 Phase 1 (largest delta).

---

## 5. After this round

When this round lands:

- pkg70 + pkg57 → verified end-to-end on user's hardware.
- pkg71 → first canonical Cycles parity numbers committed; the "matches
  Cycles" claim has data. Future PRs measure deltas vs this baseline.
- pkg56 Phase A → measured viewport sync cost; Phase B/C work on the
  measured hot spots.
- pkg64 Phase 1 → SMS skeleton ported; pkg64 Phase 2 (spectral MNEE)
  is the next pickup.
- pkg72 + pkg73 → spec'd; OptiX temporal denoiser becomes available
  as a follow-up implementation pickup.
- pkg74 Phase 1 → benchmark + visualisation framework runnable;
  produces material zoo / convergence grid contact sheets and the
  RMSE-vs-spp graph from any commit. Phase 2 (full coverage) and
  Phase 3 (HTML dashboard polish + weekly CI run) become
  follow-ups.

Then the queue is:
- pkg56 Phase B (refactor uploadScene → split uploaders, ~2 weeks)
- pkg56 Phase C (depsgraph-driven dispatch, ~2-3 weeks)
- pkg64 Phase 2 (spectral wavelength Newton iteration from Hanika 2015,
  ~1.5 weeks)
- pkg64 Phase 3 (fold SMS into default path_tracer, ~½ week)
- pkg72 implementation (motion vectors, ~3 days)
- pkg73 implementation (OptiX temporal denoiser, ~3-4 days)
- pkg74 Phase 2 (full stat coverage, ~1 week)
- pkg74 Phase 3 (HTML dashboard polish + weekly CI run, ~3 days)
- pkg55 wavefront SoA refactor (8-12 weeks, the big architectural
  pivot — defer until pkg56 + pkg64 land so we have measured baselines
  to compare against)

When pkg56 + pkg64 land, **Pillar 4 thaws**. The Codex-paste-ready
specs for pkg41/pkg42/pkg43/pkg44/pkg47/pkg48/pkg49 are waiting; pkg40
(Kerr metric) already landed during the pre-strategic-shift round.

Bump this report when pkg56 Phase A or pkg64 Phase 1 lands — that's
the next major queue movement.
