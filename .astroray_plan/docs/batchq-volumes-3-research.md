# Batch Q (volumes part 3) — research notes (cite-algorithm)

2026-09-20. Covers #828 (GPU blackbody + grid cache + RNG keying), pkg271
`volume_bounces`, #833. Companion to `pkg270-spectral-tracking-volume-emission-research.md`.

## 1. GPU blackbody emission (#828 item 1)

### What the CPU does (pkg270, the oracle)

`normalizedPlanck(λ,T) = B(λ,T)·1e9 / ∫ B(λ',T)·1e9·ȳ(λ') dλ'` (Planck × the pkg122
photopic normalisation over the engine CMF ȳ, 360–830 nm, 1 nm), times Cycles'
`σ_SB·1e-6/π·mix(1,T⁴,I)` and the JH-upsampled tint.

### CPU defect found (fixed here)

`blackbodyLuminanceNorm()` returns the normaliser as a **float**, and
`normalizedPlanck` multiplies `float(B)` by it. Measured on main's `.pyd`
(`astroray.volume_blackbody_emission`): T = 25, 30, 50, 80, 100 K → **NaN** on
every λ (∫ underflows → norm = inf; `float(B)` = 0 → 0·inf). T ≤ 20 K → 0,
T ≥ 150 K finite. Temperature grids multiply the socket (Cycles), so the cold
rim of a fire (grid value 0.02–0.1 × 1500 K) lands in the NaN band.
Fix: evaluate the ratio in double from a double memo of the integral. The memo
(1 K bins, thread_local) is now evaluated AT the rounded kelvin; the old one kept
whichever T a thread saw first in the bin (thread-order dependent). Integer
temperatures are unchanged to ≤ 1 float ulp.

### GPU design

- Log-domain Planck, so no T underflows in float:
  `ln B(λ,T)·1e9 = ln(2hc²) − 5 ln λ_m − ln(expm1(x)) + ln 1e9`, `x = hc/(λ_m k T)`;
  `ln(expm1 x) ≈ x` for x > 20; `x > 700 → 0` (mirrors `planck()`).
- LUT: `ln ∫ B·1e9·ȳ dλ` on a uniform ln-T grid, 2048 entries, T ∈ [30 K, 1e6 K],
  linear interpolation, linear extrapolation above 1e6 K, emission 0 below 30 K.
  Built on the host from the SAME double integral the CPU memoises
  (`src/volume/volume_emission.cpp`), uploaded once to a `__device__` array owned
  by `gpu_spectral_tables.cu` (lazy: only when a medium has blackbody).
  Interpolation error `h²/8·|f''|`, `f'' ≈ −hc/(λ̄kT)`: 0.2 % at 30 K,
  < 1e-4 at fire temperatures (h = ln(1e6/30)/2047 = 0.0051).
  Below 30 K the CPU luminance is ≤ (30/T_fire)⁴ of the fire (< 2e-7 at 1500 K).
- Temperature grid: dense float array (same layout as the CPU `DenseGrid`,
  nearest voxel), uploaded beside the density NanoVDB buffer. Dense matches the
  CPU lookup exactly; a second NanoVDB grid would need a second host build path.
- The blackbody term lives in `gpu_gridVolumeTrack` (called only from
  `intersectPathSlotT<…, HasGridVolume=true>`), gated like the CPU `emissionAt`.
- `emissionFloor` (8/diag) stays on upload: with blackbody on the GPU, a
  density-free blackbody medium needs the tentative collisions (#828 review note).

## 2. Device grid cache (#828 item 2)

Tie the NanoVDB + temperature uploads to the #801 `reuse` decision
(`reuseDeviceScene && sceneCached && !sceneInvalidated && owner match`): on reuse
the `WfContext` grid buffers already hold the grids and no memcpy runs. Every
host mutation (`clear_grid_media`, `set_volume_grid`, `add_homogeneous_medium`)
calls `cuda_wavefront_invalidate_scene()` through the existing
`invalidateWavefrontScene()` hook. Media side-table fields are rebuilt every
frame (host struct, cheap).

## 3. Counter-based RNG keying (#828 review note)

`gpu_freeflightUniform` keys PCG32 on a 32-bit `dimSalt`. pkg269 used
`base + bounce·4096 + draw` (tracker) and `base + bounce·4096 + k·1024 + draw`
(shadow), so > 4096 / > 1024 draws alias into the next bounce/medium.
New layout (disjoint bit fields, no hashing):
tracker `0xE | bounce(8) | draw(20)`, shadow `0xD | bounce(8) | medium(3) | draw(17)`.
Draws wrap inside their own field (`& mask`), so an overflow repeats the flight's
own stream (a correlation, never a cross-bounce/medium alias). Limits:
1,048,576 tentative collisions per flight, 131,072 per shadow segment per medium,
bounce taken mod 256, medium index < 8 (the side-table cap).

## 4. `volume_bounces` (pkg271)

Source: Cycles (Apache-2.0), `blender/cycles` main, read 2026-09-20:
- `src/scene/integrator.cpp` `device_update`:
  `kintegrator->max_volume_bounce = max_volume_bounce + 1;`
  ("Plus one so that a bounce of 0 indicates no global illumination, only direct illumination").
- `src/kernel/integrator/path_state.h` `path_state_next`, `LABEL_VOLUME_SCATTER`:
  `volume_bounce += 1; if (volume_bounce >= max_volume_bounce) flag |= PATH_RAY_TERMINATE_AFTER_TRANSPARENT;`
- `src/kernel/types.h`: `PATH_RAY_TERMINATE_AFTER_TRANSPARENT` = "Ray is to be terminated,
  but continue with transparent bounces and emission as long as we encounter them.
  This is required to make the MIS between direct and indirect light rays match".
- `src/kernel/integrator/shade_volume.h`: `attenuation_only = (flag & PATH_RAY_TERMINATE) || is_zero(sigma_s)`;
  distance sampling for scatter is skipped when `PATH_RAY_TERMINATE` is set.

Semantics adopted (both backends): the k-th volume scatter (grid, homogeneous
bounded, or world fog) takes its medium NEE as usual; if `k > volume_bounces`
its continuation ray is **terminate-after**: media along it only attenuate and
emit (no scatter), a surface hit adds its emission (MIS as usual) then ends, a
lamp hit / background miss adds as usual. Default `-1` (engine API) = unlimited
= byte-identical.

Why not the pkg201 surface-limit convention (drop the continuation): with
`volume_bounces = 0` (Blender's default) smoke lit only by its own fire would
render black — Cycles gets that light through the terminate-after continuation
collecting volume emission, which no NEE samples.

Divergence kept: Cycles also continues through transparent surfaces after the
limit; the engine's alpha pass-through is not special-cased (ends at the hit).

## 5. #833 (mesh volume as world AABB)

Minimum shipped: the addon reports it (`[astroray volume] mesh '<name>' volume
rendered as its bounding box`) and records an APPROXIMATED degradation row.
Voxelisation / an engine volume stack are follow-ups.
