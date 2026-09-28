# pkg294 — Area-lamp NEE variance in media: spherical-rectangle sampling + light-tree importance at volume points (#922; unblocks pkg290)

**Pillar:** 2
**Track:** A
**Status:** open
**Estimated effort:** 2 sessions (~6 h); Phase 0 needs a CPU diagnostic build only; Phase 1 shares Batch AK's CUDA build; Phase 2 (if convicted) gets its own
**Depends on:** pkg289

---

## Goal

Before: area lamps are sampled uniformly over their area on both backends
(`AreaLight::sampleSurface`, `lamp_sampling.h`) and the same area pdf is used
for the MIS weight when a phase-sampled ray hits the lamp, so a hit on a
900 W backlight carries a much larger weight than in Cycles; at volume
scatter points the light tree's importance is evaluated with a surface normal
and picks no better than the power sampler. Result: scatter cube noise 2–4×
Cycles at equal spp, and the default indirect clamp removes 20 % of the
cube's energy vs Cycles' 6.5 % (pkg290 blocked). After: the lamp-hit forward
pdf and the NEE pdf evaluated at the scatter point are the spherical-
rectangle solid-angle pdf (Ureña, Fajardo & King 2013) for rectangles and
Cycles' disk branch for disks, on both backends, exactly as Cycles
(`area_light_eval<false>`); the per-segment draw stays area-uniform as in
Cycles' `area_light_eval<true>` with the pdf updated at the chosen scatter
point (`light_sample_update`); the light tree evaluates a segment/no-normal
importance at volume points; clamp-off cube noise at 64 spp is ≤ 1.5×
Cycles' and pkg290's ≤ 2-point clamp-loss gate is reachable.

---

## Context

The night-shift report named the media variance the most valuable open
transport item. #925/#929 fixed the segment estimator (shaft 100× → 2–7×);
the residual is lamp-hit MIS allocation, not the estimator. Every `v2_media`
corpus gate and every fog showcase render with Blender's default clamp is
biased dark until this lands. Physics-heavy on both backends, register-
sensitive on the GPU (`stage_volume_hetero.cu` NEE path, not the shade
kernel): an Opus 5.5 lane with a Terra review.

---

## Evidence

- 2026-09-27 (pkg290, lane ad1): `test_results/pkg290/clamp_sweep.txt` — leaving only the lamp-hit site unclamped removes ~90 % of the excess (scatter 20.4 → 2.1 %, principled 4.9 → 0.7 %); Cycles' light tree alone cuts its loss 16.5 → 6.5 %, Astroray's tree changes nothing (19.8 vs 20.4 %); clamp-off cube noise 2–4× Cycles.
- `src/lights/area_light.cpp:60-139`: `sampleLi` draws `sampleSurface` (uniform area) and returns pdf d²/(A·cosθ); `pdfLi` mirrors it.
- `src/gpu/gpu_nee.cuh:189-225` (`gpu_lamp_sample_ext`, `gpu_dedicated_sample`) and `include/astroray/lamp_sampling.h::sample` share the disk/sphere maps; rectangles are area-uniform on the GPU too.
- `src/light_tree.cpp:581` `LightTree::importance(node, point, normal)` and `src/gpu/light_tree_device.cuh:117` — no normal-free variant; `stage_volume_hetero.cu:617` passes the tree into the medium NEE.

---

## Reference

