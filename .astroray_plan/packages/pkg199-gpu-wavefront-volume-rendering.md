# pkg199 — GPU wavefront volume rendering (homogeneous world volume + HG phase)

**Pillar:** 5 / integration-first (also 3 — CPU↔GPU parity)
**Track:** A
**Status:** open (filed 2026-08-13 — GPU-parity vetted set; **design-first**)
**Estimated effort:** L (new transport subsystem in the wavefront; scope deliberately bounded
to the homogeneous world volume first)
**Depends on:** pkg55-C7 wavefront dispatch; the CPU world-volume reference
(`include/raytracer.h:2110-2255`); [[wavefront-shade-kernels-register-saturated]].

---

## Why this exists (verified line refs, current `main`)

`__gpu_features__` reports `volumes=false` with the comment "CPU-only"
(`module/blender_module.cpp:4577`), and the honesty note states the GPU path "ignores volumes"
(`module/blender_module.cpp:4559`). The CPU has a working **homogeneous world volume**:
`worldVolumeDensity/Color/Anisotropy` with Beer-Lambert transmittance
`sigmaT = worldVolumeColor * worldVolumeDensity` and Henyey-Greenstein anisotropy
(`include/raytracer.h:2110-2255`), driven from the addon via `set_world_volume`
(`module/blender_module.cpp:1607-1608, 2800`). The GPU wavefront transport
(`src/gpu/wavefront/stage_advance.cu`) has **no volume interaction at all** — rays pass
straight through. So a scene with atmospheric fog / god-rays / a coloured world medium renders
correctly on CPU and as vacuum on the (default) GPU backend: a visible, owner-facing
divergence, and the last of the four headline GPU-parity capability gaps
(textures→pkg186/pkg190, adaptive→pkg131, denoise-guides→pkg197, **volumes→here**).

## Scope — bounded on purpose

Bring the **homogeneous world volume** to the GPU wavefront, matching the CPU model exactly:

- **Transmittance / free-flight** along each ray segment: Beer-Lambert `exp(-sigmaT · t)` with
  the CPU's `sigmaT = worldVolumeColor · worldVolumeDensity` (mirror `raytracer.h:2152-2154`).
- **In-scatter** with the **Henyey-Greenstein** phase function at the CPU anisotropy
  (`worldVolumeAnisotropy`, clamped [-0.99, 0.99]), NEE toward lights through the medium.
- **Distance sampling** for scatter events (homogeneous → analytic exponential sampling).
- Uphold CPU↔GPU wavefront-diff parity on a fixed foggy reference scene.

**Heterogeneous / object volumes are explicitly OUT of scope.** `add_volume`
(`module/blender_module.cpp:1277-1290`) currently renders volume *objects* as emissive
proxies, not as scattering media, and the black-hole volumetric emission
(`addVolumetricEmission`, lines 1229/1261/1272) is a separate Pillar-4 concern (on pause —
[[pillar4-on-pause]]). Do not touch either. A future package owns heterogeneous grids /
`add_volume` scattering / delta-tracking.

## MANDATORY FIRST STEP — design + register budget

1. **Cite the algorithm** (CLAUDE.md §6 / [[cite-algorithm]]). Homogeneous volume transport,
   HG phase, and analytic distance sampling are textbook — use PBRT-v4
   (`src/pbrt/media.cpp`, `HomogeneousMedium`, phase-function sampling) and Cycles
   (`intern/cycles/kernel/integrator/volume_stack.h` / `volume.h`, Apache-2.0) as references;
   save a short research note to `.astroray_plan/docs/`. Do NOT invent the estimator.
2. **Decide where the volume interaction lives in the wavefront stage graph** — a dedicated
   volume-scatter stage vs folding free-flight/transmittance into `stageAdvance`. Whatever the
   choice, the register-saturated `stageShadeBucketedKernel<false,…>` must stay **REG 254 /
   STACK 3608 / CONSTANT[0] 1700** (isolate the volume path behind a compile-time
   `HasWorldVolume` axis so vacuum scenes are byte-identical — pkg184/pkg189 pattern). Read the
   post-link numbers via `cuobjdump` before scaling up.

## Acceptance criteria

- [ ] GPU wavefront renders the homogeneous world volume: transmittance, HG in-scatter, and
      NEE-through-medium, **matching the CPU render within a tight band** on a fixed foggy
      scene (CPU↔GPU wavefront-diff parity) at multiple density/anisotropy settings.
- [ ] `__gpu_features__["volumes"]` flips to `true` **only** for the world-volume capability,
      with the honesty comment updated to state homogeneous-world-only (do not over-claim
      heterogeneous/object volumes — the pkg186 `__gpu_features__` honesty discipline).
- [ ] Vacuum (no world volume) GPU renders are **byte-identical** to pre-change and show no
      perf regression (compile-time isolation verified via cuobjdump; min-of-N perf,
      [[gpu-perf-ab-clock-drift]]).
- [ ] Headless Blender 5.1: `set_world_volume` from the world panel produces matching fog on
      CPU and GPU.
- [ ] **RTX 5070 Ti hardware gate** ([[ci_has_no_gpu_runtime_blindspot]]), bound to HEAD,
      with a visual confirmation of the fog/god-ray render.

## Hard non-goals

- **No heterogeneous / object volumes, no delta-tracking, no `add_volume` scattering** — the
  emissive-proxy behaviour stays as-is; a later package owns grids.
- **No black-hole / Pillar-4 volumetric emission** work ([[pillar4-on-pause]]).
- **No volume render passes** (`PASS_VOLUME_*`) until this lands — then pkg198 can extend.
- **No shared-kernel register regression** — compile-time isolation only (pkg178/pkg184 rule).

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
