# pkg329 — Filter Glossy (Cycles blur_glossy) on CPU and GPU

**Pillar:** 1
**Track:** A
**Status:** done — lane p329, branch lane/pkg329-filter-glossy (awaiting merge); v2_viewport witness Welch-1b 0/6720 vs Cycles as authored on CPU and GPU
**Estimated effort:** 2 sessions (CPU + GPU, each with one build and a register / perf probe)
**Depends on:** pkg201

---

## Goal

Before: Astroray stores `filterGlossy` (`Renderer::setFilterGlossy`, fed from
`scene.cycles.blur_glossy`, Blender default 1.0) and never reads it, on either backend. A glossy
surface seen through a diffuse or rough bounce keeps its sharp lobe, where Cycles blurs it.
After: both backends carry Cycles' per-path `min_ray_pdf` and floor the GGX alpha of every glossy
microfacet closure at `sqrt(1 - min_ray_pdf / blur_glossy) / 2`, so the v2_viewport Grid100k
witness passes Welch-1b against Cycles as authored.

---

## Context

Issue #1231: the largest gate (b) witness (v2_viewport Grid100k Principled BSDF, 43.5 of 474
weight on each backend) fails Welch-1b with Astroray +2.5 % R in the ROI and up to +15 % where the
gold sphere meets the grid. It is entirely Filter Glossy: with the Cycles leg at blur_glossy 0
the witness passes 0/6720 on CPU and GPU. It is a default-on native setting silently ignored, so
gate (e) rates it high. pkg201 item C parked it on 2026-08-29 for architecture (no
closure-mutation point; materials recompute `roughness*roughness` inline). This package takes the
design that research recommended: a per-shade alpha floor in the hit record, read wherever a
glossy closure forms its alpha, with no virtual signature change.

---

## Evidence

- 2026-11-02: #1231 bisect (`.astroray_plan/docs/issue1231-filter-glossy-research.md`):
  Welch-1b CPU 1749/6720, GPU 1761/6720 vs Cycles as authored; 0/6720 on both vs Cycles with
  blur_glossy 0. Changing filter_glossy on the Astroray leg leaves frames bit-identical.

---

## Reference

- Cycles v5.2.0 (`intern/cycles`, Apache-2.0), fetched with `gh api` at tag v5.2.0:
  - `scene/integrator.cpp:269`: kernel `filter_glossy = 1 / blur_glossy`, `FLT_MAX` when 0 (off).
  - `kernel/integrator/path_state.h:62`: `min_ray_pdf = FLT_MAX` at path start.
  - `kernel/integrator/shade_surface.h:608-612`: after a non-transparent scatter,
    `min_ray_pdf = fminf(unguided_bsdf_pdf, min_ray_pdf)` (the mixture pdf of the sampled
    direction, before path guiding).
  - `kernel/integrator/shade_volume.h:2668`: the same update with the phase pdf after a volume
    scatter.
  - `kernel/integrator/surface_shader.h:189-213`: at the next surface, before any eval, NEE or
    sample, `blur_pdf = filter_glossy * min_ray_pdf`; if `< 1`,
    `blur_roughness = sqrtf(1 - blur_pdf) * 0.5f` and `bsdf_blur` runs on every closure
    (skipped on MNEE paths).
  - `kernel/closure/bsdf.h:658-686` `bsdf_blur`: GGX / Beckmann reflection, refraction, glass and
    thin-glass transmission (`bsdf_microfacet_blur`), Ashikhmin-Shirley, hair Chiang / Huang.
    Diffuse, sheen, toon, translucent, transparent are untouched. "TODO: Recompute energy
    preservation after blur?" (`:670`): `energy_scale`, the darkening folded into the weight and
    `sample_weight` keep the setup alpha.
  - `kernel/closure/bsdf_microfacet.h:1095-1101`: `alpha_{x,y} = fmaxf(roughness, alpha_{x,y})`.
    Singular closures are GGX with alpha 0 (`:673-676` threshold 2e-10), so a blurred sharp
    glossy or glass becomes rough; `|eta - 1| < 1e-4` stays singular (`:869`). Singular samples
    report pdf x 1e6 (`:876-879`, `:1345-1348`).
