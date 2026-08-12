# pkg185 — GPU glass-sphere photon-caustic parity gate fails structurally (SSIM 0.01)

**Pillar:** 3/5 (light transport / GPU parity)
**Track:** A (RTX hardware root-cause)
**Status:** done (PR #TBD, 2026-08-12 — SSIM 0.0101 → 0.9606, GPU peak 1007 → 0.41;
root cause: the test scene's sun used raw irradiance `6.0` (radiance S/Ω ≈ 19100)
instead of the reference scene's Ω-scaled `6.0·Ω` (radiance ≈ 6.0). Harmless
until pkg181 made dedicated lamps BSDF-visible, at which point the ball-lens
produced correct-but-high-variance specular sun-disk images (peak ~1007) that
the CPU reference's independent RNG did not hit at the same pixels, collapsing
the variance-based SSIM. Fix mirrors the reference scene's Ω-scaling; the
transport is confirmed in parity — clamp_indirect on both sides independently
lifts SSIM to 0.97. Found 2026-08-12 during the hygiene run's full clean-build
RTX sweep; pre-existing on `main` — failed identically at 63d94d4 and 24106ca.)
**Estimated effort:** M
**Depends on:** pkg113 GPU photon-caustic pre-pass; `tests/test_gpu_caustic_parity.py`.

## Symptom

```
tests/test_gpu_caustic_parity.py::test_gpu_glass_sphere_caustic_parity
pkg113 GPU glass-sphere SSIM 0.0101 < 0.80 — GPU diverges from CPU structurally.
caustic-ROI energy GPU=24106 CPU=22193 ratio=1.086x | SSIM=0.0101 | GPU peak luminance=1006.97
[CUDA wavefront] pkg113 photon caustic: 820694 photons, scale 2.65261e-07
```

ROI energy ratio is fine (1.086×) but SSIM ≈ 0.01 with a peak luminance of
~1007 — the GPU caustic is structurally wrong (firefly-like spikes or
misplaced deposition), not dim/bright. This was the ONLY substantive failure
in the otherwise green full sweep (1847 passed / 2 failed; the other failure
was a hygiene-branch test artifact, fixed).

## Attribution status

- Fails identically on `main` (63d94d4) and the hygiene branch → NOT caused
  by the 2026-08-11 hygiene deletions (which removed only caller-less
  kernels; A/B-verified).
- Onset unknown. The last claimed-green full sweep (2026-08-06, "1563
  passed") predates the pkg178 Stage-4/5 + pkg182 merges, but per
  [[pkg183-incremental-build-staleness-guard]] any historical local result
  from incremental builds is suspect. **A bisect of this failure MUST use
  clean builds per step** (the hygiene run demonstrated an incremental-build
  bisect fabricating a false first-bad-commit).
- Candidate onset window: the 2026-08-08..10 merges that touched GPU shade
  (pkg178 Stage-2/3b/4 GPU twins, pkg182 eval-D, pkg181 dedicated-light
  visibility, pkg172A guarded light-pdf legs — several alter the closure
  eval/pdf the photon pre-pass and ROI shading share).

## Work

1. Reproduce; dump the GPU and CPU caustic images (test writes them under
   test_results) and inspect visually (per [[general-photon-loop-needs-solid-glass]]:
   caustic gates have passed numerically on garbage before — LOOK at it).
2. Check the pkg157-style firefly clamp path for the photon contribution
   (peak 1007 suggests unclamped spikes), and the photon deposition
   coordinates (wavefront snapshot semantics class-of-bug).
3. Clean-build bisect over 2026-08-06..11 engine merges if (1)/(2) don't
   localize it.
4. Re-run the caustic family gates (pkg29a/64/106/109/110/111/113) after the fix.
