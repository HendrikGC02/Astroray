# pkg201 Stage 2 — results & findings delta (vs pkg200 honour matrix)

**Scope:** GPU host/splat/pre-pass settings-honour. Closes pkg200 Findings **D**
(pixel reconstruction filter) and the **F-alpha** row (`film_transparent`); the
`film_transparent_glass` (F-glass) and `caustics_*` (E) rows are **reclassified**,
not flipped — see the reclassification notes below and in the pkg201 spec.

Gate: verbatim re-run of `scripts/verify_pkg200_honour_matrix_run.py` on Blender
5.1 AND 5.2, RTX 5070 Ti, LINEAR EXRs (`apply_gamma=False`), per-channel
mean-ratio. `.pyd` mtime stated next to the render legs (see PR body).

## Row verdict delta

| Row | pkg200 verdict | pkg201 Stage 2 | How |
|-----|----------------|----------------|-----|
| `film_transparent` | HONEST-FAIL (alpha 1.000 = 1.000) | **PASS** (pending HW) | GPU bounce-0 background-miss coverage → `alphaBuffer`; alpha = 1 − miss/samples |
| `pixel_filter_type` | HONEST-FAIL (grad 0.21583 = 0.21583) | **PASS** (pending HW) | filter importance sampling (BOX vs GAUSSIAN) at primary-ray gen |
| `filter_width` | HONEST-FAIL (grad 0.21583 = 0.21583) | **PASS** (pending HW) | GAUSSIAN offset drawn over full `filter_width`; wide blurs edges |
| `film_transparent_glass` | HONEST-FAIL (|dLum| 1.4e-7) | **RECLASSIFIED** (stays HONEST-FAIL) | needs world-through-glass beauty compositing — a new feature, not an alpha copy-back; filed as follow-up |
| `caustics_reflective` | HONEST-FAIL (|dLum| 5e-11) | **RECLASSIFIED → Stage 3** (stays HONEST-FAIL) | per-ray specular-caustic path classification = REG-254 shade-kernel state |
| `caustics_refractive` | HONEST-FAIL (|dLum| 5e-11) | **RECLASSIFIED → Stage 3** (stays HONEST-FAIL) | as above |

(HW numbers filled in the PR body after the batched 5.1/5.2 driver rerun.)

## Finding D — pixel reconstruction filter (SHIPPED)

Implemented as **filter importance sampling** in `src/gpu/wavefront/stage_init.cu::filterSample`:
the primary-ray sub-pixel offset is drawn from the reconstruction filter's own
distribution over `[-width/2, +width/2]` and accumulated with unit weight — the
canonical Cycles (`filter_table` inverted CDF, Apache-2.0) / PBRT-v4 §8.8
(`FilterSampler`, BSD) / Ernst-Stamminger-Greiner (IRT 2006) approach; NOT a
cross-pixel splat. Research note: `.astroray_plan/docs/pkg201-pixel-filter-research.md`.

- **BOX (type 0):** uniform `[-0.5, 0.5]`, width-ignored — byte-identical to the
  pre-pkg201 GPU default AND to the CPU box, so the fleet baseline is untouched.
- **GAUSSIAN (type 1):** Box-Muller normal, σ = width/6, clamped to the support;
  `width > 1` crosses pixel boundaries → edge blur (lower gradient).
- **BLACKMAN-HARRIS (type 2):** rejection-sample the 4-term BH window over the
  support (same coefficients as the CPU/Cycles filter), width-scaled.

Published per frame into a `__constant__` (`setWavefrontPixelFilter`), mirroring the
pkg197/pkg199 binding pattern — no kernel signature grows, register-neutral for the
shade/intersect kernels (it lives in the primary-ray stage).

**Matching CPU gap (recorded, not fixed here):** the CPU `Renderer::filterSample`
(raytracer.h:2424) clamps every filter type to within one pixel, so it honours
filter *type* weakly and does **not** honour `filter_width` as a reconstruction
radius. Left as-is: the pkg200 honour gate is the GPU F12 path, the CPU
`filterSample` is guarded by many CPU parity gates, and there is no CPU honour test
to gate a CPU change. A separate small follow-up.

## Finding F — transparent film (F-alpha SHIPPED; F-glass RECLASSIFIED)

**F-alpha (`film_transparent`) — SHIPPED, and it is the FIRST implementation of
transparent-film alpha in the engine.** The spec's "mirror the CPU path" premise
was false: `getUseTransparentFilm()`/`getTransparentGlass()` and the stored
`useTransparentFilm`/`transparentGlass` flags are read **nowhere** on the CPU —
`SampleResult.alpha` is a constant 1.0 across every integrator — so `film_transparent`
was equally inert on CPU and GPU. The GPU wavefront now:
1. counts bounce-0 background-miss samples per pixel (`c_wfMissCoverage` atomicAdd in
   `intersectPathSlot`'s miss branch, published per frame, gated on
   `useTransparentFilm` so it is null/byte-identical otherwise);
2. derives `alpha = clamp(1 - miss/samples, 0, 1)` in the driver and writes it to
   `Camera::alphaBuffer` (which the addon already reads via `get_alpha_buffer` and
   composites into the EXR combined pass). Opaque 1.0 when transparent film is off.

Register-neutral for shade (rides the intersect stage, the pkg197 guide-AOV precedent).
Glass under transparent film (with `transparentGlass` OFF, the default) renders opaque
(alpha 1) — which is the correct Cycles behaviour for that toggle state.

**F-glass (`film_transparent_glass`) — RECLASSIFIED to a follow-up feature.** Its
predicate `p_changes_pixels` tests the **beauty luminance**, not alpha. Honouring it
is Cycles "transparent glass" world-through-glass compositing (glass shows the
background, changing RGB) — a genuine new feature touching the miss/shade path, out
of scope for an alpha copy-back. Filed for the next-round architect.

## Finding E — native caustic toggles (RECLASSIFIED → Stage 3)

Cannot flip on a verbatim rerun as Stage-2 host-side work. Verified against code
2026-08-15: the pkg113 photon caustic pre-pass is **never enabled** in the honour
scene (nothing calls `set_use_photon_caustics`; no `is_caustic_caster` is flagged),
so `usePhotonCaustics` stays false and the pre-pass never runs — gating an already-off
pre-pass on the native toggles changes nothing. The real caustic light on the floor
is the **wavefront path tracer's own reflective/refractive paths**; honouring the
toggles Cycles-style means classifying and suppressing those specular-caustic paths
in the shade/continuation logic — a per-ray path-history flag in the REG-254 shade
kernel. That is register-hostile and belongs behind Stage 3's up-front cuobjdump
probe (reclassified into Stage 3 item 8). No gate weakening — the two rows keep their
HONEST-FAIL verdict with this evidence.
