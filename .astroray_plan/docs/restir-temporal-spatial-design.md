# ReSTIR Temporal and Spatial Reuse — Design Note

**Package:** pkg23  
**Status:** accepted  
**Author:** Claude Code / Track A  
**Date:** 2026-04-29  
**Depends on:** pkg22 (initial sampling), Bitterli et al. 2020

---

## 1. Overview

Initial sampling (pkg22) produces one direct-light reservoir per pixel per
frame. Each reservoir holds the best candidate from N light samples. This is
already unbiased, but variance is still high because N is small (default 4).

Temporal and spatial reuse dramatically reduce variance by sharing reservoir
state across adjacent pixels and frames. A pixel can effectively "see" the
candidates chosen by its neighbours and its own recent history without paying
the cost of sampling those candidates again.

This document defines:
- What data must be stored between frames (history buffers)
- When previous-frame reservoirs are valid for reuse (temporal gate)
- How neighbours are selected and merged (spatial pass)
- Where bias enters and how it is corrected
- What the CPU/GPU boundary looks like now vs at CUDA time
- A concrete validation plan for pkg24

---

## 2. Algorithm Summary (Bitterli 2020)

Each frame, for each pixel p:

```
1. Initial sampling  (pkg22):  build R_p from M initial candidates
2. Temporal reuse    (pkg24):  R_p ← merge(R_p, R_prev[reproject(p)])
3. Spatial  reuse    (pkg24):  for each neighbour q: R_p ← merge(R_p, R_q)
4. Shade: contribution = f(p, R_p.y) * L_e(R_p.y) * R_p.W
```

The merge rule is the same reservoir merge from pkg20 (Algorithm 2):
```
R_out.update(R_other.y, R_other.W * p_hat_at_current(R_other.y) * R_other.M)
R_out.M += R_other.M
```

`p_hat_at_current` is the **target function re-evaluated at the current pixel**,
not at the neighbour. This is the key correctness requirement: merging uses the
integrand at the destination pixel, not the source.

---

## 3. Temporal Reuse

### 3.1 History Buffer Layout

Two `ReservoirBuffer` instances per integrator (see `frame_state.h`):

| Field | Type | Notes |
|---|---|---|
| `reservoirs[w*h]` | `Reservoir<ReSTIRCandidate>` | One per pixel, flat row-major |
| `history[w*h]` | `PixelHistory` | normal + depth + valid flag |

At the start of each frame, `FrameState::advanceFrame()` swaps current ↔
previous and clears current. This is a zero-copy swap (`std::swap` on vectors).

### 3.2 Reprojection

For a static camera, the reprojected position of pixel p is simply p itself.
For a moving camera, full reprojection requires:
```
screen_prev = project(world_pos(p), camera_prev)
```

MVP: assume static or slow-moving camera; use identity reprojection (same pixel
coordinates). When motion vectors are added, they are stored as a `Vec2` per
pixel in the history buffer. This is a pkg24+ extension.

### 3.3 Temporal Invalidation Rules

A previous-frame reservoir at (px, py) must **not** be reused when any of:

| Condition | Threshold | Rationale |
|---|---|---|
| Out of screen bounds | — | No history exists |
| `PixelHistory::valid == false` | — | Sky hit or no geometry |
| `dot(n_curr, n_prev) < 0.9` | ~26° | Different surface orientation |
| `|d_curr - d_prev| / max(d_curr, d_prev) > 0.1` | 10% | Different surface depth |

These are implemented in `isTemporallyValid()` in `frame_state.h`. The thresholds
are conservative starting points; pkg24 validation may tighten them.

### 3.4 Merge Algorithm and Bias

The temporal merge is:
```cpp
float p_hat = candidate.targetLuminance(lambdas_at_current_pixel);
current.merge(previous.at(px, py), p_hat, gen);
```

**Bias source**: the previous reservoir's selected candidate `y` may now be
occluded at the current pixel's shading point. Merging without checking
visibility introduces a **positive bias** (too-bright pixels where a light
was once visible but is now blocked).

**Unbiased correction (deferred to pkg24)**: trace a shadow ray to `y` before
merging. If occluded, skip the merge entirely. Alternatively, use a bias-
corrected MIS weight that accounts for the probability that the same candidate
would be selected in an unbiased version of the algorithm.

**Decision**: ship temporal reuse *with* bias in the first pass (pkg24 initial
implementation), measure the bias magnitude against the path tracer, then add
the shadow-ray correction in a second pass. The design here explicitly supports
this staged approach.

---

## 4. Spatial Reuse

### 4.1 Neighbourhood Selection

For each pixel p, select N random neighbours q from a (2R+1)×(2R+1) window
(default R=15, N=5 per Bitterli 2020 Fig. 7). Implemented in
`selectSpatialNeighbors()` in `frame_state.h`.

The paper also evaluates fixed-offset patterns; random sampling is used here
because it averages out structured aliasing over multiple frames.

### 4.2 Target Weight Re-evaluation

