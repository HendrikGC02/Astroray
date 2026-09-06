# pkg69 - Albedo Pass for Blender Compositor Denoise Node

**Pillar:** 5
**Track:** A
**Status:** done
**Estimated effort:** TBD

## Goal

Expose Astroray's first-hit albedo buffer as Blender's compositor Albedo
denoising guide pass when `use_pass_denoising_data` is enabled, matching the
Cycles compositor denoise workflow alongside the existing Normal guide buffer.

## Scope

- Register Albedo and Normal as 3-channel denoising data passes in the Blender
  addon.
- Write the renderer albedo buffer to the Albedo pass in `write_pixels`.
- Reuse the existing `Renderer.get_albedo_buffer()` binding.
- Add pure-Python Blender-addon tests for pass registration and pixel emission.

## Verification

- `python scripts\dev\run_tests.py -- tests/test_blender_compositor_denoise_passes.py tests/test_blender_view_layers.py -v --tb=short`
  - 6 passed in 0.18s
