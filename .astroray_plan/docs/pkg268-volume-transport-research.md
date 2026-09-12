# pkg268 research — CPU heterogeneous volume transport (cite-algorithm)

Batch F, 2026-09-13. Required by CLAUDE.md §6 before the non-trivial tracking /
phase / MIS code. Companion to pkg267's NanoVDB+majorant note.

## Scope decision (spectral σ): GREY extinction in pkg268

The engine is spectral, but the volumes-track research note (§2 table, §4.1) and
the pkg268 spec assign **per-λ chromatic extinction (spectral/decomposition
tracking, Kutz 2017)** to **pkg270**. So pkg268 uses a **scalar σ_t** and a
**spectral single-scattering albedo** (Principled Volume `color`):

* `σ_t(x)   = density(x) · extinctionScale`   (scalar, units 1/world-length),
* `σ_s(x,λ) = σ_t(x) · albedo(λ)`, `σ_a = σ_t·(1-albedo)` (grey absorption).

Consequence: transmittance is grey (achromatic). The #807 cabinet's red look
comes from the colored **scattering albedo**, not colored absorption — sufficient
for the "soft translucent red patch" cross-check bar. **Colored absorption
(chromatic σ_t) is explicitly deferred to pkg270**, and the exporter emits a
degradation note when a volume's absorption color is non-grey (pkg200 rule:
never claim honour silently).

This keeps delta/ratio tracking SCALAR against the pkg267 majorant — the simplest
provably-unbiased estimator — which is the right choice for the CPU correctness
oracle (north star: correctness > fidelity > speed).

## Algorithms

### Delta (Woodcock) tracking — free-flight distance

- **Paper:** Woodcock et al. 1965 (GEM code); pbrt-v4 §14.1–14.2.
- **Ref impl / licence:** pbrt-v4 `media.h` `SampleT_maj`, `cpu/integrators.cpp`
  `VolPathIntegrator` (Apache-2.0). Clean-room, cited in volume_transport.h.
- **Method (scalar, majorant σ̄ from the pkg267 majorant grid via the DDA):**
  walk the ray's majorant segments (DDAMajorantIterator). Within a segment with
  majorant σ̄_seg, sample candidate collisions at rate σ̄_seg
  (`t -= ln(1-u)/σ̄_seg`). At a candidate, a **real** collision occurs with
  probability `σ_t(x)/σ̄_seg` (else a null collision: continue). Unbiased:
  reaching the far boundary with no real collision happens with exactly the
  transmittance probability, so NO explicit transmittance multiply is applied on
  pass-through.

### Ratio tracking — NEE transmittance (shadow rays)

- **Paper:** Novák, Selle, Jarosz 2014, "Residual Ratio Tracking…", SIGGRAPH Asia.
- **Ref impl / licence:** pbrt-v4 `SampleLd` transmittance loop; Cycles
  `shade_volume.h` `volume_integrate_step` (Apache-2.0). Clean-room, cited.
- **Method:** `Tr = Π (1 - σ_t(x_i)/σ̄_seg)` over candidate collisions x_i sampled
  at rate σ̄_seg along each majorant segment. Unbiased estimator of
  `exp(-∫σ_t)`, required because σ_t is spatially varying (the analytic
  exponential used by the homogeneous world volume is only valid for constant
  σ_t). Scalar here (grey σ_t).

### Henyey–Greenstein phase function

- **Paper:** Henyey & Greenstein 1941.
- **Ref impl:** already in `raytracer.h` (`phaseHG`/`sampleHG`, PBRT-v3, BSD) —
  generalized into `include/astroray/volume/phase.h` alongside isotropic, so the
  medium phase has one home (the orphaned `isotropic` plugin used `Lambertian`).

### Equiangular sampling + distance MIS

- **Paper:** Kulla & Fajardo 2012, "Importance Sampling Techniques for Path
  Tracing in Participating Media".
- **Ref impl / licence:** pbrt-v4 / Cycles `shade_volume.h`
  `volume_equiangular_sample` (Apache-2.0). Clean-room, cited.
- **Method:** for an in-scatter NEE toward a point/area light at distance, sample
  the scatter vertex distance along the ray by the equiangular pdf (concentrates
  samples near the ray's closest approach to the light), and combine with
  distance (delta-tracking) sampling via the **power/balance heuristic** MIS. The
  homogeneous world volume already does phase↔light MIS; pkg268 adds the
  equiangular strategy for the bounded-grid NEE (god-rays / spot-in-fog).

## Determinism

Thread the engine RNG (`std::mt19937` seeded from the per-pixel/sample seed) —
NO `std::random_device` (the legacy `ConstantMedium` non-determinism bug,
research note §1b). A fixed render seed must reproduce bit-for-bit.

## Brute-force numpy reference (gate author)

`tests/volume_reference.py`: ray-marched transmittance `exp(-Σ σ_t·Δ)` and
single-scatter radiance `Σ Tr(0→t)·σ_s·phase·Tr(t→light)·L / dist²·Δ` over a
fine step, for a known analytic density field. The tracking estimators must
converge to this within the stated tolerance (independent method → a real
oracle, not self-consistency).
</content>
