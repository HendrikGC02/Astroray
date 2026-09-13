# pkg268 research — CPU heterogeneous volume transport (cite-algorithm)

Batch F, 2026-09-13. Required by CLAUDE.md §6 before the non-trivial tracking /
phase / MIS code. Companion to pkg267's NanoVDB+majorant note.

## Scope decision (spectral σ): GREY extinction in pkg268

The engine is spectral, but the volumes-track research note (§2 table, §4.1) and
the pkg268 spec assign **per-λ chromatic extinction (spectral/decomposition
tracking, Kutz 2017)** to **pkg270**. pkg268 therefore uses the exact **Cycles
`svm_node_principled_volume` per-channel coefficients** and then collapses them to
a **scalar σ_t + spectral single-scattering albedo** for the grey tracker:

Cycles (per channel, `density` = the Density socket `D`):

* `σ_s(λ) = color(λ) · D`
* `σ_a(λ) = max(1 − color(λ), 0) · max(1 − sqrt(absorption_color(λ)), 0) · D`
* `σ_t(λ) = σ_s(λ) + σ_a(λ)`

With the **default white `absorption_color`, σ_a = 0** — the medium is lossless
(per-channel albedo 1), NOT the over-absorbing `σ_a = (1−color)·D` an earlier cut
used (that was the cycles-parity-reviewer finding — the previous claim of grey
parity was **wrong** and is corrected here).

Scalar-σ_t collapse (grey tracker):

* `extinction_scale = D · max_c(σ_s_c + σ_a_c)`  (one conservative grey majorant),
* `albedo_c = σ_s_c / max_c(σ_s_c + σ_a_c) ∈ [0,1]`  (energy-safe: albedo ≤ 1 per
  channel, so no per-channel energy gain).

Consequence: **extinction is grey** (all channels attenuate at the max-channel
rate); the colour lives entirely in the spectral scattering albedo. The max
channel is exact vs Cycles; sub-max channels are over-extincted (the documented
grey approximation). The #807 cabinet's red look comes from the red scattering
albedo, sufficient for the "soft translucent red patch" cross-check bar. **True
per-λ (chromatic) extinction is pkg270**; the exporter emits a degradation note
whenever `color` OR `absorption_color` is chromatic (pkg200 rule).

Volume Absorption node (Cycles `σ_a = (1 − Color)·D`, `σ_s = 0`) is exported by
setting `color = 0`, `absorption_color = Color²`, which the formula above turns
into `σ_a = (1 − Color)·D` exactly — so a default white-Color absorption cube is
**transparent** (matching Cycles), where the first cut made it opaque.

This keeps delta/ratio tracking SCALAR against the pkg267 majorant — the simplest
provably-unbiased estimator — which is the right choice for the CPU correctness
oracle (north star: correctness > fidelity > speed).

### Known scope limitations (pkg268; follow-ups)

* **Equiangular sampling is validated in the test oracle only.** The production
  medium NEE (`raytracer.h`, the loop-top grid block) samples the scatter vertex
  by delta tracking and does light↔phase MIS (power heuristic) — unbiased, matches
  the world-volume scaffold. The equiangular+distance MIS estimator (Kulla &
  Fajardo 2012) lives in `equiangularSample`/`equiangularPdf` and the
  `volume_single_scatter_estimate` binding, where it is gated against the numpy
  ray-march; folding it into the heterogeneous render-path NEE is a variance
  follow-up (pkg271-scope). The oracle uses the **balance** heuristic; the
  production path uses the **power** heuristic (both valid MIS weights).
* **Nearest-medium in-scatter only.** Each escaping segment runs free flight
  against the single nearest entered medium; overlapping/stacked bounded media are
  not composited in one segment (the #807 cabinet cubes are disjoint, so this is
  moot there). A medium stack is a pkg272-scope follow-up.

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
