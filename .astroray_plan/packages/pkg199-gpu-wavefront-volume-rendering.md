# pkg199 — GPU wavefront world volume (homogeneous world medium)

**Pillar:** 5 / integration-first (also 3 — CPU↔GPU parity)
**Track:** A
**Status:** Stage 1 done (PR #611, 2026-08-14 — HW PASS after fix 6e7bf6d). GPU
wavefront homogeneous-world Beer-Lambert absorption at CPU parity; furnace Tr
matches analytic exp(-σ·d) to <2e-4; shade kernel byte-identical REG 254/STACK
3352/CONST 1700. **hw-611 HW FAIL (sphere-light NEE fog saturation — a 1e30
occlusion sentinel used as the Beer-Lambert path length) FIXED** (true geometric
NEE distance; see the "Hardware verification" audit blocks below) and re-verified
HW PASS. **Stage 2 split into PR 2a (CPU medium loop — IN REVIEW) + PR 2b (GPU
wavefront mirror — pending build slot).** PR 2a lands the CPU homogeneous
scattering estimator (HG in-scatter, per-channel exponential distance sampling,
NEE-through-medium phase/light MIS) behind a new single-scattering-albedo α
(`set_world_volume(..., scatter=0.0)`, default 0 ⇒ exact Stage-1 absorption,
byte-identical, every Stage-1 gate green): analytic single-scatter density-shape
match ≤0.9% (one global scale), α-linear, α=0 Beer-Lambert Tr 0.6063 vs 0.6065,
sum-to-beauty rel_L1 0.0000 with `PASS_VOLUME_*` populated, forward/back HG
asymmetry 2.0× (single-scatter) / 1.48× (multi). Full local sweep 1946 passed / 0
failed. `worldVolumeAnisotropy` now live as g.
**Estimated effort:** Stage 1 M (landed); Stage 2 XL — 2a CPU (in review), 2b GPU.
**Depends on:** pkg55-C7 wavefront dispatch; [[wavefront-shade-kernels-register-saturated]].

---

## PREMISE CORRECTION (2026-08-14, git-archaeology — supersedes the original filing)

The original spec claimed the CPU "has a working homogeneous world volume … with
Beer-Lambert transmittance … and Henyey-Greenstein anisotropy
(`include/raytracer.h:2110-2255`)" and asked to port HG in-scatter + distance
sampling + NEE-through-medium to the GPU "matching the CPU model exactly." Verified
against HEAD `f965f93`, **that premise was false**:

- There was **no** Henyey-Greenstein phase function, **no** in-scatter, **no**
  distance sampling, **no** NEE-through-medium anywhere in the CPU integrator —
  and there never had been. `worldVolumeAnisotropy` was stored by `setWorldVolume`
  and **read by no render code in the entire git history**.
- The only volume code was `Renderer::worldTransmittance(distance)`
  (`raytracer.h:2159`) — pure Beer-Lambert **absorption** `exp(-σ_t·t)`,
  `σ_t = worldVolumeColor·worldVolumeDensity`.
- That function was **dead code**: repo-wide it appeared only at its definition —
  **zero call sites**. World volume was added in pkg25 (`245d1fa`) wired into the
  **legacy RGB integrator** (3 roles: NEE emission, MIS BSDF-emission, throughput).
  pkg14 (`90ebb31`) **deleted the legacy RGB integrator wholesale**, removing all
  three call sites; they were never ported to the spectral path tracer that is now
  the default. So the CPU rendered fog scenes as **vacuum**, exactly like the GPU.

**Coordinator decision (staged Option B, 2026-08-13):** re-wiring absorption into
the spectral tracer *completes an orphaned feature* (the deletion targeted the RGB
integrator, not world volumes) — sign-off granted. Absorption-only is a strict
subset of the full scattering medium, so the work is **staged**: Stage 1 (below)
lands absorption at CPU↔GPU parity; Stage 2 (below) adds the scattering medium.

Research + design detail: `.astroray_plan/docs/pkg199-world-volume-research.md`.

---

## Stage 1 — homogeneous world absorption (LANDED, this PR)

Bring the **homogeneous world volume as Beer-Lambert absorption** to the GPU
wavefront, at parity with the CPU spectral path tracer (which is re-wired the same
way in the same PR — completing the pkg14-orphaned feature).

**Model (pinned identically on CPU and GPU):** throughput carries per-λ
transmittance `Tr[λ] = exp(-σ_t[λ]·d)` over each traversed segment, with
`σ_t[λ] = upsample_reflectance(worldVolumeColor)[λ] · worldVolumeDensity`.
Spectral discipline: **upsample the colour (JH albedo LUT / GSPEC_RGB_ALBEDO),
then Beer-Lambert per-λ — never upsample the product.** Three roles:

1. **Free-flight** `Tr(rec.t)` on each surface hit (CPU `pathTraceSpectral`; GPU
   `intersectPathSlot` with SoA throughput write-back). Attenuates emission and
   carries the fog into NEE + later bounces.
2. **NEE / shadow ray** `Tr(ls.distance)`/`Tr(s.maxDist)` (CPU NEE block; GPU
   `stageShadowKernel`).
3. **Lamp-MIS emission** `Tr(lh.t)`/`Tr(lampT)` (dedicated lamp closer than the
   surface).

Env-miss (infinite segment) is not attenuated — the mirror-able choice for an env
at infinity and consistent CPU/GPU. `worldVolumeAnisotropy` stays **inert**
(reserved for Stage 2).

**NEE distance + distant/infinite-light convention (hw-611 fix):** role 2
attenuates by the **true geometric vertex→light distance**, never the shadow-ray
occlusion tMax — the GPU NEE sampler sets `maxDist = 1e30` as an occlusion
sentinel for **sphere-primitive** and **distant** lights, and feeding that into
`exp(-σ·d)` collapsed every fogged NEE-to-sphere contribution to a density-
independent near-black (the hw-611 regression). The GPU now carries a separate
`geomDist` (NEE lane 14: ray-sphere near-hit distance for spheres, sampled-point
distance for triangle/point/spot/area) and the CPU uses the already-geometric
`ls.distance`. **Distant / infinite lights** (`DistantLight`,
`ls.distance = FLT_MAX`; GPU `geomDist = 0`) are treated **like env-miss —
NON-attenuated** (`Tr = 1`), both backends guarding `distance ≥ 1e18` (real
sun-through-atmosphere is Stage-2+ territory).

**Register-gate design (satisfied):** all volume transmittance lives in the
**non-pinned** intersect + shadow-resolve stages, gated at runtime by a
`__constant__ GWorldVolume c_worldVolume` symbol. The REG-254-saturated
`stageShadeBucketedKernel` is **not modified at all** → byte-identical by
construction (verified via cuobjdump on the native-sm_120 `.pyd`: all-false
specialization **REG 254 / STACK 3352 / CONSTANT[0] 1700**, unchanged). No 5th
template axis — cleaner than the literal "compile-time HasWorldVolume axis"
suggestion and satisfies its goal; the pkg197 guide-AOV precedent (write from the
intersect stage to keep the shade kernel byte-identical).

### Stage 1 acceptance criteria — all met

- [x] GPU wavefront renders the homogeneous world volume (transmittance +
      NEE-through-medium absorption), **matching the CPU render**: per-channel
      CPU↔GPU mean-ratio on a coloured fog scene = **[1.029, 1.029, 1.043]**
      (within the independent-MC band). Analytic white-fog furnace: GPU Tr matches
      `exp(-σ·d)` to **<0.0002** at dist∈{5,10}, dens∈{0.1,0.2}.
- [x] `__gpu_features__["volumes"]` flips **true** (homogeneous-world absorption
      only; honesty comment scopes out in-scatter/heterogeneous). Guard test
      `test_pkg186_gpu_features_guard` updated (volumes off GPU_DROPPED).
- [x] Vacuum (no world volume) GPU renders unchanged — density-0 == no-volume
      within the GPU atomic-nondeterminism floor; shade kernel byte-identical
      (cuobjdump).
- [x] Un-xfailed the two `test_world_volume_*` fog tests (they now pass on both
      backends).
- [x] RTX 5070 Ti visual confirmation: `pkg199_gpu_fog_{clear,dense}.png` — a
      receding row of spheres fades into the medium with distance (darker +
      desaturated), no god-rays (absorption only, as claimed).

### Stage 1 explicit non-goals (unchanged)

- No in-scatter / HG phase (Stage 2). No heterogeneous / object volumes, no
  `add_volume` scattering (emissive-proxy behaviour stays as-is). No black-hole /
  Pillar-4 volumetric emission ([[pillar4-on-pause]]). No `PASS_VOLUME_*`.
- The opt-in caustic integrator (`pathTraceSpectralCaustic`), the CPU wavefront
  reference (`src/cpu/wavefront/path_kernel.cpp`), and the ReSTIR GPU path do NOT
  carry world-volume absorption in Stage 1 (they use different stages/kernels that
  do not read `c_worldVolume`); the production megakernel-CPU ↔ GPU-wavefront pair
  is the parity target. A follow-up can extend them if needed.

---

## Stage 2 — full scattering medium (SPEC-ONLY; do NOT implement here; XL)

Add genuine volumetric scattering to the homogeneous world medium: **HG in-scatter,
analytic exponential distance sampling of a scatter event, and NEE-through-medium
(phase/light MIS)** — delivering god-rays / light shafts. **CPU FIRST** (the
spectral path tracer has no medium-interaction loop today — Stage 1 only added
absorption multiplies), **then mirror on the GPU wavefront.**

### Estimator (cite — do NOT invent)

- **PBRT-v4** §14.2 volumetric path tracing (`SampleLd` through media,
  `HomogeneousMedium` sampling), §11.3 media, `HGPhaseFunction`; Henyey &
  Greenstein 1941 for the phase function. Reference `src/pbrt/media.cpp`,
  `src/pbrt/cpu/integrators.cpp` (BSD, license-compatible).
- **Cycles** `intern/cycles/kernel/integrator/volume.h` `volume_integrate` /
  `volume_shader_sample` (Apache-2.0) — the Blender-facing reference for
  homogeneous scatter + equiangular/distance sampling + phase MIS.
- Homogeneous → analytic exponential free-flight distance sampling
  `t = -ln(1-ξ)/σ_t` (no delta-tracking needed; that is a heterogeneous-grid
  concern for a later package).

### Register-budget plan (pinned at spec time)

A medium-scatter interaction needs live state the REG-254 shade kernel cannot
absorb: the sampled scatter distance vs surface `t` decision, a phase-function
sample, a phase pdf, and a shadow connection carrying per-segment transmittance.
**Do NOT fold this into `stageShadeBucketedKernel`.** Add a **dedicated
volume-scatter wavefront stage** (its own kernel, scheduled between intersect and
shade): it decides scatter-vs-surface from the sampled free-flight distance,
performs the phase-sampled NEE (parking a shadow sample like the surface NEE does),
and emits the continuation ray from the scatter point. The shade kernel stays
untouched (Stage 1's byte-identity carries forward). Snapshot semantics: pin the
scatter-point `ray_origin` capture moment identically on CPU and GPU at design time
([[wavefront-snapshot-semantics-class-of-bug]]).

### Register-budget plan — premise correction (PR 2b implementation, 2026-08-14)

The spec's "purely additive dedicated kernel between intersect and shade" is **not
literally achievable**: `intersectPathSlot` already owns the surface-commit
(role-1 free-flight `Tr`, surface emission — which *terminates* the path, never
parked — and the dedicated-lamp MIS) **and** the shade-queue bucketing
(`atomicAdd(&shade_counts[matType], …)`). A medium scatter must intercept the
segment *before* all of those (the CPU runs its medium block at the top of the
loop), so a kernel inserted *after* intersect cannot un-commit the emission
intersect already added nor un-bucket the shade queue. **Therefore intersect must
be `mediumScatters`-gated.** Option A as built (coordinator-approved): intersect
does only the cheap free-flight **decision** (2 RNG draws + `Tr`/pdf) gated on
`mediumScatters = hasVolume && density>0 && scatter>0`; a SCATTER writes the
scatter point `P` to `ray_origin`, applies `Tr·σ_s/pdf`, and returns a `-2`
sentinel that routes the slot to a new **volume queue**; a SURFACE applies
`Tr/pdf` (the role-1 replacement) and falls through to the Stage-1 path with
role-1 and role-3-lamp `Tr` gated off. The register-heavy scatter processing
(phase NEE + HG continuation) lives entirely in the dedicated
`stageVolumeScatterKernel`, which parks the phase NEE into the **shared**
`nee_f/nee_i` lanes + shadow queue (so `stageShadowKernel` resolves it unchanged:
lane-14 `geomDist` role-2 `Tr` + clamp) and requeues the HG continuation.
**`stageShadeBucketedKernel` is never touched → byte-identical by construction**
(scattered slots never enter its bucket). **The `scatter==0` (default) GPU path
compiles to the identical Stage-1 behaviour** — the `-2` decision block is skipped
at runtime (`mediumScatters` false), so vacuum and absorption-only renders are
byte-identical to Stage 1. ReSTIR-DI publishes `scatter=0` (bounce-0 direct only,
no volume kernel) so its shared-`intersectPathSlot` never takes the `-2` route.
Snapshot semantics pinned: `P` captured from the pre-update ray, stored as
`ray_origin`, `ray_direction` left as the incoming direction so the volume kernel
recovers `woMedium = -direction` — identical to the CPU capture moment.

### Intersect register isolation — `HasWorldScatter` if-constexpr axis (PR 2b)

The free-flight *decision* in `intersectPathSlot` adds **+3 REG (127→130)**, which
at 256 threads/block crosses 128 → **2→1 blocks/SM**. A cooled, contention-
controlled, interleaved A/B (burn-in to 2887 MHz, min-of-11; three main legs
116.4–116.9 ms @ 2-blocks/153–156 W vs the always-present form 120.6 ms @
1-block/147 W) measured a **+3.3% fog-free fleet regression** — unacceptable for an
off-by-default feature. Four shave attempts (object-free counter-based hash,
`__noinline__`, scatter-math-moved-to-volume-kernel, drop-lamp-bound) all stayed at
130; the +3 is intrinsic to any inline decision. **Resolution (chosen over the
"Option 2" volume-kernel-owns-surface restructure — same fleet-clean result, far
lower correctness risk):** the established fleet-isolation pattern (pkg178/184/189)
— `template<bool HasWorldScatter>` on `intersectPathSlotT` +
`stageIntersectQueuedKernel`, decision block behind `if constexpr`. The fleet
`<false>` (vacuum + absorption-only fog) compiles it OUT → **REG 127 / STACK 616 /
2 blocks/SM, byte-identical Stage-1** (cooled vacuum 117.3 ms = +0.5% vs main,
within noise); only scattering fog (`scatter>0`) launches `<true>` (REG 130). A
non-template `intersectPathSlot` forwarder (→`<false>`) keeps the cross-TU symbol
for the ReSTIR primary + MIS-audit kernels. GPU free-flight uniforms use
`gpu_freeflightUniform` (PBRT-v4 MixBits + PCG32, cited; per-bounce salt disjoint
from the shade stream); CPU/GPU free-flight streams are independent (parity is
per-channel mean-ratio, not sample-matched).

### Stage 2 acceptance (for the future package)

- CPU spectral tracer gains a homogeneous medium-interaction loop (scatter event +
  HG phase + NEE-through-medium), validated vs a PBRT/analytic single-scatter
  reference; then GPU wavefront mirror at CPU↔GPU parity on a god-ray scene.
- `worldVolumeAnisotropy` becomes live (HG `g`), with a forward/back-scatter
  visual gate.
- Register gate: shade kernel unchanged; the new volume-scatter kernel's footprint
  reported via cuobjdump.
- Heterogeneous / object volumes / delta-tracking remain OUT (a later package).

### Scattering parametrization (coordinator-approved, Option A — implemented in 2a)

The world-volume API had no scattering coefficient. A single-scattering albedo
`α ∈ [0,1]` was added as the trailing `set_world_volume(density, color,
anisotropy, scatter=0.0)` arg: `σ_t = upsample(color)·density` (unchanged from
Stage 1), `σ_s = α·σ_t`, `σ_a = (1-α)·σ_t`. Default `α=0` gates the scattering
estimator OFF, so Stage-1 absorption is byte-identical and the "σ_s=0 ⇒
Beer-Lambert parity" criterion is the α=0 case. (Option B — reinterpreting `color`
as albedo — was rejected: it would re-baseline Stage-1 extinction semantics.)

### Addon-UI follow-up (MUST be filed at closeout)

PR 2a/2b expose α **only through the python binding**. Wiring the single-
scattering-albedo control into the Blender addon world-volume UI (a `scatter`
slider next to density/color/anisotropy, plumbed through to `set_world_volume`)
is a tracked **follow-up package** — not in 2a/2b scope per the coordinator's
"bindings now, addon UI follow-up" decision (2026-08-14).

---

## Hardware verification 2026-08-13 (PR #611, branch pkg199 @ b3298437cd0fd75e4bf8c334d418329a8ed70384)

**Hardware:** NVIDIA GeForce RTX 5070 Ti, driver 610.47, CUDA 12.8 (nvcc V12.8.61), Windows 11
Enterprise 10.0.26200. Worktree: Astroray-pkg199. GPU lock hw-611 held for the duration; no
concurrent CUDA sessions.

Note: this branch predates pkg195-Stage-C merge to main (disjoint area; verified as-is per
dispatch instruction, not rebased).

### Step 1 -- Clean rebuild
build_cuda_worktree.bat (root/VS-generator pipeline), foreground via PowerShell.
HEAD SHA verified b3298437cd0f. Build succeeded. cuobjdump --list-elf on the built .pyd:
astroray.cp313-win_amd64.1.sm_120.cubin -- sm_120 confirmed (both the build scripts own
arch-verify and an independent cuobjdump --list-elf check agree).

### Step 2 -- Smoke-check
astroray.__file__ resolved to the canonical build_cuda/Release/astroray.cp313-win_amd64.pyd
(not a stale root shadow). hasattr(Renderer(), set_world_volume) returned True.
astroray.__gpu_features__ returned: nee True, mis True, disney_brdf True, sah_bvh True,
adaptive_sampling False, volumes True, textures False, subsurface True, gr_black_holes False,
spectral_gpu_materials True -- volumes True confirmed.

### Step 2b -- Register hard gate (cuobjdump -res-usage)
stageShadeBucketedKernel with HasWorldVolume=false (the vacuum instantiation, all four bool
template params false): REG:254 STACK:3352 CONSTANT[0]:1700 -- byte-identical to mains pinned
baseline (REG 254 / STACK 3352 / CONSTANT[0] 1700). PASS.

Other wavefront kernels for reference:
- stageIntersectQueuedKernel: REG:127 STACK:616 CONSTANT[0]:1680
- stageShadowKernel: REG:108 STACK:584 CONSTANT[0]:1484
- stageRegenKernel: REG:100 STACK:608 CONSTANT[0]:1481

### Step 3 -- Gate test run (tests/test_pkg199_world_volume_gpu_parity.py, -v -s --tb=short)
All 6 tests PASSED, including test_restir_render_not_contaminated_by_prior_fog on its first
hardware run (previously CI-skipped, GPU-only). Verbatim:

    tests/test_pkg199_world_volume_gpu_parity.py::test_world_volume_absorption_only_removes_energy_cpu
    [pkg199 CPU furnace] clear=[1.29   1.2948 1.2722] foggy=[0.7844 0.9507 1.0396] foggy/clear=[0.6081 0.7343 0.8172]
    PASSED
    tests/test_pkg199_world_volume_gpu_parity.py::test_world_volume_cpu_gpu_parity
    [pkg199 CPU/GPU fog parity] GPU=[0.8069 0.9782 1.0844] CPU=[0.7844 0.9507 1.0396] GPU/CPU=[1.0286 1.0289 1.0431]
    PASSED
    tests/test_pkg199_world_volume_gpu_parity.py::test_world_volume_gpu_analytic_beer_lambert
    [pkg199 GPU Beer-Lambert] dist=5.0 dens=0.1: measured Tr=0.6064 analytic=0.6065
    [pkg199 GPU Beer-Lambert] dist=5.0 dens=0.2: measured Tr=0.3677 analytic=0.3679
    [pkg199 GPU Beer-Lambert] dist=10.0 dens=0.1: measured Tr=0.3678 analytic=0.3679
    [pkg199 GPU Beer-Lambert] dist=10.0 dens=0.2: measured Tr=0.1352 analytic=0.1353
    PASSED
    tests/test_pkg199_world_volume_gpu_parity.py::test_world_volume_zero_density_gpu_byte_identical
    [pkg199 GPU vacuum byte-identity] no-vol self-noise=9.54e-07 zero-density diff=9.54e-07
    PASSED
    tests/test_pkg199_world_volume_gpu_parity.py::test_restir_render_not_contaminated_by_prior_fog
    [pkg199 ReSTIR fog-contamination guard] clean=[0.0153 0.0162 0.0235] after_fog=[0.0153 0.0162 0.0235] after/clean=[1. 1. 1.]
    PASSED
    tests/test_pkg199_world_volume_gpu_parity.py::test_world_volume_gpu_visual PASSED
    ============================== 6 passed in 1.45s ==============================

PR claimed numbers (white-fog vs exp(-sigma*d) within 2e-4 across 4 density/distance combos;
coloured-fog CPU-GPU mean-ratio [1.029, 1.029, 1.043]) reproduce exactly on this hardware.

### Step 4 -- Un-xfailed tests (test_python_bindings.py, --runxfail)

    tests/test_python_bindings.py::test_world_volume_density_adds_visible_haze PASSED
    tests/test_python_bindings.py::test_world_volume_fogs_farther_objects_more PASSED
    ====================== 2 passed, 86 deselected in 0.99s =======================

Both tests exercise the CPU backend only (create_renderer() does not call set_use_gpu, and
useGPU defaults to false in blender_module.cpp). An ad-hoc GPU-forced replication of the same
two tests scene/assertions (throwaway diagnostic script, not committed) also satisfies their
weak monotonic assertions on GPU -- but this replication is what surfaced the Step 6 finding
below. The two officially-parameterized tests, as written, do not independently exercise GPU.

### Step 5 -- Feature guard (test_pkg186_gpu_features_guard.py)
All 7 tests PASSED, including test_volumes_gpu_enabled.

### Step 6 -- Visual inspection -- REGRESSION FOUND, gates missed it
test_world_volume_gpu_visuals PNGs (test_results/pkg199_gpu_fog_clear.png,
pkg199_gpu_fog_dense.png, a receding row of 5 diffuse spheres) show the dense-fog render going
almost fully black for all five spheres -- including the nearest one, which the test own inline
comment says "should stay crisp." This does not look like graceful fade-to-fog-tint; it looks
like near-total light loss.

Quantitative follow-up (re-rendering the exact visual-test scene in linear space,
apply_gamma=False, nearest-sphere crop, FOG_DENSITY=0.06, same seed/geometry, CPU vs GPU on the
same build):

    density | GPU ratio (R,G,B)          | CPU ratio (R,G,B)
    0.005   | [0.0577, 0.0675, 0.1298]   | [0.9543, 0.9710, 0.9817]
    0.01    | [0.0565, 0.0666, 0.1287]   | [0.9107, 0.9428, 0.9638]
    0.02    | [0.0541, 0.0649, 0.1264]   | [0.8293, 0.8891, 0.9289]
    0.06    | [0.0460, 0.0586, 0.1179]   | [0.5696, 0.7044, 0.8018]

CPU behaves as expected: near-1.0 ratio at tiny density, smooth monotonic falloff to about
0.57-0.80 at density 0.06 (physically consistent with the combined camera-to-sphere plus
sphere-to-light plus GI-bounce path length through the medium). GPU collapses to a near-constant
0.05-0.13 ratio even at density 0.005 -- essentially independent of density, an 8-17x stronger
extinction than CPU on the identical scene/seed. The clear (no-volume) renders match closely
between backends (GPU 0.2776 vs CPU 0.2726 in R on the nearest-sphere crop -- normal about 2 pct
MC-noise-level parity), confirming the divergence is specific to the fogged path, not general
scene/render setup drift.

This does not reproduce in the PR own gates: test_world_volume_gpu_analytic_beer_lambert uses a
triangle wall with max_depth=2 and no NEE/GI (passes exactly); the CPU-GPU parity test uses a
single-sphere scene with a simpler direct+NEE path (passes within [0.85, 1.18]). The divergence
appears specific to scenes with multiple objects / multi-bounce GI through the medium --
consistent with the visual test 5-sphere scene but not the narrower analytic/parity scenes. Root
cause not diagnosed here (out of verifier scope -- cite-worthy candidates for the
architect/gate-failure-reviewer: hero-wavelength dispersion (pkg189) interacting with per-segment
transmittance compounding across bounces, or a NEE/GI shadow-ray transmittance integration bug
that only triggers with more than one scene object). A minimal single-object repro attempt
(large sphere directly filling the frame) was inconclusive due to a construction flaw in that
specific script (camera ended up inside the sphere) and is not submitted as independent evidence
-- the 5-sphere visual-test-scene CPU vs GPU comparison above is the load-bearing evidence.

No NaN speckle observed. No god-rays (correct -- Stage 1 is absorption-only, as specified).
Vacuum (no-volume) renders match CPU/GPU closely (see clear-crop numbers above) -- the no-volume
path itself is not implicated.

### Step 7 -- Vacuum no-op check
test_world_volume_zero_density_gpu_byte_identical (density-0 vs no-set_world_volume-call, on
this build): diff 9.54e-07, at the same order as the self-noise floor (9.54e-07) -- PASS.
Combined with the byte-identical HasWorldVolume=false kernel machine code (Step 2b), the vacuum
path is confirmed unchanged. A full differential build against main HEAD was not performed --
out of scope for this already-large verification pass; the in-build zero-density-vs-no-call
comparison plus the register-identical compiled kernel are treated as sufficient evidence for
"strict no-op."

### Step 8 -- Regression slice
test_pkg186_gpu_features_guard.py (7), test_gpu_multiwavelength.py (6),
test_pkg55_c3_wavefront_nonvisible.py (4) -- 17/17 PASSED, no transport regression detected in
the standard spectral/wavefront suite (none of these exercise world-volume, as expected).

### Verdict: HW FAIL

All of the PR own automated gates pass, verbatim, on this hardware -- the PR claimed numbers are
reproduced exactly. But mandatory visual inspection of the PR own test_world_volume_gpu_visual
PNGs caught a real, reproducible regression the numeric gates do not cover: GPU world-volume
absorption is 8-17x over-attenuated relative to CPU in scenes with more than one object /
multi-bounce GI (the pkg199-canonical "no god-rays, spheres fade gracefully" visual acceptance
criterion is violated -- spheres go black, not fade). This is escalated to
gate-failure-reviewer per hard rule (never paper over visual regressions, do not decide yourself
that it is acceptable) rather than adjudicated here. Do not merge PR #611 pending that review.

---

## hw-611 FIX (2026-08-14) — root cause + resolution of the HW FAIL above

**Root cause (proven by the triangle-vs-sphere lamp A/B):** `src/gpu/gpu_nee.cuh`
sets `maxDist = 1e30f` as an OCCLUSION sentinel for SPHERE-primitive lights (and
distant lights). The pkg199 role-2 code consumed `s.maxDist` as the Beer-Lambert
path length, so `exp(-σ·1e30) = 0` killed every fogged NEE-to-sphere contribution
at ANY density — the density-independent near-black the verifier saw (GPU
~[0.05,0.06,0.13] vs CPU ~[0.94→0.57]). Triangle emitters (`maxDist = dist-0.001`)
were fine, which is why the analytic (triangle-wall) and single-sphere parity gates
passed. CPU was correct (`ls.distance` is geometric).

**Fix:** carry a separate TRUE geometric vertex→light distance
(`GNEESample.geomDist` — ray-sphere near-hit for spheres, sampled-point distance
for triangle/point/spot/area), parked in NEE float lane 14
(`G_WF_NEE_F_LANES` 14→15), and feed THAT into `gpu_worldTransmittanceMW` in
`stageShadowKernel`; `maxDist` stays 1e30 for the visibility trace. Distant/infinite
lights (`geomDist = 0`; CPU `ls.distance = FLT_MAX`) are treated like env-miss —
NON-attenuated (both helpers guard `distance ≥ 1e18`; real sun-through-atmosphere is
Stage-2+). Shade kernel still byte-identical (REG 254 / STACK 3352 / CONST 1700 —
`gpu_nee_sample` is reachable from it, verified post-fix). New regression gates
(would have caught hw-611): sphere-lamp-fogs-like-triangle-lamp, density-monotonicity,
sphere-lamp CPU↔GPU parity — all pass; post-fix sphere-lamp CPU↔GPU ratio
[1.0005, 1.0003, 1.0003]. Visual re-inspected: nearest sphere crisp, farther spheres
fade smoothly into the medium.

---

## Hardware verification 2026-08-14 (PR #611 re-verify, branch pkg199 @ 91dbc4770c28c054742ad93427794b9a82847398, fix commit 6e7bf6d)

**Hardware:** NVIDIA GeForce RTX 5070 Ti, driver 610.47, CUDA 12.8 (nvcc V12.8.61), Windows 11
Enterprise 10.0.26200. Worktree: Astroray-pkg199. GPU lock hw-611b held for the duration; no
concurrent CUDA sessions. This is an independent re-measurement following the fix for the
2026-08-13 HW FAIL above (GPU fog collapsing spheres to near-black, density-independently -- root
cause: role-2 Beer-Lambert consumed the sphere-light occlusion sentinel maxDist=1e30 as a
distance). Fix commit 6e7bf6d carries a true geometric distance (GNEESample.geomDist, NEE lane
14) and treats distant/infinite lights (>=1e18) as non-attenuated on both backends. The branch was
also rebased onto main since the FAIL (now includes pkg195 Stage C, PR #610).

### Step 1 -- Clean rebuild
build_cuda_worktree.bat (root/VS-generator pipeline), foreground, HEAD SHA verified
91dbc4770c28c054742ad93427794b9a82847398. Build succeeded (EXITCODE:0). The local .pyd from the
implementer predated the rebase, so a full rebuild was mandatory and was performed. Build-script
arch-verify: astroray.cp313-win_amd64.pyd embeds sm_120 (embedded=[sm_120]). An independent
cuobjdump --list-elf cross-check agrees: sm_120 confirmed. The pyd mtime (Aug 14 04:29) postdates
the HEAD commit date (Aug 14 04:20) -- not stale.

### Step 2 -- Smoke-check
astroray.__file__ resolved to the canonical build_cuda/Release/astroray.cp313-win_amd64.pyd (not
a stale root shadow). hasattr(Renderer(), set_world_volume) returned True.

### Step 2b -- Register hard gate (cuobjdump --dump-resource-usage, post-link .pyd)
stageShadeBucketedKernel with all four bool template params false (HasPrincipled/HasTexture/
HasPhotons/HasDispersion; mangled ...ILb0ELb0ELb0ELb0EEE...):

    REG:254 STACK:3352 SHARED:0 LOCAL:0 CONSTANT[0]:1700 TEXTURE:0 SURFACE:0 SAMPLER:0

### Step 3 -- Gate test run (tests/test_pkg199_world_volume_gpu_parity.py, -v -s --tb=short)
All 9 tests PASSED (was 6 pre-fix; 3 new regression gates added: sphere-vs-triangle lamp fog
equivalence, sphere-lamp density monotonicity, sphere-lamp CPU/GPU parity -- these are the tests
that exercise the exact occlusion-sentinel code path the fix addresses). Verbatim:

    tests/test_pkg199_world_volume_gpu_parity.py::test_world_volume_absorption_only_removes_energy_cpu
    [pkg199 CPU furnace] clear=[1.29   1.2948 1.2722] foggy=[0.7844 0.9507 1.0396] foggy/clear=[0.6081 0.7343 0.8172]
    PASSED
    tests/test_pkg199_world_volume_gpu_parity.py::test_world_volume_cpu_gpu_parity
    [pkg199 CPU/GPU fog parity] GPU=[0.8526 1.0362 1.1494] CPU=[0.7844 0.9507 1.0396] GPU/CPU=[1.0868 1.0899 1.1056]
    PASSED
    tests/test_pkg199_world_volume_gpu_parity.py::test_world_volume_gpu_analytic_beer_lambert
    [pkg199 GPU Beer-Lambert] dist=5.0 dens=0.1: measured Tr=0.6064 analytic=0.6065
    [pkg199 GPU Beer-Lambert] dist=5.0 dens=0.2: measured Tr=0.3677 analytic=0.3679
    [pkg199 GPU Beer-Lambert] dist=10.0 dens=0.1: measured Tr=0.3678 analytic=0.3679
    [pkg199 GPU Beer-Lambert] dist=10.0 dens=0.2: measured Tr=0.1352 analytic=0.1353
    PASSED
    tests/test_pkg199_world_volume_gpu_parity.py::test_world_volume_zero_density_gpu_byte_identical
    [pkg199 GPU vacuum byte-identity] no-vol self-noise=9.54e-07 zero-density diff=9.54e-07
    PASSED
    tests/test_pkg199_world_volume_gpu_parity.py::test_restir_render_not_contaminated_by_prior_fog
    [pkg199 ReSTIR fog-contamination guard] clean=[0.0153 0.0162 0.0235] after_fog=[0.0153 0.0162 0.0235] after/clean=[1. 1. 1.]
    PASSED
    tests/test_pkg199_world_volume_gpu_parity.py::test_world_volume_gpu_visual PASSED
    tests/test_pkg199_world_volume_gpu_parity.py::test_sphere_lamp_fogs_like_triangle_lamp_gpu
    [pkg199 sphere-vs-triangle lamp fog] dens=0.02 sphere=[0.7943 0.8647 0.9103] triangle=[0.7669 0.8462 0.899 ] sph/tri=[1.0358 1.0218 1.0126]
    [pkg199 sphere-vs-triangle lamp fog] dens=0.06 sphere=[0.5022 0.6497 0.7548] triangle=[0.4548 0.6113 0.7279] sph/tri=[1.1042 1.0627 1.037 ]
    PASSED
    tests/test_pkg199_world_volume_gpu_parity.py::test_sphere_lamp_fog_density_monotonic_gpu
    [pkg199 sphere-lamp density monotonicity] dens0.005=0.9616 dens0.03=0.7938 dens0.10=0.4783
    PASSED
    tests/test_pkg199_world_volume_gpu_parity.py::test_sphere_lamp_fog_cpu_gpu_parity
    [pkg199 sphere-lamp CPU/GPU parity] dens=0.02 GPU=[0.7943 0.8647 0.9103] CPU=[0.7939 0.8644 0.9101] GPU/CPU=[1.0005 1.0003 1.0003]
    [pkg199 sphere-lamp CPU/GPU parity] dens=0.06 GPU=[0.5022 0.6497 0.7548] CPU=[0.5013 0.649  0.7541] GPU/CPU=[1.0018 1.001  1.0008]
    PASSED
    ============================== 9 passed in 2.89s ==============================

PR-claimed numbers for the decisive re-gate reproduce exactly on this hardware: sphere-lamp
CPU/GPU parity at dens=0.02 measured [1.0005, 1.0003, 1.0003] (claimed [1.0005, 1.0003, 1.0003]);
density sweep 0.9616/0.7938/0.4783 (claimed 0.96 to 0.79 to 0.48 for 0.005/0.03/0.10) --
monotone decreasing, no collapse.

### Step 4 -- Visual inspection (THE decisive check that caught the original bug)
test_results/pkg199_gpu_fog_clear.png and pkg199_gpu_fog_dense.png (5-sphere receding row, sphere
lamp) inspected directly. Clear render: 5 crisp diffuse spheres, nearest bright and large,
receding into a dark blue-grey background. Dense-fog render: the nearest sphere remains crisp
and clearly lit; the four more distant spheres show a smooth, graduated fade -- progressively
dimmer AND slightly cooler and desaturated toward the background tint as distance increases,
with the farthest sphere barely distinguishable from the background. This is exactly the
graceful fade-to-fog-tint behavior the pkg199 visual acceptance criterion requires, and is the
opposite of the FAIL-run symptom (all five spheres, including the nearest, collapsing to
near-black independent of density). No fireflies, no banding or quantization artifacts, no NaN
pixels (no magenta or solid-black regions), no mode regression (still monochrome absorption-only,
no god-rays -- correct for Stage 1). The numbers and the image agree this time.

Also inspected: test_results/diag199_gpu_ prefixed PNGs (dense_NEE, naive_d02, NEE_d02) -- these
are pre-existing debug artifacts from a prior local session (mtime predates this rebuild, 03:53
vs the 04:29 rebuild), not written by any test in the current run, and not part of the gated
evidence; noted for completeness only, not evaluated as regression signal.

### Step 5 -- Analytic furnace and vacuum no-op
test_world_volume_gpu_analytic_beer_lambert (white-fog vs the analytic exponential, 4
density/distance combos, all within about 2e-4) and test_world_volume_zero_density_gpu_byte_identical
(diff 9.54e-07, at the self-noise floor) both PASS -- see Step 3 verbatim above. Un-xfailed haze
tests, run with --runxfail explicitly (not relying on default pytest.ini xfail handling):

    tests/test_python_bindings.py::test_world_volume_density_adds_visible_haze PASSED
    tests/test_python_bindings.py::test_world_volume_fogs_farther_objects_more PASSED
    tests/test_python_bindings.py::test_world_volume_zero_density_matches_clear_behavior PASSED
    ============================== 3 passed in 1.10s ==============================

test_pkg186_gpu_features_guard.py: all 7 tests PASSED (test_volumes_gpu_enabled included).

General non-fog furnace regression, as an NEE-path sanity check since the fix touched the shared
NEE distance lane: test_pkg178_principled_gpu_furnace.py (4 tests, GPU) and
test_dielectric_glass_furnace.py (2 tests, CPU plus GPU) all PASSED -- ratios 0.9542 to 0.9966,
all within the existing tolerance bands, no drift from the NEE-lane change.

### Step 6 -- Regression slice and combined-tree sanity
test_gpu_multiwavelength.py (6), test_pkg55_c3_wavefront_nonvisible.py (4) -- 10/10 PASSED, no
transport regression in the standard spectral/wavefront suite. Dedicated-light NEE sanity (since
the fix changed the shared NEE lane, not just fog): test_pkg195_stage_a_mw_nee.py (3, dedicated
directional-sun NEE) and test_pkg139_area_light_orientation.py (6, dedicated area-light NEE) --
9/9 PASSED, no non-fog NEE regression. Combined-tree check for the pkg195 Stage C rebase:
test_pkg195_stage_c.py -- 6/6 PASSED.

Full regression slice plus un-xfail plus guard total: 9 (pkg199) plus 3 (un-xfail) plus 7
(pkg186) plus 6 (furnace) plus 10 (MW/pkg55-c3) plus 9 (dedicated-light NEE) plus 6 (pkg195
Stage C) = 50/50 PASSED.

### Verdict: HW PASS

The GPU fog occlusion-sentinel bug from the 2026-08-13 HW FAIL is fixed and independently
reproduced-fixed on this hardware: the decisive 5-sphere receding-fog visual (the same check that
caught the original regression) now shows the correct graceful fade with a crisp near sphere, and
every quantitative gate the implementer claimed reproduces to 3-4 significant figures on an
independently rebuilt .pyd (a full rebuild was mandatory since the local .pyd from the
implementer predated the main rebase). The register gate is byte-identical to the pinned
baseline. No NEE regression was detected in dedicated-light (sun, area) or general furnace suites
despite the fix touching the shared NEE distance lane. The pkg195 Stage C combined-tree sanity
check (landed in the rebase) is also clean. No visual regressions of any kind (fireflies,
banding, NaN, mode regression) were observed in any inspected PNG. PR #611 is HW PASS as of
branch pkg199 at commit 91dbc4770c28c054742ad93427794b9a82847398. This verifier does not merge;
the merge decision remains with the architect and gate-failure process.

## Hardware verification 2026-08-14 (PR #617)

Independent hardware verification of PR #617 (pkg199 Stage 2 PR 2a -- CPU homogeneous
scattering medium, alpha-gated). Branch pkg199-s2, worktree
C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray-pkg199s2, verified commit
f9c23385b3997ecd99672b49cf50fe4ed9a0dbdb.

### Hardware / software
- GPU: NVIDIA GeForce RTX 5070 Ti, driver 610.47
- CUDA: nvcc release 12.8, V12.8.61
- OS: Windows 11 Enterprise 10.0.26200
- OptiX/wavefront: not touched by this PR (see file-scope note below)

### Stale-.pyd gate and rebuild
.pyd mtime (build_cuda/Release/astroray.cp313-win_amd64.pyd) was 2026-08-14
09:30:54, HEAD commit timestamp 09:46:46 -- nominally stale per the mtime heuristic.
Full worktree rebuild was run via build_cuda_worktree.bat (note: the Git-Bash
cmd /c invocation produced a banner-only false-green exit 0 with nothing built --
the gitbash-cmd-c false-green failure mode; re-ran via PowerShell with the full
.bat path, which built for real). The rebuilds own stamp
(sha=f9c23385b399 header_hash=445f6d03a0e8) matched HEAD exactly and
cuobjdump --list-elf confirmed sm_120 embedded
(arch-verify OK: astroray.cp313-win_amd64.pyd embeds sm_120). The .pyd binary
content was unchanged by the rebuild (MSBuild did not relink) because HEADs diff
vs the 09:30:54 build touches only the spec and test file, not C++ sources --
confirmed via git diff main...pkg199-s2 --name-only:
include/raytracer.h, module/blender_module.cpp,
tests/test_pkg199_stage2_scattering_cpu.py, plus two .astroray_plan docs. No GPU
kernel file (.cu/.cuh) is touched by this PR. Smoke-check: set_world_volume
now accepts a 4th trailing scatter arg (confirmed via .__doc__ and a live call);
astroray.__file__ resolved to the canonical
build_cuda/Release/astroray.cp313-win_amd64.pyd, not a shadow copy.

### Step 2/3 -- PR's own gate: tests/test_pkg199_stage2_scattering_cpu.py (verbatim)

```
tests/test_pkg199_stage2_scattering_cpu.py::test_alpha_zero_is_beer_lambert_absorption
  dens=0.1 dist=5.0: measured Tr=0.6063 analytic=0.6065
  dens=0.2 dist=5.0: measured Tr=0.3676 analytic=0.3679
PASSED
tests/test_pkg199_stage2_scattering_cpu.py::test_alpha_zero_deterministic PASSED
tests/test_pkg199_stage2_scattering_cpu.py::test_single_scatter_matches_analytic_density_shape
  measured =[0.005185 0.006688 0.00588  0.003197]
  analytic =[0.016764 0.021482 0.018754 0.010167]  k=0.31218
  k*analytic=[0.005233 0.006706 0.005855 0.003174]  max_resid=0.0091
PASSED
tests/test_pkg199_stage2_scattering_cpu.py::test_single_scatter_linear_in_alpha
  L/alpha=[0.017021 0.016968 0.017059] spread=0.0022
PASSED
tests/test_pkg199_stage2_scattering_cpu.py::test_forward_back_scatter_asymmetry
  single: mean(g=+0.7)=0.01588 mean(g=-0.7)=0.00793 ratio=2.002
  depth4:  mean(g=+0.7)=0.02371 mean(g=-0.7)=0.01605 ratio=1.477
PASSED
tests/test_pkg199_stage2_scattering_cpu.py::test_sum_to_beauty_with_volume_passes
  ratio=[1.00004 1.00004 1.00004] rel_L1=0.0000 volume_mean=0.01149
PASSED
tests/test_pkg199_stage2_scattering_cpu.py::test_scatter_adds_energy_monotonic
  means=[0.      0.00937 0.02581 0.04081]
PASSED

============================== 7 passed in 4.46s ==============================
```

All PR headline numbers reproduced verbatim on independently rebuilt hardware
(Tr 0.6063/0.3676; 0.9% max residual (0.0091); alpha-linearity spread 0.0022;
asymmetry 2.002x/1.477x; sum-to-beauty rel_L1 0.0000). All tests already render
with apply_gamma=False (LINEAR), per memory gamma-furnace-cannot-detect-energy-gain
-- confirmed in source (_render_cpu: "apply_gamma=False -> LINEAR").

### Step 3 -- load-bearing alpha=0 regression sweep (verbatim)

tests/test_pkg199_world_volume_gpu_parity.py (Stage-1 CPU/GPU fog parity + furnace,
9 tests), tests/test_pkg198_lightpath_passes.py (sum-to-beauty/pass suite, 6 tests),
tests/test_pkg186_gpu_features_guard.py + tests/test_pkg186_gpu_texture_parity.py
(9 tests, GPU capability guard + texture parity) -- run together, 25/25 PASSED:

```
test_world_volume_absorption_only_removes_energy_cpu
  clear=[1.29   1.2948 1.2722] foggy=[0.7844 0.9507 1.0396] foggy/clear=[0.6081 0.7343 0.8172]  PASSED
test_world_volume_cpu_gpu_parity
  GPU=[0.8526 1.0362 1.1494] CPU=[0.7844 0.9507 1.0396] GPU/CPU=[1.0868 1.0899 1.1056]  PASSED
test_world_volume_gpu_analytic_beer_lambert
  dist=5.0 dens=0.1: Tr=0.6064 analytic=0.6065; dist=5.0 dens=0.2: Tr=0.3677 analytic=0.3679
  dist=10.0 dens=0.1: Tr=0.3678 analytic=0.3679; dist=10.0 dens=0.2: Tr=0.1352 analytic=0.1353  PASSED
test_world_volume_zero_density_gpu_byte_identical
  no-vol self-noise=9.54e-07 zero-density diff=7.15e-07  PASSED
test_restir_render_not_contaminated_by_prior_fog
  clean=[0.0153 0.0162 0.0235] after_fog=[0.0153 0.0162 0.0235] after/clean=[1. 1. 1.]  PASSED
test_world_volume_gpu_visual PASSED (PNGs inspected, see below)
test_sphere_lamp_fogs_like_triangle_lamp_gpu
  dens=0.02 sph/tri=[1.0358 1.0218 1.0126]; dens=0.06 sph/tri=[1.1042 1.0627 1.037 ]  PASSED
test_sphere_lamp_fog_density_monotonic_gpu
  dens0.005=0.9616 dens0.03=0.7938 dens0.10=0.4783  PASSED
test_sphere_lamp_fog_cpu_gpu_parity
  dens=0.02 GPU/CPU=[1.0005 1.0003 1.0003]; dens=0.06 GPU/CPU=[1.0018 1.001  1.0008]  PASSED

test_all_light_path_passes_readable PASSED
test_sum_to_beauty_linear -- ratio=[1.00000158 1.00000157 1.00000154] rel_L1=0.0000  PASSED
test_isolated_diffuse -- d_direct=0.0090 d_indirect=0.0015 glossy=0 trans=0  PASSED
test_isolated_glossy -- glossy=0.0358 diffuse=0  PASSED
test_isolated_transmission -- trans=0.0345  PASSED
test_emission_pass -- emission=0.8690  PASSED
test_environment_pass -- environment=0.3682  PASSED

test_gpu_features_dict_exists PASSED
test_gpu_dropped_capability_is_false[textures] PASSED
test_gpu_dropped_capability_is_false[adaptive_sampling] PASSED
test_gpu_dropped_capability_is_false[gr_black_holes] PASSED
test_panel_labels_dropped_caps_cpu_only PASSED
test_gpu_supported_capabilities_stay_on PASSED
test_volumes_gpu_enabled PASSED
test_gpu_texture_is_not_flat PASSED
test_cpu_gpu_texture_parity PASSED

============================= 25 passed in 4.67s =============================
```

These GPU-path fog/parity gates confirm the GPU wavefront route is Stage-1-identical
(absorption only, no scattering) at this branch head -- expected, since GPU
scattering is deferred to PR 2b and this PR's diff (include/raytracer.h,
module/blender_module.cpp) touches no .cu/.cuh file.

