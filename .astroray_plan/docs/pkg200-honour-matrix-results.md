# pkg200 — Native-settings F12 pixel-honour matrix: results & findings

**Run:** 2026-08-14, RTX 5070 Ti. Driver: `scripts/verify_pkg200_honour_matrix_run.py`
(+ in-Blender leg `verify_pkg200_honour_matrix.py`, contract layer `pkg200_honour_matrix.py`).
**Engine `.pyd`:** `build_blender_addon_cuda/astroray.cp313-win_amd64.pyd`, mtime 2026-08-14 08:58:42
(OpenMP-OFF, built via `dev_addon.ps1 -Smoke`; register + liveness smoke PASS on Blender 5.1 AND 5.2).
**Method:** each row renders two variants (A/B) through the TRUE F12 path
(`bpy.ops.render.render`, CUSTOM_RAYTRACER, GPU) to 32-bit **LINEAR** EXRs
(`view_transform=Standard`, `apply_gamma=False`); metrics via cv2
`IMREAD_UNCHANGED` per-channel mean/max/variance (never SSIM); nonzero pinned
seeds. Gate = printed `PKG200_LEG PASS` sentinel, not the Blender exit code.
**Enumeration:** the 25 rows are generated from `blender_addon/settings_map.py`
(`check_completeness()` hard-fails on any unassigned DIRECT-plumbed prop) — the
matrix cannot drift from the pkg176 contract.

Results were **byte-identical on Blender 5.1 and 5.2** (deterministic); one row
per setting shown below.

## Results (per-setting, 5.1 ≡ 5.2)

| Stage | Row | Scene | Kind | Verdict | Measured (LINEAR) |
|-------|-----|-------|------|---------|-------------------|
| 0 | resolution | closed_box | auto | **PASS** | shape A=(64,64) B=(96,96) |
| 1 | max_bounces | closed_box | auto | **PASS** | lum_mean 0.0344 → 0.4304 (12.5×) |
| 1 | diffuse_bounces | closed_box | auto | **HONEST-FAIL** | 0.4304 = 0.4304 (ratio 1.000) |
| 1 | glossy_bounces | closed_box_glossy | auto | **HONEST-FAIL** | 0.6952 = 0.6952 |
| 1 | transmission_bounces | glass_sphere | auto | **HONEST-FAIL** | 0.5056 = 0.5056 |
| 1 | transparent_max_bounces | transparent_tower | auto | **HONEST-FAIL** | 0.3763 = 0.3763 |
| 1 | volume_bounces | volume_box | auto | **HONEST-FAIL** | 0.0500 = 0.0500 |
| 1 | world_max_bounces | hdri_box | auto | **HONEST-FAIL** | 1.0971 = 1.0971 |
| 2 | sample_clamp_direct | firefly | auto | **PASS** | lum_max 28.37 → 0.508; hi_pct 26.82 → 0.507 |
| 2 | sample_clamp_indirect | firefly_indirect | auto | **NEEDS-VISUAL** | 1670 = 1670 (inconclusive — see finding I) |
| 2 | blur_glossy | firefly | auto | **HONEST-FAIL** | lum_max 28.37 = 28.37 |
| 3 | film_exposure | closed_box | auto | **PASS** | per-ch mean-ratio 2.000, 2.000, 2.000 |
| 3 | film_transparent | open_object | auto | **HONEST-FAIL** | alpha_mean 1.000 = 1.000 |
| 3 | film_transparent_glass | open_glass | visual | **HONEST-FAIL** | |dLum| mean 1.4e-7 (no change) |
| 3 | samples | open_object | auto | **PASS** | MC-noise 16spp=0.00781 → 64spp=0.00398 (0.510 ≈ 1/√4); mean 1.000 |
| 3 | seed_distinct | closed_box | auto | **PASS** | mean 0.998, |dLum| mean 0.2216 |
| 3 | seed_repeat | closed_box | auto | **PASS** | |dLum| max 7e-7 (reproducible ≤1e-5) |
| 3 | preview_samples | closed_box | limitation | **LIMITATION** | viewport-only (not an F12 control) |
| 4 | caustics_reflective | caustic | visual | **HONEST-FAIL** | |dLum| mean 5e-11 (no change) |
| 4 | caustics_refractive | caustic | visual | **HONEST-FAIL** | |dLum| mean 5e-11 (no change) |
| 4 | pixel_filter_type | closed_box | auto | **HONEST-FAIL** | grad_mean 0.21583 = 0.21583 |
| 4 | filter_width | closed_box | auto | **HONEST-FAIL** | grad_mean 0.21583 = 0.21583 |
| 4 | use_denoising | denoiser_scene | visual | **PASS** | var 0.788×; visual: noisy → clean box (not garbage) |
| 4 | denoiser | denoiser_scene | visual | **NEEDS-VISUAL** | both backends render valid frames; OIDN ≡ OPTIX (|dLum|=0) |
| 4 | use_preview_denoising | closed_box | limitation | **LIMITATION** | viewport-only |

