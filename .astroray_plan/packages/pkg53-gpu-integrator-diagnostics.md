# pkg53 — GPU Integrator Capability Diagnostics

**Pillar:** 5
**Track:** B / E
**Status:** open
**Estimated effort:** 1 session (~3 h)
**Depends on:** pkg34 (material capabilities, done)

---

## Goal

**Before:** Selecting an integrator the GPU does not support (today: `multiwavelength_path_tracer`, `caustic_path_tracer`, anything spectral that needs Sellmeier or spectral emitters) silently falls back to CPU or, worse, runs a structurally-different code path on GPU. Users cannot tell which integrators work where.

**After:** Each registered integrator declares a `gpuSupported` capability (analogous to `Material::backendCapabilities`). Selecting an unsupported integrator with `device_mode='gpu'` produces a clear UI error. `device_mode='auto'` falls back to CPU only when the user did not explicitly choose GPU. The Diagnostics panel lists per-integrator GPU support.

---

## Context

This is the smallest version of the GPU-parity work that gives users honest feedback. We do not write any new GPU kernel here — we just stop lying about which kernels exist. Everything in pkg54 and pkg55 builds on having this metadata.

---

## Reference

- Pattern: pkg34 (`Material::backendCapabilities`).
- Touch points: [plugins/integrators/*.cpp](plugins/integrators/), [include/astroray/integrator.h](include/astroray/integrator.h), [module/blender_module.cpp](module/blender_module.cpp).

---

## Prerequisites

- [ ] pkg34 done.
- [ ] Integrator base class accessible at the registry level.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `tests/test_integrator_capabilities.py` | Asserts every registered integrator declares `gpuSupported` and that the unsupported list matches expectations. |

### Files to modify

| File | What changes |
|---|---|
| `include/astroray/integrator.h` | Add `struct IntegratorCapabilities { bool gpuSupported; std::string gpuFallbackReason; }; virtual IntegratorCapabilities capabilities() const;` Default: `{false, "no GPU kernel implemented"}`. |
| `plugins/integrators/*.cpp` | Override `capabilities()` for: `path_tracer` (true on GPU), `ambient_occlusion` (true on GPU), all others (false + reason). |
| `module/blender_module.cpp` | Bind `astroray.integrator_capabilities(name) -> dict`. |
| [blender_addon/__init__.py](blender_addon/__init__.py) | In `configure_backend`/render path, check the chosen integrator's GPU support. If `device_mode='gpu'` and unsupported, `self.report({'ERROR'}, ...)` and abort the render. If `device_mode='auto'` and unsupported on GPU, fall back to CPU with a one-line `INFO` report. Diagnostics panel lists each integrator's support status. |

### Key design decisions

1. **No silent CPU fallback when the user chose GPU.** This matches pkg37's "no silent feature downgrade" rule.
2. **Auto = CPU fallback is fine, but logged.** Auto is opt-in to fallbacks.
3. **One source of truth.** Capabilities live in C++ and are surfaced verbatim in Python; do not duplicate the table in the addon.

---

## Acceptance criteria

- [ ] `astroray.integrator_capabilities("multiwavelength_path_tracer")` returns `{gpuSupported: False, gpuFallbackReason: "..."}`.
- [ ] Selecting Multi-Wavelength + Device=GPU in the addon shows a Blender error popup and aborts cleanly.
- [ ] Selecting Multi-Wavelength + Device=Auto runs on CPU and prints a one-line INFO.
- [ ] Diagnostics panel shows the support matrix.
- [ ] `tests/test_integrator_capabilities.py` passes.

---

## Non-goals

- Do not write new GPU kernels (pkg54+ owns that).
- Do not change material backend capabilities.

---

## Progress

- [ ] Add `IntegratorCapabilities` struct and virtual method.
- [ ] Override in each integrator plugin.
- [ ] Python binding.
- [ ] Addon wiring (refuse / fallback / report).
- [ ] Diagnostics panel rows.
- [ ] Tests.

---

## Lessons

*(Fill in after the package is done.)*
