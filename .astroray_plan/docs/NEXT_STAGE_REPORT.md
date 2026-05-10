# Astroray Next Stage Report

**Date:** 2026-05-10 (mid-Round-5 — pkg56-C and pkg74-3 landed; **strategic gate released; Pillar 4 thawed**)
**Prepared by:** Claude (Anthropic Code, Sonnet 4.5 in Max 5x)
**Scope:** Remainder of Round 5 + first Pillar-4 thaw work. The
gate-releasing package (pkg56 Phase C) and the Round 4 carryover
(pkg74 Phase 3) have already landed since the Round 5 report opened.
Four Round-5 sessions remain (pkg76, pkg55-A, pkg78, verifier), and
the post-gate Pillar-4 queue is now spawnable.

> Strategic gate: **RELEASED 2026-05-10** by PR #233 (pkg56 Phase C).
> Pillar 4 sessions are now spawnable. Strategy in
> [`ROADMAP.md`](ROADMAP.md), status in [`STATUS.md`](STATUS.md).

---

## 1. Current state (one screen)

**Done since this report opened (mid-Round-5):**

- **pkg56 Phase C** depsgraph-driven dispatch shipped — per-domain
  uploaders dispatched from `depsgraph_update_post`, idle frames at
  ≤5 ms p99 on the 99k-tri Phase A scene. **Strategic gate released.**
  PR #233.
- **pkg74 Phase 3** interactive HTML showcase + weekly self-hosted CI
  workflow shipped (Round 4 carryover cleared). PR #232.

**Done in Round 4 (the round before this report):**

- **pkg73** OptiX TEMPORAL_AOV denoiser shipped — `OPTIX_DENOISER_MODEL_KIND_TEMPORAL_AOV`
  upgrade path with motion + albedo + normal guides, prev-output ping-
  pong, destroy-and-recreate handle on kind transition. Static cameras
  fall back to AOV cleanly (no prev-output memory cost). PR #228.
  Cycles `intern/cycles/device/optix/device_impl.cpp` Apache-2.0
  consulted as design reference. Hardware verifier still pending.
- **pkg56 Phase B** uploadScene split — `uploadGeometry`,
  `uploadMaterials`, `uploadLights`, `uploadEnvironment` per-domain
  bindings + `update_object_transform` BVH-refit fast path. Cycles
  `intern/cycles/blender/sync.cpp` Apache-2.0 cited for the per-domain
  pattern. PR #229. **Phase A baseline 129.92 → 183.30 ms** as the
  measurement target for Phase C.
- **pkg64 Phase 3** SMS folded into default `path_tracer` — shared
  `astroray::manifold::runSMSAttempt` helper at
  `include/astroray/manifold/sms_attempt.h`, per-bounce hook through
  `Renderer::pathTraceSpectral` as a `std::function<...>`, per-object
  `is_caustic_caster` opt-in (Cycles UX mirror), Blender addon
  checkbox, MIS-disjoint additive combination with NEE. PR #230.
  Phase 1 + 2 acceptance tests still pass — refactor is provably
  behaviour-preserving.
- **pkg76 spec** filed — Astroray `.blend` importer (parity scope only),
  unblocks 3 of the 5 pkg71 baseline scenes. Drops the UDIM monster
  from the manifest (Cycles itself errors "no camera" on
  `udim-monster.blend`). PR #227.
- **pkg72 + pkg64-2 hardware verifier** re-baselined on RTX 5070 Ti /
  Windows MSVC `build_cuda`: **6/6 motion-vector tests pass in 0.19 s**;
  pure-translation pan shows **100 % of hit pixels with `motion.x > 0`**
  and exact-zero motion on sky pixels (OptiX flow contract confirmed
  end-to-end). pkg64-2 spectral SMS PSNR delta **+8.83 dB matches
  implementer baseline to 0.00 dB**. PR #226.