**Tally (25 unique):** PASS 8 · HONEST-FAIL 13 · NEEDS-VISUAL 2 · LIMITATION 2.

**Visual inspections (multimodal):** `use_denoising` B — clean Cornell box, red/green
walls, ceiling light, not garbage (A is heavy MC noise) → honour confirmed.
`denoiser` A(OIDN)/B(OPTIX) — both clean denoised boxes, visually identical.
`caustics_refractive` B — no caustic visible when toggled on → consistent with
the toggle being inert on GPU.

## Findings (follow-ups — NOT fixed in pkg200 per the verify-only scope)

The dominant result: **the GPU wavefront F12 path honours only a subset of the
plumbed steering-wheel controls** — `maxDepth`, seed, `filmExposure`, the pkg157
clamps, and the pkg197 denoise pass. It silently drops the rest. Since F12 uses
the GPU on this hardware, these are genuine F12 honest-fails; several are honoured
on the CPU path, so they are GPU-plumbing gaps, not total lies.

**Finding A (major) — per-type bounce limits dropped on GPU.**
`diffuse_/glossy_/transmission_/volume_/transparent_max_bounces` all produce
byte-identical A/B on GPU. Root cause: `module/blender_module.cpp` — the CPU
path passes the five per-type bounce args to `renderer.render(...)` (≈L1906) but
the GPU call `astroray::wavefront::cuda_wavefront_render(...)` (≈L1863–1868)
receives only `maxDepth`. *Proposed spec stub `pkg201`:* thread the per-type
bounce limits into `cuda_wavefront_render` and the wavefront advance stage.
(`volume_bounces` is additionally KNOWN-PARTIAL — volume transport itself is
partial — but the primary block is the dropped arg.)

**Finding B — `world_max_bounces` reads a non-existent Blender attribute.**
`blender_addon/__init__.py` (≈L4773) reads `world.light_settings.max_bounces`;
`WorldLighting` has no such member (it is AO settings), so `getattr(..., 1024)`
always wins and the control is inert. The real Cycles world prop is
`world.cycles.max_bounces`. *Proposed:* one-line addon fix to the native read
path (small follow-up).

**Finding C — `blur_glossy` (Filter Glossy) not honoured on GPU.**
`renderer.filterGlossy` is stored (raytracer.h) but never referenced in `src/gpu/`.
*Proposed:* apply the glossy-roughness widening in the wavefront shade stage.

**Finding D — pixel reconstruction filter not honoured on GPU.**
`pixel_filter_type` + `filter_width` produce byte-identical edge gradients;
`pixelFilterType`/`pixelFilterWidth` are stored but never read in `src/gpu/`
(the wavefront does no reconstruction filtering). *Proposed:* apply the pixel
filter in the wavefront splat/accumulate.

**Finding E — native caustic toggles inert on GPU.**
`caustics_reflective`/`caustics_refractive` change nothing. GPU photon caustics
gate on a SEPARATE `usePhotonCaustics` opt-in (pkg113); the native toggles set
`renderer.useReflective/RefractiveCaustics`, which `src/gpu/` never reads.
*Proposed:* map the native toggles onto the GPU photon-caustic gate.

**Finding F — transparent film not honoured on GPU.**
`film_transparent` / `film_transparent_glass` leave the background alpha at 1.0
(no `transparentFilm` handling in `src/gpu/`; the GPU alpha buffer stays opaque).
*Proposed:* honour transparent-film background alpha on the wavefront path.

**Finding G (minor) — denoiser backend selector produces identical output.**
OIDN vs OPTIX are byte-identical (|dLum|=0). "Both yield a denoised frame" holds
(the honour claim), but the enum may not switch backends. *Proposed:* verify
`resolve_denoiser_pass` maps OPTIX/OIDN to distinct backends.

**Finding I (inconclusive) — `sample_clamp_indirect`.**
Could not construct a scene whose fireflies the engine NEE-classifies as INDIRECT
(clampDirect clips them as direct). `clampIndirect` is the sibling param of
`clampDirect` in the same pkg157 kernel call (`stage_advance.cu`), and
`sample_clamp_direct` empirically PASSES (28.37 → 0.508) — so this is almost
certainly honoured but was not isolated by render. Recorded NEEDS-VISUAL, not a
failure.

## Known gaps (pre-recorded, not tested as honoured)

- **`use_light_tree`** — APPROXIMATED and NOT read at F12: `convert_scene` reads
  the custom `light_sampler` tri-state, never the native `use_light_tree` bool.
  Toggling the native prop changes nothing. Follow-up: reconcile the tri-state vs
  bool semantic mismatch (`settings_map` `light_sampling` row).

## Degradation-honesty leg

`report_unsupported_native_controls` emits the consolidated WARNING naming the
DROPPED controls the user has set off-default (camera ORTHO/PANO, clip, polygonal/
anamorphic bokeh, per-light `specular_factor`) and stays quiet on defaults —
verified in `tests/test_pkg200_honour_matrix.py` (bpy-free, fake datablocks).
Closes pkg176's "zero silently-ignored controls on adopted panels".
