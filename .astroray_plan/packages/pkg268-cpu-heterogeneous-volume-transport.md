# pkg268 — CPU heterogeneous volume transport (delta/ratio tracking) + Principled Volume basics + volume NEE

**Pillar:** 3
**Track:** A
**Status:** open
**Estimated effort:** 1 week
**Depends on:** pkg267

---

## Goal

Before: heterogeneous media cannot be rendered — the only transport is analytic
Beer–Lambert on a homogeneous world volume, and grids from pkg267 are inert data.
After: the CPU spectral integrator renders a bounded `GridMedium` correctly:
delta-tracking free-flight through spatially-varying σ_t (majorant from pkg267),
ratio-tracking transmittance for NEE shadow rays, HG/isotropic phase in-scatter
with equiangular+distance MIS, and Principled Volume basics (density, color =
scattering albedo, absorption color, anisotropy). Bounded object media join the
modern spectral path (superseding the legacy `ConstantMedium`). This is the
correctness oracle for the GPU stage (pkg269).

---

## Context

Per the north star (correctness > fidelity > speed), the CPU oracle must render
heterogeneous volumes correctly before any GPU work is attempted. This package
turns pkg267's grids into images and is the dependency of pkg269 (GPU), pkg270
(emission), and pkg272 (optional). It is physics- and multi-file-heavy: dispatch
to an **Opus-tier** implementer (memory `delegate-tier-stalls-on-hard-packages`),
not an open-weight lane, despite Track A. Research:
`docs/volumes-track-research-2026-09-12.md` §2, §4, §5.

---

## Reference

- Design doc: `.astroray_plan/docs/volumes-track-research-2026-09-12.md` §2 (algorithm map), §4 (divergences)
- External: Woodcock 1965 (delta tracking); Novák/Selle/Jarosz 2014 (residual
  ratio tracking); Kulla & Fajardo 2012 (equiangular); Henyey–Greenstein 1941;
  pbrt-v4 `media.h` `SampleT_maj` + `cpu/integrators.cpp` `VolPathIntegrator`
  (Apache-2.0); Cycles `kernel/integrator/shade_volume.h`, `volume_stack.h`,
  `kernel/closure/volume.h`, `svm/closure.h` `svm_node_closure_volume` (Apache-2.0).
- Existing scaffold to imitate: `include/raytracer.h` world-volume in-scatter /
  NEE-through-medium (~L3039+); the `isotropic` phase plugin.

---

## Prerequisites

- [ ] pkg267 is done and its tests are green (grids + majorant available).
- [ ] `cite-algorithm` run for delta tracking, ratio tracking, and equiangular
      sampling; per-algorithm notes saved under `.astroray_plan/docs/`.
- [ ] A brute-force numpy volume reference (ray-marched transmittance + single
      scatter) authored to gate the tracking estimators.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `include/astroray/volume/volume_transport.h` | Delta-tracking free-flight + ratio-tracking transmittance over a `GridMedium` (spectral, seed-deterministic) |
| `include/astroray/volume/phase.h` | HG + isotropic phase eval/sample/pdf (generalize the `isotropic` plugin + world-volume HG into one home) |
| `include/astroray/volume/principled_volume.h` | Principled Volume basics: density scale, color (scattering albedo), absorption color, anisotropy → σ_a(λ)/σ_s(λ) |
| `tests/test_pkg268_homogeneous_slab_furnace.py` | Homogeneous slab transmittance vs analytic Beer–Lambert (linear, floor+ceiling) |
| `tests/test_pkg268_heterogeneous_reference.py` | Delta/ratio tracking vs the brute-force numpy ray-march reference |
| `tests/test_pkg268_volume_nee.py` | Ratio-tracking NEE unbiasedness + determinism (fixed seed reproducible) |

### Files to modify