- Test bootstrap: `tests/runtime_setup.py` deduped
  `os.add_dll_directory` calls — pytest collection went from
  "0 collected, 11 errors" → **801 collected**. PR #225.

**Open pickup pool (remainder of Round 5 + post-gate Pillar 4):**

| Pkg | Title | Effort | Status |
|---|---|---|---|
| **pkg76** impl | Astroray .blend importer | ~1–2 weeks | Spec landed (PR #227); ready to implement |
| **pkg55** Phase A | Wavefront SoA instrumentation | ~1 week | Unblocked (pkg56 + pkg64 baselines exist) |
| pkg73 verifier | OptiX TEMPORAL_AOV CUDA hardware re-baseline | ~1 hour | Post-pkg73 follow-up |
| pkg64-3 verifier | Default-integrator SMS PSNR + walltime on RTX | ~1 hour | Post-pkg64-3 follow-up |
| pkg78 (new) | pkg54c SSIM gate re-baseline (post-pkg75 detail-preservation drift, 0.999263 → 0.9986 at spp=8192) | ~½ day | Surfaced post-pkg75 verifier; visual diff confirmation gate |
| **pkg41** | Kerr metric validation | ~1 week | **Newly unblocked by gate release**; Codex-paste-ready |
| pkg42 / 43 / 44 | Synchrotron / slim disk / ADAF (Pillar 4) | weeks each | Newly unblocked; Codex-paste-ready specs queued |
| pkg55 Phases B + C | Wavefront SoA migration proper | 8–12 weeks | After Phase A measured baselines |
| pkg67 | Metric-aware path tracer | ~1 month | Now unblocked alongside Pillar 4 (revisit when pkg40 + pkg55 maturity is in place) |

**Pillar 4 (THAWED 2026-05-10):** pkg40 Kerr metric done; pkg41 Kerr
validation paste-ready; pkg42–51 specs queued. Codex may pick up
pkg41 first; pkg42 / 43 / 44 in parallel as bandwidth allows.

---

## 2. Recommended next deployable set (Round 5 remainder + Pillar 4 thaw)

Five sessions, all parallel-safe:

| # | Agent | Worktree / location | Package | Effort |
|---|---|---|---|---|
| 1 | Claude tech | `pkg76-impl` (new) | pkg76 — Astroray .blend importer (parity scope) | ~1–2 weeks |
| 2 | Claude tech | `pkg55-phase-a` (new) | pkg55 Phase A — wavefront SoA instrumentation pass (no behaviour change) | ~1 week |
| 3 | Codex | main directory | **pkg41 Kerr metric validation** (Pillar 4, newly unblocked) | ~1 week |
| 4 | Codex (after #3 lands) | main directory | pkg78 — pkg54c SSIM gate re-baseline + visual diff vs pkg75 reference | ~½ day |
| 5 | CUDA verifier | hardware | re-baseline pkg73 OptiX TEMPORAL_AOV inter-frame variance + pkg64-3 default-integrator SMS PSNR + walltime on RTX 5070 Ti | ~1 hour |

Sessions 1, 2, 5 spawn at once. Session 3 starts immediately;
session 4 follows 3 (Codex serializes in the main directory).

Round 5 closes when:
- pkg76 implementation merged (Classroom / Junkshop / BMW27 pkg71 rows possible)
- pkg55 Phase A merged (wavefront baselines measured; Phases B + C unblocked)
- pkg41 Kerr validation merged (first post-gate Pillar-4 deliverable)
- pkg78 verified or closed (pkg54c gate re-set against post-pkg75 reality)
- pkg73 + pkg64-3 hardware-verified

Then **Round 6** continues Pillar 4 (pkg42 / 43 / 44 in parallel as
Codex bandwidth allows) and starts **pkg55 Phase B** — the wavefront
SoA migration proper.

---

## 3. Drop-in prompts per agent

### 3.1 Claude tech (worktree `pkg76-impl`) — Astroray .blend importer

```
You are Claude Code in worktree .claude/worktrees/pkg76-impl,
branched from current main. Implement pkg76 end to end. The spec
landed in PR #227.

Read first:
  - .astroray_plan/packages/pkg76-blend-importer-parity-scope.md
    (the full spec, including the parity-scope cap and the explicit
    Cycles features we DO NOT implement)
  - .astroray_plan/docs/blend-importer-research.md (license analysis,
    parser pick: blender_python_io / bpy in --background)
  - blender_addon/__init__.py (the existing convert_objects path —
    same Astroray-side data model the importer must produce)
  - benchmarks/cycles_parity/run.py (the pkg71 driver; the importer
    feeds it)

Goal: produce `scripts/parity/import_blend.py` that takes a
`.blend` path + a parity-scope manifest entry, runs `blender
--background --python` to extract scene data, and writes a JSON
scene description that the existing pkg71 harness consumes to
produce a comparable Astroray render. Acceptance: Classroom,
Junkshop, BMW27 pkg71 rows produce SSIM numbers vs Cycles-CPU EXR.

Constraints (from spec):
  - Parity-scope only: Principled BSDF (subset), point/area/sun
    lights, world env, camera. No volumes, no hair, no SSS, no
    UDIMs (the dropped monster scene's blocker).
  - DO NOT depend on bpy at runtime in the addon path — bpy is only
    invoked from the import script as a subprocess.
  - Cite all Cycles parity-mapping decisions in code comments
    ("matches intern/cycles/blender/shader.cpp:set_principled_*").
  - CLAUDE.md sections 2, 3, 6.

When done:
  - pkg76 spec status -> "implemented".
  - benchmarks/cycles_parity/results.csv extended with at least 3
    new rows.
  - PR titled "feat(pkg76): Astroray .blend importer (parity scope)".
```

### 3.2 Claude tech (worktree `pkg55-phase-a`) — wavefront SoA instrumentation

```
You are Claude Code in worktree .claude/worktrees/pkg55-phase-a,
branched from current main. Implement pkg55 Phase A.

Read first:
  - .astroray_plan/packages/pkg55-wavefront-soa.md (full spec)
  - src/gpu/cuda_renderer.cu (current AoS path — the measurement
    target)
  - benchmarks/showcase/* (existing perf-stats infrastructure
    pkg74 ships — re-use it)

Phase A is INSTRUMENTATION ONLY. No SoA conversion, no kernel
splits, no behaviour change. Goal: produce a per-bounce, per-
warp, per-kernel timing + occupancy + register-pressure dump for
the current AoS megakernel that Phases B + C will compare against.

Implementation outline:
  1. CUDA events around each major kernel section in cuda_renderer.cu
     (intersection, shading, NEE, accumulation). Conditional on
     ASTRORAY_PROFILE=1 env var so production renders pay nothing.
  2. NVTX ranges for nsight-compute consumption.
  3. Python harness benchmarks/wavefront_baseline.py that runs the
     Cornell + Classroom (post-pkg76) scenes at fixed spp and
     records results in benchmarks/wavefront/baseline.json.
  4. Acceptance: baseline.json populated with measured numbers for
     at least 2 scenes; the data is what Phases B + C must beat.

Reference (Apache-2.0):
  - intern/cycles/device/cuda/queue.cpp — Cycles' wavefront queue
    instrumentation pattern. Cite, do not copy code yet.
  - PBRT v4 wavefront integrator profiler hooks.

Constraints:
  - Zero behaviour change. CI must show bit-identical outputs for
    the ASTRORAY_PROFILE=0 default path.
  - CLAUDE.md sections 2, 3, 6.

When done:
  - pkg55 Phase A subsection in the spec filled with measured numbers.
  - PR titled "feat(pkg55-A): wavefront SoA baseline instrumentation".
```

### 3.3 Codex (main directory) — pkg41 Kerr metric validation (first Pillar-4 thaw deliverable)

```
You are Codex working in the main Astroray directory. The
strategic gate released on 2026-05-10 with PR #233 (pkg56 Phase C);
Pillar 4 is now thawed. pkg41 is the first paste-ready Pillar-4
deliverable.

Read first:
  - .astroray_plan/packages/pkg41-kerr-validation.md (the spec —
    paste-ready, has been queued since pre-gate)
  - .astroray_plan/packages/pkg40-kerr-metric.md (pkg40 landed
    earlier; pkg41 is its validation harness)
  - the relevant Kerr code paths in src/ that pkg40 introduced

Goal: implement the validation harness specified in pkg41 — closed-
form geodesic comparisons, image-plane regression vs published
GR ray-tracer reference (GYOTO / RAPTOR / ipole as cited in the
spec), and the acceptance gates defined in the spec.

Constraints:
  - CLAUDE.md sections 1, 2, 3, 6.
  - This is Pillar 4. Cite the GR papers + reference renderers per
    the existing Kerr research notes in .astroray_plan/docs/.
  - DO NOT change the pkg40 metric code itself — pkg41 is validation
    only. If the harness surfaces a real defect, file it as a follow-
    up package and STOP.

When done:
  - pkg41 spec status -> "implemented".
  - PR titled "feat(pkg41): Kerr metric validation harness".
```

### 3.4 Codex (main directory, after #3) — pkg78 SSIM gate re-baseline

```
You are Codex in the main Astroray directory. pkg78 is a small
follow-up surfaced by the post-pkg75 verifier run.

Symptom: pkg54c gate drifted from SSIM 0.999263 to 0.9986 at
spp=8192 against the visible-band reference. The drift coincides
with pkg75 (one-line `r.normal = rec.normal` fix in
plugins/integrators/spectral_path_tracer.cpp::sampleFull) — the
same detail-preservation mechanism documented in PR #223 for the
OIDN noise-ratio metric.

Read first:
  - .astroray_plan/packages/pkg54c-spectral-rgb-jakob-hanika.md
    (the gate definition)
  - PR #219 + #223 (the pkg75 fix and noise-ratio re-baseline)
  - tests/test_spectral_visible_band.py (the gate test)

Goal:
  1. Render the current spp=8192 visible-band reference with HEAD
     and visually compare against the saved reference. Confirm the
     drop is detail preservation (sharper, not noisier).
  2. If confirmed: re-save the reference + drop the gate floor to
     0.998. Document in the spec that the previous reference was
     pre-pkg75.
  3. If NOT confirmed: file pkg78 as a real defect and STOP — do
     not change the gate.

Constraints:
  - CLAUDE.md sections 1, 3, 4. This is a gate-tightening decision,
     so verification before the gate change is mandatory.

When done:
  - PR titled either "verify(pkg78): pkg54c SSIM re-baseline post-pkg75"
    (re-save case) or "fix(pkg78): pkg54c regression investigation"
    (real defect case).
```

### 3.5 CUDA verifier (hardware session) — pkg73 + pkg64-3 RTX re-baseline

```
You are the CUDA verifier on the RTX 5070 Ti / Windows MSVC
build_cuda branch. Run the following on real hardware and append
Lessons-style sections to the relevant package specs.

  1. tests/test_optix_denoiser_temporal.py — full run against the
     OptiX 9.1.0 + CUDA 12.8 build. Record:
       - inter-frame variance reduction pkg73 (TEMPORAL_AOV) vs
         pkg70 (AOV) on the 10-frame camera-pan sequence.
       - first-frame fallback behaviour (no prev-output buffer).
       - kind-transition reset (HDR -> AOV -> TEMPORAL_AOV cycle).
     Acceptance: ≥30% inter-frame variance reduction per pkg73 spec.
     Append section "Hardware verification 2026-05-10" to
     .astroray_plan/packages/pkg73-optix-temporal-denoiser.md.

  2. tests/test_pkg64_phase3_default_integrator.py +
     tests/test_pkg64_phase3_no_regression.py — full run.
     Record:
       - SMS receiver-energy ratio (≥1.10× the no-caustics baseline).
       - per-bounce walltime overhead with empty hook (≤5%).
       - PSNR floor non-regression (≥-0.5 dB).
     Append section "Phase 3 hardware verification 2026-05-10" to
     .astroray_plan/packages/pkg64-spectral-caustics.md.

Constraints:
  - Doc-only PR. No source touched.
  - PR titled "verify(pkg73, pkg64-3): hardware re-baseline".
```

---

## 4. Coordination

**File-touching map** (zero hard collisions across sessions):

| Session | Files |
|---|---|
| pkg76 impl | new `scripts/parity/import_blend.py`, `benchmarks/cycles_parity/run.py` (importer hookup), `benchmarks/cycles_parity/results.csv`, pkg76 spec, STATUS.md |
| pkg55 Phase A | `src/gpu/cuda_renderer.cu` (instrumentation only, gated), new `benchmarks/wavefront_baseline.py`, pkg55 spec, STATUS.md |
| pkg41 (Pillar 4) | `src/` Kerr-validation harness as specified, new tests, pkg41 spec, STATUS.md |
| pkg78 verifier | reference PNG re-save in `tests/reference/` + pkg54c spec note (or no change if defect path) |
| pkg73 + pkg64-3 verifier | doc-only Lessons appends to pkg73 + pkg64 specs |

**Conflict points to watch:**

1. **`STATUS.md`** — five sessions all touch it. Same three-way merge
   race we keep hitting. Mitigation: rebase + manual STATUS.md
   resolution preserving all rows.

2. **`src/gpu/cuda_renderer.cu`** — only pkg55 Phase A touches it
   this round (gated CUDA events / NVTX ranges). pkg41 is CPU-side
   GR validation; should be conflict-free.

**Recommended merge order:** verifier (doc-only) → pkg78 (small) →
pkg41 Kerr validation (Codex, focused) → pkg55 Phase A (no behaviour
change, low risk) → pkg76 impl (largest, last).

---

## 5. After Round 5 lands

Already in the bag (mid-Round-5):

- **pkg56** done end-to-end (Phases A + B + C). Viewport idle ≤ 5 ms.
- **pkg74** done end-to-end (Phases 1 + 2 + 3). Showcase self-
  publishes weekly; HTML dashboard ships.
- **Strategic gate released. Pillar 4 thawed.**

When the remainder of this round lands:

- **pkg76** implementation done. Classroom / Junkshop / BMW27 pkg71
  rows have measured Astroray-vs-Cycles SSIM numbers.
- **pkg55 Phase A** done. Wavefront baselines measured; Phases B + C
  unblocked with concrete numbers to beat.
- **pkg41** done. First Pillar-4 deliverable post-gate; Kerr metric
  has its validation harness.
- **pkg73 + pkg64-3** hardware-verified.
- **pkg78** resolved (gate re-baselined or real defect filed).

Then **Round 6**:

- **Codex** continues Pillar 4 — pkg42 / 43 / 44 paste-ready specs
  (synchrotron / slim disk / ADAF) in parallel as bandwidth allows.
- **Claude tech** starts **pkg55 Phase B** (the wavefront SoA
  migration proper begins — multi-month, but unlocks measurable GPU
  parity claims with Cycles X for the eventual paper).
- **pkg67 metric-aware path tracer** unblocks once pkg40 + pkg55
  maturity is in place.

After Round 6:

- Pillar 4 actively shipping (pkg41 + early pkg42–44).
- pkg55 Phase B in progress (wavefront SoA refactor).
- Pillar 5 essentially feature-complete; remaining work is the
  ongoing-opportunistic polish bullets in `production.md`.

Bump this report when pkg76 or pkg41 lands — those are the next major
queue movements.