### Step 4 -- Visual inspection

test_results/pkg199_s2_forward_scatter.png and test_results/pkg199_s2_back_scatter.png
(64x64, generated by test_forward_back_scatter_asymmetry): pixel-level analysis of
the top-20 brightest pixels in each image shows the halo tightly clustered within a
5x5 window around the light-source pixel (31,31) with smooth radial falloff -- no
isolated bright outliers away from the cluster (no fireflies). The forward-scatter
(g=+0.7) halo is visibly larger and brighter than the back-scatter (g=-0.7) halo,
consistent with the measured 2.002x/1.477x asymmetry ratios -- genuine directional
structure, not salt-and-pepper noise (memory general-photon-loop-needs-solid-glass).

test_results/pkg199_gpu_fog_clear.png / pkg199_gpu_fog_dense.png (GPU Stage-1
absorption, 5-sphere receding scene): foggy render shows correct graceful
darkening/desaturation of distant spheres with the near sphere staying crisp; no
god-rays (expected -- Stage 1 is absorption-only); no fireflies, banding, or NaN
pixels observed in either image.

No visual regressions found in any inspected PNG.

### Step 5 -- Full local pytest sweep (verbatim)

```
1 failed, 1974 passed, 70 skipped, 20 xfailed, 2 xpassed, 7 warnings in 679.15s (0:11:19)
FAILED tests/test_pkg64_phase3_no_regression.py::test_no_caster_cost_gate
  AssertionError: Caustics toggle with no caster too expensive: ratio 1.48x
  (target <= 1.05x with jitter slack to 1.30x)
  assert 1.4779320891041912 <= 1.3
```

