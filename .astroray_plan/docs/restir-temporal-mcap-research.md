# ReSTIR temporal M-cap divergence — root cause + fix (pkg55-C6b, PR #503)

**Date:** 2026-07-21. **Context:** HW gate for PR #503 failed —
`test_temporal_reduces_variance` showed no variance reduction (parked).

## Two independent defects found

### 1. Reachability (test-side)
The ReSTIR validation helpers (`tests/restir_helpers.py`) never call
`set_use_gpu(True)`. `useGPU` defaults to `false` (`blender_module.cpp:359`),
so `r.render()` takes the CPU `restir_di` path — the new
`cuda_wavefront_render_restir` GPU driver is never exercised by the gate.
Measured: identical scene, no-GPU mean = 0.397, GPU (`set_use_gpu(True)`) mean
= 0.283 — different code path, confirming CPU was being measured.

### 2. Effectiveness (GPU merge divergence)
Once GPU is enabled, temporal reuse *increases* variance because the merged
reservoir's contribution weight `W` inflates without bound across frames. The
temporal frame mean drifts up monotonically (0.283 → 0.378 over 40 frames);
the drift onset is at ~frame 20, exactly when the accumulated `M` reaches the
cap of 80 (grows 4/frame).

## Root cause of (2): M-cap applied to the wrong quantity

Bitterli et al. 2020 §5.2 (DOI 10.1145/3386569.3392481): the **previous**
reservoir's confidence `M` must be clamped to at most 20× the current
reservoir's `M` **before** the merge; the combined reservoir's `M` then
accumulates (`M = M_cur + M_prev_clamped`) and is **not** re-clamped. Without
capping the source `M`, temporal correlation grows unbounded (Chris Wyman's
"A Gentle Introduction to ReSTIR", 2023 course notes, §temporal; tatran5
ReSTIR README: "clamp M ... otherwise this can go unbounded").

The Astroray code instead clamps the **combined** `M` **after** the merge:

    res.merge(pr, pHatPrev, rng);
    res.M = min(res.M, mCap);   // <-- clamps COMBINED M (wrong)

Effect: the stored `prev.M` is frozen at the cap (80) while `w_sum` keeps
accumulating (`w_sum_new = S + w_sum_prev`, no attenuation), because the merge
weight `prev.W · pHat · prev.M = prev.w_sum` with `prev.M == cap`. So
`W = w_sum/(pHat·80)` grows linearly → runaway brightening + rising variance.

Numeric prototype (`scratchpad/reservoir_sim.py`), 60-frame single-pixel
recursion, true integrand = 1.0:

| variant | estimate mean (frames 30-60) | std |
|---------|------------------------------|-----|
| buggy (clamp combined M after)   | 2.359 | 0.4211 |
| fixed (clamp prev.M before merge)| 1.082 | 0.0210 |

The fixed variant converges to the true value with ~20× lower variance.

## Fix (device stage `stage_restir.cu`)

Clamp the source reservoir's `M` **before** the merge (both temporal and each
spatial neighbour), and remove the post-merge combined-M clamp. `pr`/`nbr` are
local copies (`loadReservoir` returns by value), so mutating `.M` is safe and
the shared `Reservoir::merge` template is untouched:

    pr.M = min(pr.M, mCap);        // Bitterli 2020 §5.2: cap PREV M
    res.merge(pr, pHatPrev, rng);  // combined M = cur.M + capped prev.M (kept)

## CPU note (latent, not exercised)

`plugins/integrators/restir_di.cpp:237,257` has the same clamp-after-merge
pattern. It does not manifest in the CPU tests because CPU temporal reuse is a
no-op there (frameState history does not accumulate across the harness's
separate `render()` calls — verified: CPU temporal frame means are flat at
~0.40 for 40 frames, identical to no-reuse). Flagged for a parity follow-up so
the "mirror CPU term-for-term" claim stays honest; not fixed here to keep the
GPU-scoped PR surgical.

## References
- Bitterli et al. 2020, "Spatiotemporal reservoir resampling…", DOI
  10.1145/3386569.3392481, §5.2 (M-capping).
- Wyman, "A Gentle Introduction to ReSTIR Path Reuse in Real-Time", 2023
  course notes, https://intro-to-restir.cwyman.org/
- tatran5/Reservoir-Spatio-Temporal-Importance-Resampling-ReSTIR (README,
  M-cap discussion).
