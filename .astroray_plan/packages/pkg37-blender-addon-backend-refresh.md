# pkg37 — Blender Addon Backend Refresh

**Pillar:** 5  
**Track:** A / E  
**Status:** open  
**Estimated effort:** 1-2 sessions (~6 h)  
**Depends on:** pkg34 recommended; pkg35/pkg36 improve coverage but are not hard blockers

---

## Goal

**Before:** The Blender addon can launch Astroray renders, but it still
behaves like a mostly CPU-era frontend. GPU rendering is manually opted
in for final renders, viewport rendering does not apply the GPU setting,
the packaged addon build forces CUDA off, and users cannot easily tell
which module/backend/features Blender is actually using.

**After:** The addon has a capability-aware backend policy with
`Auto / GPU / CPU` device selection, defaults to GPU when available and
safe, applies the same policy to final and viewport renders, packages
the intended CUDA/tiny-cuda-nn-capable module when requested, and shows
clear diagnostics for module path, build features, GPU device, active
integrator, neural-cache readiness, and fallback reasons.

---

## Context

Astroray's renderer has moved to spectral-first materials, CUDA support,
plugin integrators, neural-cache experiments, and backend capability
guardrails. The Blender addon has not kept pace: the UI exposes only a
boolean `Use GPU`, the build script uses a stale `build_tncc` directory
and passes `ASTRORAY_ENABLE_CUDA=OFF`, and viewport preview appears to
remain CPU-only. This package makes Blender a trustworthy production
entrypoint again before more Pillar 4 and material work lands.

---

## Reference

- Addon entrypoint: `blender_addon/__init__.py`
- Addon packaging: `scripts/build_blender_addon.py`
- Addon manifest: `blender_addon/blender_manifest.toml`
- Python bindings: `module/blender_module.cpp`
- Backend capability bridge: `pkg34-material-backend-capabilities.md`
- Spectral GPU material bridge: `pkg35-spectral-gpu-materials.md`
- Shared closure graph bridge: `pkg36-material-closure-graph.md`
- Production design: `.astroray_plan/docs/production.md`

---

## Prerequisites

- [ ] Build passes with the current CPU module.
- [ ] `astroray.Renderer` exposes `set_use_gpu`, `gpu_available`,
      `gpu_device_name`, `set_integrator_param`, `get_integrator_stats`,
      and `__features__`.
- [ ] If pkg34 is complete, use its material/backend capability metadata
      for safe Auto-device decisions. If pkg34 is not complete, Auto may
      use conservative built-in checks and report that capability metadata
      is unavailable.
- [ ] Confirm the Blender version actually targeted by the addon
      manifest (`blender_version_min`) matches the supported test host.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `tests/test_blender_backend_policy.py` | Pure-Python addon tests for Auto/GPU/CPU policy, viewport parity, diagnostics, and fallback messages using renderer stubs. |

### Files to modify

| File | What changes |
|---|---|
| `blender_addon/__init__.py` | Replace `use_gpu` boolean UI with `device_mode = auto/gpu/cpu`; apply the same backend policy in final render and viewport render; add diagnostics panel; expose neural-cache/integrator params where supported; show module path/features/fallback reason. |
| `scripts/build_blender_addon.py` | Replace stale hard-coded CPU build with `--backend auto/cpu/cuda/tcnn`; use a clear build dir (`build_blender`, `build_blender_cuda`, or `build_tcnn`); stop using `build_tncc`; package/report the selected module and required runtime DLLs. |
| `scripts/README.md` | Update Blender addon build instructions to explain backend modes and how to verify the packaged module. |
| `module/blender_module.cpp` | Add missing feature/status bindings only if needed by the addon diagnostics. Prefer existing `__features__`, GPU properties, registry names, and integrator stats when enough. |
| `tests/test_blender_view_layers.py` | Extend existing addon stubs or keep as-is if new backend tests cover the device path. |
| `.astroray_plan/docs/STATUS.md` | Mark pkg37 active/done as work proceeds and record any important backend decision. |

### Key design decisions