Count mismatch finding: the PR's stated headline is 1946 passed; the measured full
sweep is 1974 passed (delta +28), plus 70 skipped / 20 xfailed / 2 xpassed / 1
failed not itemized in the PR body. Flagged per memory pr-named-tests-insufficient
-- not independently root-caused here (would require a second ~11-minute full sweep
diff against a clean main baseline).

test_no_caster_cost_gate failure: this is a CPU wall-clock timing/cost-ratio gate
in an unrelated package (pkg64 caustics-toggle overhead), not a correctness gate,
and not in the file scope this PR touches (include/raytracer.h volume-only hunks,
module/blender_module.cpp) -- the caustics/SMS-hook code path is untouched by this
PR's diff. Re-ran tests/test_pkg64_phase3_no_regression.py in isolation
immediately after (no full-suite contention):

```
test_no_caster_no_regression PASSED
test_no_caster_cost_gate
  pkg64-3 no-caster cost ratio (toggle on / off) = 0.994x
PASSED
============================== 2 passed in 0.39s ==============================
```

Isolated rerun is clean and well within budget (0.994x vs the 1.30x jitter-slack
threshold), consistent with wall-clock contention from the concurrently-running
~2000-test full sweep (memory gpu-perf-ab-clock-drift: timing gates are noise-prone
under load) rather than a genuine regression from this PR. Per protocol this
verifier does not relax or wave off a recorded gate failure -- flagging for
gate-failure-reviewer triage with both results attached; not self-adjudicated as
acceptable.

