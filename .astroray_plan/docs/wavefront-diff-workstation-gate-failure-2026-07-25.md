# wavefront_diff gate failures on unmodified MAIN — root-cause analysis (2026-07-25)

**Scope:** read-only diagnosis. No GPU re-runs (evidence already captured), no
code changes, no threshold edits. Names the two most-likely causes per failure
class and the exact discriminating measurement for each, runnable in a later
GPU-lock-holding session.

**Subject commit:** MAIN @ `8c49bbb` (fresh `.pyd`). Failures reproduce
bit-deterministically across two runs: `pkg141_wavefront_diff.txt` (pkg141
worktree, i.e. WITH PR #518) and `pkg141_wavefront_diff_rerun.txt` (unmodified
main). The two runs are near-identical — the failures are a property of MAIN,
not of any PR. Hardware: RTX 5070 Ti workstation.

## TL;DR

- These are NOT laptop-pinned thresholds. Every failing gate's baseline was
  measured on this same RTX 5070 Ti on 2026-06-11 (recorded verbatim in the
  test docstrings). They are genuine on-hardware regressions introduced
  between 2026-06-11 and 2026-07-25.
- Ratio gates (3 tests): a GPU-side, R-channel-specific color drift of +5-6%
  since 06-11. Both GPU pipelines (wavefront and megakernel) moved together
  (they agree with each other to 0.3%) while diverging identically from the CPU
  oracle. Deterministic, SPP-independent -> a units/color-space / light-energy
  change, per memory mc-noise-vs-deterministic. Do NOT re-baseline blind.
- Perf gate: wavefront 0.90x vs the 1.30x floor, which was measured on this box
  (1.41-1.46x, 2026-06-11 evening). Real regression: the wavefront accreted ~6
  feature commits since (TLAS, multiwavelength, always-on MIS instrumentation,
  photon hooks, ReSTIR SoA) the megakernel did not.
- SSIM flake: SSIM is the wrong gate for independent-RNG noisy caustics
  (memory ssim-wrong-gate-for-independent-rng); the real signal is the ~24%
  peak-luminance deficit (WF 1.208 vs MW 1.591), a probable photon under-gather.
- PR #518 is not implicated and must not be blocked by these. Its own evidence
  (pkg141 worktree) shows the SAME ratios as unmodified main.

## Failure class 1 — the three ratio gates (R-channel high ~13-15%)

Measured vs baseline (same RTX 5070 Ti):

| Gate | 2026-06-11 baseline (docstring) | 2026-07-25 measured | R drift |
|------|--------------------------------|---------------------|---------|
| test_gpu_wavefront_final_image_mean_ratio | [1.089, 0.991, 1.045] | [1.153, 1.007, 1.068] | +0.064 |
| test_megakernel_open_env_scene_mean_ratio | [1.091, 0.993, 1.050] | [1.148, 1.007, 1.069] | +0.057 |
| test_megakernel_world_max_bounces_env_gate | [1.085, 0.999, 1.035] | [1.133, 1.008, 1.046] | +0.048 |

Gate = |ratio-1| <= 0.12. In 06-11 the R residual was ~0.09 (inside the gate
with headroom); today it is ~0.13-0.15 (just over). G ~= 1.00 unchanged, B up
slightly. The regression is almost entirely in R and entirely on the GPU side
(the perf gate independently reports WF/MK image ratio [0.9976, 0.9978, 0.9971]
— the two GPU pipelines are identical to each other; only the GPU-vs-CPU-oracle
gap moved). Signature from memory mc-noise-vs-deterministic: a stable
per-channel ratio that does not shrink with SPP is a units / color-space /
light-energy bug, not RNG.

### Suspect 1A — GPU dedicated-light energy re-derivation (#489 pkg89-GPU, and/or #500 pkg122)

