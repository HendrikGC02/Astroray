# pkg213 — Expose light intensity (Power) in the Astroray light panel

**Pillar:** Integration Milestone (Blender/DCC integration — reuse Blender's native settings as the steering wheel)
**Track:** A
**Status:** open (filed 2026-08-21).
**Estimated effort:** S.
**Depends on:** none.

## Goal

Give the artist a way to set a light's **intensity** in the Astroray Properties UI. Today the light panel exposes only the light *type* (Blender's own) and the Astroray *spectrum* (mode + measured-SPD preset). There is no intensity control anywhere in the Astroray UI, so a sodium/mercury preset lamp — or any light — cannot be made brighter or dimmer from the panel.

The engine already consumes intensity: `blender_addon/__init__.py:4632` reads `intensity = float(light.energy)` and passes it into `add_point_light` / `add_sun_light_dedicated` / `add_area_light_dedicated`, and `settings_map.py:250` marks `light.data.energy` as **SUPPORTED** (`direct`). So intensity is **wired but not exposed** — this is a UI-surfacing fix, not a plumbing fix.

## Context

- **The only Astroray light panel** is `DATA_PT_custom_raytracer_light` ("Astroray Spectrum", `__init__.py:5681`). Its `draw()` (`:5694`) draws `spectrum_mode`, then `preset_profile` / `custom_profile`, then informational labels. It never draws `light.energy` (or `light.color`).
- **No native light-data panel is adopted for our engine.** `ADOPTED_NATIVE_PANELS` (`:5830`) adopts only the Light-Paths family (render-settings panels). The wholesale `_iter_compat_panels()` loop (`:5808`) requires `'BLENDER_RENDER' in COMPAT_ENGINES` (`_is_compatible_panel`, `:5759`). Blender's light-data panels that carry the Power/Strength slider advertise `{'CYCLES'}` or `{'BLENDER_EEVEE'}` — never `BLENDER_RENDER` — so neither path shows them for `CUSTOM_RAYTRACER`. Net effect: with our engine active, the light Properties tab shows Blender's built-in type/shape controls plus our Spectrum panel, but **no intensity field**.
- `light` in the panel `draw()` is `context.light` — the Light *datablock* — and `energy` is a native property on it. Exposing it is a one-line `layout.prop(light, "energy")`; Blender auto-labels it "Power" and applies the type-appropriate unit (W for point/spot/area, W/m² for sun). This directly follows the integration-first directive to *reuse Blender's native settings as the steering wheel* rather than invent a parallel knob.

**Design forks considered (surface, don't force):**
- *Add `layout.prop(light, "energy")` to the existing Spectrum panel* — **chosen.** Minimal, honest units, reuses the already-wired native property, no new state.
- *Adopt the native Cycles light panel* (`CYCLES_LIGHT_PT_light`) — rejected. It drags in node/other controls that are not honestly mapped, violating the pkg176 adoption discipline ("every control must map to a `direct` row"); heavier than a one-line prop.
- *Add a new Astroray `intensity` PropertyGroup field that feeds emission* — rejected. `light.energy` is already the wired intensity; a second knob is redundant and would desync from the engine's actual input at `:4632`.

## Reference

- `blender_addon/__init__.py:4632` — `intensity = float(light.energy)` (the value the slider will set).
- `blender_addon/__init__.py:5681` / `:5694` — `DATA_PT_custom_raytracer_light` panel + `draw()`.
- `blender_addon/__init__.py:5830` — `ADOPTED_NATIVE_PANELS` (why no native light panel is shown).
- `blender_addon/settings_map.py:250` — `light.data.energy` = SUPPORTED / `direct`.
- Memory: `integration-first-directive-2026-08` (reuse Blender's native settings).

## Specification

1. In `DATA_PT_custom_raytracer_light.draw()` (`__init__.py:5694`), add `layout.prop(light, "energy")` near the top of the panel (before or after `spectrum_mode`). `light` is already bound to `context.light` at `:5699`.
2. Keep the Power control visible in **all** spectrum modes (`native` / `preset` / `custom_profile`) — `light.energy` multiplies the emission unconditionally in the engine (`:4632` runs regardless of mode), so hiding it in preset mode would misrepresent behaviour.
3. **No engine / C++ change** — the `intensity` argument is already consumed by every `add_*_light*` call. This package only surfaces the existing input.
4. **No new property** on `CustomRaytracerLightSettings`.

## Acceptance criteria

- [ ] **Render-brighter gate (engine-level pytest, machine-verifiable, no Blender needed):** render a white lambertian sphere lit by a point lamp at two intensities (e.g. 30 vs 120) via `add_point_light(..., intensity=...)`, CPU integrator, **LINEAR** output (memory `gamma-furnace-cannot-detect-energy-gain`). Assert the higher-intensity mean linear RGB is ≥1.5× the lower (proportional scaling is the expected physics). This locks the value the slider sets to a brighter render.
- [ ] **UI-wiring gate (headless Blender):** in headless `bpy`, create a Light, set `light.data.energy = 200`, run the addon export/convert path, and assert `add_point_light` (or the matching `add_*_light*`) receives `intensity == 200.0` — proving the property the new control edits reaches the engine end-to-end.
- [ ] **Panel-draws-control smoke (headless Blender):** with `CUSTOM_RAYTRACER` active and a light selected, `DATA_PT_custom_raytracer_light.draw()` runs without exception in `native` and `preset` modes and references `light.energy`.
- [ ] Existing pkg195 spectral-lamp tests (`tests/test_pkg195_stage_b_spectral_lamp.py`) still pass unchanged.
- [ ] CI green on all matrix jobs (`gh run view` on HEAD — memory `mingw_local_vs_gcc_ci_divergence`).

## Non-goals

- **No new intensity property or unit remapping.** Blender's native Watt units are honoured as-is; the known ~3× Astroray-vs-Cycles light-energy-scale divergence (pkg89 / pkg122, noted in `settings_map.py:251`) is a separate calibration concern, out of scope here.
- **No exposure / color-management / tone-map controls** — intensity only.
- **No native-Cycles light-panel adoption** and no change to `ADOPTED_NATIVE_PANELS`.
- **No `light.color` (gel tint) UI change** — the panel already documents the tint behaviour; scope is intensity.

## Progress

_(none yet)_

## Lessons

_(none yet)_