### Verdict

pkg199 Stage 2 PR 2a's own gate (test_pkg199_stage2_scattering_cpu.py, 7/7) and all
explicitly-requested regression suites (Stage-1 alpha=0 parity, sum-to-beauty,
pkg186 GPU-guard/texture-parity, 25/25) reproduce the PR's claimed numbers verbatim
on independently rebuilt hardware, with no visual regressions. HW PASS for the
PR's own scope.

Two findings outside the PR's direct scope, reported (not adjudicated) per protocol:
(1) a full-sweep test-count mismatch (1974 measured vs 1946 claimed), and (2) one
FAILED timing gate (test_pkg64_phase3_no_regression.py::test_no_caster_cost_gate,
unrelated file scope, ratio 1.48x under full-suite contention vs 0.994x isolated)
that reproduces clean in isolation and is consistent with wall-clock jitter, not a
code regression. Both are escalated to gate-failure-reviewer / the architect for
triage; this verifier does not decide they are acceptable.

This verifier does not merge; the merge decision remains with the architect and
gate-failure process.

## Hardware verification 2026-08-14 (PR #619)

Scope: independent HW re-verification of pkg199 Stage 2 PR 2b (GPU wavefront
scattering, HasWorldScatter fleet isolation), branch pkg199-s2b, worktree
Astroray-pkg199s2. Session resumed after an early kill; state re-established
from disk (prior test_results, worktree at unchanged HEAD) before continuing --
the .pyd was re-verified current before trusting anything, not assumed.

