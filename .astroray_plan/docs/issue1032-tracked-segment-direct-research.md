# #1032 — tracked-collision distance strategy for the bounded-media segment direct light

## Problem

`v2_media` smoke_plume: per-sample variance 79x Cycles (old main 13a841be) / 21.6x
(main 6f2b0c70, 20 seeds). Ablation (CPU, 64 spp, `ASTRORAY_PKG306_DIAG`): turning the
segment direct light off drops the ROI to 0.5x, the NEE/equiangular switches barely move
it, and distance-only explodes to 3.45e4x. Owner: the #925 distance strategy, a lane
mixture of truncated exponentials at the media hull's GLOBAL majorant, which piles
samples at the AABB entry or into empty space of a sparse dense VDB.

## Sources

- Miller, Georgiev, Jarosz, "A Null-Scattering Path Integral Formulation of Light
  Transport", SIGGRAPH 2019, ACM TOG 38(4) 44, DOI 10.1145/3306346.3323025, §5-6: path
  pdfs with null vertices; the distance pdf of a scatter at t, over the exponential
  factors both strategies share, is Π p_n · σ̄(t) · p_s(t).
- Blender Cycles v5.2.0 `intern/cycles/kernel/integrator/shade_volume.h` (Apache-2.0):
  `volume_indirect_scatter_advance` :908, `VolumeSampleReservoir` :1011,
  `volume_scatter_probability` :1315, `volume_integrate_step_scattering` :1411,
  `volume_equiangular_direct_scatter` :1491, `volume_direct_scatter_mis` :1559, 50/50
  strategy pick :1595. Fetched copy (one-off) in the lane evidence folder.
- Local majorants: pkg267 majorant grid + DDA (pbrt-v4 §11.4.2, Apache-2.0),
  `include/astroray/volume/majorant_grid.h`; research note pkg267.
- Kulla & Fajardo 2012 equiangular (unchanged from #925).

## Estimator (Cycles-faithful)

`volume::sampleSegmentDirectTracked` (CPU) / `gpuSampleSegmentDirectTracked` (GPU, kind 0):

1. Pick equiangular or distance with probability 1/2 (Cycles MIS mode, the Blender
   default `volume_sampling`).
2. Walk the null-collision chain from the hull entry at the LOCAL majorant
   (`walkSegmentMajorants`: one grid => its supervoxel DDA plus any overlapping
   homogeneous σ̄; two or more grids => Σ global majorants, the #842 rule). Collisions
   before the lit interval are forced null (pdf 1 in both strategies).
3. Ratio-tracking Tr = Π σ_n(λ)/σ̄ rides the chain (RR below 0.05 on the max lane).
4. Distance strategy: reservoir over scatter candidates on [a,b], W_k = Π p_n · p_s,k
   (Cycles `VolumeSampleReservoir`); the kept k carries ΣW (RIS normalisation, so the
   expectation is the collision estimator Σ Tr_k σ_s,k / σ̄).
5. p_s = hero average of σ_s/(σ_s+σ_n) (Cycles uniform channel pdf), absorption a weight.
6. Power-heuristic one-sample MIS, w = 2·p_c/(p_c² + p_o²).
7. Segment-NEE shadow rays use local-majorant ratio tracking too (surface NEE unchanged).

## Verification

- `tests/test_issue1032_tracked_segment_direct.py` (seam `segment_tracked_probe`):
  slab + 1D grid step closed form, distance-only and MIS; local/global Tr vs
  Beer-Lambert; E[ΣW] = 1 − exp(−σ̄ p_s (b−a)).
- v2_media CPU, 64 spp, 20 seeds, vs Cycles: smoke_plume 21.6x → 2.05x, shaft 14.9x →
  2.14x, full 3.28x → 2.98x, trimmed 8.62x → 3.40x; every ROI mean |z vs base| ≤ 2.4.

## Rejected / not needed

- Separate light sample counts at P (16 samples: 7.25x → 5.15x on old main) — not
  Cycles, not needed once the gate held.
- Supervoxel edge 4/8/16: no measurable difference on the smoke.
- VSPG volume guiding (Cycles :1067): the remaining lever if a denser scene still fails.
