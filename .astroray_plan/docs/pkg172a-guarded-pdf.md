# pkg172(A) — guarded-pdf fix for the universal ~0.628%/bounce energy loss

## The defect (convicted 2026-08-02, architect verdict in the pkg172 spec)

Every throughput/NEE estimator divided by an **additive** pdf epsilon:

```
throughput *= f_spectral * (1.0f / (pdf + 0.001f));      // BSDF throughput
nee += f * L * (wt / (ls.pdf + 0.001f));                  // NEE
```

An additive `+ε` in the denominator is a systematic **under-weighting** of
every estimate. Under cosine-sampled diffuse (`f = albedo·cosθ/π`,
`pdf = cosθ/π`, so `f/pdf = albedo` exactly, zero-variance per sample), the
analytic loss is exactly **`2π·ε = 0.628%` per bounce** for `ε = 1e-3`. A
0.5-albedo Lambertian wall under a unit white env must reflect exactly 0.5
(Veach 1997; the scene is zero-variance), so this deterministic deficit is a
defect, not a convention. Confirmed by the spec's probe: dropping ε to `1e-6`
reads the wall at exactly 0.500.

## The fix (pbrt-v4 convention — cited, not invented)

pbrt-v4 never biases the estimate with a denominator epsilon; it **rejects the
sample at the source** when the pdf is degenerate and otherwise divides by the
**exact** pdf (see *Physically Based Rendering* 4e, §13.3 "The Light Transport
Equation" / the `SampleLd` and path-throughput updates: `if (bs->pdf == 0)
break;` then `beta *= bs->f * AbsDot(...) / bs->pdf`). Expressed as the local
guarded reciprocal used here:

```
f_spectral * (pdf > 1e-8f ? 1.0f / pdf : 0.0f)
```

- Degenerate pdf (`≤ 1e-8`, i.e. a sample essentially at the horizon, measure
  ~zero and with `f→0` too) contributes zero — equivalent to pbrt's
  `break`/terminate, with no NaN/Inf risk.
- Every real sample divides by the **true** pdf → the estimator is now
  unbiased; the furnace wall reads the analytic value.

Applied to the three convicted legs (CPU path_tracer + CPU wavefront, CPU
multiwavelength, GPU wavefront) — `include/raytracer.h`,
`src/cpu/wavefront/{path_kernel,reference_pt_production}.cpp`,
`plugins/integrators/multiwavelength_path_tracer.cpp`,
`src/gpu/wavefront/{stage_advance,stage_light_sample,stage_shade_lambertian,stage_shade_metal}.{cu}`.

## Deliberately NOT fixed here (surgical scope)

`plugins/integrators/neural_cache.cpp` and `plugins/integrators/restir_di.cpp`
carry the **same** additive-epsilon bias but are specialized integrators
outside the convicted three legs; their gates are already pinned to the biased
value. Left as a noted follow-up so this PR's re-pin batch stays attributable
to the analytic 0.628%/bounce prediction. (The `gpu_nee.cuh:439` occurrence is
commented-out dead code.)

## Consequence: coordinated re-pin

The fix **brightens every diffuse bounce** toward the true value on all three
legs. Any furnace/parity/reference gate pinned to the old (dark) value shifts
up by ~0.628%/bounce (compounding with depth). Each re-pin in this PR is
justified against that analytic prediction and the furnace-analytic oracle
(0.5 wall → 0.5), never re-pinned to "whatever the new number is."
