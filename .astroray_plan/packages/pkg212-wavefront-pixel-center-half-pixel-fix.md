# pkg212 — Wavefront ray-gen half-pixel center fix (CPU+GPU wavefront → Cycles raster convention)

**Pillar:** Integration Milestone (Blender/DCC integration — reconstruction-filter / raster parity)
**Track:** A
**Status:** open (filed 2026-08-20).
**Estimated effort:** XS–S.
**Depends on:** nothing (independent of, but discovered by, **pkg203** — the pkg203 RTX visual-centering gate exposed this). Cross-links: **pkg203** (Cycles σ mapping — orthogonal, merged), **pkg200** (honour matrix), **pkg119-B** (numeric Cycles parity).

## Goal

Fix a **pre-existing half-pixel pixel-centering convention gap** between the megakernel ray-gen and the wavefront ray-gen paths, discovered during pkg203 hardware verification (2026-08-20): the GPU wavefront silhouette is shifted a rigid ~0.4–0.6px right of the CPU megakernel, identical across all pixel filters (box/gaussian/blackman-harris), independent of pkg203's σ edit. Root-caused by gate-failure-reviewer (2026-08-20, see pkg203 §"Hardware verification").

- **Megakernel** (`include/raytracer.h`): `filterSample` returns a value centered at 0.5 (box `dist(gen)`∈[0,1), Gaussian `0.5+off`, BH `x`∈[0,1)); caller `raytracer.h:~3478` does `(x + filterSample())/(width-1)` → sample centered at pixel **x+0.5**. **This is CORRECT** — matches Cycles' raster convention (pixel center at integer+0.5). Do NOT change it.
- **GPU wavefront** (`src/gpu/wavefront/stage_init.cu`): `filterSample` returns an offset centered at 0 (box `Uniform()-0.5`∈[-0.5,0.5]); caller `stage_init.cu:169-170` does `(px + filterSample())/(width-1)` → sample centered at pixel **px+0.0**. **WRONG.**
- **CPU wavefront twin** (`src/cpu/wavefront/path_kernel.cpp`): `filterSample` also returns `Uniform()-0.5` (centered 0); caller `path_kernel.cpp:84-85` `(x + filterSample())/(width-1)` → centered at **px+0.0**. **WRONG** (consistent with GPU wavefront, which preserves the CPU↔GPU byte-identity invariant).

## Specification

Add the `+0.5` **pixel-center at the call sites** (NOT inside `filterSample` — its centered-at-0 offset in [-0.5,0.5] is the correct "filter offset" semantics; the pixel-center belongs at the caller):

1. `src/gpu/wavefront/stage_init.cu` lines 169–170:
   - `float u = (px + 0.5f + filterSample(rng)) / float(width - 1);`
   - `float v = 1.0f - (py + 0.5f + filterSample(rng)) / float(height - 1);`
2. `src/cpu/wavefront/path_kernel.cpp` lines 84–85: identical `+ 0.5f` on u and v.

**Both wavefront callers MUST change together in the same commit** to preserve the CPU-wavefront↔GPU-wavefront byte-identity invariant (`path_kernel.cpp:34-49` design decision #9). Do NOT touch `raytracer.h` (megakernel already matches Cycles).

## Non-goals

- The shared `/(width-1)` divisor (vs Cycles' `/width`) is a separate, second-order convention affecting BOTH backends equally; it does not cause the CPU↔GPU differential. Out of scope unless a later Cycles absolute-alignment gate demands it.

## Acceptance gate (HW/render-gated)

- The pkg203 Gate-3 visual-centering harness: CPU-vs-GPU same-scene/same-seed silhouette edge shift ≤ 0.2px (was ~0.5px) across box/gaussian/blackman-harris.
- CPU-wavefront ↔ GPU-wavefront PostInit byte-identity check (confirm the pair stayed locked after the edit).
- pkg200 honour matrix stays PASS (no regression on `pixel_filter_type` / `filter_width`).

## Routing

Open-model implement tier (deepseek-v4-pro) — the code change is tiny and precisely specified. Claude owns the byte-identity invariant verification and the RTX visual re-gate. Adversarial different-model SIGN-OFF required on the fix diff before re-gate push (per gate-failure-reviewer deliverable).

## Cite

No new algorithm — this is a raster-convention alignment (pixel center at integer+0.5, standard raster/Cycles convention). Reference: pkg203 §"Hardware verification 2026-08-20" gate-failure-reviewer root-cause; Cycles `kernel/camera` raster-to-camera (pixel + 0.5 raster offset).
