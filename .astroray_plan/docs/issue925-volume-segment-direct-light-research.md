# #925 — Per-segment volume direct light — Research

## Paper
- **Title:** Importance Sampling Techniques for Path Tracing in Participating Media
- **Authors:** Christopher Kulla, Marcos Fajardo
- **Year / Venue:** EGSR 2012 (Computer Graphics Forum 31(4))
- **DOI:** 10.1111/j.1467-8659.2012.03145.x

## Reference implementation
- **Repo:** Blender Cycles, `src/kernel/integrator/shade_volume.h` (main, read 2026-09-27)
- **License:** Apache-2.0 — compatible with Astroray's MIT/Apache target.
- **Mirrored (derived, not transcribed):**
  - `integrate_volume_sample_direct_light` — pick a light for the segment (`light_sample_from_volume_segment`), use its point as the equiangular anchor.
  - `volume_valid_direct_ray_segment` — clip the segment to what the light can light (spot cone, area-light half-space).
  - `volume_integrate_state_init` / `volume_direct_scatter_mis` — one-sample MIS: equiangular vs distance, 50/50, weight `2·power_heuristic`.
  - `integrate_volume_direct_light` — re-sample the SAME light from the chosen point.
  - Homogeneous indirect: absorption is a throughput weight, not a termination.

## What we reproduce
- Equiangular distance pdf `D / ((θb-θa)(D²+t²))` (K&F 2012 §4).
- Distance strategy: lane mixture of truncated exponentials with the per-λ σ_t (majorant for grids) — unbiased under hero-λ since the pdf depends only on the λ bundle.
- One direct-light sample per medium segment, weighted by Tr(0,t)·σ_s(t); phase components MIS'd per medium against their own HG pdf (the complement of the lamp-hit weight after a phase-sampled continuation from that medium).
- Free flight: real collision with pdf σ_t[0]/σ̄ scatters with beta *= σ_s/σ_t[0], r_u *= σ_t/σ_t[0] (pbrt-v4 VolPath spectral MIS with absorption folded into the weight).
- Homogeneous transmittance is analytic (Beer-Lambert) in shadow and camera segments.

## Differences from the reference
- Light tree mode: the pick depends on the shading point, so no same-light re-sample and no segment clip; the NEE at P is a fresh pick (unbiased, less efficient). Cycles picks with the segment-aware tree.
- Clip for spot lights is conservative (outer angle + 1e-3, apex pulled back by r/sin θ so the cone contains the lamp sphere).

## Measured (pkg289 fixture, CPU, 64 spp, 12 seeds; nv R/G/B)
- Before: 0.53 / 0.50 / 0.88 (100x / 100x / 180x Cycles). After: 0.0144 / 0.0114 / 0.0328 (2.8x / 2.3x / 6.8x).
- Single scatter only (vb0): Astroray 0.0045/0.0023/0.018 vs Cycles 7e-5. The residual is spectral: a delta-lit diffuse floor with no medium has nv 0.0024/0.0005/0.0155 (pkg206 hero-λ pdf under-samples blue, #848), so B cannot reach 4x Cycles until the λ sampler changes.
- World fog: 0.41/0.36/0.73 -> 0.0082/0.0054/0.024; means match the old engine to 0.2 % at 2048 spp.

## Integration
- `include/astroray/volume/volume_transport.h` (`sampleSegmentDirect`, `segmentTransmittanceSpectral`, spectralTrack/Overlap weight change), `include/raytracer.h` (`segmentDirectLight`, `boundedSegmentDirect`, fog + bounded blocks), `Light::clipLitSegment` (spot/area), `PowerLightSampler::resample`.
- Tests: `tests/test_pkg289_medium_chromatic_variance.py`.
- GPU twin: not yet (`stage_advance.cu` volume path, `stage_volume_hetero.cu`).
