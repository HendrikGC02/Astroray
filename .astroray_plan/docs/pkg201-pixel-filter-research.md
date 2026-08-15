# pkg201 Stage 2 (Finding D) — pixel reconstruction filter research

**Question:** how to honour `pixel_filter_type` (Box / Gaussian / Blackman-Harris)
and `filter_width` on the GPU wavefront path so the pkg200 `pixel_filter_type` and
`filter_width` rows flip HONEST-FAIL → PASS (predicate `p_grad_sharper`: a narrow
filter must produce measurably sharper edges — higher luminance gradient — than a
wide one), WITHOUT a cross-pixel atomic splat.

## Canonical approach: filter importance sampling (NOT weighted splat)

The steering-wheel-correct, register-neutral way to apply a reconstruction filter
is **filter importance sampling**: draw the primary ray's sub-pixel offset from the
*filter's own distribution* over its full support `[-width/2, +width/2]`, and
accumulate every sample with weight **1** (no per-sample filter weight, no
cross-pixel splat). Because the offset can exceed ±0.5 px for `width > 1`, samples
naturally land in neighbouring pixels, which is exactly what blurs edges — a wide
filter lowers the luminance gradient, a narrow one preserves it.

This is precisely how **Cycles** implements pixel filters: it precomputes an
inverted CDF of the filter (`filter_table`) and, at ray generation, maps a uniform
`u ∈ [0,1)` through it to a sub-pixel offset scaled by the filter width; the sample
then accumulates with unit weight. (Cycles `kernel/film` filter table + Blender
task T45519 "Cycles Image Reconstruction kernel", Apache-2.0. The Blackman-Harris
option was added by Lukas Stockner, 2015.) The Cycles docs note the equivalent
alternative — uniform sub-pixel sampling with per-sample filter *weights* — but
Cycles uses importance sampling (unit weight) because it composes cleanly with
progressive accumulation, which is exactly our wavefront `atomicAdd` accumulate.

**References**
- Ernst, Stamminger, Greiner, *Filter Importance Sampling*, IEEE Symposium on
  Interactive Ray Tracing 2006 — the canonical statement: sample offsets ∝ filter,
  accumulate weight 1 (variance-equivalent to, and simpler than, weighted splat).
- PBRT-v4 §8.8 *Image Reconstruction* / `FilterSampler` (Pharr, Jakob, Humphreys,
  BSD) — inverts the filter's 2D distribution and returns a unit-weight sample.
- Cycles `intern/cycles/kernel/film/` filter table; Blender T45519 (Apache-2.0).
- Blackman & Harris window (Blackman-Harris 4-term): the same coefficients Cycles
  and the existing CPU `Renderer::filterSample` (raytracer.h:2433) already use
  (0.35875, 0.48829, 0.14128, 0.01168).

## What we implement (GPU, stage_init.cu::filterSample)

Per-axis (u and v drawn independently), offset in pixels:

- **Box (type 0):** offset = `Uniform() - 0.5` — uniform over one pixel, **width-
  ignored**. This is byte-identical to the pre-pkg201 GPU behaviour AND matches the
  CPU box (which also ignores width), so the default fleet render is unchanged and
  the register/parity baseline is untouched. 1 RNG draw (unchanged draw count).
- **Gaussian (type 1):** Box-Muller normal `z` (2 draws), offset =
  `clamp(z · width/6, -width/2, +width/2)`. `σ = width/6` places the ±3σ mass at the
  ±width/2 support edge (the same σ the CPU `filterSample` uses). Importance-sampled
  (offset ∝ gaussian), unit weight. For `width > 1` the offset crosses pixel
  boundaries → edge blur.
- **Blackman-Harris (type 2):** rejection-sample `x` uniform in `[0,1)`, accept with
  probability equal to the normalised 4-term BH window evaluated at `x` (≤ 20
  attempts, uniform fallback), then map to a width-scaled centred offset
  `(x - 0.5)·width` — the same rejection scheme the CPU uses, scaled to the full
  width.

The filter (type + width) is published once per frame into a `__constant__`
(`setWavefrontPixelFilter`), mirroring the pkg197 guide / pkg199 world-volume
binding pattern, so no kernel launch signature grows and the fleet shade/intersect
register footprint is untouched. `filterSample` lives in `stage_init.cu` (primary-
ray generation), NOT the REG-254 shade kernel, so this is register-neutral for shade.

## CPU divergence (recorded, deliberately not fixed here)

The CPU `Renderer::filterSample` (raytracer.h:2424) shapes the *within-pixel*
jitter but **clamps every filter type to `[0,1)`** — the Gaussian is centred at 0.5
and clamped, Blackman-Harris rejection is over `[0,1)`. So the CPU filter never
crosses a pixel boundary and `filter_width > 1` does not blur across pixels: the CPU
honours filter *type* weakly and does **not** honour `filter_width` as a
reconstruction radius. This is a matching CPU gap. It is left as-is because:
(1) the pkg200 honour gate is the **GPU F12 path** (this row renders on the GPU),
(2) `filterSample` is on the hot CPU render path guarded by many CPU parity gates,
and (3) there is no CPU honour test to gate a CPU change. Fixing the CPU side is a
separate small follow-up; it is recorded in the pkg201 results delta, not silently
skipped.