When merging reservoir from neighbour q into current pixel p:
```cpp
// p_hat is evaluated at p's geometry, NOT q's:
float p_hat = q_reservoir.y.targetLuminance(lambdas_at_p);
current.merge(q_reservoir, p_hat, gen);
```

If `p_hat == 0` (candidate not visible/illuminating from p's geometry), the
merge weight is zero and the candidate is never selected. This is correct
behaviour — no explicit rejection needed.

### 4.3 Bias Sources

**Geometric bias**: neighbours with significantly different geometry will
contribute candidates with wrong directional distributions. Mitigated by a
geometry check analogous to temporal validation (normal + depth threshold)
before merging a neighbour.

**Visibility bias**: even a valid neighbour may have a different visibility
status for the same candidate. Full unbiased spatial reuse requires a visibility
test (shadow ray) for each candidate before merging. This is expensive: N
shadow rays per pixel per spatial pass. The staged plan:

1. **pkg24 initial**: merge without shadow-ray correction; measure bias.  
2. **pkg24 correction**: add pairwise MIS weights (Z-test per Alg. 4 in
   Bitterli 2020) or a single visibility test per merge.

### 4.4 Multiple Spatial Passes

The paper runs 1–2 spatial passes per frame. Each pass replaces the current
buffer with the merged result. With a single buffer, this requires a copy;
with double-buffering it is a swap. Design allows this: `ReservoirBuffer` is
cheap to swap.

---

## 5. CPU/GPU Boundary

### Now (CPU-only)

- `FrameState::resize`, `advanceFrame`: called once per frame, low overhead.
- Initial-sampling loop: single-threaded per tile (OpenMP already parallelises
  across tiles).
- Temporal/spatial passes: straightforward per-pixel loops, naturally parallel.
- Shadow-ray correction: BVH traversal, same as existing NEE.

### Future (CUDA)

Three natural CUDA kernels:
1. **Initial-sampling kernel**: one thread per pixel, fills `current.reservoirs`.
2. **Temporal-reuse kernel**: one thread per pixel, reads `previous.reservoirs`,
   merges into `current.reservoirs`.
3. **Spatial-reuse kernel**: one thread per pixel, reads neighbour reservoirs,
   merges into `current.reservoirs`.

**Data layout requirement**: the flat `y * width + x` indexing in
`ReservoirBuffer` maps directly to a CUDA thread index. When porting, convert
`std::vector` to device-allocated arrays; the indexing arithmetic is unchanged.

**AoS → SoA**: for coalesced CUDA access, each field of `Reservoir<ReSTIRCandidate>
` should become its own array. This refactor is deferred: it would break the
current CPU code and gains nothing on CPU. Mark the struct layout as stable until
the CUDA port begins.

---

## 6. Reprojection Extension (Future)

Full temporal reuse needs per-pixel motion vectors to handle camera movement.
The `PixelHistory` struct is intentionally minimal now. When motion vectors are
added:
- Add `Vec2 motionVector` to `PixelHistory`.
- Compute in the initial-sampling pass from the ray's camera frame and the
  previous frame's camera matrix.
- `isTemporallyValid` already accepts arbitrary (px, py); the caller is
  responsible for computing the reprojected coordinates.

---

## 7. pkg24 Validation Plan

pkg24 must validate that the reuse passes improve quality without introducing
large bias. Concrete checks:

| Test | Method | Pass criterion |
|---|---|---|
| Temporal reduces variance | Run 1spp ReSTIR with and without temporal; compare pixel stddev over 100 frames | Temporal version has lower stddev |
| Spatial reduces variance | Run multi-spp ReSTIR with/without spatial at same total SPP | Spatial version has lower MSE vs reference |
| Temporal bias magnitude | Converge both with/without temporal (256 spp); compare mean pixel value | Mean difference < 5% |
| Spatial bias magnitude | Same as above for spatial | Mean difference < 5% |
| No NaN/Inf after reuse | Any scene with multiple lights, temporal + spatial enabled | No NaN/Inf pixels |
| Determinism | Seeded render with reuse, two runs | Bit-identical output |

The bias tests use the converged `path_tracer` output as the reference ground
truth. The 5% threshold is generous for the initial pass; it should be tightened
once bias-correction shadow rays are added.

---

## 8. Open Questions

1. **Shadow-ray correction timing**: add in pkg24 immediately, or ship biased
   first and measure? Current plan: ship biased first, measure, then add.
2. **Number of spatial passes**: 1 or 2? Start with 1; add a second if the
   improvement is measurable in the validation scenes.
3. **Spatial radius R**: 15 pixels (paper default) or smaller for faster CPU
   validation? Use R=5 for CPU tests (smaller neighbourhood, faster), R=15 as
   the target for GPU.
4. **M-cap**: Bitterli 2020 §5.2 recommends capping M at 20× the initial sample
   count to prevent history build-up from causing over-weighting. Add `M_cap`
   parameter to `FrameState` in pkg24.
