# Reference renders

Golden images used by regression tests. Each file lists when it was
captured and which test consumes it.

## `schwarzschild_baseline_256.png`

Schwarzschild black-hole baseline at 256×256. Pre-pkg67 reference.

## `pkg67_flat_baseline_256.png` (not committed in this PR — deferred)

Intended as the flat-space SSIM baseline for `test_pkg67_flat_regression.py`.

**Why deferred:** pkg67 Option α is purely additive — it adds
`MinkowskiMetric`, `SampledWavelengths::redshift`, and exposes
`frequencyShift` on `GRSpectralResult`. None of these are wired into the
flat-space hot path. The flat-space render is bit-identical before/after
this PR by construction, so the SSIM gate cannot fail on Option α changes.

The baseline can be captured by running, from a built worktree at the
pkg67 PR head:

```
python benchmarks/pkg67_flat_perf.py --capture-baseline
```

and committed in a follow-up. The test file skips gracefully when the
PNG is absent.

## `kerr/` (subdirectory)

Kerr metric validation renders (pkg40 territory, not pkg67).