- Evidence: #489 (2026-07-20) rewrote GPU NEE light energy — src/gpu/gpu_nee.cuh
  (+151), src/gpu/multiwavelength_kernel.cu, src/gpu/scene_upload.cu,
  src/gpu/wavefront/stage_advance.cu, src/emission_spectrum.cpp ("energy
  audit"). #500 (2026-07-21) then re-derived dedicated-light wattage->radiance
  vs Cycles (AREA/POINT/SPOT/DISTANT/blackbody) touching emission_spectrum.cpp,
  gpu_nee.cuh and all four src/lights/*.cpp. Both env-Cornell scenes are lit by
  3 dedicated lights; a warmer (higher-R) re-derived emission or a GPU-only NEE
  energy change raises GPU R vs the CPU oracle exactly as seen. The drift is
  largest on the light-dominated open-env scene.
- Test to distinguish (GPU-lock): bisect on the megakernel ratio. Check out
  41101a5^ (pre-#489), rebuild, run
  tests/wavefront_diff/test_pkg55_megakernel_env_open_scene.py. If R returns to
  ~1.09 it is the light-energy arc (#489/#500). Cheaper (no rebuild): in
  session_n1_envmap_cornell zero the dedicated lights (env-only). If the R
  drift vanishes with lights removed it is the light path; if it persists it is
  not.

### Suspect 1B — shared spectral-table extraction (#481 pkg55-C1)

- Evidence: #481 (2026-07-18) extracted src/gpu/gpu_spectral_tables.cu (+326) /
  .h (+150) out of multiwavelength_kernel.cu (-365) and path_trace_kernel.cu
  (-39). This is the RGB->spectral (Jakob-Hanika LUT) / CMF / D65 machinery now
  shared by both GPU pipelines — which precisely explains why WF and MK moved
  together while the CPU oracle (separate CPU spectral path) did not. A refactor
  that changes a table's sampling, normalization, or a float literal shifts GPU
  color deterministically and per-channel. R is the channel most sensitive to
  JH-LUT clamping (memories rough-glass-residual-is-multiscatter,
  gpu-dielectric-lowers-to-closure-graph: eta^2 / rgb>1 clamps bite R first).
- Test to distinguish: check out a7f09d1^ (pre-#481), rebuild, run the
  megakernel ratio gate. If R returns to ~1.09 it is the spectral-table
  extraction. Combined with the 1A env-only test this fully partitions the
  cause: {drift survives env-only render} AND {drift disappears at a7f09d1^} =>
  spectral tables; {drift dies with lights removed} => light energy.

Only two suspects are listed per protocol. #490 (TLAS), #494 (photon), #486
(multiwavelength) are ruled lower because they do not touch the constant-color
spectral/light path a stable per-channel R shift requires.

## Failure class 2 — perf gate (wavefront 0.90x < 1.30x floor)

[perf-gate] MK 0.585s WF 0.647s speedup 0.90x on the disney_contact_sheet,
256x256, 512 spp. The 1.30x floor was measured on THIS RTX 5070 Ti (perf-gate
docstring: "stable 1.41-1.46x @ 512spp on RTX 5070 Ti, 2026-06-11 evening"). So
the wavefront went from 1.46x faster to 10% slower than the megakernel on the
same box — a real regression, not a laptop baseline, and too large (38% swing)
for thermal/clock alone.

### Suspect 2A — wavefront intersect/shade overhead accreted since 06-11

- Evidence: since the 1.46x baseline the wavefront (src/gpu/wavefront/) gained,
  in order: MIS-audit always-on instrumentation stores (#484; stage_advance.cu
  ~line 401, "Pure stores to instrumentation arrays" that execute every
  NEE-firing slot in the render path — only bit-identical, not free), a naive
  multiwavelength branch (#486), TLAS/instancing two-level traversal (#490),
  and photon-caustic hooks (#494). The megakernel gained none of these on the
  timed r.render path. Extra per-bounce global writes plus the added TLAS
  indirection on a non-instanced contact-sheet scene erode the wavefront's
  coherence advantage.
- Test to distinguish: bisect the perf ratio. Check out 5455850^ (pre-#484, the
  1.46x-era tree), rebuild, run tests/wavefront_diff/test_pkg55_perf_gate.py. If
  it returns to ~1.4x the regression is the post-06-11 feature stack; then
  re-time at 40c9ef7^ (pre-TLAS #490) to attribute the largest single step.
  Cheaper: Nsight-profile one cuda_wavefront_render and compare stage_intersect
  + stage_advance kernel time to the megakernel path-trace kernel time.

### Suspect 2B — megakernel got faster / harness or thermal skew

- Evidence: the gap could also be the megakernel side improving (e.g. #515
  firefly-clamp / other MW-path work) narrowing the ratio, or a harness
  artifact: the perf test warms with 64 spp then times a single 512-spp render
  each (no repeat/median). A single cold-clock or shared-process sample (the
  SSIM/ratio tests run in the same process) skews one leg; 0.90x with MK 0.585 /
  WF 0.647 is close enough that a ~15% one-leg skew flips it.
- Test to distinguish: run the perf gate 5x in isolation (GPU lock held, nothing
  else on the device); report median + spread. Median ~1.3-1.4x with 0.90x an
  outlier => harness/thermal (re-baseline the measurement protocol to
  median-of-N, not the kernel). Reproducible ~0.9x median => genuine 2A
  regression.

## Failure class 3 — test_wavefront_photon_caustic_parity SSIM flake

SSIM=-0.0000, peak WF=1.208 MW=1.591, same signature for weeks
(tests/test_pkg55_c5_photon_wavefront.py, gate SSIM >= 0.80). Compares the
wavefront photon route vs the MW-megakernel baseline, both GPU, independent RNG,
64 spp, on the pkg113 glass-sphere caustic.

### Suspect 3A — SSIM is the wrong gate for independent-RNG noisy caustics

- Evidence: SSIM = -0.0000 (zero structural correlation) is the textbook result
  of windowing two independent noisy MC caustic renders at modest spp — exactly
  memory ssim-wrong-gate-for-independent-rng (windowed SSIM unreachable for
  independent streams; use per-channel mean-ratio). A sharp glass caustic at 64
  spp is nearly all high-variance speckle, so per-window covariance is ~0 even
  when both images are individually correct.
- Test to distinguish: re-render both legs at 512+ spp and compare mean ratio
  and peak, not SSIM. If mean ratio -> ~1.0 as spp climbs while SSIM stays low,
  the metric is wrong (convert to mean-ratio + peak-ratio like the other pkg55
  gates).

### Suspect 3B — real wavefront photon under-gather (~24% peak deficit)

- Evidence: peak WF 1.208 vs MW 1.591 is a 24% brightness deficit in the
  wavefront caustic that is NOT noise (peak luminance is biased; independent
  noise alone would not systematically dim WF). Echoes memory
  photon-caustic-exit-refraction-oriented-normal: forward photon loops must use
  the geometric outward normal for the exit eta^2 — a wrong exit factor or a
  smaller gather-kernel radius in the new wavefront gather (#494) under-collects
  flux. src/gpu/photon_caustic.cu / include/astroray/gpu_photon_caustic.h are
  the surfaces.
- Test to distinguish: at high spp, if WF peak stays ~20-25% below MW it is a
  genuine gather bug — diff the wavefront gather's eta / kernel-radius /
  photon-count constants against the MW baseline in photon_caustic.cu.

## Recommendation

1. Do NOT re-baseline the ratio or perf thresholds yet. All three baselines were
   set on this exact GPU on 2026-06-11; the drift is a real, deterministic
   post-06-11 change, not a laptop->workstation move. Re-baselining now would
   bake a silent GPU color/perf regression into the gate. NEXT_STAGE_REPORT's
   "laptop-pinned observations may differ" warning does NOT apply to these three
   — their docstrings pin them to the 5070 Ti.
2. Bisect the ratio gate across the two candidate arcs (a7f09d1^ for the
   spectral-table extraction #481; 41101a5^ for the light-energy audit
   #489/#500) using the discriminators above. Expected: one commit restores R to
   ~1.09.
   - Caveat / possible re-baseline path: if the bisect lands on #500 (light
     wattage->radiance re-derived toward Cycles ground truth), then the CPU
     oracle is the stale side and the fix is to update the CPU reference (and
     only then re-baseline the ratio), NOT to revert the GPU. Prove this by
     bisect + a ground-truth check; never assume it.
3. Bisect the perf gate at 5455850^ (pre-#484). If the wavefront's added
   features are legitimately irreducible cost, re-baseline the floor with a
   median-of-N harness and a written justification; if #490 TLAS traversal is
   the bulk, fast-path non-instanced scenes past the top-level walk.
4. Convert the photon-caustic parity gate off SSIM to mean-ratio + peak, and
   separately open the ~24% WF under-gather investigation.

## Impact on PR #518 and other PRs gated tonight

- PR #518 (pkg141, "route Disney metal closure-graph lobe to gpu_disney_eval")
  is not implicated and must not be blocked by these failures. Its own targeted
  gates (test_pkg123_disney_metal_gpu_cpu_parity) are green, and its own
  worktree evidence (pkg141_wavefront_diff.txt) shows the SAME failing ratios
  [1.153, 1.007, 1.068] as unmodified main @8c49bbb (..._rerun.txt). #518
  therefore neither causes nor fixes the wavefront_diff drift — empirically
  discharging the a-priori worry that a Disney-metal routing change might have
  moved these metal-bearing scenes. #518 may merge on its own merits.
- All PRs gated tonight: the 4 wavefront_diff ratio/perf failures + the
  photon-caustic SSIM flake are pre-existing MAIN failures. Any full
  wavefront_diff sweep shows them regardless of the PR under test. Gate runners
  must treat them as known-main quarantine and not attribute them to the PR. The
  one exception: a PR that itself touches the GPU spectral-table,
  dedicated-light, or wavefront-kernel path must be evaluated against the
  (regressed) baseline documented here so its own effect is not masked or
  mis-blamed — ideally after the ratio regression is root-caused.

## Evidence & source index (absolute paths)

- Failing run (pkg141 worktree, with #518):
  C:\Users\hgcom\OneDrive\Astroray\Astroray_repo\Astroray\test_results\overnight_report_2026-07-24\pkg141_wavefront_diff.txt
- Rerun on unmodified main @ 8c49bbb:
  C:\Users\hgcom\OneDrive\Astroray\Astroray_repo\Astroray\test_results\overnight_report_2026-07-24\pkg141_wavefront_diff_rerun.txt
- Ratio gates: tests\wavefront_diff\test_pkg55_gpu_wavefront_image.py,
  tests\wavefront_diff\test_pkg55_megakernel_env_open_scene.py
- Perf gate: tests\wavefront_diff\test_pkg55_perf_gate.py
- SSIM flake: tests\test_pkg55_c5_photon_wavefront.py
- Color-path suspects: src\gpu\gpu_spectral_tables.cu (#481), src\gpu\gpu_nee.cuh
  + src\emission_spectrum.cpp + src\lights\*.cpp (#489/#500)
- Perf suspects: src\gpu\wavefront\stage_advance.cu,
  src\gpu\wavefront\stage_intersect.cu,
  src\gpu\wavefront\gpu_wavefront_snapshot.cu (#484/#486/#490/#494)
- Photon gather: src\gpu\photon_caustic.cu, include\astroray\gpu_photon_caustic.h

## Handoff

Route this report to a fresh package-implementer to drive the two bisects
(ratio arc: a7f09d1^ vs 41101a5^; perf arc: 5455850^) in a GPU-lock-holding
session, then draft the fix. Before that fix is pushed for re-gate, obtain an
independent different-model sign-off on the diff against the named root cause
(SIGN-OFF states which lines close it; silence/uncertainty resolves to BLOCK).
