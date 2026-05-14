# pkg85-D — HDRI world-only render GPU/CPU SSIM parity

**Pillar:** 5
**Track:** A (RTX verifier)
**Status:** open (filed 2026-05-14 — surfaced by pkg85-C after the "Scene not uploaded" early-exit was removed)
**Estimated effort:** ½ day (~4 h on RTX)
**Depends on:** pkg85-C (the precondition fix that lets this test reach SSIM)

---

## Goal

**Before:** `tests/test_world_hdri_parity.py::test_gpu_cpu_ssim_hdri` runs to completion (post-pkg85-C) but the GPU image is wildly different from the CPU image — SSIM ≈ 0.35 against a gate of 0.97. Scene is `load_environment_map(...) + setup_camera(...)` with no geometry; CPU path-traces against the env map, GPU does the same but produces a different image.

**After:** GPU vs CPU SSIM ≥ 0.97 on the same 64×64×64-spp setup.

---

## Context

pkg85-B's `RuntimeError("Scene not uploaded — call uploadScene() first")` masked this for months. pkg85-C unblocked the render path (geometry-less scenes are allowed if an env map is uploaded). The result is no longer a crash or an exception — it's a wrong picture.

Probably one of:
- `gpu_envmap_lookup` vs CPU `EnvironmentMap::sample` disagreeing on rotation matrix / color tint / strength multiplier.
- `pathTraceKernel`'s miss-branch tonemapping differs (CPU integrator may multiply by a different factor or skip the `* 0.2f` fallback that the GPU applies when `envMap.loaded` is false).
- The CPU first-bounce env contribution uses NEE; the GPU first-bounce env contribution uses BSDF MIS only (with no geometry, both should collapse to "miss → env lookup" — but the path may differ).

## Reference

- `src/gpu/path_trace_kernel.cu` — miss branch (lines ~265–285).
- `include/astroray/gpu_materials.h` — `gpu_envmap_lookup` and friends.
- `include/raytracer.h` — `EnvironmentMap::sample` and CPU `pathTrace` miss handling.
- `tests/test_world_hdri_parity.py::test_gpu_cpu_ssim_hdri` — the gate.

## Specification

### Phase 1 — Localise the divergence

Render the CPU and GPU images, save both to PNG, eyeball them. Then for the same camera ray (e.g., centre pixel), trace by hand on both backends and find where they diverge.

### Phase 2 — Fix the env-lookup math

Whatever Phase 1 surfaces. Pkg63 already baked the rotation matrix; this is likely a smaller miss (strength, tint, channel order, or the 0.2f sky-gradient fallback firing when it shouldn't).

### Acceptance

- `test_gpu_cpu_ssim_hdri` passes with margin (SSIM ≥ 0.97).
- No regression on other env-map tests (`test_pkg63_*`, `test_world_hdri_parity::test_other_*`).
