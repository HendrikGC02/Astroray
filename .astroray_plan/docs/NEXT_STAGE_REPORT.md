# Astroray Next Stage Report

**Date:** 2026-05-11 (post-Round-6 — pkg42 + pkg73 fix + pkg80 + pkg81 P1+P2 + pkg55 Phase A.1 all landed; **denoiser story closed end-to-end**; Pillar 4 actively shipping; viewport-parity gate now formally owned by pkg55 Phase B)
**Prepared by:** Claude (Anthropic Code, Sonnet 4.5 in Max 5x)
**Scope:** Round 7. Round 6 closed on planned scope. The next round is
shaped by one big package and a long Pillar-4 tail:

(a) **pkg55 Phase B** — per-material shade kernels (~4–6 weeks Claude
    tech). The single most consequential package on the roadmap until
    Pillar 4 is feature-complete: it owns the viewport-parity gate
    pkg81 quantified, breaks the 158 regs/thread cliff pkg55-A.0
    measured, and unblocks Phase C megakernel removal.

(b) **Pillar 4 continuation** — pkg43 (slim disk) + pkg44 (ADAF), in
    series, on the VolumetricEmission interface pkg42 just established.

(c) **Round-6 leftovers** — four small ½–1-day pickups carried
    forward (pkg82, pkg76 CSV, pkg83, pkg84).

> Strategic gate: **RELEASED 2026-05-10** by pkg56 Phase C; Pillar 4
> has been actively shipping since. Strategy in
> [`ROADMAP.md`](ROADMAP.md), status in [`STATUS.md`](STATUS.md).

---

## 1. Current state (one screen)

**Done since the previous report (Round 6 closure):**

