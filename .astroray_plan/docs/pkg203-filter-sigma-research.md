# pkg203 — Cycles-accurate pixel-filter width→σ — Research

**Question:** what is the *correct* width→σ mapping for the Gaussian reconstruction
filter (and the Blackman-Harris support), so the reconstruction-filter spread
matches Cycles? The pre-pkg203 mapping was `σ = filterWidth / 6` (both backends),
which on pkg200's honour matrix left the `pixel_filter_type` row (BOX@1 vs
GAUSSIAN@3, predicate: BOX must be ≥1% sharper than the wide Gaussian) at
**0.83% sharper — HONEST-FAIL** (correct direction, below threshold). The Gaussian
was not spreading enough, so a wide Gaussian did not blur the edge enough relative
to a box.

## Canonical source — Cycles pixel filter table

Cycles builds an inverted-CDF `filter_table` from three filter kernels and applies
a per-kernel width pre-scale. Reference (verbatim):

Blender Cycles, `intern/cycles/src/scene/film.cpp` (main branch, Apache-2.0):

```cpp
static float filter_func_box(float /*v*/, float /*width*/) { return 1.0f; }

static float filter_func_gaussian(float v, const float width) {
  v *= 6.0f / width;
  return expf(-2.0f * v * v);
}

static float filter_func_blackman_harris(float v, const float width) {
  v = M_2PI_F * (v / width + 0.5f);
  return 0.35875f - 0.48829f * cosf(v) + 0.14128f * cosf(2.0f * v)
         - 0.01168f * cosf(3.0f * v);
}
```

and in `filter_table(...)` the *user* width is pre-scaled before building the
inverted CDF over `[0, width*0.5]` (symmetric → full support `[-width/2, +width/2]`):

- **Box**:            `width` as-is                → support `[-0.5·w, +0.5·w]`
- **Gaussian**:       `width *= 3.0f`              → support `[-1.5·w, +1.5·w]`
- **Blackman-Harris**:`width *= 2.0f`              → support `[-1.0·w, +1.0·w]`

(`w` = the user `filter_width`; the CDF is inverted with `util_cdf_inverted`,
`symmetric=true`.)

### Deriving the equivalent Gaussian σ

With the pre-scale, `filter_func_gaussian` is evaluated with `width_scaled = 3w`:

```
f(v) = exp(-2 · (6v / 3w)^2) = exp(-2 · (2v/w)^2) = exp(-8 v^2 / w^2)
```

Matching the normal form `exp(-v^2 / (2σ^2))`:

```
8 / w^2 = 1 / (2σ^2)   ⇒   σ^2 = w^2 / 16   ⇒   σ = w / 4
```

and the truncation/support half-extent is `1.5·w` (= 6σ, i.e. essentially the full
Gaussian). So the Cycles-accurate mapping is:

- **Gaussian:** `σ = width / 4`, support `[-1.5·width, +1.5·width]`.
- **Blackman-Harris:** support `[-1.0·width, +1.0·width]` (offset = `(p-0.5)·2·width`
  where `p∈[0,1)` is the rejection-sampled normalised window position).

The pre-pkg203 mapping was `σ = width/6`, support `[-0.5·width, +0.5·width]`
(Gaussian) and `[-0.5·width, +0.5·width]` (BH). Both were **too narrow** — the
Gaussian spread was `σ=0.5, support ±1.5` for width 3, versus the Cycles-correct
`σ=0.75, support ±4.5`. Widening to the Cycles values makes the wide Gaussian
blur the edge more, so a box (support ±0.5) reads measurably sharper (> 1%).

## Corroborating textbook source — PBRT

PBRT-v4 §8.8 *Image Reconstruction*:
- `GaussianFilter(radius, σ)` — a truncated Gaussian, radius = full support half-extent,
  `f(x) = max(0, exp(-x^2/(2σ^2)) - exp(-radius^2/(2σ^2)))`. The Cycles pre-scale
  `width*=3` with `σ=w/4` places the support at `±1.5w = ±6σ`, i.e. the truncation
  term is negligible — consistent with PBRT's truncated-Gaussian convention.
- `MitchellFilter` / `BlackmanHarrisFilter` — support = `radius`, windowed; Cycles'
  `width*=2` maps the user width to a `±w` support, the same convention.
- Filter *importance sampling* (unit-weight offset ∝ filter) is PBRT-v4 §8.8
  `FilterSampler` (BSD) and Ernst/Stamminger/Greiner, *Filter Importance Sampling*,
  IEEE Symp. Interactive Ray Tracing 2006 — see `pkg201-pixel-filter-research.md`.

## Scope note (§2 of the spec) — CPU support widened

The pre-pkg203 CPU `Renderer::filterSample` (raytracer.h) clamped every filter type
to a within-pixel `[0,1)` jitter (never crossed a pixel boundary). Cycles' Gaussian
support is `±1.5·width` (and BH `±1.0·width`), which for `width > 1` **strictly
requires wider-than-pixel support**. Per spec §2 this scope change is stated
explicitly: the CPU Gaussian/BH branches now emit a *centred* offset over the
Cycles support (mirroring the GPU filter-importance-sampling topology added by
pkg201-S2), so both backends read the **same σ / support constants**. This is NOT
a splat-topology change — every sample still accumulates to its originating pixel
with unit weight (the ray origin jitters, the target pixel does not). The **Box**
branch is unchanged on both backends (uniform, width-ignored), so the default
fleet render (pixelFilterType=0) and its parity/convergence baselines are untouched.

## Where cited in code

- CPU: `include/raytracer.h::Renderer::filterSample` (Gaussian + Blackman-Harris branches).
- GPU: `src/gpu/wavefront/stage_init.cu::filterSample` (Gaussian + Blackman-Harris branches).

Each site cites Cycles `scene/film.cpp` and points at the other as the byte-mirror.