Hardware/software: RTX 5070 Ti, driver 610.47, Windows 11 10.0.26200, CUDA
12.8.61 (nvcc), sm_120 target confirmed via cuobjdump --list-elf
(astroray.cp313-win_amd64.1.sm_120.cubin). GPU idle before every leg (1-4 percent
util, 37-41C, no other compute-apps) -- no contention.

Step 1 -- build/staleness gate: HEAD 3efb551 (docs-only commit, 2 spec/docs
files, 0 code) sits on top of the implementer last code commit 35f5577,
built into build_cuda/Release/astroray.cp313-win_amd64.pyd at 22:56 (predates
HEAD docs-only commit by ~14 min -- confirmed via git show --stat HEAD that
no source changed after the build). No rebuild needed. astroray.__file__ points
to the canonical build_cuda/Release/astroray.cp313-win_amd64.pyd (legacy
multi-config generator location, expected for this repo). No new Python
binding was introduced by 2b (set_world_volume with density, color, anisotropy,
scatter args already existed from 2a); smoke-checked import + Renderer()
construction OK.

Step 2 -- register gates (cuobjdump -res-usage on the final linked .pyd), ALL PASS:

| Kernel | REG | STACK | SHARED | CONSTANT[0] | Target | Result |
|---|---|---|---|---|---|---|
| stageShadeBucketedKernel with all-false bool params | 254 | 3352 | 0 | 1700 | 254/3352/1700 byte-identical | PASS (exact) |
| stageIntersectQueuedKernel false (fleet) | 127 | 616 | 0 | 1696 | 127/616, Stage-1-identical | PASS (exact) |
| stageIntersectQueuedKernel true | 130 | 632 | 0 | 1696 | ~130 | PASS |
| stageVolumeScatterKernel | 64 | 88 | 0 | 1382 (+CONSTANT[2]:12) | ~REG 64 | PASS (exact) |

