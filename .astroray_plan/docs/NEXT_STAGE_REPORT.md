# Astroray Next Stage Report

**Date:** 2026-05-10 (post-Round-3 — pkg72 + pkg64-2 + pkg74-2 + pkg75 + pkg75-rebaseline all landed)
**Prepared by:** Claude (Anthropic Code, Sonnet 4.5 in Max 5x)
**Scope:** Round 4 prompts. Round 4 closes the OIDN/OptiX denoiser story
end-to-end (pkg73 OptiX temporal mode), drives pkg56 incremental scene
sync into Phase B (uploadScene split), folds pkg64 SMS into the default
path tracer (Phase 3), polishes pkg74 into a CI-running showcase
(Phase 3), formally specs the Astroray .blend importer (pkg76) so non-
Cornell pkg71 rows can produce parity numbers, and re-baselines pkg72
on hardware.

> Strategic gate (unchanged): Pillar 4 (astrophysics) remains parked.
> Focus is locking in Blender integration + measured parity + perf.
> Strategy in [`ROADMAP.md`](ROADMAP.md), status in [`STATUS.md`](STATUS.md).
>
> The gate's release condition is now visible: pkg56 Phases B+C and
> pkg64 Phase 3 are the last big Pillar 5 implementations. Once those
> land, Pillar 4 thaws.

---

## 1. Current state (one screen)

**Done since the previous report (Round 3):**

- **pkg75** AOV normal-guide defect fixed and verified — root cause was
  one-line missing `r.normal = rec.normal` in
  `plugins/integrators/spectral_path_tracer.cpp::sampleFull`. Visual diff
  confirmed detail preservation (the OIDN noise-ratio metric drop was
  edge-detail picked up by the variance estimator, not real degradation).
  PR #219 + #223 (re-baseline). **Headline pkg68 win up 2.57× → 2.77×**;
  OIDN-pass-only delta **−23%**.
- **pkg72** per-pixel motion vector AOV landed — camera-only screen-space
  flow, OptiX prev→curr convention, `Renderer.get_motion_buffer()`
  zero-copy NumPy view, `motion_vector_aov` visualisation pass. **Unblocks
  pkg73**. PR #220.
- **pkg64 Phase 2** spectral wavelength-Newton — Hanika 2015 §4 math
  (Cycles MNEE GPL fence held). PSNR delta **+8.83 dB** at equal sample
  count vs Phase 1 RGB-only; runtime **0.98×** (faster, not slower).
  Behind `spectral_newton` opt-in param so Phase 1 regression baseline
  is bit-identical. PR #221.
- **pkg74 Phase 2** full stat coverage — 8 categories per research
  catalog (geometry, memory, timing, sampling, quality, spectral, GPU,
  integrator-specific). Convergence rate slope **−0.453** (vs MC target
  −0.5). New `integrator_compare` scene + bar-chart timing artefact.
  PR #222.
- **pkg71 first canonical Cornell baseline** — Astroray-CPU SSIM
  **0.9536**, Astroray-GPU SSIM **0.9548** vs Cycles-CPU EXR reference;
  Astroray-GPU **5.2× faster than Cycles-CUDA** at the same Cornell
  sample budget; Astroray uses **3-4× less memory** than Cycles. **First
  measured Astroray vs Cycles parity datapoint we have ever shipped.**
  PR #218.
- Build hygiene: pkg70 Windows OptiX build (NOMINMAX + FindOptiX glob),
  OIDN DLL bootstrap (`sitecustomize.py` + addon DLL handle keep-alive +
  test runtime expansion + harness subprocess env), and Cornell harness
  parity (matching tri-scene on both engines, EXR-vs-EXR SSIM with
  99.9th percentile clipping). PRs #213 + #215 + #218.

**Open Pillar 5 (the Round 4 + Round 5 pickup pool):**

| Pkg | Title | Effort | Status |
|---|---|---|---|
| **pkg73** | OptiX temporal denoiser (AOV + motion mode) | 3–4 days | Spec filed, **unblocked** by pkg72 |
| **pkg56** Phase B | uploadScene split into incremental uploaders | ~2 weeks | Phase A baseline measured (129.92 ms) |
| **pkg56** Phase C | depsgraph-driven dispatch | ~2–3 weeks | After Phase B |
| **pkg64** Phase 3 | Fold SMS into default path_tracer | ~½ week | Phases 1 + 2 done |
| **pkg74** Phase 3 | Interactive HTML dashboard + weekly CI | ~3 days | Phases 1 + 2 done |
| **pkg76** (new) | Astroray .blend importer (parity scope) | spec → ~1–2 weeks impl | Surfaced by pkg71 baseline run; specs need filing |
| pkg77 (new, tiny) | Replace UDIM monster source / drop from set | ½ day | Surfaced by pkg71 baseline run |
| pkg55 | Wavefront SoA GPU refactor | 8–12 weeks (3 phases) | Deferred until pkg56 + pkg64 land |
| pkg67 | Metric-aware path tracer | ~1 month | Research-blocked (Pillar-4-coupled; revisit when astrophysics thaws) |