- Prior research: `.astroray_plan/docs/pkg201-item-c-filter-glossy-research.md`.

---

## Prerequisites

- [x] #1231 root cause confirmed (research note above).
- [x] Cycles authored legs for v2_viewport, 8 seeds, from pkg328 Phase 2
      (`%LOCALAPPDATA%\astroray-evidence\2026-11-01\p328b\audit\stacks\v2_viewport\cycles`).

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `tests/test_pkg329_filter_glossy.py` | CPU / GPU twin tests of the floor rule |

### Files to modify

| File | What changes |
|---|---|
| `include/astroray/light_path.h` | HD helpers: kernel, alpha floor, singular pdf for min_ray_pdf |
| `include/raytracer.h` | `HitRecord::glossyAlphaFloor`; `minRayPdf` in pathTraceSpectral / pathTraceSpectralCaustic; `getFilterGlossy` |
| `plugins/integrators/restir_di.cpp` | pathTraceSpectral twin: same accumulator and floor |
| `plugins/integrators/multiwavelength_path_tracer.cpp` | same |
| `plugins/materials/principled.cpp` | `Lobe::blur`, `ggxAlpha` / `blurAlphas`; floor in D / G / sample / pdf of coat, metallic, specular, glass, thin-glass lobes |
| `plugins/materials/metal.cpp` | `shadeRoughness(rec)` in eval / sample / pdf and the near-delta test |
| `plugins/materials/disney.cpp` | `shadeAlpha(rec)` / `roughGlass(rec)` at every GGX alpha and delta-glass test |
| `include/astroray/gpu_wavefront_state.h` | per-path `min_ray_pdf` SoA field, set at init, updated in the shade stage (GPU phase) |
| `include/astroray/gpu_materials.h` | floor in `gpu_pr_*`, `gpu_metal_*`, dielectric / glass and closure-graph glossy alphas (GPU phase) |
| `scripts/pkg200_honour_matrix.py` | blur_glossy row note (no longer an expected GPU honest-fail) |

### Key design decisions

- **Per-hit floor, no closure mutation.** The integrator computes
  `rec.glossyAlphaFloor = lightpath::filter_glossy_alpha_floor(1/blur_glossy, minRayPdf)` once
  per surface hit, right after the Light Path context and caustic gate are set, so NEE eval, the
  emission MIS pdf and the BSDF sample all see the same blurred closure (Cycles blurs `sd`
  before all three). Decorators (`NormalMapped`, `TwoSided`, `Mix`) copy the hit record, so the
  floor reaches nested leaves without signature changes.
- **Single alpha per lobe.** Each glossy material forms its shading alpha in one helper that
  returns `max(alpha, floor)`; energy compensation (`ggxE` / glass E tables), layering albedo and
  selection weights keep the setup roughness, as Cycles keeps `energy_scale` and
  `sample_weight`. Anisotropic lobes take the geometric-mean energy roughness before the floor.
- **Off is today's code.** Floor 0 (blur_glossy 0, camera rays, or `min_ray_pdf >= blur_glossy`)
  makes every helper return the pre-pkg329 alpha exactly (`max(x, 0) == x` for `x >= 0.0064`).
