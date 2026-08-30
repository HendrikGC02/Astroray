# pkg131 Adaptive Sampling — Cycles auto-threshold derivation (research)

Fills the one gap in `.astroray_plan/docs/2026-07-other-engines-research.md §5`:
the exact **zero-knob** `threshold = 0` → noise-threshold + min-samples derivation,
the check cadence, and the verbatim convergence-check / dilation math. Verified
against the live Cycles source 2026-08-30.

## Paper
- **Title:** A Hierarchical Automatic Stopping Condition for Monte Carlo Global Illumination
- **Authors:** Holger Dammertz, Johannes Hanika, Alexander Keller, Hendrik P. A. Lensch
- **Year / Venue:** WSCG 2010
- **PDF:** http://jo.dreggn.org/home/2009_stopping.pdf
- Half-buffer variance inspiration: Christensen et al., "RenderMan: An Advanced
  Path-Tracing Architecture", ACM TOG 37(3) 2018, DOI 10.1145/3182162.

## Reference implementation
- **Repo:** https://github.com/blender/cycles (main, fetched 2026-08-30)
- **License:** Apache-2.0 — compatible with Astroray's LICENSE (already the cited
  basis for the wavefront RNG, JH LUT, cryptomatte post, and pkg224 Sobol').
- **Files mirrored:**
  - `src/scene/integrator.cpp` — `Integrator::get_adaptive_sampling()` (the zero-knob derivation)
  - `src/integrator/adaptive_sampling.cpp` — `AdaptiveSampling::need_filter`, `::align_samples` (cadence)
  - `src/kernel/film/adaptive_sampling.h` — `film_adaptive_sampling_convergence_check`, `_filter_x/_y` (per-pixel error + dilation)

## The zero-knob derivation (verbatim logic, `get_adaptive_sampling()`)

Given `aa_samples` (the sample budget = our `max_samples`) and user `adaptive_threshold`:

```
if (aa_samples > 0 && adaptive_threshold == 0)
    threshold = max(0.001f, 1.0f / (float)aa_samples);   // auto (zero-knob)
else
    threshold = adaptive_threshold;                       // manual override

// min_samples derived from the PRE-scale threshold (order matters):
if (threshold > 0 && adaptive_min_samples == 0)
    min_samples = max(4, (int)ceilf(16.0f / powf(threshold, 0.3f)));
else
    min_samples = max(4, adaptive_min_samples);

threshold *= 5.0f;        // "arbitrary factor" applied AFTER min_samples is computed
adaptive_step = 16;       // power of two; bitwise cadence
```

Worked values (auto path, threshold pre-scale = 1/aa_samples clamped to ≥0.001):
- `aa_samples=64`  → thr=0.0156 → min=ceil(16/0.0156^0.3)=ceil(16/0.283)=**57**? recompute:
  0.0156^0.3 = exp(0.3·ln0.0156)=exp(0.3·−4.16)=exp(−1.25)=0.287 → 16/0.287=55.7 → **56**; final thr=0.078.
- `aa_samples=256` → thr=0.0039 → 0.0039^0.3=exp(0.3·−5.55)=exp(−1.66)=0.190 → 16/0.190=84.2 → min=**85**; final thr=0.0195.
- `aa_samples=1024`→ thr=0.00098→clamp 0.001 → 0.001^0.3=exp(0.3·−6.9)=exp(−2.07)=0.126 →16/0.126=126.7→min=**127**; final thr=0.005.

(The famous "0.1→32, 0.01→64, 0.001→128" comment matches: min grows ~as thr shrinks.)

## Cadence (`adaptive_sampling.cpp`)

```
need_filter(sample):                       // 0-indexed sample
    if (!use) return false;
    if (sample <= min_samples) return false;
    return (sample & (adaptive_step-1)) == (adaptive_step-1);   // every 16th past floor
```
So convergence is checked at samples 15,31,47,… but only once `sample > min_samples`.
`align_samples` snaps a render chunk so it ends exactly on a filter sample (we drive
our own rounds, so we replicate the intent: run to the next `k*16-1` boundary).

## Convergence check (`film/adaptive_sampling.h`, verbatim math)

Per pixel, `I` = full/combined buffer, `A` = auxiliary HALF-sample buffer:
```
intensity_scale = exposure / sample;                       // sample = count so far
error_difference = (|I.x-A.x| + |I.y-A.y| + |I.z-A.z|) * intensity_scale;
intensity = (I.x + I.y + I.z) * intensity_scale;           // scaled combined intensity
error_normalize = (intensity < 1.0f) ? sqrtf(intensity) : intensity;
error = error_difference / (0.0001f + error_normalize);    // Dammertz §2.1, brightness-relative
converged = (error < threshold);
```
Cycles stores the aux buffer's alpha lane as the converged flag (0 = unconverged).

## Filter dilation (`_filter_x` then `_filter_y`)

Two sequential 1-D passes, radius 1: a pixel that is unconverged forces its
immediate ±1 neighbor (row pass, then column pass) to keep sampling. Net effect is a
3×3 dilation of the unconverged mask so early-out boundaries are not splotchy.

## Astroray adaptation decisions

- **Scalar-luminance half-buffer** (8 GB constraint, research §5b): store `A` as one
  float (luminance) not float3; `error_difference` becomes `|Ilum − Alum| *
  intensity_scale`, `intensity = Ilum * intensity_scale`. This is a deliberate,
  documented deviation from Cycles' float3 aux — luminance noise is the stopping
  signal Dammertz actually thresholds, and it halves-or-better the aux memory.
- **Half-buffer accumulation:** `A` accumulates only even-indexed samples (0,2,4,…);
  `I` accumulates all. At a check with `n` samples, `A` holds `⌈n/2⌉` samples' mean
  and `I` holds `n` samples' mean — the |I−A| difference is the half-vs-full noise
  estimate. (Cycles uses the same odd/even split via the aux pass.)
- **`aa_samples` ↔ `max_samples`:** our `max_samples` cap plays the role of Cycles'
  `aa_samples` in the auto-threshold formula.
- **`exposure`:** Astroray applies exposure (`filmExposure`) at resolve; use 1.0f in
  the metric unless a film exposure is set, matching where Cycles reads
  `kernel_data.film.exposure`.

## What we deliberately do NOT take
- Cycles' tile/work scheduler and its render-buffer pass layout — Astroray has its own
  wavefront flat-pool scheduler (GPU) and per-pixel CPU loop; we port only the metric,
  the auto-threshold, and the dilation.

## Integration plan
- New header `include/astroray/sampling/adaptive_sampling.h` — the metric + auto-derive
  as pure `__host__ __device__` free functions (unit-testable on CI, no GPU).
- CPU leg: convergence check in the CPU per-pixel sample loop.
- GPU leg: **compacted active-pixel round** on top of the existing flat work pool
  (regen indexes `activePixels[w % numActive]`, per-pixel sample counter, per-pixel
  final divide) — additive, byte-identical when off, respects the flat-pool perf
  design (the 1.5 s ceiling). NOT a wave-based rewrite.
- Package: `.astroray_plan/packages/pkg131-zero-knob-adaptive-sampling.md`.

## Open questions
- None blocking. The GPU compacted-active-list is an implementation detail of "the
  wavefront already owns compaction" (spec), not a fork needing owner input.
