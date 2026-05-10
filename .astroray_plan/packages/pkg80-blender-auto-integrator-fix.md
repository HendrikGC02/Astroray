# pkg80 — Blender addon: resolve `'auto'` integrator before C++ calls

**Pillar:** 5
**Track:** A
**Status:** done
**Estimated effort:** ~½ day (~3 h)
**Depends on:** pkg37 (Blender addon backend refresh), pkg53 (integrator capability diagnostics)

---

## Goal

**Before:** When the Astroray Blender addon's integrator dropdown is set to
`Auto (Best Available)`, viewport rendered-view crashes on the very first
frame with:

```
RuntimeError: Astroray: integrator 'auto' does not support GPU
(capability query failed: astroray: unknown plugin 'auto')
```

The addon passes the literal string `'auto'` into
`astroray.integrator_capabilities('auto')` and `set_integrator('auto')`,
but no plugin is registered under that name. `'auto'` is a UI-only
sentinel that should be resolved to a concrete plugin name (per the
pkg27b "Auto (Best Available)" design) before any C++ call.

**After:** `_effective_integrator_name(settings)` resolves `'auto'` →
the best available registered plugin for the current `device_mode`.
Viewport renders without raising. CPU + GPU paths both clean.

---

## Context

Surfaced by the project owner during a viewport interactivity test
2026-05-10:

- Blender 5.1, Astroray addon, `device_mode='gpu'`,
  integrator dropdown = `Auto (Best Available)`.
- The addon's `view_update` → `_sync_viewport_scene` →
  `_configure_backend_for_context` → `configure_backend` chain calls
  `astroray.integrator_capabilities(integrator_name)` with
  `integrator_name='auto'`. Crashes immediately.

This is a regression that pkg27b's auto-default work was supposed to
prevent. Either pkg27b never wired the addon-side resolution, or a
later addon refactor (pkg37) broke it.

---

## Reference

- `blender_addon/__init__.py` — current
  `_effective_integrator_name(settings)` returns
  `settings.integrator` verbatim, without resolving the `auto` case
  (lines around 373, 416, 980, 1075, 1122 in the user's traceback).
- `module/blender_module.cpp` — `integrator_registry_names()` Python
  binding (added in pkg05 / pkg53).
- `.astroray_plan/packages/pkg27b-nrc-indirect-validation.md` — the
  original "Auto (Best Available)" design; defines the resolution
  policy as "fastest validated default per `Renderer::render()`'s
  internal selection".

---

## Specification

### Files to modify

| File | Change |
|---|---|
| `blender_addon/__init__.py` | Update `_effective_integrator_name(settings)` to resolve `'auto'` against `astroray.integrator_registry_names()` + capabilities, returning a concrete plugin name. Resolution policy below. |
| `tests/test_blender_backend_policy.py` (or new `tests/test_blender_auto_integrator.py`) | New test: settings with `integrator='auto'` + `device_mode='gpu'`, assert `_effective_integrator_name(settings)` returns a registered plugin that reports `gpu_supported=True`. Same with `device_mode='cpu'`. |

### Resolution policy

1. If `settings.integrator != 'auto'`, return it unchanged.
2. If `'auto'`, query `astroray.integrator_registry_names()`. Pick the
   first entry that satisfies `device_mode`:
   - `device_mode='gpu'`: first plugin whose
     `astroray.integrator_capabilities(name)` reports
     `gpu_supported=True`.
   - `device_mode='cpu'`: first plugin (CPU support is required of
     every registered integrator).
   - `device_mode='auto'`: GPU-capable if any plugin supports GPU AND
     a CUDA device is present; otherwise the same fallback as `cpu`.
3. Preferred order: `path_tracer` first (the spectral default), then
   `multiwavelength_path_tracer`, then any other plugin in registry
   order. Hardcoded preference list in the addon, so the addon owns
   the UX policy and the engine doesn't need to know about it.
4. If resolution fails (registry empty or no GPU-capable plugin when
   GPU was requested), raise a `RuntimeError` with a clear message
   ("integrator 'auto' could not be resolved to a registered plugin
   for device_mode='gpu' — set the dropdown to a specific
   integrator").

### Acceptance criteria

- [ ] Viewport rendered-view with `device_mode='gpu'` + integrator
      dropdown=`Auto (Best Available)` produces a frame without
      `RuntimeError: unknown plugin 'auto'`.
- [ ] Same with `device_mode='cpu'`.
- [ ] Same with final-render F12.
- [ ] New addon-policy unit test green; existing
      `tests/test_blender_backend_policy.py` still green.
- [ ] Final addon `_effective_integrator_name` is a pure function of
      `(settings, registry_names, capability_query)` — no global
      state — so the policy is testable without `bpy`.

### Non-goals

- Changing the C++ side. There is no `'auto'` plugin and there
  shouldn't be one — the addon owns this UX choice.
- Selecting between `path_tracer` and `multiwavelength_path_tracer`
  by scene content (e.g., wavelength range). Future polish.

---

## Reference matrix

| Source | License | Mirror? | What we borrow | What we cite | Hard fence |
|---|---|---|---|---|---|
| `intern/cycles/blender/properties.py` ("device_type" auto-resolution pattern) | Apache-2.0 | n/a | UI policy shape (registry query → first capable backend) | yes, in code comment | nothing |

No code is copied; the file is read for pattern only.

---

## Lessons (filled in on completion)

- Resolved 2026-05-10. `blender_addon/__init__.py` now defines
  `_resolve_auto_integrator(settings)` which queries
  `astroray.integrator_registry_names()` and walks a hardcoded preference
  list (`path_tracer` → `multiwavelength_path_tracer` → registry order),
  filtering by `integrator_capabilities(name)["gpuSupported"]` when
  `device_mode='gpu'`. `_effective_integrator_name(settings)` calls it
  only when `settings.integrator_type == 'auto'`; the existing wavelength
  override (`multiwavelength_path_tracer` for non-visible ranges) is
  preserved untouched.
- `RuntimeError` raised with a clear "set the dropdown to a specific
  integrator" hint when no registered plugin reports GPU support and
  `device_mode='gpu'`.
- Tests: `tests/test_blender_auto_integrator.py` covers the four
  acceptance cases (cpu/auto resolves, gpu CUDA-build resolves,
  gpu CPU-only-build raises, non-auto returns unchanged without touching
  the registry). 19/19 pass alongside `test_blender_backend_policy.py`.
- C++ side untouched per spec non-goal: `'auto'` stays a UI-only sentinel.