| File | What changes |
|---|---|
| `include/raytracer.h` | Route a ray entering a `GridMedium` AABB into `volume_transport` free-flight; add in-scatter + NEE-through-medium for grids; register the medium on a shape/object |
| `module/blender_module.cpp` | Bind attaching a `GridMedium` (+ Principled Volume params) to an object; expose transmittance/free-flight for tests |
| `blender_addon/exporter.py` | Lower a `ShaderNodeVolumePrincipled` (density/color/absorption/anisotropy sockets) onto the object's `GridMedium` |

### Key design decisions

- **Free-flight:** delta (Woodcock) tracking against the pkg267 majorant, spectral
  (per-λ σ_t), unbiased. Clean-room from pbrt-v4 `SampleT_maj`, cite in comments.
- **Transmittance for NEE:** ratio tracking (Novák 2014), not analytic (σ_t is
  spatially varying). This replaces the analytic exponential used by the
  homogeneous world volume for grid media only.
- **Phase MIS:** combine equiangular light sampling with distance sampling via
  MIS (Kulla & Fajardo 2012) — matches Cycles, essential for spot-in-fog.
- **Principled Volume basics only:** density, color, absorption color, anisotropy.
  Emission / blackbody / temperature and per-λ spectral coefficient work is
  pkg270. Follow Cycles `svm_node_closure_volume` for socket semantics.
- **Determinism:** thread the engine RNG through — no `std::random_device`
  (the legacy `ConstantMedium` bug). Seed pinning must reproduce.
- **Legacy `ConstantMedium`:** superseded by a bounded homogeneous `GridMedium`
  (constant grid) in the spectral path; mark it deprecated in a comment, do not
  delete it in this package (leave removal to a hygiene follow-up).
- Bounded media integrate via the object AABB + medium interface, following the
  world-volume in-scatter scaffold in `raytracer.h`.

---

## Acceptance criteria

- [ ] `test_pkg268_homogeneous_slab_furnace.py` passes: slab transmittance matches
      analytic Beer–Lambert within tolerance, rendered linear with a floor AND a
      ceiling assert (`apply_gamma=False`).
- [ ] `test_pkg268_heterogeneous_reference.py` passes: delta-tracking
      transmittance and single-scatter radiance converge to the brute-force numpy
      ray-march reference within the stated tolerance.
- [ ] `test_pkg268_volume_nee.py` passes: ratio-tracking NEE mean matches the
      reference (unbiased) and a fixed seed reproduces bit-for-bit.
- [ ] A bounded VDB smoke/cloud renders on the CPU with visible density variation
      and is inspected qualitatively by Astra or Claude (visual evidence saved).
- [ ] Full CPU suite green; grid-free scenes unchanged.

---

## Non-goals

- Do not implement the GPU stage — that is pkg269.
- Do not implement emission / blackbody / temperature-grid evaluation — pkg270.
- Do not implement velocity/motion blur or multi-scatter — pkg272.
- Do not add volume render passes/AOVs for heterogeneous media — pkg271.
- Do not reintroduce a biased fixed-step ray march.
- Do not delete the legacy `ConstantMedium`.

---

## Progress

- [x] cite-algorithm for delta/ratio tracking + equiangular + HG
      (`.astroray_plan/docs/pkg268-volume-transport-research.md`).
- [x] numpy brute-force reference (`tests/volume_reference.py`) + `phase.h` +
      `volume_transport.h` (delta/Woodcock, ratio tracking, equiangular MIS).
- [x] Principled Volume basics lowering (`principled_volume.h` + exporter
      `_try_export_volume`). SCOPE NOTE: scalar σ_t + spectral scattering albedo;
      chromatic absorption (per-λ σ) deferred to pkg270 with a degradation note.
- [x] Integrator routing (`raytracer.h`): loop-top bounded-medium free flight +
      medium NEE (ratio-tracking transmittance) + surface-NEE attenuation through
      media. Byte-identical when no media are registered.
- [x] Tests: slab furnace vs Beer–Lambert, heterogeneous delta/ratio vs numpy,
      NEE unbiasedness + determinism, red-scatter-cube visual. Numbers in the
      batch-F PR.

---

## Lessons

*(Fill in after the package is done.)*
</content>