- Ureña, Fajardo & King 2013, "An Area-Preserving Parametrization for Spherical Rectangles" (EGSR); reference code in the paper's appendix (permissive) and pbrt-v4 `src/pbrt/util/sampling.cpp::SampleSphericalRectangle` (Apache-2.0).
- Cycles `intern/cycles/kernel/light/area.h` (`area_light_eval<in_volume_segment>`, `area_light_rect_sample`, `area_light_eval_from_intersection`, `area_light_mnee_sample_update`), `kernel/light/light.h::light_sample_update`, `kernel/integrator/shade_volume.h` (segment light sample → distance → update), `kernel/light/tree.h` (`light_tree_sample<in_volume_segment>`, `light_tree_node_importance<true>` with P, D, t) — Apache-2.0.
- `include/astroray/lamp_sampling.h` (shared CPU/GPU maps, `AR_LAMP_HD`), `include/astroray/area_spread.h` (#852 spread attenuation, keep).
- `.astroray_plan/docs/pkg144-firefly-clamp-research.md` §pkg290; `docs/pkg289-medium-chromatic-noise-ladder.md`.
- Memory: `unbiased-strategy-switch-moving-a-mean-is-a-bug-signal`, `verify-attribution-with-a-baseline-build`, `mc-noise-vs-deterministic`.

---

## Prerequisites

- [ ] #929 merged (yes, #932) so the medium NEE site is the per-segment one.
- [ ] Baseline build of main for the variance A/B; GPU lock window for the GPU leg.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `include/astroray/spherical_rectangle.h` | `AR_LAMP_HD` Ureña 2013 parametrisation: `init(o, s, ex, ey)`, `sample(u1,u2)`, `pdf()` (= 1/solid angle); shared by CPU and GPU. Cited in the header. |
| `tests/test_pkg294_area_solid_angle_sampling.py` | Unit: spherical-rectangle pdf vs numerical solid angle (±0.5 %) for 5 poses; forward pdf at a lamp hit == NEE pdf at the same point (CPU == GPU to 1e-6); NEE on/off means agree within 1 % on a Lambertian plane and in the fog cube (CPU and GPU); one-lamp and three-lamp scatter-cube clamp-off variance at 64 spp ≤ 1.5× Cycles' (Cycles headless, 3 seeds each); Phase 2: tree pick at a volume segment prefers the nearer of two equal-power lamps ≥ 70 %. |
| `.astroray_plan/docs/pkg294-media-lamp-variance-ablation.md` | Phase 0 table (equal spp and equal time) and the convicted term. |

### Files to modify

| File | What changes |
|---|---|
| `src/lights/area_light.cpp` | Rectangle: surface `sampleLi`/`pdfLi` via `spherical_rectangle.h`; disk/ellipse: Cycles' disk branch; a `pdfLiAt(point)` used by the medium path after the distance draw (Cycles `light_sample_update`). Spread clamp/attenuation unchanged. |
| `include/astroray/lamp_sampling.h` | Add the rectangle branch to `sample()` so `gpu_lamp_sample_ext` and the CPU dedicated-lamp path share one map; keep the sphere/disk maps byte-identical. |
| `src/gpu/gpu_nee.cuh` | `gpu_dedicated_sample` / `gpu_reconstruct_light_pdf`: rectangle pdf = solid-angle pdf; MIS uses it for BSDF/phase hits. |
| `src/light_tree.cpp` | Phase 2: segment importance `importance(node, P, D, t)` mirroring Cycles `light_tree_node_importance<true>`; medium NEE passes the segment. |
| `include/astroray/light_tree.h` | Phase 2: declaration of the segment importance overload. |
| `src/gpu/light_tree_device.cuh` | Phase 2: GPU twin of the segment importance; float math identical to CPU. |
| `src/gpu/wavefront/stage_volume_hetero.cu` | Segment NEE site: pdf updated at the scatter point (Phase 1); passes the segment to the tree (Phase 2). |
| `include/raytracer.h` | Medium NEE call sites use the no-normal tree pick; the lamp-hit MIS weight uses the new pdf. |

### Key design decisions

- **Phase 0 — attribution ablation (½ session, before any sampling code):**
  one-lamp and unequal-three-lamp scatter cubes, clamp off, 3 seeds, both
  engines: variance per ROI for (i) baseline, (ii) lamp-hit site with the
  solid-angle pdf only (MIS weight change, no draw change), (iii) tree pick
  disabled vs enabled. Equal-spp AND equal-time. This names whether the
  excess is the hit-site MIS weight, the NEE draw, or light selection; the
  one-lamp cube cannot convict selection. **Mean preservation is required
  per variant:** every variant's ROI means must sit inside the baseline's
  3-seed MC band; a variant that lowers variance while moving a mean is a
  diagnostic perturbation, not evidence (memory
  `unbiased-strategy-switch-moving-a-mean-is-a-bug-signal`). Variant (ii)
  is only admissible with the paired NEE pdf changed to the same measure
  (MIS accounting stays consistent); a hit-pdf-only run is not a candidate
  implementation. Phase 0 runs on a CPU (MinGW) diagnostic build behind an
  env switch that is deleted before Phase 1 lands; no CUDA build.
- **Mirror Cycles' actual branches, verified 2026-09-29 in `kernel/light/area.h`:**
  segment draw = area-uniform (`in_volume_segment`: `pdf = invarea ·
  area_to_solid_angle`); lamp-hit forward pdf and the pdf re-evaluated at the
  scatter point = spherical rectangle (`area_light_eval<false>`,
  `area_light_eval_from_intersection`, `light_sample_update`). Do not
  spherical-rectangle-sample the segment draw; Cycles does not.
- **Phase 1 = pdf/draw parity (rectangle + disk), Phase 2 = tree at volume
  segments** (Cycles `light_tree_sample<true>` takes P, D, t — not just a
  point without a normal). Phase 2 ships only if Phase 0 (iii) convicts
  selection; otherwise it is filed, not built.
- **One shared header for the map and the pdf** so CPU and GPU cannot diverge
  (the #862/#912 class of bug is CPU/GPU asymmetry in light pdfs); forward
  and NEE pdfs must include selection probability, spread clamp and the
  near-plane fallback identically.
- **No estimator change elsewhere**: the clamp (`clampContribSpectral`) and
  pkg288 lamp pass-through are untouched; pkg290 re-measures after this
  lands (closure not guaranteed).
- **Register note:** the change lives in the NEE/light-sample stages, not the
  REG-254 shade kernel; report `stage_volume_hetero` and intersect REG/STACK
  before and after. Separate commits and evidence per phase; Phase 1 rides
  Batch AK's single CUDA build (with pkg295); Phase 2, if convicted, is its
  own PR and build so phase attribution survives.

---

## Acceptance criteria

- [ ] `tests/test_pkg294_area_solid_angle_sampling.py` green CPU and GPU (RTX 5070 Ti).
- [ ] pkg290's `clamp_sweep` re-run: scatter cube clamp-removed fraction within 2 points of Cycles at `sample_clamp_indirect=10` (was 20.4 vs 6.5 %); cabinet ROI ratios ≥ 0.97 clamp-on.
- [ ] NEE on/off means agree within 1 % (surface plane and fog shaft) on both backends; `test_883`, `test_pkg288_lamp_passthrough`, `test_925_*`, `test_929_*`, pkg262 light-tree rows and the lighting_studio AREA booth (#852, 1.04–1.10 of Cycles) unchanged within their bands.
- [ ] Any reference that moves (bank, corpus v1/v2) is re-pinned in the same PR with an attribution line (memory `fix-tests-calibrated-on-broken-engine`).
- [ ] Shade kernel SASS unchanged; `stage_volume_hetero` REG/STACK delta reported.

---

## Non-goals

- Do not change the clamp metric or limit (pkg290 owns the re-measure).
- Do not add ReSTIR/other samplers at volume points; no equiangular changes (#925 done).
- Do not touch mesh-emitter (triangle) sampling; that path is MIS-corrected by #912/#886.

---

## Progress

- [ ] Phase 0: attribution ablation table (one-lamp / three-lamp, hit-site pdf, tree on/off, equal spp + equal time).
- [ ] Phase 1: spherical-rectangle + disk solid-angle pdf at hits and at the scatter point, CPU then GPU; variance A/B.
- [ ] Phase 2 (if convicted): segment light-tree importance at volume points, CPU + GPU; pick test.
- [ ] pkg290 re-measure; references re-pinned with attribution.

---

## Lessons

*(Fill in after the package is done.)*
