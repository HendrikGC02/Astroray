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
- GPU twin (#929): `stage_volume_hetero.cu gpu_volumeSegmentDirect` (rdc, out of the
  intersect kernel's frame) is called by `intersectPathSlotT` before the bounded / fog
  free flight with the pre-flight throughput. It parks one standard NEE record into a
  per-segment slot (kind 0 bounded, kind 1 fog; `GWavefrontGridVolumeBinding.segNee*`),
  resolved by a second `stageShadowKernel` launch per kind (`volSegment=1`: occlusion,
  world/grid shadow Tr, clamp, VOLUME_DIRECT/INDIRECT pass). The scatter kernels no
  longer do NEE. Same light pick / clip / MIS as the CPU; RNG is counter-based
  (`gpu_segSalt`), independent of the CPU stream. Lamp pass runs before the bounded
  flight with explicit grid Tr; tracking takes absorption as a weight; homogeneous
  `gpu_gridVolumeTransmittance` is Beer-Lambert.

## MIS pairing (review follow-up, Cycles main a456b761)
- `integrate_volume_direct_light` re-samples the same light from the direct point P and weights it
  `light_sample_mis_weight_nee(ls.pdf, phase_pdf)` at P; `volume_direct_scatter_mis` combines only
  the equiangular and distance pdfs (`2·power_heuristic`). The phase continuation stores
  `mis_ray_pdf = phase_pdf` at the indirect point. Direction weights are point functions of
  (x, ω), so NEE at P and the lamp hit from P' sum to 1 at every point. Astroray does the same.
- Test `tests/test_925_medium_segment_nee_unbiased.py` (area lamp in box / world fog, mesh
  emitter; NEE on vs off) found a pre-existing bug instead: in bounded media a lamp hit was
  weighted by survival to the surface, not Tr(lamp) (NEE off 17-20 % dark on the batchAE base).
  Fixed by running the lamp pass before the bounded free flight with explicit Tr (the pkg288
  world-fog design). GPU twin has the same structure (follow-up).
- Light-tree mode: no same-light re-sample (the tree pick depends on the point), so the anchor
  light and the connected light may differ: unbiased, less efficient. Fixing it needs a tree
  re-sample API and point-consistent weights; left as a note.
