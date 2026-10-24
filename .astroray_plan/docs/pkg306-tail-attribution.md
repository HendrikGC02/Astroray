# pkg306 Phase 0: tail attribution for v2_media and v2_dispersion_caustics

2026-10-25, lane-pkg306, branch `lane/pkg306` (base main 624e32df). CPU only so far; the GPU leg
is pending a build (section 5). Evidence (summaries, scratch drivers, sheets):
`%LOCALAPPDATA%\astroray-evidence\2026-10-24\pkg306\` (`var/*_table*.txt`, `var/summary_*.json`,
`sheets/`).

## 1. Setup

- Build: CPU MinGW, OpenMP on, 8 threads, in the lane worktree. The untouched main build is
  kept as `baseline_pyd/`. The diagnostic build with `ASTRORAY_PKG306_DIAG` unset is
  bit-identical to it on both scenes (`np.array_equal`, seed 278). Re-renders are
  deterministic.
- Renders: `mc_tolerance.render` (`render_leg.py`, Blender 5.2), 64 spp, seeds 278-282.
  Adaptive sampling, denoise, clamps and filter glossy are off. The rare-event check uses 20
  decorrelated seeds, 278 + 1009 k (#986).
- Metrics: `mc_tolerance.tail_stats`, the new `--tail-report`. Luminance, across-seed variance,
  pixels with 1024 spp Cycles reference luminance > 0.01.
  - full: sum var / sum var Cycles.
  - trimmed: each engine's top 1 % of pixels dropped.
  - bulk: median per-pixel ratio.
  - share: top-0.1 % of Astroray's pixels. "C same" is Cycles' share on those same pixels.
  - `max_frac`: largest seed / seed sum. 1.0 = a 1-in-N firefly; 0.2 = a stable pixel.
  - z: ROI mean against Cycles or against the baseline, from the 5 seed means.
- Variants: `include/astroray/pkg306_diag.h`. `only_<cls>` / `drop_<cls>` are contribution
  masks on the same paths and the same RNG stream. The `only_` renders of all classes sum to
  the baseline (max |diff| 8.5e-5 relative), so the class decomposition is exact.
  - glint: camera → delta+ → lamp/emitter.
  - caustic: delta hit after a non-delta vertex (D S+ L).
  - bsdfhit: MIS'd BSDF or phase hit.
  - nee, envnee, voldirect, volemit, photon, sms.

  Strategy switches: `nee_only`, `bsdf_only`, `photon_off`, `sms_off`, `no_term2`,
  `equi_only`, `dist_only` and `spot_cone_cycles`.

## 2. Re-measured on main (CPU, 5 seeds)

| scene | full | trimmed | bulk | top-0.1 % share (C same px) | image mean | tail pixels |
|---|---|---|---|---|---|---|
| v2_media | 4.27x | 13.1x | 2.97x | 0.500 (0.484) | 0.997 | 46/48 in the emitter glows, `max_frac` 0.26 |
| v2_dispersion_caustics | 38.9x | 80.5x | 5.22x | 1.000 (0.000) | 1.432 | 2 single-seed events: 1048 at (177,98), 204 at (201,149) |
| v2_dispersion_caustics, 20 seeds | **2.82x** | 83x | 5.1x | 1.000 (0.000; Cycles' own 1.000) | 1.398 | Cycles also has 6 events > 20 (max 1017) |

The 09-29 figures (media 43x, dispersion 67x / 65x trimmed) predate #961/#1019. The
dispersion "full" ratio is set by which engine drew a glint in 5 seeds.

## 3. v2_media

| variant | full | trimmed | smoke_plume var | shaft var | emitter_cool var | ROI \|z\| vs base (max) |
|---|---|---|---|---|---|---|
| base | 4.27 | 13.1 | 82.9 | 14.1 | 4.10 | - |
| nee_only | 4.81 | 13.6 | 83.5 | 14.3 | 4.67 | 3.2 (fog_floor_lit; see below) |
| bsdf_only | 7.44 | 85.5 | 78.5 | 29.1 | 3.5 | 77 (biased by design) |
| equi_only | 3.83 | 12.6 | **74.1** | 8.8 | 3.59 | 1.9 |
| dist_only | 186 | 10.6 | **34482** (1-in-N) | 145 | 17.0 | 8.8 |
| only_voldirect | 1.56 | 7.3 | **82.0** | **14.05** | 0.70 | (masked) |
| drop_voldirect | 2.67 | 2.57 | **0.52** | **0.09** | 3.3 | (masked) |

Variance ratios are against Cycles on the same ROI.

**Tail (top-0.1 %): closed by #961/#1019.** The share is 0.500 against Cycles' 0.484 on the
same pixels (1.03x, gate ≤ 2x). The worst pixels are stable bright emitter-edge pixels
(`max_frac` 0.24-0.28), not fireflies. Every ROI mean is within |z| ≤ 2.3 of Cycles.

**Residual full 4.27x (gate ≤ 3x).**
- 49 % of the excess variance sits in 87 emitter pixels (ref > 2, ratio 2.9x, stable).
  - Not ablated further.
  - The suspect is pixel-position stratification (pkg297), unverified.
- 51 % is in the rest of the image (10.7x). It is concentrated in smoke_plume (83x) and the
  shaft (14x).
  - **Owner: medium segment direct light, #1032.** `only_voldirect` keeps 82x / 14x.
    `drop_voldirect` leaves 0.52x / 0.09x.
  - Neither distance strategy covers the dense plume alone: equiangular-only gives 74x,
    exponential-only gives 3.4e4x with 1-in-N fireflies.
  - This confirms #1032's reading: the exponential runs at the hull's global majorant. Cycles
    uses tracked collisions with local majorants (Miller et al. 2019).
  - Sites: `include/raytracer.h:3211` `segmentDirectLight`, `:3283` `boundedSegmentDirect`,
    `include/astroray/volume/volume_transport.h:685` `sampleSegmentDirect`.

Mean shifts in media:
- `bsdf_only`: the shaft spot is NEE-only by design (pkg181: radius > 0 spot/point lamps are
  not hittable), so fog_floor_lit falls to 0.40x. This is expected bias, not a bug.
- `nee_only`: drops background hits after bounces. The constant-colour world has no NEE, and a
  medium vertex has no env NEE. fog_floor_lit moves 0.5 % (z -3.2 vs base). This is expected
  bias.

## 4. v2_dispersion_caustics

### 4a. Exact class decomposition (`only_<cls>`, 5 seeds)

| class | share of total var | share of top-0.1 % var | share of image mean | trimmed var / Cycles trimmed |
|---|---|---|---|---|
| glint (camera → glass+ → sun) | 0.963 | **0.963** | 0.065 | 0.07 |
| caustic (D → glass+ → lamp, past the bounce-0 split) | 0.037 | 0.037 | 0.027 | 0.11 |
| bsdfhit | 0.000 | 0 | 0.290 | 0.44 |
| nee | 0.0001 | 0 | 0.337 | **63** |
| photon (CPU K-NN gather) | 0.000 | 0 | 0.284 | **12.4** |
| camera, envnee | 0 | 0 | 0 | 0 |

### 4b. Strategy variants (5 seeds)

| variant | full | trimmed | bulk | share | tail var kept | ROI notes (var ratio vs Cycles; z vs base) |
|---|---|---|---|---|---|---|
| base | 38.9 | 80.5 | 5.22 | 1.000 | 1 | beam 40.6, limb 36.5, spot_floor 39.8, prism_floor 75 |
| drop_glint | 1.43 | 80.5 | 5.16 | 0.997 | **0.037** | means unchanged except glint light |
| only_glint | 37.5 | 0.07 | 0 | 1.000 | **0.963** | (complement) |
| drop_caustic | 37.5 | 80.4 | 5.22 | 1.000 | 0.963 | |
| only_caustic | 1.42 | 0.11 | 0.11 | 1.000 | 0.037 | |
| **spot_cone_cycles** | 38.9 | **25.1** | 4.65 | 1.000 | 1 | beam **4.5**, limb **2.7**, spot_floor 17.5; \|z vs base\| ≤ 0.4 |
| spot_cone_cycles, 20 seeds | 2.82 | **25.5** | 4.29 | 1.000 | | |
| no_term2 (biased) | 1.26 | 69.1 | 4.81 | 0.997 | 0 (RNG divergence) | spot_floor 27.4 |
| spot_cone_cycles + no_term2 | 1.26 | 21.7 | 4.07 | 0.999 | | spot_floor 12.8 |
| photon_off | 97.6 | 63.8 | 2.2 | 1.000 | 1 | prism_floor mean 10.7x on one 834 event, var 3.4e7x |
| photon_off + sms_off | identical to photon_off | | | | | |
| sms_off | identical to base | | | | | |
| nee_only | 0.005 | 79.9 | 1.82 | 0.043 | 0 | biased by design; background_firefly 0.06x |
| bsdf_only | 81.2 | 12.8 | 3.15 | 1.000 | 0 | biased by design (spot NEE-only, pkg181) |
| light tree off (power sampler), both engines | 80.1 | 7.3 | 2.5 | 0.999 | | **limb 0.36x, spot_floor 0.47x Cycles; z vs base -37 / -27** |

### 4c. Verdicts

1. **Unbiased switch that moved a mean (reported first): `use_light_tree` off.**
   - With the power sampler, sphere_limb reads 0.36x and sphere_spot_caustic_floor 0.47x of
     Cycles. Cycles itself is unchanged with the tree off.
   - The NEE class shows no sun light on the sunlit strips (`sheets/disp_nee_tree_vs_power_vs_cycles.png`).
   - Cause: `DistantLight::power()` (`src/lights/distant_light.cpp:243-254`) returns
     Y · S · Ω. Since pkg122, `intensity_` is the irradiance S, so the sun's power-CDF weight
     is about 6e-5 of what it should be (S times a scene area, as in pbrt-v4 `DistantLight::Phi`).
   - Effect: the sun is practically never NEE-sampled. The estimator is formally unbiased but
     sun-starved at any practical spp.
   - The tree path is unaffected: `treeEnergy` = S (#859).
   - Light selection is a pkg306 non-goal. **To file.**
2. **Tail (top-0.1 %) owner: the glint class.**
   - `drop_glint` removes 96.3 % of the tail variance; its complement `only_glint` keeps 96.3 %.
     The remaining 3.7 % is the caustic class.
   - Site: the `pathTraceSpectral` lamp pass (`include/raytracer.h:4059`, `intersectDedicated`;
     w_B = 1 after a delta vertex) with `DistantLight::intersect` (`src/lights/distant_light.cpp:197`).
   - **Verdict: correct transport, not a defect.** The sun disc (0.5°, L ≈ 6.7e4) is seen
     through, or reflected by, the glass. Cycles renders the same class: its firefly is a
     sphere glint at (202,109).
   - At 20 seeds the event rates match: Cycles has 6 events > 20 (144 per render), Astroray 7
     (3 glint and 4 caustic, 316 per render). Full relVar is 2.82x.
   - Astroray's glint is dispersed (Sellmeier) and Cycles' is not, so where the energy lands is
     an RGB reference limit. Arbitration: the pkg307 Mitsuba spectral leg.
   - Not suppressed (non-goal). Variance reduction (gathering after a specular camera chain,
     the #909 known limit) is a follow-up.
3. **Trimmed / bulk excess (80.5x).**
   - **(a) NEE light selection** (NEE holds 63x Cycles' trimmed variance).
     - `SpotLight::orientationCone()` (`src/lights/spot_light.cpp:167`, via
       `OrientationCone::fromAxisAngle`, `include/astroray/light.h:112`) sets
       theta_o = theta_e = the half angle.
     - Cycles (`scene/light_tree.cpp`, `LightTreeEmitter`, Apache-2.0) uses theta_o = 0 and
       theta_e = the half angle. Astroray's spot therefore keeps tree importance out to twice
       its cone.
     - Probe (`debug_light_tree_pick`): at the sun-lit floor point (2.06, 0.34, 0), 11.4° off
       the spot axis (cone 5.75°), the tree picks the spot 87 % of the time, giving binomial
       sun-NEE noise. At 16° it picks the sun 100 % of the time.
     - Per-sample NEE relStd 3.5. relStd halves from 64 to 256 spp, so the noise is iid.
     - `spot_cone_cycles` (unbiased; means |z| ≤ 0.4): trimmed 80.5 → 25x, beam 40.6 → 4.5x,
       limb 36.5 → 2.7x. Crops: `sheets/disp_spotcone_crop_s279.png`.
     - A light-selection non-goal. **To file.** Related: `OrientationCone::fullSphere()` gives
       theta_e = π where Cycles' point light uses π/2. Not measured here.
   - **(b) Photon gather** (12.4x Cycles' trimmed variance) on the prism sun caustic floor.
     - The mean there is 3.28x Cycles, a documented divergence: Cycles renders no caustic
       there.
     - This is variance of transport the reference does not have. **RGB reference limit**:
       arbitrate against Mitsuba 3 (pkg307 arbitration suite, "prism under sun"). Do not
       suppress it.
   - **(c) Remainder** (spot_floor 17x after the cone fix): dispersion colour noise in NEE seen
     through the sphere and prism (hero-wavelength collapse).
     - `no_term2` (biased) moves it 17.5 → 12.8x. Same arbitration.
4. **SMS is inert in this scene on the CPU** in every configuration. `gatherSphereCasters`
   finds no analytic sphere (the corpus sphere is a mesh), so `photon_off + sms_off` is
   bit-identical to `photon_off`.
5. **`photon_off`** sends the caustic floor through path tracing. One 834 event at 5 seeds
   gives a mean 10.7x Cycles and variance 3.4e7x. The photon map is a large variance reduction
   there, not a tail owner.

## 5. GPU leg (pending a build)

Mirrored as `__constant__` switches. Host-side switches: `photon_off`, `drop_photon`
(gather scale 0, map and split kept), `bsdf_only`, `spot_cone_cycles` (the device tree is
built from host cones).

| switch | device site |
|---|---|
| `c_wfPkg306Keep` | intersect kernel: lamp pass, env miss, both emission branches; `stageShadowKernel` (nee / voldirect); `stageEnvShadowKernel` (envnee) |
| `c_wfPkg306Vol` | `stage_volume_hetero.cu` `segSampleDistance` (`equi_only` / `dist_only`) |

The GPU classifies post-specular hits only as `spechit` (glint + caustic): telling them apart
would need the ancestor flag in the shade kernel.

Not mirrored, to keep the REG-254 shade kernel untouched:
- `no_term2`: on the CPU it is not attributable (RNG divergence).
- The `nee_only` weight forcing: for the 0.5° sun and the r = 0.03 spot, w_L = 1 - O(1e-8),
  so `only_nee` is the equivalent mask.

Expected register impact:
- `stageShadeBucketedKernel`: no source change.
- Intersect kernels: four predicate-only reads of one constant, no per-path state, about +0-2
  registers. The snapshot harness kernel that fuses intersect and shade (`stage_advance.cu`)
  may move by the same amount.
- Shadow kernels: about +0-1 registers. Hetero: 0.

GPU questions:
- GPU full / trimmed numbers on both scenes.
- The rainbow prism beam (09-29: mean 1.73x, CPU 1.43x today): does it sit in `only_photon`,
  `only_spechit` or `only_nee`?
- Does `spot_cone_cycles` cut the GPU trimmed ratio the same way?
- Does the media voldirect split match #1032?

## 6. Follow-ups (to file; outside pkg306 scope)

1. Light tree: Cycles spot cone (theta_o 0, theta_e half angle). Check the point-light theta_e
   at the same time. Unbiased; dispersion trimmed variance about 3.2x lower.
2. Power sampler: `DistantLight::power()` Ω scaling starves suns.
3. Variance reduction for glints and caustics past the bounce-0 photon split. This is new
   caustic transport, so it is filed, not done here.
4. Mitsuba arbitration rows for the prism caustic floor and the dispersed glint (pkg307).
