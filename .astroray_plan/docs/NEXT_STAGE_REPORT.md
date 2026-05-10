# Astroray Next Stage Report

**Date:** 2026-05-10 (post-Round-5 + viewport-parity reality check — pkg76 + pkg55-A + pkg41 + pkg73-diag + verifier set all landed; Pillar 4 actively shipping; **two new Pillar-5 packages filed (pkg80, pkg81) after the project owner surfaced an `'auto'` integrator GPU crash and that viewport pan/zoom is "a slog vs Cycles"**)
**Prepared by:** Claude (Anthropic Code, Sonnet 4.5 in Max 5x)
**Scope:** Round 6. Round 5 closed cleanly on package count, but the
user-facing competitive-parity goal in ROADMAP.md is *not* satisfied
in viewport rendered-view yet — pkg81 quantifies the gap and pkg80
fixes a daily-workflow blocker. Round 6 priorities:
(a) **pkg80** Blender `'auto'` integrator resolution (unblocks owner's daily workflow — small),
(b) closing the pkg73 defect,
(c) starting **pkg81** viewport-interactivity measurement (the *real* Pillar-5-closing work),
(d) extending Pillar 4 with pkg42,
(e) wavefront SoA scaffold (pkg55 Phase A.1).

> Strategic gate released **2026-05-10** (PR #233). Pillar 4
> active. Strategy in [`ROADMAP.md`](ROADMAP.md), status in
> [`STATUS.md`](STATUS.md).

---

## 1. Current state (one screen)

**Done since the previous report (Round 5 closure):**

- **pkg76** Astroray `.blend` importer shipped — offline SDNA-walking
  Python reader (no `bpy` runtime), `tools/blend_import/{sdna,
  reader, scene_builder, blend_to_astroray}.py`, returns
  `astroray.Scene`. Roundtrip passes on `synthetic_min.blend`
  (1 cube + 1 sun + 1 camera + Principled BSDF). PR #240. The
  three deferred CSV rows (Classroom / Junkshop / BMW27) need a
  reference run on the RTX box and are queued as a Round 6
  follow-up.
- **pkg55 Phase A** wavefront baseline instrumentation shipped —
  `ASTRORAY_PROFILE=1`-gated CUDA events + NVTX, baseline.json
  populated for `cornell_diffuse` + `cornell_glass`. Headline
  measurement: **158 regs/thread, 1 active block/SM** at the 256-
  thread launch — exactly the Laine 2013 occupancy cliff the SoA
  refactor is meant to relieve. PR #238.
- **pkg41** Kerr metric validation harness shipped — first Pillar-4
  deliverable post-gate. 39 tests for BPT 1972 / Chandrasekhar
  analytic quantities + null circular photon residuals + Kerr a=0
  vs Schwarzschild identity + shadow-contour image-plane regression.
  Bardeen/Chandrasekhar references, no GPL/CeCILL code mirrored.
  PR #236.
- **pkg73 diag** instrumentation shipped — `[pkg73-diag]` stderr
  prints in `Camera::snapshotForMotion`, `renderFrame` entry, and
  `OptiXDenoiser::execute` so the next RTX run produces a decision-
  tree-resolvable signal for the 0% inter-frame variance reduction
  defect. Static analysis in PR #241 ruled out logic bugs in the
  chain — root cause needs hardware evidence. PR #241.
- **pkg64-3 hardware verifier (rebuild)** — the previous verifier
  pass (PR #235) hit a stale `.pyd` predating PR #230's
  `scene_object_count` binding; the rebuild pass (#239) captured
  the actual numbers: **SMS receiver-energy ratio 1.18× ✅**, **PSNR
  floor +0.26 dB ✅**, **per-bounce overhead 2.0 % ✅**. All three
  Phase 3 gates met on RTX 5070 Ti.
- **pkg73 + pkg64-3 verifier (initial pass)** — honest doc-only
  record of the 0% pkg73 result and pkg64-3 stale-build block. The
  audit trail is preserved (PR #235 + #239 stack), not overwritten.
- **pkg78** verifier ran the spec's branch logic correctly — the
  re-baseline precondition did **not** hold (CPU/GPU output bit-
  identical pre/post pkg75), so the gate floor was **not** lowered
  and the drift was filed as defect [#237](https://github.com/HendrikGC02/Astroray/issues/237).
- **pkg78 bisect** session refused the 20-commit hardware bisect
  on §1 grounds (static enumeration of `5aba401..fcbbbf2` showed
  zero commits touching the multiwavelength integrator path —
  bisect would have been theatre). Diagnosis posted on issue #237:
  the gate is too tight relative to NVCC build-time non-
  determinism in the SSIM saturation regime (0.999263 sat 6.3e-4
  above a 0.999 floor; cross-build FMA reordering moves it by
  O(1e-4)). **pkg78 closes as diagnosed**; the variance
  characterisation that justifies the actual gate decision is
  filed as **pkg82** *(new)*.

**Pillar-5 reality check (filed 2026-05-10):**

The package counter says Pillar 5 is **27/28 done, 96%**. The lived
experience is that the `'auto'` integrator crashes on GPU and the
viewport "is a slog vs Cycles". Two new packages capture the gap:

- **pkg80** *(new, small)* — Blender addon resolves `'auto'`
  integrator dropdown to a registered plugin before C++ calls.
  Daily-workflow blocker; ~½ day. Surfaced by the project owner.
- **pkg81** *(new, big)* — Viewport interactivity parity with
  Cycles. pkg52 + pkg56 + pkg68 + pkg73 + pkg74 all closed against
  internal gates, but **none against Cycles-CUDA on the same scene
  during pan/zoom**. pkg81 builds the harness, diagnoses the gap,
  fixes it. ROADMAP.md's "rival Cycles" promise isn't satisfied
  until this lands. ~1–2 weeks. **The actual Pillar-5-closing
  package.**

**Open pickup pool (Round 6 + Round 7):**

| Pkg | Title | Effort | Status |
|---|---|---|---|
| **pkg80** *(new)* | Blender addon `'auto'` integrator resolution | ~½ day | Daily-workflow blocker; small Codex pickup |
| ~~pkg73 fix~~ | ~~TEMPORAL_AOV upgrade branch never fires on RTX~~ | — | **DONE 2026-05-11** (PR #249): two compounding bugs fixed (plugin: `temporalModeUsePreviousLayers` was 0; test: AOV ref silently upgraded). Hardware: 53.1 % reduction vs ≥30 % gate. Denoiser story closes end-to-end. |
| ~~pkg81~~ | ~~Viewport interactivity parity with Cycles (Phase 1 + 2 + 3)~~ | — | **Phase 1+2 DONE 2026-05-11** (PR #248). H4 megakernel-register-pressure dominates: **CUDA 104 ms vs CPU 58 ms on 100k tris** — the pkg55-A 158 regs/thread cliff measured at viewport scale. **Phase 3 routes to pkg55 Phase B** per the spec's escape clause; Phase B's acceptance now includes the viewport-parity gate. Smaller H2/H5 follow-ups split out as **pkg83** + **pkg84**. |
| **pkg83** *(new)* | Progressive accumulation continuation across camera changes (H2 from pkg81) | ~½ day | Addon-only; user-facing UX win independent of pkg55 Phase B |
| **pkg84** *(new)* | CUDA kernel pre-warm at viewport start (H5 from pkg81) | ~½ day | Addon-only; moves the 12 s first-frame freeze to a moment the user expects |
| **pkg42** | Synchrotron emission (Pillar 4) | ~2 weeks | Codex-paste-ready spec |
| **pkg43** | Slim disk model (Pillar 4) | ~2 weeks | Codex-paste-ready spec |
| **pkg44** | ADAF model (Pillar 4) | ~2 weeks | Codex-paste-ready spec |
| **pkg55** Phase A.1 | SoA infra + intersect queue | ~1–2 weeks | Renamed in spec by PR #238; first real refactor before Phase B; pkg81 may surface this as a viewport bottleneck too |
| pkg55 Phase B | Per-material shade kernels | 4–6 weeks | After A.1; **now owns the viewport-parity gate** (pkg81 Phase 3) — Phase B isn't done until the wavefront `path_tracer` clears CUDA pan-frame p99 ≤ 1.2× Cycles-CUDA on the pkg81 harness scene |
| pkg55 Phase C | Megakernel removal | 2–4 weeks | After B |
| pkg76 CSV | Classroom / Junkshop / BMW27 baseline rows | ~½ day on RTX | After pkg73 fix (so denoiser path is healthy for parity numbers) |
| **pkg82** *(new)* | pkg54c gate variance characterisation (intra-binary + cross-build SSIM distribution; data-driven gate decision) | ~1 day on RTX | Replaces pkg78 bisect after the diagnosis ruled out a code regression; [#237](https://github.com/HendrikGC02/Astroray/issues/237) closes when this lands |
| pkg79 (tiny) | ReSTIR `test_spatial_reduces_mse` flake (margin 0.000004) | ~½ day | Surfaced by PR #236 CI |
| pkg47 / 48 / 49 | FITS / HDF5 / SPH loaders (Pillar 4 data import) | weeks each | Codex-paste-ready specs queued; deferred behind pkg42–44 |
| pkg67 | Metric-aware path tracer | ~1 month | Unblocks once pkg40 + pkg55 maturity in place |

---

## 2. Recommended next deployable set (Round 6)

Eight sessions, parallel-safe (pkg80 + pkg81 added this round):

| # | Agent | Worktree / location | Package | Effort |
|---|---|---|---|---|
| 1 | Codex | main directory | **pkg80** Blender `'auto'` integrator resolution — daily-workflow blocker; ship first | ~½ day |
| 2 | CUDA verifier | hardware | **pkg73 diag capture** — run #241's instrumented build on RTX 5070 Ti, post `[pkg73-diag]` stderr to PR #241 | ~15 min |
| 3 | Claude tech (after #2) | `pkg73-fix` (new) | **pkg73 fix** — apply the diag-pointed fix; re-run; clear ≥30% gate | ~½ day |
| 4 | Claude tech | `pkg81-viewport-parity` (new) | **pkg81 Phase 1 + Phase 2** — viewport-interactivity benchmark harness + Cycles A/B + diagnosis note | ~1 week |
| 5 | Claude tech | `pkg55-phase-a1` (new) | pkg55 Phase A.1 — SoA infra + intersect queue | ~1–2 weeks |
| 6 | Codex (after #1) | main directory | **pkg42 synchrotron emission** (Pillar 4) | ~2 weeks |
| 7 | Codex (after #6) | main directory + RTX | **pkg82** — pkg54c gate variance characterisation (replaces the pkg78 bisect, which closed as "diagnosed: not a code regression") | ~1 day on RTX |
| 8 | Codex (after #7) | main directory | pkg76 CSV — populate Classroom / Junkshop / BMW27 rows on RTX | ~½ day |

Sessions 1, 2, 4, 5 spawn at once. Session 3 starts the moment #2
posts. Sessions 6→7→8 chain in the main directory.

The ReSTIR flake (pkg79) is small enough to fold into whichever
session is least busy.

**Why pkg80 is #1:** the project owner's daily Blender workflow
currently crashes on GPU + `Auto (Best Available)`. Until that's
fixed, the rest of the round's value is harder to evaluate.

**Why pkg81 is in this round even though it's big:** Phase 1
(harness) and Phase 2 (diagnosis) together produce the first
honest Astroray-vs-Cycles viewport number. That alone is worth
shipping; Phase 3 (the fix) may then route through pkg55 Phase B
if H4 (register pressure) dominates — in which case pkg81 partially
closes as "measured, remediation tracked under pkg55".

Round 6 closes when:
- pkg80 merged (daily workflow unblocked)
- pkg73 fix merged + gate clears on RTX (denoiser story closed)
- pkg81 Phase 1 + Phase 2 merged (viewport gap quantified)
- pkg42 merged (second Pillar-4 deliverable)
- pkg55 Phase A.1 merged (SoA scaffolding in tree)
- pkg78 bisect comment posted on #237
- pkg76 CSV rows populated

Then **Round 7** runs pkg81 Phase 3 (whichever fix the diagnosis
points at), pkg43 + pkg44 (Codex Pillar 4), and pkg55 Phase B
(per-material shade kernel split — possibly the pkg81 Phase 3 fix
itself if H4 wins).

---

## 3. Drop-in prompts per agent

### 3.1 CUDA verifier (hardware) — pkg73 diag capture

```
You are the CUDA verifier on the RTX 5070 Ti / Windows MSVC box.
PR #241 landed `[pkg73-diag]` stderr instrumentation in
`Camera::snapshotForMotion`, `Renderer::renderFrame` entry, and
`OptiXDenoiser::execute` to localise the 0 % inter-frame variance
reduction defect. The fix session (3.2) is blocked on this signal.

Step 1 — sync main + clean rebuild:
  git checkout main && git pull --ff-only
  cmake --build --preset windows-tcnn-vs-release
  (or build_cuda equivalent)

Step 2 — run the failing tests with -s (so stderr is captured):
  python scripts/dev/run_tests.py --build-dir build_cuda --
    tests/test_optix_denoiser_temporal.py
  -v -s --tb=short 2>&1 | tee test_results/pkg73-diag/run.log

Step 3 — post the captured `[pkg73-diag]` lines as a comment on
PR #241 (the now-merged diag PR). Per-frame, in render order, raw.
Do NOT trim; the fix session needs the full signal — motion buf
pointer, non-zero count, abs-max, hasPrevCamera, prevOrigin — for
each frame to discriminate among:

  (a) motion buffer pointer mismatch (snapshot/execute see different
      ptr)
  (b) buffer populated with zeros (snapshot ran, but motion-write
      site never fired)
  (c) buffer populated, non-zero, but `desiredKind` selection
      branch never taken (test methodology issue)

Step 4 — also re-record the test pass/fail summary (5 tests, prior
result was 3 pass / 2 fail). Append to the same comment.

Constraints:
  - Doc + comment only. No source touched.
  - Do NOT relax the ≥30 % gate.
  - If rebuild errors before producing any [pkg73-diag] lines,
    post the build/run failure verbatim and STOP.
```

### 3.2 Claude tech (worktree `pkg73-fix`, after 3.1) — pkg73 fix

```
You are Claude Code in worktree .claude/worktrees/pkg73-fix,
branched from current main. The CUDA verifier posted the
[pkg73-diag] hardware capture as PR #241 issuecomment-4415448408
on 2026-05-11. Findings (READ THE COMMENT FIRST):

  - Test result: 4 passed, 1 failed. Only
    test_inter_frame_variance_reduction stays red (0.4 %
    reduction vs ≥30 % gate).
  - The previously-failing TEMPORAL_AOV-substring test now
    passes — the kind transition is firing (8996 → 8998 once
    after the first motion-bearing frame, honored thereafter).
  - Discriminators (a) and (b) RULED OUT by the trace:
    * (a) pointer mismatch — cam= matches between renderFrame
      entry and the following snapshot for every frame; motion
      buffer pointers in execute reuse a stable ring.
    * (b) zero-buffer — every hasMotion=1 execute reports
      motion_nonzero_count 4142–7842 and motion_abs_max ≈ 0.32
      on stepped frames (~1e-5 on duplicate-camera frames, as
      expected).
  - Discriminator (c) is most consistent. Failure must be
    DOWNSTREAM of the kind-transition. Two candidates remain:
       (c1) prev-output guide-layer wiring bug (code)
       (c2) test methodology — RMS metric at noise floor at
            96×96 / 1 spp, dominated by content change rather
            than denoiser noise (gate vs scene).

Read first:
  - PR #241 issuecomment-4415448408 (the verifier's full trace
    + per-frame numbers)
  - plugins/passes/optix_denoiser.cpp (the TEMPORAL_AOV setup
    block — focus on OptixDenoiserGuideLayer fields: `flow`,
    `previousOutputInternalGuideLayer`,
    `outputInternalGuideLayer`. These have to ping-pong; if
    they point at the same buffer or the same internal guide
    layer object, OptiX runs TEMPORAL_AOV but loses temporal
    info)
  - tests/test_optix_denoiser_temporal.py
    ::test_inter_frame_variance_reduction (the failing gate;
    note the 96×96 / 1 spp choice)
  - intern/cycles/device/optix/device_impl.cpp the
    `prev_output` cache + ping-pong pattern. Apache-2.0.
    Reference for what correct wiring looks like.

Decision procedure — bisect (c1) vs (c2):

  Step A. Read the OptiX TEMPORAL_AOV docs §AI Denoiser flow
  contract. Trace through the implementation against:
    * Two internal guide layers exist (current + previous)
    * The pair is swapped after each execute (current becomes
      previous for the next frame)
    * First frame has previousOutputInternalGuideLayer = a
      zero-initialised buffer (or Cycles' "no-prev-frame"
      sentinel — see device_impl.cpp)
    * Layout (pixelStrideInBytes, format, rowStrideInBytes)
      is consistent

  If you find a wiring bug — fix it. That's (c1).

  If the wiring is correct, prove it. Add a temporary
  diagnostic print of the prev_output_buf address at execute
  entry and exit, and log the swap. Re-run the test on RTX.
  If both buffers are populated and swap correctly across
  frames but variance reduction stays at ~0 %, the wiring is
  good and (c2) is the answer.

  If (c2): the gate is the wrong shape for the test scene.
  TWO acceptable resolutions, choose with measurement:
    Option 1: bump test resolution + spp so MC noise is the
    dominant variance source (e.g. 256×256 / 16 spp). At that
    point, TEMPORAL_AOV vs AOV should show a real (>30 %)
    delta because temporal coherence between frames at moderate
    spp IS what TEMPORAL_AOV is designed to exploit.
    Option 2: change the gate metric. Instead of RMS of
    inter-frame difference (which is dominated by pan-induced
    content change), compare per-pixel variance of N
    re-renders of the SAME frame with different RNG seeds
    against the prev-frame guide. Cycles' temporal denoising
    benchmarks measure this way.

  Choose by measurement: if Option 1 (higher spp) hits ≥30 %,
  ship it — it's the simpler fix. If it doesn't, the metric
  itself is wrong and Option 2 is required. Show numbers in
  the PR body either way.

Step 1 — diagnose. Write up which branch (c1 or c2) and why
in the PR body, with the measurements that justified the call.
Step 2 — fix the root cause. ONE surgical fix.
Step 3 — REMOVE the [pkg73-diag] prints (the previous diag PR
explicitly marked them "remove after fix" with date — do it
now).
Step 4 — re-run the gate on RTX. Must clear ≥30 %.

Build provenance note: build_cuda is NMake-generated. The
verifier flagged that nmake/cl aren't on MSYS-bash PATH. Run
the rebuild from a VS Developer Command Prompt (vcvars64
shell), or use the windows-tcnn-vs-release preset which uses
MSBuild via cmake --build. Either path works; do not bash-
escape your way around it.

Constraints:
  - CLAUDE.md sections 1, 2, 3, 6.
  - Do NOT relax the ≥30 % gate by lowering the floor. If you
    change the test (Option 1 or 2), the new gate must show a
    ≥30 % delta on a real measurement; the gate STAYS at 30 %.
  - Do NOT add a "force temporal mode" flag — the auto-upgrade
    on real motion is correct design.
  - DO NOT consult Cycles MNEE source (wrong concern); pkg73
    reference is intern/cycles/device/optix/device_impl.cpp
    (Apache-2.0).

When done:
  - Append "Defect fix 2026-05-XX" section to pkg73 spec with
    the (c1 vs c2) call + measured numbers.
  - PR titled either:
    * "fix(pkg73): prev-output guide-layer ping-pong (c1)"
    * "fix(pkg73): variance gate moved to spp=16 / 256x256 (c2)"
    Whichever applies, with the one-line root cause in the title.
```

### 3.3 Claude tech (worktree `pkg55-phase-a1`) — SoA infra + intersect queue

```
You are Claude Code in worktree .claude/worktrees/pkg55-phase-a1,
branched from current main. Phase A landed in PR #238 (gated
profiling, baseline.json populated, 158 regs/thread + 1 block/SM
documented as the cliff). Phase A.1 is the first real refactor
toward wavefront — drop in the SoA path-state buffer + an
intersect queue, BEHIND a build-time flag so the AoS megakernel
remains the default and bit-identical.

Read first:
  - .astroray_plan/packages/pkg55-wavefront-soa-refactor.md
    (the full spec; Phase A.1 was carved out of the original
    Phase A in PR #238)
  - src/gpu/profile.h + the ScopedTimer/NvtxRange + Aggregator
    machinery from PR #238 (re-use it)
  - src/gpu/path_trace_kernel.cu (the AoS megakernel's launchers
    are now wrapped in ScopedTimer; Phase A.1 adds parallel SoA
    launchers)
  - benchmarks/wavefront/baseline.json (the numbers Phase A.1
    must not regress)

Phase A.1 goal:
  1. SoA path-state struct(s) for primary + secondary ray state
     (origin, direction, throughput, pdf, depth, RNG state).
     One CUDA-friendly layout per Laine 2013 §4 + PBRT v4
     wavefront integrator.
  2. An intersect queue: enqueue rays from launch, dequeue in
     a separate kernel that does only intersection. Behind
     `-DASTRORAY_WAVEFRONT_INTERSECT=ON` (default OFF).
  3. Smoke test that the SoA intersect path produces bit-
     identical first-hit positions to the AoS megakernel on
     the Cornell baseline. Behaviour parity is the gate; perf
     numbers come in Phase B.
  4. Re-run benchmarks/wavefront_baseline.py with the flag both
     ways; record both columns in baseline.json.

References (Apache-2.0, mirrorable with citation):
  - mmp/pbrt-v4 src/pbrt/wavefront/* — the canonical wavefront
    integrator architecture in C++/CUDA. Cite per-kernel.
  - intern/cycles/kernel/integrator/state.h — Cycles' SoA
    IntegratorState; cite for the field layout.
  - Laine, Karras, Aila — "Megakernels Considered Harmful:
    Wavefront Path Tracing on GPUs" (HPG 2013) §4. Already
    cited in pkg55 spec.

Constraints:
  - CLAUDE.md sections 2, 3, 6.
  - Default build path UNCHANGED — production renders see no
    SoA code unless the flag is on.
  - Do NOT touch the integrator interface or any plugin.
  - Bit-identical AoS output gated by CI.

When done:
  - pkg55 Phase A.1 subsection in the spec filled with measured
    numbers + bit-identity proof.
  - PR titled "feat(pkg55-A.1): SoA path state + intersect queue
    (gated)".
```

### 3.4 Codex (main directory) — pkg42 synchrotron emission

```
You are Codex working in the main Astroray directory. The
strategic gate released; pkg41 (Kerr validation) shipped first
out of the Pillar-4 queue. pkg42 is next: synchrotron emission
on top of the Kerr metric.

Read first:
  - .astroray_plan/packages/pkg42-synchrotron-emission.md (paste-
    ready spec)
  - .astroray_plan/packages/pkg40-kerr-metric.md + pkg41 spec for
    the metric-tensor + analytic-quantity surface pkg42 calls
    into.
  - The relevant src/ Kerr code paths.

Goal: implement synchrotron emission as a plugin emitter (or
volume contribution per the spec) that consumes the Kerr metric
quantities. Validate against the spec's reference (likely
Pandya 2016 fitting formulae or the GR-MHD synchrotron papers
the spec cites).

Constraints:
  - CLAUDE.md sections 1, 2, 3, 6.
  - This is Pillar 4 — cite the synchrotron / GRMHD papers per
    the spec; check license fence on any reference renderer
    consulted (RAPTOR/ipole/GYOTO are reference only, not
    mirrored).
  - DO NOT change pkg40/pkg41 code.

When done:
  - pkg42 spec status -> "implemented".
  - PR titled "feat(pkg42): synchrotron emission".
```

### 3.5 Codex (main directory + RTX, after #4) — pkg82 pkg54c gate variance characterisation

```
You are Codex on the RTX 5070 Ti box. The pkg78 bisect session
correctly refused the hardware bisect on §1 grounds — static
enumeration of 5aba401..fcbbbf2 (the 20-commit range) showed zero
commits touching the multiwavelength integrator path, so the
bisect would have been theatre. The diagnosis (posted on #237)
points at NVCC build-time non-determinism: the original 0.999263
sat 6.3e-4 above the 0.999 floor in the SSIM saturation regime,
and FMA reordering across rebuilds (pkg68/pkg70 added OptiX
detection in CMakeLists, which can flip the CUDA build context)
moves saturated SSIM by O(1e-4) without touching kernel logic.

pkg82 measures the variance and re-sets the gate (or bumps spp)
based on data. NO opinion-based gate changes.

Read first:
  - .astroray_plan/packages/pkg82-pkg54c-gate-variance.md (the
    full spec; Phase 1 + Phase 2 + Phase 3 procedures)
  - https://github.com/HendrikGC02/Astroray/issues/237 (the
    defect filing + pkg78 diagnosis comment)
  - tests/test_gpu_multiwavelength.py::test_visible_band_cpu_gpu_ssim
  - .astroray_plan/packages/pkg54c-gpu-jakob-hanika-upsampling.md
    (gate definition; will append Lessons section here)

Procedure (per spec):
  Phase 1 — intra-binary repeatability:
    Run the test 20× against the SAME .pyd. Record SSIM each
    run. Compute mean / stddev / min / max / unique-values.
    If stddev > 1e-6, you can stop early — gate floor decision
    falls out of Phase 1 alone (see spec).

  Phase 2 — cross-build variance (only if Phase 1 stddev ≈ 0):
    Five clean rebuilds with the variations specified in
    pkg82 spec §"Phase 2" (control × 2, OptiX-disabled,
    --fmad=false, RelWithDebInfo). One run each, record SSIM.

  Phase 3 — gate decision (Option A re-baseline OR Option B
  spp bump). Choose based on data, NOT preference.

Output:
  1. Phase 1 + Phase 2 measured tables in
     pkg54c-gpu-jakob-hanika-upsampling.md "Cross-build variance
     characterisation 2026-05-XX" Lessons section.
  2. ONE-LINE change in tests/test_gpu_multiwavelength.py —
     EITHER the gate floor OR the spp constant, never both.
  3. Closing comment on issue #237 with the table and the
     chosen resolution.
  4. PR titled "verify(pkg82): pkg54c gate variance + data-driven
     {gate floor | spp bump}".

Constraints:
  - CLAUDE.md sections 1, 4. This is THE template for every
    future numerical-gate decision in the project — get the
    methodology right.
  - NO kernel changes. Measurement only.
  - NO pytest.approx fudging. The gate is a number; we change
    the number based on data.
  - If Phase 2 shows variance > 1e-3 (large enough to hide a
    real regression), STOP and file a follow-up package on
    reducing CUDA build non-determinism — don't try to fix it
    here.
```

### 3.6 Codex (main directory) — pkg80 Blender `'auto'` integrator resolution (ship FIRST)

```
You are Codex working in the main Astroray directory. The project
owner hit a daily-workflow blocker 2026-05-10:

  RuntimeError: Astroray: integrator 'auto' does not support GPU
  (capability query failed: astroray: unknown plugin 'auto')

The Blender addon's integrator dropdown "Auto (Best Available)"
passes the literal string 'auto' to
astroray.integrator_capabilities() and set_integrator(), but
'auto' is not a registered plugin name.

Read first:
  - .astroray_plan/packages/pkg80-blender-auto-integrator-fix.md
    (the spec; resolution policy is defined there)
  - blender_addon/__init__.py — find _effective_integrator_name(),
    _configure_backend_for_context(), configure_backend() (the
    error path is in the user's traceback at lines 373/416/980/
    1075/1122)
  - tests/test_blender_backend_policy.py — existing addon-policy
    test pattern; mirror it

Fix:
  1. _effective_integrator_name(settings) must resolve 'auto' to a
     registered plugin per the spec policy:
       - If settings.integrator != 'auto', return it unchanged.
       - Else query astroray.integrator_registry_names().
       - Hardcoded preference: path_tracer →
         multiwavelength_path_tracer → other registered names.
       - Filter by device_mode capability via
         astroray.integrator_capabilities(name).gpu_supported when
         device_mode='gpu'.
       - Raise a clear RuntimeError if no plugin satisfies the
         requested device_mode.
  2. New test
     tests/test_blender_auto_integrator.py
     (or extend tests/test_blender_backend_policy.py) covering:
       - integrator='auto' + device_mode='cpu' → returns a registered name
       - integrator='auto' + device_mode='gpu' (CUDA build) →
         returns a GPU-capable registered name
       - integrator='auto' + device_mode='gpu' (CPU-only build) →
         raises a clear RuntimeError
       - integrator='path_tracer' (any non-auto) → returns it
         unchanged

Constraints:
  - CLAUDE.md sections 1, 2, 3.
  - DO NOT touch the C++ side. There is no 'auto' plugin and there
    shouldn't be one — the addon owns this UX choice.
  - DO NOT broaden scope to "best plugin per scene content" — out
    of scope (future polish).
  - The resolved name must come from astroray.integrator_registry_
    names() at runtime, not a hardcoded constant — the registry is
    the source of truth.

When done:
  - pkg80 spec status -> "done" with measured fix.
  - PR titled "fix(pkg80): resolve 'auto' integrator in addon
    before C++ calls".
```

### 3.7 Claude tech (worktree `pkg81-viewport-parity`) — Phase 1 + Phase 2

```
You are Claude Code in worktree .claude/worktrees/pkg81-viewport-parity,
branched from current main. The project owner reported 2026-05-10
that "moving the camera in rendered view is a bit of a slog vs
Cycles". The package counter says Pillar 5 is 27/28 done — but no
package has ever measured Astroray-vs-Cycles in the viewport
during pan/zoom. pkg81 fills that gap.

This session lands Phase 1 (harness) + Phase 2 (diagnosis). Phase 3
(fix) is a separate session, possibly routed through pkg55 Phase B
if H4 dominates.

Read first:
  - .astroray_plan/packages/pkg81-viewport-interactivity-parity.md
    (full spec; the five hypotheses you'll test)
  - .astroray_plan/packages/pkg52-persistent-viewport-session.md +
    pkg56-incremental-scene-sync.md (the existing viewport
    machinery you'll measure)
  - blender_addon/__init__.py — _sync_viewport_scene, view_update,
    view_draw (the entry points the harness drives)
  - benchmarks/wavefront/baseline.json (pkg55-A numbers — the
    starting point for H4)
  - intern/cycles/blender/session.cpp — BlenderSession::view_update
    / view_draw / sample loop (Apache-2.0; reference for
    progressive-continuation policy)

Phase 1 — harness (~3 days):
  1. New benchmarks/viewport_parity/run.py: scripted Blender
     session that loads a parameterised scene (10k / 100k / 1M
     tris), drives a deterministic camera pan/zoom/orbit
     sequence, records per-frame wall time at view_draw level
     PLUS a finer breakdown using the pkg56-A ring buffer +
     pkg55-A profile.h instrumentation.
  2. Same harness for Cycles by switching render_engine —
     measure on the same hardware, same scene, same camera path,
     matched spp + denoiser settings.
  3. Outputs benchmarks/viewport_parity/{date}.json + summary.html.
  4. Commit fixture .blends under
     benchmarks/viewport_parity/scenes/ (small enough to commit;
     synthetic_min-style or imported via pkg76).
  5. tests/test_viewport_parity_harness.py — smoke test that the
     harness runs against a tiny scene without launching Blender
     (uses the persistent viewport in-process).

Phase 2 — diagnosis (~3 days):
  Run the harness. Test each hypothesis IN ORDER and record:

  H1: pkg56-C dispatches more uploaders than necessary during pan
       — count uploader calls per frame from the ring buffer
  H2: progressive accumulation resets every pan tick instead of
       continuing — sample-counter trace + visual at 1/2/4 spp
  H3: OIDN denoising blocks the frame loop — A/B with the pass on
       vs off
  H4: megakernel register pressure (158 regs/thread) caps first-
       pixel latency — A/B Astroray-CPU vs Astroray-CUDA on the
       same scene
  H5: view_draw setup overhead is large — first-vs-Nth-draw delta

  Output: .astroray_plan/docs/pkg81-diagnosis.md identifying the
  dominant gap with measured numbers, ranked by how much frame
  time each hypothesis owns.

Constraints:
  - CLAUDE.md sections 1, 2, 3, 6.
  - NO source fixes in this session — Phase 1 + 2 only. Phase 3
    is a separate package or routes through pkg55 Phase B.
  - Honest numbers — if Astroray is 10× slower than Cycles, the
    diagnosis says 10×, not "comparable".
  - Cycles reference reads only, no code copied. Cite per
    intern/cycles/* path in code comments.
  - The harness must run repeatably on the project owner's RTX
    5070 Ti / Windows MSVC build_cuda. Document any hardware
    assumptions in the run.py docstring.

When done:
  - pkg81 spec Phases 1 + 2 checkboxes ticked; Phase 3 stays
    open with the dominant-bottleneck hypothesis named.
  - PR titled "feat(pkg81): viewport-parity harness + Cycles A/B
    diagnosis (Phase 3 fix open)".
```

### 3.8 Codex (main directory, after #7) — pkg76 CSV row population

```
You are Codex on the RTX 5070 Ti box. pkg76 (PR #240) shipped
the .blend importer code path but explicitly deferred the three
new parity-baseline CSV rows because they need a reference run
on real hardware. With pkg73 fixed and the denoiser path healthy
again, run them now.

Read first:
  - benchmarks/cycles-parity/README.md
  - benchmarks/cycles-parity/scenes/manifest.toml (Monster is
    correctly dropped; Classroom / Junkshop / BMW27 are the
    targets)
  - scripts/run_parity.py (the harness; pkg76 wired the
    importer in)
  - .astroray_plan/packages/pkg76-blend-importer-parity-scope.md
    "Lessons" section

Step 1 — populate the .blend cache if not already there
(`benchmarks/cycles-parity/scenes/cache/`).

Step 2 — run scripts/run_parity.py for each of Classroom,
Junkshop, BMW27 against Cycles-CPU EXR reference at the
manifest's reference SPP. Acceptance per spec: SSIM ≥ 0.85
(parity-scope, not Cornell's 0.95).

Step 3 — append rows to benchmarks/cycles-parity/results.csv
(or whichever dated CSV the harness writes). Commit them.

Step 4 — if any of the three scenes fails the 0.85 gate,
report which channel(s) (geometry / material / light /
camera) drove the miss. Do NOT re-baseline the gate.

Constraints:
  - CLAUDE.md sections 1, 4.
  - Doc + CSV + no source touched.
  - PR titled "verify(pkg76): Classroom/Junkshop/BMW27 parity
    rows on RTX".
```

---

## 4. Coordination

**File-touching map** (zero hard collisions):

| Session | Files |
|---|---|
| pkg80 (auto integrator) | `blender_addon/__init__.py` (small), new test, pkg80 spec, STATUS.md |
| pkg73 diag capture | comment on PR #241; doc-only Lessons append to pkg73 spec |
| pkg73 fix | `plugins/passes/optix_denoiser.cpp` (+ remove diag prints), `include/raytracer.h` (remove diag prints), maybe `module/blender_module.cpp`, pkg73 spec, STATUS.md |
| pkg81 Phase 1+2 | new `benchmarks/viewport_parity/*`, new fixture `.blend`s, new test, new `.astroray_plan/docs/pkg81-diagnosis.md`, pkg81 spec, STATUS.md |
| pkg55 Phase A.1 | new `src/gpu/wavefront/*.cu` + headers, `src/gpu/path_trace_kernel.cu` (alt launcher behind flag), CMake guard, new test, `benchmarks/wavefront/baseline.json` (extra column), pkg55 spec, STATUS.md |
| pkg42 synchrotron | new `plugins/emitters/synchrotron.cpp` (or volumes), maybe Kerr-side accessors, new tests, pkg42 spec, STATUS.md |
| pkg82 (variance) | `tests/test_gpu_multiwavelength.py` (one-line gate or spp change), pkg54c spec Lessons append, issue #237 close comment |
| pkg76 CSV | `benchmarks/cycles-parity/results.csv` only |

**Conflict points:**

1. **`STATUS.md`** — five sessions touch it (pkg80, pkg73 fix,
   pkg81, pkg55-A.1, pkg42). Same merge race as before; rebase +
   manual STATUS.md resolution preserving all rows.
2. **`include/raytracer.h`** — pkg73 fix removes the diag prints;
   pkg55 Phase A.1 may add SoA-side hooks. Different sections.
3. **`blender_addon/__init__.py`** — only pkg80 touches it.
   Conflict-free.

**Recommended merge order:** pkg80 (small, daily-blocker) → pkg73
diag capture (comment, no PR) → pkg73 fix (small, gate-closing) →
pkg78 bisect (small) → pkg76 CSV (doc/data only) → pkg81 Phase 1+2
(medium, harness + diagnosis only — no behaviour change) → pkg55
Phase A.1 (medium, CI must show bit-identical AoS path) → **pkg42
last** (largest, Pillar 4).

---

## 5. After Round 6 lands

When Round 6 closes:

- **pkg80** done; daily Blender workflow no longer crashes on
  GPU + Auto integrator.
- **pkg73** fully done; the entire denoiser story (pkg33 → pkg68 →
  pkg69 → pkg70 → pkg72 → pkg73) is closed.
- **pkg81 Phase 1 + 2** done; first honest Astroray-vs-Cycles
  viewport numbers exist. The Pillar-5 fitness-for-use claim is
  finally measurable. Phase 3 routing decided (own fix vs. pkg55
  Phase B).
- **pkg55 Phase A.1** done; SoA path-state + intersect queue in
  tree behind a flag. Phase B's per-material shade-kernel work has
  a real scaffolding to build on.
- **pkg42** done; second Pillar-4 deliverable shipped. Synchrotron
  emission available on Kerr backgrounds.
- **pkg76 CSV** populated; the 5-scene parity baseline is finally
  4 rows wide (Cornell + Classroom + Junkshop + BMW27; Monster
  correctly dropped).
- **#237** diagnosed (pkg78) and resolved (pkg82) — gate either re-set with measured headroom or spp bumped, both options data-driven.

Then **Round 7**:

- **pkg81 Phase 3** — the targeted fix(es) the diagnosis pointed
  at. May be a small standalone Claude-tech session OR may route
  entirely through pkg55 Phase B if H4 (register pressure) won.
- **Codex** continues Pillar 4 — pkg43 (slim disk) + pkg44 (ADAF)
  in series.
- **Claude tech** picks up **pkg55 Phase B** — the per-material
  shade kernel split (the place the 158 regs/thread cliff
  actually breaks; possibly the pkg81 Phase 3 fix).
- Optional Codex side track: pkg47/48/49 (FITS / HDF5 / SPH
  loaders) once the dust settles on the emission-model trio.

After Round 7:

- Pillar 4 has three emission models (synchrotron, slim disk,
  ADAF) + Kerr metric + validation. Real astrophysical scenes
  become renderable end-to-end.
- pkg55 Phase B reduces register pressure measurably; baseline.json
  shows two columns (AoS megakernel vs SoA per-material), and the
  cliff documented in PR #238 is the comparison anchor.
- Pillar 5 essentially feature-complete; remaining work is the
  ongoing-opportunistic polish bullets in `production.md`.

Bump this report when pkg73 fix lands or when pkg42 lands —
those are the next major queue movements.