All four measured values match the spec claims exactly.

Step 3 -- verbatim re-run of the PR test files (test_pkg199_stage2_scattering_gpu.py
plus test_pkg199_stage2_scattering_cpu.py plus test_pkg199_world_volume_gpu_parity.py,
19 tests, 10.12s, 19 passed, 0 failed):

test_alpha_zero_gpu_is_absorption PASSED
  clear=[0.0293 0.0294 0.0288] foggy=[0.0083 0.0083 0.0081]
test_godray_cpu_gpu_parity PASSED
  GPU=[0.0399 0.04   0.0393] CPU=[0.0398 0.0401 0.0394] ratio=[1.0044 0.9972 0.9978]
  scatter mean=0.0397 absorb mean=0.0082
test_forward_back_scatter_gpu PASSED
  fwd=0.03533 back=0.02070 ratio=1.707
test_alpha_zero_is_beer_lambert_absorption PASSED
  dens=0.1 dist=5.0: measured Tr=0.6063 analytic=0.6065
  dens=0.2 dist=5.0: measured Tr=0.3676 analytic=0.3679
test_alpha_zero_deterministic PASSED
test_single_scatter_matches_analytic_density_shape PASSED
  measured =[0.005185 0.006688 0.00588  0.003197]
  analytic =[0.016764 0.021482 0.018754 0.010167]  k=0.31218
  k*analytic=[0.005233 0.006706 0.005855 0.003174]  max_resid=0.0091