1. **Device mode is explicit, but Auto is default.** `Auto` chooses GPU
   when available and when scene/backend capability checks say the render
   is safe. `GPU` requests GPU and reports a warning/error if unsupported.
   `CPU` is always available and is used for CPU-targeted tests.

2. **Viewport and final render share one policy function.** The addon
   should not have separate logic that lets final render use GPU while
   viewport silently stays CPU-only. A small helper such as
   `configure_backend(renderer, settings, scene, mode)` should be called
   from both paths.

3. **No silent feature downgrade.** If Blender imports a CPU-only module,
   the UI must say that plainly. If tiny-cuda-nn is not compiled or not
   runtime-available, neural-cache controls must show fallback state
   instead of implying acceleration is active.

4. **Build script controls packaging, not the user's memory.** The
   packaged zip should include a manifest/build report naming the module
   path, CMake flags, backend mode, CUDA state, tiny-cuda-nn state, and
   Python/Blender ABI target.

5. **Capability metadata gates correctness.** Once pkg34 is available,
   Auto must refuse GPU for unsupported material/backend combinations
   unless a material explicitly declares an acceptable preview fallback.
   Until then, Auto can use GPU for simple known-safe scenes and must
   label the decision as conservative.

6. **NRC/tiny-cuda-nn remains observable.** The addon may expose
   `neural-cache` selection and params, but defaulting to neural-cache
   should only happen after benchmarks show it is performance-positive
   and visually stable for the scene class. GPU path tracing can be Auto
   default earlier than NRC.

---

## Acceptance criteria

- [ ] Blender render settings expose `Device: Auto / GPU / CPU`; Auto is
      the default for new scenes.
- [ ] Final render and viewport render both call the shared backend policy
      and both use GPU when Auto/GPU selects it.
- [ ] CPU-only modules, missing CUDA devices, and unsupported scene
      features produce visible diagnostics instead of silent fallback.
- [ ] `scripts/build_blender_addon.py --backend cpu` produces a CPU addon
      zip, and `--backend cuda` or `--backend tcnn` either produces the
      requested addon zip or fails with an actionable message.
- [ ] The build script no longer uses `build_tncc` and no longer forces
      `ASTRORAY_ENABLE_CUDA=OFF` for every package.
- [ ] Addon diagnostics show at least: imported `astroray` module path,
      `astroray.__version__`, `astroray.__features__`, GPU availability,
      GPU device name, selected integrator, selected device mode, active
      backend, and fallback reason when any.
- [ ] Neural-cache controls are visible only when the integrator registry
      contains `neural-cache`; stats from `get_integrator_stats()` are
      displayed after a render when available.
- [ ] Tests cover Auto/GPU/CPU policy with renderer stubs, including
      viewport calling `set_use_gpu(True)` when expected.
- [ ] Existing Blender addon tests still pass.
- [ ] Documentation explains how to install/check the addon and how to
      verify that Blender is using the intended build directory/module.

---

## Non-goals

- Do not implement new material physics in this package.
- Do not make every material GPU-native; pkg35 and pkg36 own GPU spectral
  material parity and shared closure lowering.
- Do not default to neural-cache merely because tiny-cuda-nn is compiled.
  It must be benchmark-positive and observable first.
- Do not add a full interactive progressive viewport renderer here unless
  the shared backend policy work is complete and tests are green.
- Do not remove CPU rendering. CPU remains the correctness/reference
  target and the required fallback.

---

## Progress

- [ ] Replace boolean `use_gpu` with backend/device mode settings.
- [ ] Add shared backend configuration helper and call it from final render.
- [ ] Call the same backend helper from viewport render.
- [ ] Add feature diagnostics panel.
- [ ] Add neural-cache/integrator stats UI surface.
- [ ] Refresh addon build script backend modes and build directory naming.
- [ ] Update scripts README and package/build verification docs.
- [ ] Add backend policy tests with renderer stubs.
- [ ] Run focused Blender addon tests.
- [ ] Run relevant Python binding/backend tests.
- [ ] Update STATUS.md.

---

## Lessons

*(Fill in after the package is done.)*