- **Delta classification follows the blurred alpha.** Principled glass is delta iff roughness
  <= 0.03 and floor <= 0.03^2 (Astroray's own threshold); thin-glass transmission iff
  `aT^2` and `floor^2` <= 2e-10 (Cycles'); metal's near-delta threshold uses the blurred
  roughness. Eta == 1 glass stays delta.
- **Delta samples feed `min_ray_pdf` as pdf x 1e6** (`filter_glossy_ray_pdf`): Astroray's delta
  samples carry only the selection probability, Cycles' singular pdf carries x 1e6, so a mirror
  or smooth glass bounce never triggers a blur by itself.
- **Guided paths** feed the unguided BSDF pdf of the direction taken (Cycles
  `unguided_bsdf_pdf`).
- **Out of scope by design:** `dielectric` / `glass` (Sellmeier node; delta-only, no microfacet
  alpha) and `thin_glass` (ad-hoc cone, not a microfacet model) have no alpha to floor and are
  not reached by Cycles-parity exports (Glass BSDF lowers to `principled`); `mirror` has no
  Cycles twin; Disney's GTR1-style clearcoat is not a Cycles closure. Principled Hair
  (Cycles `bsdf_hair_*_blur`) is a follow-up if a hair witness needs it.
- **GPU** (phase 2): `min_ray_pdf` lives in the wavefront path SoA next to `path_bsdf_pdf`; the
  floor is a `__forceinline__` max at each `gpu_*` alpha site, no out-of-line calls from the
  shade kernels (REG 254). Gates: `scripts/dev/res_usage_compare.py` REG unchanged, STACK growth
  tens of bytes, interleaved min-of-N perf A/B within ~1 % on scenes that do not blur.

---

## Acceptance criteria

- [x] v2_viewport Grid100k witness passes Welch-1b (alpha 0.05, tile 8, delta_rel 0.01, 8 seeds
      278 1301 2711 4177 6113 7919 9371 11027, ROI `[0, 0.3614, 1, 1]`) against Cycles as
      authored (blur_glossy 1.0) on CPU and on GPU.
- [x] `tests/test_pkg329_filter_glossy.py` passes on CPU and GPU (rough-closure and camera-ray
      invariance bit-exact on CPU, within the GPU's run-to-run rounding on GPU; smooth metal
      seen from a diffuse floor changes).
- [x] Filter Glossy 0 renders within float rounding (<= 1e-6 relative) of the pre-pkg329 build
      (CPU and GPU) on a glossy scene (lead 2026-11-02: MSVC codegen in principled.cpp moves
      ULPs; the GPU differs from itself run to run by ~1e-6).
- [x] No regression in the closeout sweep relevant suites (principled, metal, disney, glass,
      bump, Light Path, caustic gate).
- [x] GPU: REG unchanged and STACK growth small on the shade kernels; perf A/B within ~1 % on
      principled, glass, bump and volume probes.

---

## Non-goals

- Do not recompute energy compensation, layering or selection weights after the blur (Cycles
  does not).
- Do not blur diffuse, sheen, translucent, transparent closures or volumes.
- Do not add a rough model to `dielectric`, `thin_glass` or `mirror`.
- Do not change the addon forwarding (`settings_map.py` already maps `blur_glossy`).

---

## Progress

- [x] Cycles mechanism verified at v5.2.0 with file:line citations (Reference).
- [x] CPU: `minRayPdf` in pathTraceSpectral (surface + both volume scatters, guided pdf),
      pathTraceSpectralCaustic, restir_di, multiwavelength; floor helpers in `light_path.h`.
- [x] CPU: single-alpha + floor in principled, metal, disney (syntax-checked with g++).
- [x] Twin tests written (`tests/test_pkg329_filter_glossy.py`); band ROI to calibrate on first
      build.
- [x] CPU build (7d9a6531), tests, Welch-1b witness, Filter Glossy 0 identity vs b1101c
      (2026-11-02, evidence `%LOCALAPPDATA%\astroray-evidence\2026-11-02\p329\`):
  - `test_pkg329_filter_glossy.py -k cpu` 3/3. Band calibrated: rows 26-34 in front of the
    contact, on/off 0.910 / 0.902 / 0.911 over seeds 7 / 11 / 23 (64 spp), off-frame seed spread
    <= 1 %; bound `< 0.95`.
  - Welch-1b v2_viewport CPU vs Cycles as authored: **0/6720**, ROI ratio 0.998; centre-contact
    band 0.995 (was up to +15 %).
  - FG-0 (attrib filter_glossy 0, seed 278) vs b1101c: not bit-exact, 45773/230400 px differ by
    <= 4.8e-7 abs / 9.4e-7 rel (float ULP). Attribution probe (`cpu/codegen_probe.py`): a
    Lambertian scene is bit-exact (integrator unchanged), a Principled roughness-1 scene (alpha 1
    > any floor, so the floor cannot act) differs in 30/4096 px by 3.6e-7: MSVC `/fp:fast`
    codegen in principled.cpp, not a logic or RNG change (any such change moves samples, not ULPs).
  - Related CPU suites (principled, layering, metal x3, disney x4, rough glass x4, thin film,
    #1112, #991, #1204/#1206, caustic toggles, pkg329): 327 passed.
- [x] GPU accumulator + floor written (lane p329): `min_ray_pdf` SoA + `c_wfFilterGlossy`
      (gated: off never touches the SoA), `GHitRecord::glossyAlphaFloor`, floors in
      `gpu_metal_*`, `gpu_disney_*` (closure-graph GGX conductor / rough dielectric leaves lower
      to these), `gpu_pr_*`.
- [x] `pkg200_honour_matrix.py` blur_glossy note. The parity matrix has no blur_glossy row
      (render setting, not a node), so no regen.
- [x] GPU build 87f01144 verified (2026-11-02, evidence `...\2026-11-02\p329\gpu\`, `perf\`):
  - Register / stack (lead, vs b1101c): shade kernels REG 254 unchanged, STACK +8..+72 B;
    shadow +2..+4 REG, intersect +1 REG; nothing missing or new.
  - `test_pkg329_filter_glossy.py` 6/6 after one test fix: the GPU frame differs from itself
    run to run by ~1e-6 rel on ~70 % of pixels, so the GPU invariance legs compare at
    rtol 1e-5 (CPU stays bit-exact). GPU subsets of the related suites (principled, layering,
    rough diffuse, metal x4, disney x4, rough glass x3, thin film x2, #1112, #991,
    #1204/#1206, caustic toggles, f82): 224 passed.
  - Welch-1b v2_viewport, 8 seeds, Cycles as authored: GPU **0/6720**, ROI ratio
    0.998 / 0.998 / 0.998, centre-contact band 0.996; GPU vs CPU 0/6720, ROI ratio 1.000.
  - FG-0 GPU vs b1101c (seed 278): 0.1 % of values differ, max 2.4e-7 abs / 7.0e-7 rel, which
    is exactly b1101c against itself (same counts and maxima); mean ratio 1.0000000.
  - Perf, interleaved min-of-8 x (burn-in + min-of-3), p329 / b1101c, Filter Glossy 0:
    principled 1.003, glass 1.002, bump 1.004, principled_tex 1.007, glass_tex 1.006,
    volume 1.028; per-round spread <= 0.3 %. The volume excess is all in
    `stageRegenKernel` (0.85 -> 1.05 ms/launch) and is a device-address layout artefact,
    not code: pre-allocating a 6-64 MB dummy buffer moves the b1101c regen to 1.02 ms and its
    frame to 0.2006-0.2013 s, where p329 measures 0.2019-0.2027 s (+0.5 %). Filter Glossy 1.0
    on principled: 0.3736 s vs 0.3912 s off (blurred lobes, informational).

---

## Lessons

- The GPU wavefront render is not bit-reproducible run to run (~1e-6 rel, float
  accumulation order), so "bit-identical" GPU tests must compare at a tolerance above that
  floor; measure the floor (same build twice) before reading an A/B diff.
- A one-scene perf A/B excess can be allocation layout: `stageRegenKernel` on the volume
  probe moves ~20 % between two address layouts of the SAME build. Before attributing a
  regression to new code, shift the baseline's device addresses (ctypes `cudaMalloc` a
  dummy buffer before the render, `perf\layout_probe.py`) and compare against that spread.
- Filter Glossy needs no virtual signature change: a per-hit floor in the hit record,
  read by each glossy material's single alpha helper, reaches nested closures through the
  decorators' hit-record copies on CPU and GPU alike.