**Pillar 4 (still parked):** pkg40 Kerr metric done; pkg41 Kerr
validation ready; pkg42–51 Codex-paste-ready specs waiting. **Do NOT
spawn Pillar 4 sessions in Round 4.** The gate releases when pkg56 +
pkg64 fully land.

---

## 2. Recommended next deployable set (Round 4)

Six sessions, all parallel-safe:

| # | Agent | Worktree / location | Package | Effort |
|---|---|---|---|---|
| 1 | Claude tech | `pkg73-optix-temporal` (new) | pkg73 OptiX temporal denoiser (depends on landed pkg72) | 3–4 days |
| 2 | Claude tech | `pkg56-phase-b` (new) | pkg56 Phase B — split `uploadScene` into per-domain incremental uploaders | ~2 weeks |
| 3 | Codex | main directory | pkg64 Phase 3 — fold SMS into default `path_tracer` as an MIS strategy gated by `use_refractive_caustics` / `use_reflective_caustics` | ~½ week |
| 4 | Codex (after #3 lands) | main directory | pkg74 Phase 3 — interactive HTML dashboard + weekly self-hosted CI workflow | ~3 days |
| 5 | CUDA verifier | hardware | re-baseline pkg72 motion-vector tests + pkg64 Phase 2 spectral SMS PSNR on RTX | ~1 hour |
| 6 | Claude research | `research-pkg76` (new) | spec **pkg76 Astroray .blend importer (parity-scope only)** — unblocks Classroom / Junkshop / BMW27 / Monster pkg71 rows | ~½ day |

Sessions 1, 2, 5, 6 spawn at once. Session 3 starts immediately;
session 4 follows 3 because Codex serializes in the main directory.

Round 4 closes when:
- pkg73 verified (eliminates viewport boiling on temporal mode)
- pkg56 Phase B merged (uploadScene split shipped)
- pkg64 Phase 3 merged (caustics on by default through MIS)
- pkg74 Phase 3 merged (showcase has interactive HTML + weekly CI run)
- pkg76 spec written (next round can implement)

Then **Round 5** picks up: pkg56 Phase C (depsgraph dispatch), pkg76
implementation, and pkg55 Phase A (wavefront refactor instrumentation —
the big architectural pivot starts).

---

## 3. Drop-in prompts per agent

### 3.1 Claude tech (worktree `pkg73-optix-temporal`) — OptiX temporal denoiser

```
You are Claude Code in worktree .claude/worktrees/pkg73-optix-temporal,
branched from current main. Implement pkg73 end to end. pkg72 motion
vectors landed in PR #220 — `Camera::motionBuffer` is populated for
every primary ray and accessible via `Renderer.get_motion_buffer()`.

Read first:
  - .astroray_plan/packages/pkg73-optix-temporal-denoiser.md (the spec)
  - plugins/passes/optix_denoiser.cpp (the pkg70 OptiX denoiser this
    extends — same shape: persistent OptixDeviceContext + handle,
    lazy init, model-kind selection by guide presence)
  - include/raytracer.h — `Camera::motionBuffer` (float2/pixel,
    OptiX prev→curr convention) and `Camera::snapshotForMotion()`
  - tests/test_motion_vector_aov.py — the contract pkg72 established

Phase 73 goal: extend OptiXDenoiser to upgrade to
OPTIX_DENOISER_MODEL_KIND_TEMPORAL_AOV when both motion + albedo +
normal guides are present. Falls back cleanly to AOV (pkg70) when
motion is absent.

Reference (Apache-2.0, mirrorable):
  - intern/cycles/device/optix/device_impl.cpp in the Blender
    repository — Cycles' OptiX temporal denoiser. Search for
    "Temporal" + the previous-output-buffer caching pattern.
  - https://raytracing-docs.nvidia.com/optix9/guide/index.html#ai_denoiser
    Section on TEMPORAL_AOV model kind. Read fully — temporal mode
    needs previous-output buffer + motion vectors + careful model-
    kind transition (destroy-and-recreate denoiser handle when
    flipping modes).

Implementation outline:

  1. plugins/passes/optix_denoiser.cpp — extend OptiXDenoiser:
     - Detect motion buffer at execute() time:
       hasMotion = fb.hasBuffer("motion") &&
                   anyNonzeroMotion(fb.buffer("motion"))
       (Don't upgrade to temporal mode for static cameras —
       previous-output buffer adds memory/latency for no win.)
     - When hasMotion + hasAlbedo + hasNormal: select model kind
       OPTIX_DENOISER_MODEL_KIND_TEMPORAL_AOV.
     - Cache previous-frame OUTPUT (denoised color) in a CUDA
       device buffer. First frame: zero buffer (or skip the
       temporal blend; OptiX docs cover this).
     - Model-kind transitions (HDR ↔ AOV ↔ TEMPORAL_AOV) require
       optixDenoiserDestroy + recreate. Implement clean handle
       lifecycle.
  2. tests/test_optix_temporal_denoiser.py — new:
     - Skip if OptiX SDK or CUDA unavailable.
     - Render scene at frame 1 with camera at A; render frame 2
       with camera panned; verify motion buffer non-zero, OptiX
       denoiser entered TEMPORAL_AOV mode (printf check via
       captured stdout, mirroring pkg68 pattern).
     - Inter-frame pixel variance: render a 10-frame camera-pan,
       compare pkg73 (TEMPORAL_AOV) vs pkg70 (AOV) on the same
       sequence. Acceptance: ≥30% reduction in inter-frame pixel
       variance per pkg73 spec.

Constraints:
  - CLAUDE.md sections 2, 3, 6.
  - DO NOT consult Cycles MNEE source — wrong concern; OptiX
    temporal denoiser code in intern/cycles/device/optix/ is the
    relevant reference and is Apache-2.0 (mirrorable with
    citation).
  - DO NOT modify pkg70's OIDN denoiser — OIDN has no analog of
    OptiX TEMPORAL_AOV (OIDN's color1 prev-frame input was an
    earlier confusion; pkg68 design decision #4 resolved it).
  - Static-camera scenes must NOT pay the memory cost of a
    previous-output buffer — fall back to AOV mode cleanly.
  - Without OptiX SDK: implementer's tests skip, mark in PR body
    "OptiX SDK + CUDA verification pending verifier session."

When done:
  - pkg73 spec status -> "implemented (pending CUDA + OptiX
    verification)".
  - STATUS.md: pkg73 row updated.
  - Append note to pkg72 Lessons: "Consumed by pkg73 OptiX
    temporal denoiser as designed."
  - Commit on this branch:
      feat(pkg73): OptiX TEMPORAL_AOV denoiser mode
      (motion-aware viewport stability)
  - PR. DO NOT merge.
```

### 3.2 Claude tech (worktree `pkg56-phase-b`) — uploadScene split

```
You are Claude Code in worktree .claude/worktrees/pkg56-phase-b,
branched from current main. Implement pkg56 Phase B only. Phase A
(viewport sync instrumentation) landed PR #210 with measured
baseline 129.92 ms/frame on a 100k-tri scene. Phase C (depsgraph-
driven dispatch) is a separate package.

Read first:
  - .astroray_plan/packages/pkg56-incremental-scene-sync.md
    (the spec — Phase B section)
  - .astroray_plan/docs/blender-depsgraph-sync-research.md
    (signed-off research, especially BlenderSync's per-domain
    upload pattern)
  - module/blender_module.cpp — find uploadScene + the per-domain
    helpers it calls (geometry, materials, lights, environment).
    Currently they all run together as a unit even when only one
    has changed.
  - blender_addon/__init__.py _sync_viewport_scene — the call
    site that always invokes the full upload.
  - The pkg56-A ring buffer in module/blender_module.cpp shows
    the per-stage cost breakdown — that's exactly what Phase B
    optimizes.

Phase B goal: refactor uploadScene from a monolithic call into
per-domain incremental uploaders, WITHOUT yet wiring depsgraph
dispatch (Phase C). Behavior unchanged for callers that invoke
all uploaders sequentially; new fine-grained API for Phase C
to use.

Implementation:

  1. Split uploadScene() in cuda_renderer.cu / module/blender_module.cpp
     into:
       uploadGeometry()    — BVH build + transforms + vertex normals
       uploadMaterials()   — material plugin uploads + GMaterial flat array
       uploadLights()      — light buffer + power CDF
       uploadEnvironment() — env map data + sampling tables
     Plus update_object_transform(obj_id, transform) for the cheap
     transform-only case (BVH refit instead of rebuild — see
     research note §4 for refit vs rebuild policy).

  2. uploadScene() becomes a thin wrapper that calls all four +
     full BVH rebuild — preserves backward-compat. Existing
     test_blender_*.py tests still pass without modification.

  3. Python bindings:
       Renderer.upload_geometry()
       Renderer.upload_materials()
       Renderer.upload_lights()
       Renderer.upload_environment()
       Renderer.update_object_transform(obj_id, transform_matrix)

  4. Tests/test_pkg56_phase_b_uploaders.py — new:
       - upload_geometry() alone produces same BVH state as
         uploadScene() (identical render output on a fixed scene).
       - upload_materials() preserves geometry buffers (no rebuild).
       - update_object_transform() refits BVH (orders-of-magnitude
         faster than rebuild on a 100k-tri scene); render output
         identical to a rebuild.
       - All four uploaders called sequentially produces identical
         render to uploadScene() on the same scene.

  5. Document Phase C (depsgraph dispatch) as an explicit non-goal
     of this PR; the new fine-grained API is the prerequisite, and
     Phase C wires the addon-side depsgraph.updates iteration to
     pick the right uploader.

Acceptance gates:
  - All 5 fine-grained uploaders accessible from Python, each with
    a unit test confirming it produces correct partial state.
  - update_object_transform() measurably faster than full rebuild
    on the pkg56-A reference scene (record numbers in pkg56
    Lessons "Phase B" subsection).
  - tests/test_blender_viewport_session.py + the existing
    pkg56-A tests pass unmodified.
  - No behavior change in the addon's _sync_viewport_scene path
    (still calls uploadScene = all four). That re-wiring is Phase C.

Constraints:
  - CLAUDE.md sections 2, 3.
  - Multi-session work — Phase B alone is ~2 weeks of focused
    Claude time across the C++ refactor, Python bindings, and
    test coverage.
  - Cite Cycles BlenderSync per-domain upload pattern in code
    comments at the new uploader sites (Apache-2.0,
    intern/cycles/blender/sync.cpp).

When done:
  - pkg56 Phase B checklist items checked; Phase C remains open.
  - STATUS.md: pkg56 noted as "Phases A + B done; C open".
  - Commit on this branch (squash later):
      feat(pkg56-B): split uploadScene into per-domain
      incremental uploaders + transform-refit fast path
  - PR. DO NOT merge.
```

### 3.3 Codex — pkg64 Phase 3 default-integrator fold

```
Implement pkg64 Phase 3 end to end. Phases 1 (RGB SMS skeleton) and
2 (spectral wavelength-Newton) are merged. Phase 3 folds SMS into
the default `path_tracer` as an MIS strategy gated by per-object
caustic-caster opt-in.

Read first:
  - .astroray_plan/packages/pkg64-spectral-caustics.md (Phase 3 section)
  - .astroray_plan/docs/caustics-research.md (the per-object
    caustic-caster opt-in UX section answers the "which objects
    contribute SMS connections" question)
  - plugins/integrators/sms_caustic_path_tracer.cpp (the Phase 1+2
    opt-in integrator — Phase 3 makes its strategy available
    through default `path_tracer` via MIS combination)
  - plugins/integrators/spectral_path_tracer.cpp (the default
    `path_tracer` registration — that's the integrator Phase 3
    augments)
  - include/raytracer.h — find where `use_refractive_caustics` /
    `use_reflective_caustics` are wired into the existing
    caustic_path_tracer; Phase 3 makes the same toggles work
    inside spectral_path_tracer through MIS.

Phase 3 goal: when `use_refractive_caustics=True` (already a
Renderer-level toggle from pkg29a), the default `path_tracer`
attempts an SMS connection per non-delta hit through any object
flagged `is_caustic_caster`. The contribution is MIS-combined with
the existing NEE direct-light estimate using the balance heuristic.

Implementation:

  1. Add per-object property `is_caustic_caster` (bool, default
     False). Plumb through:
       - Material/Object-level setter on Renderer
       - Python binding Renderer.set_object_caustic_caster(obj_id, bool)
       - Blender addon UI checkbox in object properties (a small
         "Astroray" panel under object data — pkg57 established
         the pattern)
  2. In spectral_path_tracer's per-bounce loop: when
     `use_refractive_caustics=True` AND the surface BSDF is non-delta
     AND any caustic-caster object exists: invoke the SMS connection
     attempt from sms_caustic_path_tracer (factor that out into a
     shared helper if not already done).
  3. MIS-combine the SMS contribution with NEE direct-light using
     balance heuristic. For static caustic-free scenes the SMS
     attempt's PDF is zero and MIS reduces to plain NEE — no
     regression risk.
  4. Update sms_caustic_path_tracer.cpp to share the MIS helper
     (avoid code duplication; both integrators call the same SMS
     attempt + MIS combine code).
  5. Tests:
       - tests/test_pkg64_phase3_default_integrator.py — render the
         pkg64 prism scene through default `path_tracer` with
         `use_refractive_caustics=True`. PSNR(spectral pkg64-3,
         hi-spp ground truth) − PSNR(no-caustics path_tracer,
         ground truth) ≥ 4 dB at equal sample count.
       - tests/test_pkg64_phase3_no_regression.py — render the
         standard Cornell box scene (no caustic casters). Output
         must be bit-identical (or within float-precision noise)
         to pre-pkg64-3 path_tracer output.
       - All existing tests/test_caustic_validation.py pass.

Constraints:
  - CLAUDE.md sections 2, 3, 6.
  - Cycles MNEE GPL fence: do NOT consult intern/cycles/integrator/
    mnee.cpp or related. The math is Hanika 2015 + Zeltner 2020
    SMS, both already cited in caustics-research.md.
  - Default behavior unchanged: until the user sets
    `use_refractive_caustics=True` AND marks at least one object
    as caustic_caster, path_tracer is the same as today.
  - Cost gate: on the standard Cornell box (no caustic casters),
    per-bounce cost ≤ +5% vs pre-pkg64-3 (the SMS attempt is
    short-circuited when no casters exist).

When done:
  - pkg64 Phase 3 checklist items checked; pkg64 status -> "fully
    done" (Phases 1 + 2 + 3 complete; GPU port is a future
    package outside Pillar 5 scope).
  - STATUS.md: pkg64 row updated to "Phases 1 + 2 + 3 done".
  - Commit on a fresh branch:
      feat(pkg64-3): fold SMS into default path_tracer with
      per-object caustic_caster opt-in + MIS combine
  - PR. DO NOT merge.
```

### 3.4 Codex (after #3 lands) — pkg74 Phase 3 interactive HTML + weekly CI

```
Implement pkg74 Phase 3 end to end. Phases 1 + 2 are merged. Phase 3
turns the showcase framework into a browsable interactive dashboard
and wires it to a weekly self-hosted CI run.

Read first:
  - .astroray_plan/packages/pkg74-engine-benchmark-showcase.md (Phase 3 section)
  - benchmarks/showcase/html_index.py (Phase 1 + 2 static HTML — Phase 3
    extends with vanilla-JS sortable table + collapsible category sections)
  - benchmarks/showcase/runner.py (the CLI driver — Phase 3 keeps
    invocation unchanged; just adds artefact polish)
  - .github/workflows/cycles-parity.yml (the existing pkg71 self-hosted
    CI workflow — Phase 3 adds a sibling weekly workflow for pkg74)

Phase 3 goal: interactive HTML dashboard + weekly CI workflow.

Implementation:

  1. benchmarks/showcase/html_index.py — replace the current static
     <details> sections with:
     - Inline vanilla-JS sortable table (no external CDN deps;
       the table sort code is ~30 lines of JS; embed in <script>
       block, no source-map). Sort by any column on click.
     - Collapsible category sections preserved.
     - Inline-render the convergence curve, integrator-compare
       contact sheet, and timing bar chart (already saved as PNG
       by Phase 2).
     - Footer with git SHA + Astroray version + machine ID +
       runtime metadata (OIDN version, OptiX version, CUDA
       version) — the moment-in-time provenance.

  2. .github/workflows/showcase.yml — new sibling to
     cycles-parity.yml:
     - Weekly cron (Sundays 02:00 UTC, off-peak)
     - Manual trigger via workflow_dispatch
     - Self-hosted CUDA runner (same one pkg71 uses)
     - Runs `python -m benchmarks.showcase.runner --quick`
     - Commits the resulting CSV + HTML + PNG artefacts to a
       dated branch under `benchmarks/showcase/output/<date>/`,
       opens a PR with the Markdown summary in the body.
     - Old artefacts: keep last 12 weekly runs in the branch;
       rotate older ones to a separate archive branch.

  3. tests/test_benchmark_showcase_phase3.py — new:
     - Verify generated index.html contains the sortable-table
       JS + valid HTML structure
     - Verify the runner produces all expected PNG artefacts
       and one CSV
     - Skip the CI workflow validation (workflow file syntax)
       since GitHub Actions yaml linting is the wrong place

Acceptance:
  - python -m benchmarks.showcase.runner --quick produces the
    interactive HTML in <60s on a CPU build.
  - tests/test_benchmark_showcase_phase3.py green.
  - .github/workflows/showcase.yml passes a `gh workflow view`
    sanity check.
  - First weekly run lands on a self-hosted runner (validation
    happens once the runner picks up the cron).

Constraints:
  - CLAUDE.md sections 2, 3.
  - DO NOT add npm dependencies, CDN dependencies, or any
    runtime that requires network access. Inline JS/CSS only.
  - DO NOT modify Phase 1 + 2 outputs — Phase 3 wraps them
    with a richer index, doesn't replace.
  - CI workflow: same self-hosted runner as pkg71. Don't
    spawn a parallel runner.

When done:
  - pkg74 Phase 3 checklist items checked; pkg74 -> fully done.
  - STATUS.md: pkg74 row updated to "Phases 1 + 2 + 3 done".
  - Commit on a fresh branch:
      feat(pkg74-3): interactive HTML showcase + weekly CI
  - PR. DO NOT merge.
```

### 3.5 CUDA verifier — pkg72 + pkg64 Phase 2 hardware verification

```
You are a CUDA verification session on the user's RTX 5070 Ti
Windows workstation. Two tiny verifications, both ~30 minutes.

Step 1: pull main, confirm pkg72 + pkg64-2 present.
  git fetch origin && git checkout main && git pull --ff-only

Step 2: pkg72 motion vector hardware verification.
  scripts\build\build_cuda.bat
  python scripts\dev\run_tests.py --build-dir build_cuda --
    tests/test_motion_vector_aov.py
  -v --tb=short

  Expected: all 6 tests pass. The pkg72 implementer noted
  "full Windows VS / pyd rebuild was not run from this worktree
  (existing build_cuda is configured against the main worktree);
  please run tests/test_motion_vector_aov.py after the next
  addon build." This is that step.

  Smoke-render a test scene:
    Scene: Cornell with the camera panning +0.1 in x between
           frame 1 and frame 2.
    Frame 1: render, snapshot motion buffer (should be all-zero
             — first-frame convention).
    Frame 2: render, snapshot motion buffer (should show
             non-zero positive x-component on every pixel hit
             by static geometry).
  Append the actual measured numbers (mean motion magnitude
  on hit pixels) to pkg72 Lessons.

Step 3: pkg64 Phase 2 hardware re-baseline.
  python scripts\dev\run_tests.py --build-dir build_cuda --
    tests/test_sms_caustic_validation.py
    tests/test_sms_caustic_spectral.py
  -v --tb=short

  Expected: 6 tests green. PSNR delta from
  test_sms_caustic_spectral was 8.83 dB on the implementer's
  machine (Linux build). Confirm the same number ±2 dB on RTX
  5070 Ti — material differences would suggest a CPU/GPU code-
  path divergence we want to know about.

  Append actual measured PSNR delta + runtime ratio to pkg64
  Lessons (Phase 2 subsection).

Step 4: commit on a verify branch.
  Title: verify(pkg72, pkg64-2): hardware re-baseline
  Body: include the measured numbers from steps 2 + 3 verbatim.
  Push, open PR, do NOT merge.

Constraints:
  - Do NOT modify implementation code.
  - Do NOT relax any gate.
  - If any number REGRESSES vs the implementer-machine baseline,
    stop and ask. Cross-machine variation is expected (different
    OS, compiler, CUDA toolkit), but a >25% delta is suspicious.
```

### 3.6 Claude research (worktree `research-pkg76`) — Astroray .blend importer (parity scope)

```
You are Claude Code in worktree .claude/worktrees/research-pkg76,
branched from current main. RESEARCH + SPEC session — no
implementation code. One deliverable.

Why this matters: pkg71's first canonical baseline (PR #218)
landed Cornell parity numbers cleanly (Astroray-CPU SSIM 0.9536,
Astroray-GPU SSIM 0.9548 vs Cycles-CPU EXR), but Classroom,
Junkshop, BMW27, and Monster all skipped Astroray rows with
`astroray_blend_import_not_implemented`. Astroray has no .blend
importer — the harness can only compare on scenes both engines
can build natively. To land a real 5-scene parity baseline,
Astroray needs at minimum a parity-scope .blend reader.

Deliverable: create
.astroray_plan/packages/pkg76-blend-importer-parity-scope.md.

Required reading (use WebFetch):

Blender .blend file format:
  - https://wiki.blender.org/wiki/Source/File_Format
    Official documentation on the SDNA format. SDNA self-describes
    the binary structures, so a .blend reader at parity scope
    can be quite small — read the SDNA, then walk the typed blocks.
  - https://www.atmind.nl/blender/mystery_ot_blend.html
    Shorter community walkthrough. Useful for understanding
    block indexing.

Existing third-party readers (license-fenced):
  - https://github.com/blender/blender — official .blend reader is in
    source/blender/blenkernel/intern/. License GPL-2.0+, so we cannot
    mirror code. Read for understanding only.
  - https://github.com/JTraversa/Blender-File-Reader — Python .blend
    reader, BSD-3 licensed, mirroring permitted with citation. Check
    the license tag at fetch time to confirm.
  - https://pypi.org/project/blend2json/ — Python .blend → JSON tool.
    BSD-3. Useful as a reference for which struct fields matter for
    parity-scope rendering (camera, materials, geometry).

Required H2 sections in pkg76 spec:

  1. Goal / Before / After (parity-scope only — NOT a full Blender
     compatibility layer. Only what pkg71 needs.)
  2. Reference Implementations (URL, license, what to mirror, what NOT)
  3. Specification:
     - File parser strategy: probably a small Python parser using
       the SDNA self-description, NOT a C++ reader. (Cycles uses C++
       because it's IN Blender; we're external and can read the file
       offline.)
     - Minimum field set for parity scope:
       - Camera: position, rotation, focal length, sensor size
       - Mesh: vertices + faces + per-face material index
       - Material: base color (Diffuse BSDF or Principled BSDF
         basecolor only — full shader graph is OUT of scope; pkg57
         shader nodes handle Astroray-side complexity, not
         Blender-side import)
       - Light: position + color + intensity (Point/Sun/Spot)
       - World background color (HDRI import is OUT of scope —
         document as future)
     - Output: a Python builder script that takes a .blend path
       and constructs the equivalent Astroray scene via the
       Renderer Python API.
     - Wiring into pkg71 harness: pkg71 invokes the importer for
       every Astroray-engine row when the source is a .blend file.
  4. Acceptance:
     - Classroom + Junkshop + BMW27 produce non-skip Astroray
       rows in the next pkg71 baseline run. SSIM target ≥ 0.85
       (relaxed from the 0.95 Cornell gate because parity-scope
       import will lose shader-graph and procedural-texture
       fidelity).
     - Test fixture: tiny synthetic .blend (created at test-write
       time via bpy in a pytest skip-if-no-bpy guard), verify
       roundtrip Astroray scene matches expected geometry and
       material counts.
     - Monster scene fix (the UDIM monster lacks a camera per the
     pkg71 baseline output): either find a different monster source
     OR drop monster from the pkg71 set. Whichever pkg76 chooses,
     update the pkg71 manifest.toml.
  5. Non-goals:
     - Full shader graph import (use pkg57 shader nodes manually
       on the Astroray side; this is parity scope only)
     - HDRI / image-texture import (parity scope = procedural only)
     - Animation, modifiers, particles, hair, volumes (out of
     parity scope)
  6. Front-matter:
     - Pillar 5
     - Track A
     - Estimated effort: 1-2 weeks
     - Depends on pkg71 (the harness consumer)
  7. Reference matrix per CLAUDE.md §6

Length: 4-6 pages.

When done:
  - Commit on this branch:
      docs(pkg76): Astroray .blend importer (parity scope) spec
  - PR. DO NOT merge.

Constraints:
  - CLAUDE.md section 6 (cite, borrow, verify).
  - No source code changes.
  - License-fence: Blender's own .blend reader is GPL-2.0+ and
    NOT mirrorable. Cite for understanding. Permissive readers
    (BSD-3 like Blender-File-Reader, blend2json) are mirrorable
    with attribution.
  - Be honest about scope: this is parity for pkg71, not a full
    .blend compatibility layer. Future packages can extend.
```

---

## 4. Coordination

**File-touching map** (zero hard collisions):

| Session | Files |
|---|---|
| pkg73 OptiX temporal | `plugins/passes/optix_denoiser.cpp` (extend OptiXDenoiser class), new test, pkg73 spec, STATUS.md, brief Lessons append to pkg72 spec |
| pkg56 Phase B | `module/blender_module.cpp` (split + new bindings), `src/gpu/cuda_renderer.cu` (per-domain uploaders), new test, pkg56 spec Phase B subsection, STATUS.md |
| pkg64 Phase 3 | `plugins/integrators/spectral_path_tracer.cpp` (MIS-combine SMS), `plugins/integrators/sms_caustic_path_tracer.cpp` (extract shared helper), `include/raytracer.h` (per-object caustic_caster property), `module/blender_module.cpp` (binding), `blender_addon/__init__.py` (UI checkbox), 2 new tests, pkg64 spec, STATUS.md |
| pkg74 Phase 3 | `benchmarks/showcase/html_index.py` (rewrite), new `.github/workflows/showcase.yml`, new test, pkg74 spec, STATUS.md |
| Verifier (pkg72 + pkg64-2) | only verify-branch commits + pkg72/pkg64 Lessons appends |
| pkg76 spec | only `.astroray_plan/packages/pkg76-*.md` (new) |

**Two real conflict points to watch:**

1. **`module/blender_module.cpp`** — pkg56-B (split into per-domain
   uploaders + new bindings) and pkg64-3 (per-object caustic_caster
   binding) both touch this. Different sections; trivial three-way
   merge.

2. **`plugins/integrators/spectral_path_tracer.cpp`** — pkg64-3 adds
   an MIS-combined SMS branch in the per-bounce loop. No other Round 4
   session touches this file. Should be conflict-free.

3. **STATUS.md** — five sessions all touch it. Same three-way merge
   race we've been hitting. Mitigation as before: post-round sweep PR
   to restore lost rows if the squash-merge collapse drops them.

**Recommended merge order:** verifier (smallest) → pkg76 spec
(docs only) → pkg64 Phase 3 (Codex, ½ week, ships first per Codex
ordering) → pkg74 Phase 3 (Codex, after pkg64-3) → pkg73 OptiX
temporal (Claude tech) → pkg56 Phase B (largest delta, last).

---

## 5. After Round 4 lands

When this round lands:

- **pkg73** → OptiX temporal denoiser ships; viewport animation has
  hardware-accelerated temporal stability via motion vectors.
  Together with pkg68 + pkg70 + pkg75, the entire denoiser story
  closes.
- **pkg64 Phase 3** → caustics opt-in via per-object property; the
  flagship visual-fidelity package fully done end-to-end.
- **pkg74 Phase 3** → showcase runs weekly in CI and produces an
  interactive HTML report; the engine has self-publishing benchmark
  artefacts.
- **pkg56 Phase B** → fine-grained uploaders shipped; Phase C wires
  depsgraph dispatch on top.
- **pkg76 spec** → ready for Round 5 implementation; non-Cornell
  pkg71 baseline rows become possible.

Then **Round 5** picks up:

- **pkg56 Phase C** (depsgraph-driven dispatch) — ~2-3 weeks, Claude tech.
  Uses the fine-grained uploaders from Phase B; viewport idle frames
  drop to the ≤5 ms gate.
- **pkg76 implementation** (Astroray .blend importer) — ~1-2 weeks,
  Claude tech. Unblocks 4 of 5 pkg71 baseline scenes.
- **pkg77** (monster scene fix) — ½ day, Codex. Whichever resolution
  pkg76 picks (replace source vs drop scene).
- **pkg55 Phase A** (wavefront refactor instrumentation) — ~1 week,
  Claude tech. The big architectural pivot begins. Measured baselines
  from pkg56 + pkg64 + pkg71 + pkg74 are now in place to compare
  against.
- **CUDA verifier follow-ups** as needed for pkg73 + pkg64-3.

After Round 5:

- pkg56 fully done (Phases A + B + C).
- pkg64 fully done (Phases 1 + 2 + 3).
- pkg74 fully done (Phases 1 + 2 + 3).
- pkg76 implementation done.
- pkg55 Phase A done; Phases B + C ahead (long).

When pkg56 + pkg64 + pkg76 are all done, **Pillar 5 is essentially
feature-complete** for the Cycles-parity / Blender integration push.
At that point:

- **Pillar 4 thaws.** Codex picks up pkg41 Kerr validation first
  (already ready, gated only by the strategic freeze). Then the
  Codex-paste-ready specs for pkg42 / 43 / 44 / 47 / 48 / 49 in
  parallel as Codex bandwidth allows.
- **pkg55 Phases B + C** (the wavefront SoA migration proper) become
  the major Pillar 5 architectural work. Multi-month, but unlocks
  measurable GPU parity claims with Cycles X for the eventual paper.
- **pkg67 metric-aware path tracer** (research-blocked currently)
  becomes unblocked by pkg40 + pkg55 maturity.

Bump this report when pkg56 Phase B or pkg64 Phase 3 lands — those
are the next major queue movements.