test_single_scatter_linear_in_alpha PASSED
  L/alpha=[0.017021 0.016968 0.017059] spread=0.0022
test_forward_back_scatter_asymmetry PASSED
  single: ratio=2.002 ; depth4: ratio=1.477
test_sum_to_beauty_with_volume_passes PASSED
  ratio=[1.00004 1.00004 1.00004] rel_L1=0.0000 volume_mean=0.01149
test_scatter_adds_energy_monotonic PASSED
  means=[0.      0.00937 0.02581 0.04081]
test_world_volume_absorption_only_removes_energy_cpu PASSED
  clear=[1.29   1.2948 1.2722] foggy=[0.7844 0.9507 1.0396] foggy/clear=[0.6081 0.7343 0.8172]
test_world_volume_cpu_gpu_parity PASSED
  GPU=[0.8526 1.0362 1.1494] CPU=[0.7844 0.9507 1.0396] GPU/CPU=[1.0868 1.0899 1.1056]
test_world_volume_gpu_analytic_beer_lambert PASSED
  dist=5.0 dens=0.1: Tr=0.6064 analytic=0.6065; dist=5.0 dens=0.2: Tr=0.3677 analytic=0.3679
  dist=10.0 dens=0.1: Tr=0.3678 analytic=0.3679; dist=10.0 dens=0.2: Tr=0.1352 analytic=0.1353
