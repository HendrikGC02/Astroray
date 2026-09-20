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
Fix (round 2, after the critic pass): the CPU uses the SAME formula and table as
the GPU (`include/astroray/volume/blackbody_lut.h`, below). A per-kelvin memo
(round 1: evaluated at `lround(T)` while Planck used the exact T) mis-normalises
non-integer grid temperatures; measured on the round-1 build, luminance / Cycles
intensity = 0.095 at 60.5 K, 1.035 at 500.4 K, 0.992 at 1234.5 K, 1.001 at
2718.3 K, and a 7 % step between 500.49 K and 500.51 K. Main's first-seen memo had
the same error plus thread-order dependence. `tests/test_issue828_blackbody_cpu.py`
pins all three (CPU-only).

### Shared CPU/GPU design (`blackbody_lut.h`)

- Log-domain Planck, so no T underflows in float:
  `ln B(λ,T)·1e9 = ln(2hc²) − 5 ln λ_m − ln(expm1(x)) + ln 1e9`, `x = hc/(λ_m k T)`;
  `ln(expm1 x) ≈ x` for x > 20; `x > 700 → 0` (mirrors `planck()`).
- LUT: `ln ∫ B·1e9·ȳ dλ` on a uniform ln-T grid, 2048 entries, T ∈ [30 K, 1e6 K],
  linear interpolation, linear extrapolation above 1e6 K, emission 0 below 30 K.
  Built once per process from the exact double integral
  (`blackbodyLogLuminanceLut()`, `src/volume/volume_emission.cpp`); the CPU reads
  it directly and the GPU uploads the same vector to a `__device__` array owned by
  `gpu_spectral_tables.cu` (lazy: only when a medium has blackbody). One
  `__host__ __device__` function evaluates it on both backends.
  Interpolation error, DERIVED as `h²/8·|f''|` with `f'' ≈ −hc/(λ̄kT)`
  (h = ln(1e6/30)/2047 = 0.0051): 0.2 % at 30 K, < 1e-4 at fire temperatures.
  MEASURED end-to-end by re-integrating the emitted SPD against the engine's own
  ȳ (`tests/test_issue828_blackbody_cpu.py`): luminance / Cycles intensity within
  0.05 % at 60.5–6543.2 K.
  Both backends return 0 below 30 K; the luminance lost there is ≤ (30/T_fire)⁴
  of the fire (< 2e-7 at 1500 K) when Blackbody Intensity = 1.
- Temperature grid: dense float array (same layout as the CPU `DenseGrid`,
  nearest voxel), uploaded beside the density NanoVDB buffer. Dense matches the
  CPU lookup exactly; a second NanoVDB grid would need a second host build path.
- The blackbody term lives in `gpu_gridVolumeTrack` (called only from
  `intersectPathSlotT<…, HasGridVolume=true>`), gated like the CPU `emissionAt`.
- Observer: the table is built at runtime from the CMF ȳ `astroray/spectrum.h`
  exposes — since #837 that is `cieCmf1931_2deg` (CIE 1931 2°), and the table
  follows it by construction (no baked numbers; the CPU test resolves the binding
  by prefix, so it survives a further rename). Cycles' blackbody colour is
  its own Rec.709 polynomial fit, which is the recorded divergence (pkg270 §3);
  the observer itself is NOT a divergence.
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

Source: upstream Cycles (Apache-2.0), https://github.com/blender/cycles `main`,
raw files fetched 2026-09-20 (NOT vendored in-repo; `external/cycles_light_tree`
holds only the light tree):
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

Per-path state: `GPUWavefrontState.per_type_bounce` byte 3 (bits 0-6 count,
bit 7 terminate-after). The count saturates at 127, so the published GPU cap is
clamped to 127; the pkg201 per-type counters now saturate at 255 so a
transmission-bounce increment can never carry into that byte.

Divergences kept (documented, not claimed as parity):
- Cycles' terminate-after continues through TRANSPARENT surfaces (alpha / the
  transparent BSDF, counted against `transparent_max_bounces`); the engine ends a
  past-limit path at the first non-emissive surface, alpha or not. The engine's
  `transparent_bounces` is itself unwired (pkg201 park note), and its alpha
  pass-through is a BSDF lobe sampled in the shade stage, which a past-limit path
  never reaches. Visible only where an alpha-cutout surface sits behind a volume
  at the bounce limit.
- Cycles' total `max_bounces` also sets terminate-after (the continuation still
  collects emission); the engine's total depth ends the path loop. Pre-existing,
  unchanged here. `volume_bounces` is passed unclamped by the addon (the old
  `min(volume_bounces, depth)` was output-neutral: the depth loop bounds scatters
  anyway) so the native value reaches the engine as authored.
- Only the nearest medium entered by a ray segment is tracked (pkg268/269); a
  second medium further along the same segment is skipped. Follow-up.

## 5. #833 (mesh volume as world AABB)

Minimum shipped: the addon reports it (`[astroray volume] mesh '<name>' volume
rendered as its bounding box`) and records an APPROXIMATED degradation row.
Voxelisation / an engine volume stack are follow-ups.