- **pkg42 synchrotron emission** (PR #245) — first second-wave
  Pillar-4 deliverable. VolumetricEmission interface + Pandya 2016
  power-law/thermal fits + `synchrotron_jet` plugin with a bipolar
  jet geometry + Blender jet controls + 9 focused tests.
- **pkg80 Blender `'auto'` integrator fix** (PR #246) —
  `_effective_integrator_name` now resolves `'auto'` against the
  runtime registry filtered by device-mode capability. Daily-
  workflow GPU crash is gone.
- **pkg73 OptiX TEMPORAL_AOV fix** (PR #249) — denoiser story closes
  end-to-end. Hardware-verified on RTX 5070 Ti / OptiX 9.1 / CUDA
  12.8: **53.1 % inter-frame variance reduction (gate ≥30 %), 5/5
  tests pass**. Two compounding root causes both fixed: plugin's
  `OptixDenoiserParams::temporalModeUsePreviousLayers` never set,
  AND the test's AOV reference silently upgraded to TEMPORAL_AOV by
  sub-pixel float dust in `projectToPrevPixel`.
- **pkg81 Phase 1+2 viewport-parity harness + diagnosis** (PR #248)
  — first honest Astroray-vs-Cycles viewport numbers. Harness, 16-
  config sweep, `pkg81-diagnosis.md`. Headline: **CUDA 104 ms vs
  CPU 58 ms on 100k-tri load** on the user's RTX 5070 Ti. H4
  (megakernel register pressure — pkg55-A.0's 158 regs/thread
  cliff) dominates. **Phase 3 routes to pkg55 Phase B** per spec
  escape; smaller H2/H5 findings split out as **pkg83** + **pkg84**.
- **pkg55 Phase A.1 SoA path state + intersect queue** (PR #250) —
  SoA struct + init/intersect kernels gated behind
  `-DASTRORAY_WAVEFRONT_INTERSECT=ON` (default OFF). Bit-identical
  AoS megakernel output verified. Foundation for Phase B's per-
  material shade kernels.
- **pkg82 spec filed** (PR #247) — variance characterisation that
  turns pkg78's bisect-refusal diagnosis into a data-driven gate
  decision for issue #237. Carried into Round 7.
- **pkg83 + pkg84 specs filed** (PR #253) — small addon-only fixes
  for pkg81's H2 (accumulator-reset-per-pan) and H5 (12 s cold
  start) findings. Carried into Round 7.

**Open pickup pool (Round 7 + Round 8):**

| Pkg | Title | Effort | Status |
|---|---|---|---|
| **pkg55 Phase B** | Per-material shade kernels — owns the viewport-parity acceptance gate (CUDA pan-frame p99 ≤ 1.2× Cycles-CUDA on the pkg81 harness scene) | ~4–6 weeks | **The Round 7 marquee.** Built on Phase A.1's SoA scaffold; closes the user-facing competitive parity claim. |
| **pkg43** | Slim disk accretion model (Pillar 4) | ~2 weeks | Codex-paste-ready spec; pkg42 VolumetricEmission interface available |
| **pkg44** | ADAF accretion model (Pillar 4) | ~2 weeks | After pkg43 (same Codex serialisation as Round 6's pkg42→pkg43→pkg44 plan) |
| pkg55 Phase C | Megakernel removal | ~3 weeks | After Phase B |
| **pkg82** | pkg54c gate variance characterisation (intra-binary + cross-build SSIM distribution; data-driven gate) | ~1 day on RTX | Carried from Round 6; closes issue [#237](https://github.com/HendrikGC02/Astroray/issues/237) |
| **pkg76 CSV** | Classroom / Junkshop / BMW27 baseline rows on RTX | ~½ day on RTX | Carried from Round 6; pkg73 fixed → denoiser path is healthy → numbers are now meaningful |
| **pkg83** | Progressive accumulation continuation across camera changes (H2 from pkg81) | ~½ day | Addon-only; user-facing UX win independent of pkg55 Phase B |
| **pkg84** | CUDA kernel pre-warm at viewport start (H5 from pkg81) | ~½ day | Addon-only; moves the 12 s cold-start to a moment the user expects |
| pkg45 / pkg46 | CLOUDY emissivity tables / HII region emission (Pillar 4) | weeks each | After pkg43+pkg44; specs already paste-ready |
| pkg47 / 48 / 49 | FITS / HDF5 / SPH loaders (Pillar 4 data import) | weeks each | Optional Round 7+ side track; specs queued |
| pkg79 (tiny) | ReSTIR `test_spatial_reduces_mse` flake (margin 0.000004) | ~½ day | Surfaced by PR #236 CI; recurring noise-floor failure |
| pkg50 / 51 | Weak lensing / synthetic telescope post-process (Pillar 4) | weeks each | Late-Pillar-4; deferred behind pkg43–48 |
| pkg67 | Metric-aware path tracer | ~1 month | Now plausible alongside Pillar 4; revisit once pkg40 + pkg55 maturity in place |

---

## 2. Recommended next deployable set (Round 7)

Six sessions, parallel-safe:

| # | Agent | Worktree / location | Package | Effort |
|---|---|---|---|---|
| 1 | Claude tech | `pkg55-phase-b` (new) | **pkg55 Phase B** — per-material shade kernels. Owns the viewport-parity gate. The round's marquee work. | ~4–6 weeks |
| 2 | Codex | main directory | **pkg43 slim disk accretion model** (Pillar 4) | ~2 weeks |
| 3 | Codex (after #2) | main directory | **pkg44 ADAF accretion model** (Pillar 4) | ~2 weeks |
| 4 | Codex (small) | main directory | **pkg83** progressive accumulation continuation (H2 fix) | ~½ day |
| 5 | Codex (small) | main directory | **pkg84** CUDA kernel pre-warm (H5 fix) | ~½ day |
| 6 | Codex (RTX) | hardware | **pkg82** + **pkg76 CSV** combined RTX session — both small, both hardware-only, both ~½–1 day. Run them back-to-back in the same Codex sitting on the RTX box. | ~1.5 days |

Sessions 1, 2 spawn at once. 3 chains after 2 in the main directory.
4 + 5 are tiny addon-side fixes that fit in any quiet Codex
sitting; either 4 or 5 first, the other right after. Session 6 is a
one-time RTX session that closes both #237 (pkg82) and the deferred
pkg76 CSV rows in one go.

The ReSTIR flake (pkg79) is small enough to fold into whichever
Codex session is least busy.

Round 7 closes when:
- pkg55 Phase B merged + viewport-parity acceptance gate cleared
  (CUDA pan-frame p99 ≤ 1.2× Cycles-CUDA) — **this is the round's
  defining moment**
- pkg43 + pkg44 merged (Pillar 4 has 4 emission models: synchrotron
  + slim disk + ADAF + the existing thermal/blackbody plumbing)
- pkg83 + pkg84 merged (viewport feels noticeably smoother on the
  small-bug-fix axis even before Phase B's big win lands)
- pkg82 + pkg76 CSV done (issue #237 closed; pkg71 baseline 4 rows
  wide instead of 1)

Then **Round 8** picks up: **pkg55 Phase C** (megakernel removal —
the architectural cleanup once Phase B is shipping); **pkg45**
(CLOUDY emissivity tables) + **pkg46** (HII region emission) for
Pillar 4 continuation; possibly the start of pkg47/48/49 data
loaders if astrophysical scene scope is the next constraint.

---

## 3. Drop-in prompts per agent

### 3.1 Claude tech (worktree `pkg55-phase-b`) — Wavefront per-material shade kernels

```
You are Claude Code in worktree .claude/worktrees/pkg55-phase-b,
branched from current main. This is the longest-running package
in the project's near-term roadmap (~4–6 weeks). It also owns the
user-facing viewport-parity claim that pkg81 measured: pkg55 Phase
B isn't done until the wavefront `path_tracer` clears CUDA pan-
frame p99 ≤ 1.2× Cycles-CUDA on the pkg81 harness reference scene.

Read first:
  - .astroray_plan/packages/pkg55-wavefront-soa-refactor.md
    (full spec; Phase A.0 + Phase A.1 are DONE; you implement
    Phase B per §"Phase B" of the spec)
  - .astroray_plan/docs/wavefront-gpu-research.md (the research
    note that signed off on the architecture)
  - .astroray_plan/docs/pkg81-diagnosis.md (the measurement that
    quantified what Phase B has to beat — H4 dominance, 158 regs/
    thread cliff)
  - benchmarks/wavefront/baseline.json (Phase A.0 numbers — 89.37 ms
    cornell_diffuse, 90.86 ms cornell_glass at 256×256/64 spp; the
    AoS megakernel reference Phase B beats)
  - benchmarks/viewport_parity/2026-05-10.json (Phase B's
    viewport-parity gate — CUDA 104 ms vs Cycles-CUDA on the same
    scene; Phase B must close that gap)
  - src/gpu/wavefront/* (Phase A.1's SoA struct + init+intersect
    kernels — the foundation Phase B builds on)
  - src/gpu/path_trace_kernel.cu (the AoS megakernel — Phase B's
    parity reference; lives until Phase C)

Reference (Apache-2.0, mirrorable with citation per CLAUDE.md §6):
  - intern/cycles/kernel/integrator/state.h + state_template.h —
    Cycles' SoA IntegratorState
  - intern/cycles/kernel/integrator/shade_surface.h — Cycles'
    per-material shade kernel pattern
  - intern/cycles/device/cuda/queue.cpp — wavefront queue dispatch
  - mmp/pbrt-v4 src/pbrt/wavefront/intersect.cpp +
    aggregate.cpp — PBRT-v4's per-material shade dispatch
  - Laine, Karras, Aila — "Megakernels Considered Harmful" (HPG
    2013) §4–§6

Phase B goal (per spec §"Phase B — Shade queue + material dispatch
+ wavefront pixel output"):
  1. Material-sorted shade queue: enqueue rays by material type
     (the 7 GMaterialType values from include/astroray/gpu_types.h).
  2. Per-material shade kernels — one launch per material type per
     bounce. Coherent warps within each launch eliminate the
     divergence tax pkg55-A.0 documented.
  3. Pixel-output stage that writes accumulated radiance back into
     the framebuffer in coalesced order.
  4. New `wavefront_path_tracer` integrator plugin with
     `gpuSupported=True`. The AoS megakernel's `path_tracer` stays
     live as the reference path through Phase B.
  5. Wire `multiwavelength_path_tracer.cpp::renderGPU()` to the
     wavefront pipeline behind a new `use_wavefront` param
     (default false until Phase C). ReSTIR + neural-cache get
     wavefront codepaths in Phase B too.

Acceptance gates (per spec, all must clear):
  - astroray.integrator_capabilities("wavefront_path_tracer")
    ["gpuSupported"] is True
  - Wavefront vs CPU path_tracer SSIM ≥ 0.985 at 64 spp on the
    pkg54 visible-band parity scene
  - Wavefront vs CPU path_tracer SSIM ≥ 0.97 at 64 spp on the
    NIR band parity scene
  - AoS megakernel render output unchanged (all pkg54b SSIM gates
    still pass)
  - Performance gate: wavefront ≥ 1.5× faster than the megakernel
    on a mixed-material scene (Disney contact sheet: 7 material
    types, 512 SPP, RTX 5070 Ti)
  - **Viewport-parity gate (absorbed from pkg81):** wavefront
    `path_tracer` through the persistent viewport on the pkg81
    harness's 99k-tri reference scene achieves CUDA pan-frame
    p99 ≤ 1.2× Cycles-CUDA on RTX 5070 Ti at the same denoiser +
    spp settings. **This is the user-facing competitive parity
    claim.**
  - restir_di and neural-cache integrators produce visually correct
    output via wavefront

Constraints:
  - CLAUDE.md sections 2, 3, 6.
  - Default build path UNCHANGED until Phase B ships and is the
    new default — until then, AoS megakernel is the live path.
  - Bit-identical megakernel output gated by CI throughout Phase
    B's development.
  - Cite per-kernel: each shade kernel cites the Cycles or PBRT-v4
    reference it mirrors. No invented algorithms (CLAUDE.md §6).
  - Re-use Phase A.0's `src/gpu/profile.h` + Phase A.1's SoA
    machinery; do not reinvent.

Deliverables:
  - Code: per-material shade kernels, sorted shade queue, pixel-
    output stage, wavefront_path_tracer plugin
  - Spec update: Phase B subsection filled in with measured
    numbers + Phase B Lessons section
  - Benchmarks: extra column in baseline.json (wavefront vs
    megakernel); pkg81 harness re-run with the wavefront column
    populated to prove the viewport-parity gate
  - Tests: SSIM parity gate + performance gate + viewport-parity
    gate in CI
  - PR titled "feat(pkg55-B): per-material shade kernels + wavefront
    integrator (closes viewport-parity gate)"
```

### 3.2 Codex (main directory) — pkg43 slim disk accretion model

```
You are Codex working in the main Astroray directory. pkg42
synchrotron emission shipped 2026-05-11 (PR #245). pkg43 is next:
the slim disk accretion model on the same VolumetricEmission
interface.

Read first:
  - .astroray_plan/packages/pkg43-slim-disk.md (paste-ready spec)
  - .astroray_plan/packages/pkg42-synchrotron-jets.md (the
    interface pkg43 calls into)
  - .astroray_plan/docs/accretion-emission-research.md (research
    note covering pkg42–44)
  - plugins/emitters/synchrotron_jet.cpp (the pattern pkg43
    mirrors structurally)

Goal: implement the slim disk model per the spec. Cite the
canonical references (Abramowicz et al. 1988 / Sadowski 2009 /
the references the spec lists). Build on the
VolumetricEmission interface from pkg42 — don't widen it unless
the spec calls for it.

Constraints:
  - CLAUDE.md sections 1, 2, 3, 6.
  - Pillar 4 — cite the slim-disk papers per the spec. Reference
    renderers (RAPTOR/ipole/GYOTO) are read-only references, not
    mirrored.
  - DO NOT change pkg40 / pkg41 / pkg42 code. pkg43 is purely
    additive on top of the existing interface.

When done:
  - pkg43 spec status -> "done" with PR ref + measured numbers.
  - PR titled "feat(pkg43): slim disk accretion model".
```

### 3.3 Codex (main directory, after #2) — pkg44 ADAF accretion model

```
You are Codex in the main Astroray directory. pkg43 just landed.
pkg44 is next: ADAF (advection-dominated accretion flow) on the
same interface.

Read first:
  - .astroray_plan/packages/pkg44-adaf.md (paste-ready spec)
  - pkg42 + pkg43 plugin sources (the pattern pkg44 mirrors)
  - .astroray_plan/docs/accretion-emission-research.md

Goal: implement ADAF per the spec. Cite Narayan & Yi 1994,
Yuan & Narayan 2014, plus whatever the spec adds. Build on the
VolumetricEmission interface; do not widen unless required.

Constraints:
  - CLAUDE.md sections 1, 2, 3, 6.
  - DO NOT change pkg40 / pkg41 / pkg42 / pkg43 code.

When done:
  - pkg44 spec status -> "done" + PR + numbers.
  - PR titled "feat(pkg44): ADAF accretion model".
```

### 3.4 Codex (main directory, small) — pkg83 progressive accumulation continuation

```
You are Codex in the main Astroray directory. Small ½-day fix from
the pkg81 viewport-parity diagnosis (H2: addon resets accumulator
on every camera_changed; spp_trace=[1] every pan-frame).

Read first:
  - .astroray_plan/packages/pkg83-progressive-accumulation-continuation.md
    (the spec; resolution policy is defined there)
  - .astroray_plan/docs/pkg81-diagnosis.md (H2 row: confirmed
    code-level)
  - blender_addon/__init__.py — the depsgraph handler that fires
    the accumulator reset; only "substantive" mutations should
    invalidate (focal length, lens shift, sensor size, dof toggle,
    aperture fstop). Pure transform changes (pan/orbit/dolly)
    keep accumulating.
  - intern/cycles/blender/session.cpp::BlenderSession::reset
    (Apache-2.0 reference for the substantive-vs-transform
    distinction)

Acceptance:
  - pkg81 harness `camera_only` scenario: spp_trace[-1] >= 8 across
    the 8-frame pan (was [1] every frame pre-fix).
  - transform_edit scenario still resets correctly.
  - New addon-policy test green; existing tests still green.

Constraints:
  - CLAUDE.md sections 2, 3.
  - Addon-only — no C++ changes.
  - Not a fix for the viewport-parity gap (that's pkg55 B).
    H2 is the small UX polish independent of Phase B.

When done:
  - pkg83 spec status -> "done" + numbers from re-running the
    pkg81 harness post-fix.
  - PR titled "feat(pkg83): progressive accumulation continuation
    across camera changes".
```

### 3.5 Codex (main directory, small) — pkg84 CUDA kernel pre-warm

```
You are Codex in the main Astroray directory. Small ½-day fix from
the pkg81 viewport-parity diagnosis (H5: first CUDA frame =
12,079 ms kernel JIT + context init; subsequent ~14 ms).

Read first:
  - .astroray_plan/packages/pkg84-cuda-kernel-prewarm.md
  - .astroray_plan/docs/pkg81-diagnosis.md (H5 row: confirmed
    one-shot per session)
  - blender_addon/__init__.py — persistent-viewport renderer
    instantiation site (where the pre-warm hook lands)
  - intern/cycles/blender/blender_python.cpp::list_render_devices
    (Apache-2.0; addon-load CUDA context init pattern)

Implementation:
  - On persistent-viewport renderer instantiation when device_mode
    is 'cuda', run a 1-pixel render of a trivial single-triangle
    scene. Swallow the result. This pulls all megakernel JIT into
    the warm-up phase.
  - Idempotent (runs once per session); re-fires if user changes
    device_mode mid-session.

Acceptance:
  - pkg81 harness first-frame number drops by ≥ 10× (was 12,079 ms;
    target ≤ 100 ms initialisation post-warm).
  - Pre-warm time itself is still ~12 s — the cost moved, not
    eliminated. The package's job is to move the spinner to a
    moment the user expects.
  - CPU device mode is unchanged (no warm needed).

Constraints:
  - CLAUDE.md sections 2, 3.
  - No persistent kernel cache to disk (multi-week scope; not this).
  - No PTX shipping (multi-arch; not this).
  - No background pre-warm (race-prone; not this).

When done:
  - pkg84 spec status -> "done" + measured first-frame number.
  - PR titled "feat(pkg84): CUDA kernel pre-warm at viewport start".
```

### 3.6 Codex (RTX hardware) — pkg82 + pkg76 CSV combined session

```
You are Codex on the RTX 5070 Ti box. Two small RTX-only follow-ups
combined into one ~1.5-day sitting. Run them back-to-back; they
share the build_cuda environment.

Part A — pkg82 (variance characterisation, ~1 day):
  Read: .astroray_plan/packages/pkg82-pkg54c-gate-variance.md +
        the closing comment on issue #237 from pkg78 bisect.
  Procedure: Phase 1 (intra-binary 20× repeatability) → Phase 2
  (5 clean rebuilds with controlled NVCC flag variations) → Phase 3
  (data-driven gate decision: re-baseline floor OR bump test spp,
  chosen by data, never both).
  Output: tests/test_gpu_multiwavelength.py one-line change,
  pkg54c spec Lessons "Cross-build variance characterisation"
  section, closing comment on issue #237.
  PR: "verify(pkg82): pkg54c gate variance + data-driven {floor|spp}".

Part B — pkg76 CSV (~½ day):
  Read: benchmarks/cycles-parity/README.md + scripts/run_parity.py
        + .astroray_plan/packages/pkg76-blend-importer-parity-scope.md
        Lessons.
  Procedure: populate the .blend cache; run scripts/run_parity.py
  for Classroom + Junkshop + BMW27 vs Cycles-CPU EXR at the
  manifest's reference SPP. Acceptance per spec: SSIM ≥ 0.85
  (parity-scope, not Cornell's 0.95).
  Output: rows appended to benchmarks/cycles-parity/results.csv
  (or whichever dated CSV the harness writes).
  PR: "verify(pkg76): Classroom/Junkshop/BMW27 parity rows on RTX".

Constraints (both parts):
  - CLAUDE.md sections 1, 4.
  - Doc + CSV + at most one-line test changes; no source touched.
  - Do NOT relax any gate without the measurement justifying it
    (pkg82 specifically prohibits opinion-based gate fudging;
    pkg76 specifically requires reporting which channel drove
    any miss without re-baselining).
  - The pkg82 + pkg76 PRs are independent — open one per part.
```

---

## 4. Coordination

**File-touching map** (zero hard collisions):

| Session | Files |
|---|---|
| pkg55 Phase B | new `src/gpu/wavefront/shade_*.cu`, `src/gpu/wavefront/queue.{h,cu}`, new `plugins/integrators/wavefront_path_tracer.cpp`, `plugins/integrators/multiwavelength_path_tracer.cpp` (wire `renderGPU()` to wavefront), CMake guard for the new flag, new tests, `benchmarks/wavefront/baseline.json` (extra column), `benchmarks/viewport_parity/{date}.json` (wavefront column), pkg55 spec, STATUS.md |
| pkg43 slim disk | new `plugins/emitters/slim_disk.cpp`, maybe pkg42-side accessors, new tests, pkg43 spec, STATUS.md |
| pkg44 ADAF | new `plugins/emitters/adaf.cpp`, new tests, pkg44 spec, STATUS.md |
| pkg83 (H2) | `blender_addon/__init__.py` (depsgraph handler), new test, pkg83 spec, STATUS.md |
| pkg84 (H5) | `blender_addon/__init__.py` (renderer instantiation hook), maybe a binding helper, new test, pkg84 spec, STATUS.md |
| pkg82 + pkg76 CSV | one-line test change in pkg82, CSV append in pkg76, two separate Lessons appends, two separate PRs |

**Conflict points:**

1. **`STATUS.md`** — five sessions touch it (pkg55 B, pkg43, pkg44,
   pkg83, pkg84, pkg82). Same merge race; rebase + manual
   resolution preserving rows.
2. **`blender_addon/__init__.py`** — pkg83 + pkg84 both touch it
   in different code paths (depsgraph handler vs renderer
   instantiation). Should be conflict-free but worth a sanity diff
   at merge.
3. **Per-emitter plugin files** — pkg43 and pkg44 land in different
   files. Conflict-free.
4. **`src/gpu/wavefront/`** — only pkg55 Phase B touches it
   (Phase A.1 already in tree). Conflict-free.

**Recommended merge order:** small RTX session first (pkg82 ≈ 1 day,
pkg76 CSV ≈ ½ day) → pkg83 (½ day) → pkg84 (½ day) → pkg43 (medium,
Pillar 4) → pkg44 (medium, after pkg43) → **pkg55 Phase B last**
(largest, gate-closing — viewport parity claim resolves with this
PR).

---

## 5. After Round 7 lands

When Round 7 closes:

- **pkg55 Phase B** done — wavefront `path_tracer` shipped; **the
  user-facing viewport-parity claim is met** (CUDA pan-frame p99 ≤
  1.2× Cycles-CUDA). The lived-experience "rendered view is a slog"
  complaint resolves into a measured pass.
- **pkg43 + pkg44** done — Pillar 4 has three emission models
  (synchrotron, slim disk, ADAF) on the VolumetricEmission
  interface. Real astrophysical scenes become composable.
- **pkg83 + pkg84** done — viewport feels noticeably smoother on
  the small-bug-fix axis (no per-pan accumulator reset, 12 s cold-
  start moved to viewport-start).
- **pkg82** done — issue #237 closed, gate either re-baselined
  with measured headroom or test spp bumped. Variance
  characterisation methodology is the project's template for every
  future numerical gate.
- **pkg76 CSV** done — pkg71 baseline 4 rows wide (Cornell +
  Classroom + Junkshop + BMW27).

Then **Round 8**:

- **pkg55 Phase C** — megakernel removal (~3 weeks). Architectural
  cleanup; the AoS path goes away once Phase B is the default.
- **pkg45 + pkg46** — CLOUDY emissivity tables + HII region
  emission (Pillar 4 continuation).
- Optional Codex side track: **pkg47 / pkg48 / pkg49** (FITS / HDF5
  / SPH loaders) — the data-import pillar of Pillar 4 starts.
- **pkg67 metric-aware path tracer** becomes plausible once pkg40
  + pkg55 Phase B+C are mature.

After Round 8:

- Pillar 4 has the full emission-model trio plus data-import
  groundwork. Real astrophysical scenes (synchrotron jet around a
  Kerr metric, slim-disk accretion onto a Schwarzschild metric,
  ADAF flow, etc.) are renderable end-to-end.
- pkg55 fully done (Phases A.0 + A.1 + B + C). The megakernel is
  gone. Wavefront is the production CUDA path.
- Pillar 5 is *actually* feature-complete on user-facing scope
  (viewport parity met, cold-start polished, accumulator
  continuing).

Bump this report when pkg55 Phase B lands or when pkg44 lands —
those are the next major queue movements.