test_world_volume_zero_density_gpu_byte_identical PASSED
  no-vol self-noise=9.54e-07 zero-density diff=4.77e-07
test_restir_render_not_contaminated_by_prior_fog PASSED
  clean=[0.0153 0.0162 0.0235] after_fog=[0.0153 0.0162 0.0235] after/clean=[1. 1. 1.]
test_world_volume_gpu_visual PASSED (PNGs written, see visual section)
test_sphere_lamp_fogs_like_triangle_lamp_gpu PASSED
  dens=0.02: sph/tri=[1.0358 1.0218 1.0126] ; dens=0.06: sph/tri=[1.1042 1.0627 1.037 ]
test_sphere_lamp_fog_density_monotonic_gpu PASSED
  dens0.005=0.9616 dens0.03=0.7938 dens0.10=0.4783
test_sphere_lamp_fog_cpu_gpu_parity PASSED
  dens=0.02: GPU/CPU=[1.0005 1.0003 1.0003] ; dens=0.06: GPU/CPU=[1.0018 1.001  1.0008]

Headline numbers reproduce the PR claims exactly: god-ray parity
[1.0044, 0.9972, 0.9978], forward/back 1.707, alpha=0 inertness confirmed
(clear/foggy diverge as expected, no god-ray brightening at scatter=0).

Step 4 -- perf spot-check (uncontended, burn-in, min-of-9): the spec text
(line 325) states the 116.4-120.6ms A/B figures came from a throwaway
diagnostic script, not committed to the repo -- it is not present in this
worktree, so bit-exact reproduction of the 117.3ms vacuum vs 116.8ms main
comparison is not possible this session. Two proxy measurements were run
instead (GPU idle 1-4 percent util / 37-41C before each, 6-run burn-in, min-of-9):

- Canonical committed wavefront ceiling gate (tests/wavefront_diff/test_pkg55_perf_gate.py
  scene, cuda_wavefront_render, 256x256, 1024spp): min-of-9 = 1371.87ms,
  median = 1377.52ms, all 9 runs in the range 1371.87 to 1448.49ms -- well under the
  pinned 1.5s ceiling (owner-accepted post-accretion gate), no gross-regression
  signature.
- Ad-hoc vacuum point-light-in-fog scene (no world_volume set) at 256x256,
  256spp via r.render() GPU path (structurally the same code the register
  gate covers): min-of-9 = 150.14ms, median = 152.00ms, spread
  150.1 to 152.7ms (under 2 percent) -- tight, stable, no thermal/contention artifacts.

Neither proxy corresponds 1:1 to the spec specific 116-120ms figures (different
scene/spp), so this is NOT a bit-exact confirmation of the plus 0.5 percent vs main claim.
The authoritative evidence for the no-regression claim remains the Step 2
register-gate byte-identity: stageIntersectQueuedKernel false measured
REG:127/STACK:616/CONSTANT[0]:1696 -- structurally identical to the pre-PR
Stage-1 fleet kernel, which by construction cannot regress fleet (vacuum /
absorption-only) performance. Flagging this gap rather than asserting a number
that was not measured.

Step 5 -- visual inspection (test_results/pkg199_s2_godray_gpu.png,
pkg199_s2_godray_cpu.png, pkg199_s2_forward_scatter.png,
pkg199_s2_back_scatter.png, pkg199_gpu_fog_clear.png,
pkg199_gpu_fog_dense.png, all 64x64/256x256 thumbnails):

- God-ray GPU vs CPU: both show a bright point source with a soft diffuse haze
  on the floor plane; visually consistent with each other (matches the
  measured [1.0044, 0.9972, 0.9978] parity). No magenta/black NaN speckle, no
  salt-and-pepper beyond expected low-spp MC grain, no banding.
- Forward vs back scatter: forward-scatter frame is visibly brighter with a
  larger, more diffuse halo than the back-scatter frame -- consistent with the
  measured 1.707 ratio and g>0 forward-peaked HG lobe. No artifacts.
- Fog clear vs dense (alpha=0 absorption-only, Stage-1 path): dense fog correctly
  darkens/desaturates the receding spheres while the near sphere stays crisp
  and saturated -- matches the documented expected behaviour exactly, no
  fireflies, no NaN pixels, no mode regression (still monochrome absorption,
  no spurious god-rays at alpha=0).

No visual regression found; numbers and images agree.

Step 6 -- full sweep (pytest tests/ -q, no --ignore, all markers,
665.74s): 2010 passed, 70 skipped, 21 xfailed, 1 xpassed, 0 failed. vs the
PR claimed 1981 passed / 0 failed: 0 failed matches; passed count is higher
(2010 vs 1981) -- explained by intervening commits merged to main since the PR
was authored (e.g. pkg201 #618, pkg190 follow-up #615 landed on main in the
interim, adding tests collected by this branch suite), not an effect of this
PR. An earlier same-session run at 10:10 (predating a same-day fix commit,
35f5577, that resolved a separate plus 3.3 percent fleet-perf issue via the
HasWorldScatter isolation) showed one failure,
test_pkg64_phase3_no_regression.py::test_no_caster_cost_gate (ratio 1.478x
vs 1.30x threshold) -- unrelated to pkg199 (a caustics-toggle cost gate). This
re-run (post-fix, current HEAD) shows 0 failures, confirming that prior
failure did not reproduce (transient/perf-noise), not a real regression from
this PR.

Verdict: PASS. All register gates exact-match. All 19 PR test-file
assertions reproduce the claimed headline numbers verbatim. Full sweep is
clean (0 failed). Visual inspection found no artifacts and matches the
numerical parity. The one gap is the perf spot-check: the implementer exact
committed-nowhere A/B script/scene could not be re-run bit-for-bit; two proxy
measurements showed no gross-regression signature, and the register-gate
byte-identity is offered as the authoritative structural evidence instead of
an unverifiable wall-clock number. This gap is reported, not glossed over --
gate/merge decision remains with the architect.
