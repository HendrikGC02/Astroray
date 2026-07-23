# pkg144 research notes — Cycles `film_clamp_light` (direct/indirect firefly clamp split)

## Source

- **Repo:** `blender/cycles` (upstream, mirrored into `blender/blender` as a submodule/subtree).
  Fetched via `https://raw.githubusercontent.com/blender/cycles/main/src/kernel/film/light_passes.h`
  and `https://raw.githubusercontent.com/blender/cycles/main/src/scene/integrator.cpp`
  (2026-07-23).
- **License:** Apache-2.0 (Blender/Cycles kernel sources). Already an established
  reference in this codebase (cited throughout `raytracer.h`, `path_trace_kernel.cu`,
  etc. for other Cycles-derived algorithms).

## The function (device-side clamp selection)

`src/kernel/film/light_passes.h`:

```c
ccl_device_forceinline void film_clamp_light(KernelGlobals kg,
                                             ccl_private Spectrum *L,
                                             const int bounce)
{
  *L = ensure_finite(*L);
#ifdef __CLAMP_SAMPLE__
  const float limit = (bounce > 0) ? kernel_data.integrator.sample_clamp_indirect :
                                     kernel_data.integrator.sample_clamp_direct;
  const float sum = reduce_add(fabs(*L));
  if (sum > limit) {
    *L *= limit / sum;
  }
#endif
}
```

Call sites (per-contribution, each passing the CURRENT path's bounce count):
`film_write_direct_light` (NEE/shadow-ray contribution), `film_write_background`
(environment miss), `film_write_volume_emission`, `film_write_surface_emission`.

## Host-side default handling (`src/scene/integrator.cpp`, `device_update`)

```c++
kintegrator->sample_clamp_direct = (sample_clamp_direct == 0.0f) ? FLT_MAX :
                                                                   sample_clamp_direct * 3.0f;
kintegrator->sample_clamp_indirect = (sample_clamp_indirect == 0.0f) ?
                                         FLT_MAX :
                                         sample_clamp_indirect * 3.0f;
```

`0` (the user-facing default for both) maps to `FLT_MAX`, i.e. **no clamp** —
Cycles ships firefly control fully opt-in, split direct/indirect, with direct
unclamped by default (documented UI guidance: "clamping direct light paths can
have a too extreme effect").

## What we ported vs. what we deliberately did NOT port

- **Ported:** the bounce-indexed limit SELECTION (`bounce > 0 ? indirect : direct`),
  applied per-contribution (at each site a value is added to the path's running
  radiance), and the `0 == disabled` semantics.
- **NOT ported literally:** Cycles' clamp METRIC is `sum(|R|+|G|+|B|)` (an RGB
  magnitude proxy) and the host-side `* 3.0f` scale-up that goes with it. Astroray's
  existing brightness metric (already established by the pre-pkg144
  `if (sLum > 20.0f)` cap this package removes, and by `clampLuminance()` elsewhere
  in `raytracer.h`) is **CIE XYZ photometric luminance (Y)** via
  `SampledSpectrum::toXYZ(lambdas).Y`. We kept that metric rather than switching to
  Cycles' RGB-sum convention, since (a) it's the metric already in use throughout
  this codebase, (b) switching metrics would require re-deriving the `*3.0f`
  calibration factor (which exists specifically to make an RGB-sum threshold behave
  like a luminance threshold for roughly-grey light), and (c) the bounce-indexed
  SELECTION logic (the actual "invented algorithm" concern under CLAUDE.md §6) is
  what we're porting, not the choice of scalar reduction. This is a metric
  substitution, not a re-derivation of Cycles' clamp-selection algorithm.

## Astroray's existing (dead) plumbing

`include/raytracer.h` already declared `clampDirect`/`clampIndirect` fields
(default 0), setters (`setClampDirect`/`setClampIndirect`), a `clear()` reset, and
Python bindings (`module/blender_module.cpp`: `set_clamp_direct`/`set_clamp_indirect`)
— all pre-pkg144, never read anywhere. pkg144 adds `getClampDirect()`/
`getClampIndirect()` and wires the fields into:

- `Renderer::pathTraceSpectral` / `Renderer::pathTraceSpectralCaustic` (CPU,
  `include/raytracer.h`) via a new private helper `clampContribSpectral()`.
- `tracePathGPU` (`src/gpu/path_trace_kernel.cu`, the production GPU megakernel
  for non-`path_tracer`/non-MW integrator names) via `gpu_clampContrib()`.
- `tracePathMW` (`src/gpu/multiwavelength_kernel.cu`, the production GPU megakernel
  actually dispatched for the DEFAULT `path_tracer` integrator name when
  `set_use_gpu(True)` — see `module/blender_module.cpp`'s
  `integratorName_ == "path_tracer" || ... ` branch, which routes to
  `renderMultiwavelength`) via `gpu_clampContribMW()`.

## Defaults (evidence-first, per spec)

- `clampDirect = 0.0f` (off) — non-negotiable, unchanged from the existing
  (dead) default.
- `clampIndirect = 0.0f` (off) — **measured**: the full firefly/caustic/furnace
  test suite (`test_disney_energy_conservation.py`, `test_dielectric_glass_furnace.py`,
  `test_disney_rough_glass_furnace.py`, `test_disney_reflection_not_black.py`,
  `test_caustic_validation.py`, `test_pkg140_distant_light_zero_angle.py`) passes
  in full with `clampIndirect = 0`. Per the spec's own instruction ("If the tests
  pass with clampIndirect = 0 too, prefer full Cycles parity"), we ship both
  clamps off — exact Cycles-default parity, no legacy "20" reintroduced.

## Deliberately out of scope (noted, not silently dropped)

- `src/gpu/wavefront/stage_advance.cu` (`stageRegenKernel`,
  `stageAccumulateXYZKernel`) and `src/gpu/wavefront/stage_restir.cu` carry their
  own copies of the old whole-path `lum > 20` clamp (applied at path-death /
  accumulate time, same pre-pkg144 bug shape). These are the pkg55 SoA wavefront
  **development/parity harness** (gated behind `ASTRORAY_WAVEFRONT_INTERSECT` /
  invoked only from the `tests/wavefront_diff` bit-identity suite), **not** the
  production GPU dispatch path (confirmed: `cuda_renderer.cu`'s `render()` /
  `renderMultiwavelength()` call `launchPathTraceKernel` / `launchMultiwavelengthKernel`
  directly, never the wavefront stage launchers). Restructuring them to a
  per-contribution split would require re-deriving where each contribution
  (NEE/emission/background) is added across several separate kernel-launch stages,
  and would touch the strict bit-identity gates in `tests/wavefront_diff`. Left
  as a follow-up (flagged in the PR body), consistent with "GPU parity if
  applicable... else note N/A" — the actual production twins (megakernels) are
  fixed; the dev-harness twins are not.
