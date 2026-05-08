# pkg58 — Spectral Profile UX + IR/UV Reference Scenes

**Pillar:** 5
**Track:** B
**Status:** open
**Estimated effort:** 1 session (~3 h)
**Depends on:** pkg39 (multi-wavelength rendering, done)

---

## Goal

**Before:** [`spectral_profile`](blender_addon/__init__.py:184) on each material is a `StringProperty` — users have to type the profile name. There is no way to preview a profile's reflectance curve. There are no reference IR/UV scenes shipped with the addon, so IR/UV rendering produces black output for any material the user did not pre-configure.

**After:** Material panel shows a populated `EnumProperty` of all profiles loaded from `profiles.bin` (via `astroray.spectral_profile_names()`). A small preview panel draws the reflectance curve for the selected profile across the active wavelength band. Three reference Blender scenes ship with the addon: vegetation under NIR, skin under UV, and a polished-metal sphere set sweeping 700–2500 nm.

---

## Context

pkg39 shipped multi-wavelength rendering and the `SpectralProfileDatabase`. pkg37 shipped the Diagnostics panel. Both are real, but the missing UX layer means almost no user will hit the IR/UV path correctly today. This is a small package that turns a useful feature into a usable one.

Bonus: the reference scenes give pkg54 (GPU multiwavelength) ready-made parity tests.

---

## Reference

- Backend: [include/astroray/spectral_profile.h](include/astroray/spectral_profile.h), [src/spectral_profile.cpp](src/spectral_profile.cpp).
- Python bindings: `astroray.spectral_profile_names()`, `astroray.spectral_profile_reflectance(name, lambda_nm)`.
- Current UI: `CustomRaytracerMaterialSettings` in [blender_addon/__init__.py](blender_addon/__init__.py:170).
- Profile DB: pkg38 `data/profiles.bin`, USGS / JHU / Rakic 1998 / Bashkatov 2005.

---

## Prerequisites

- [ ] pkg39 done.
- [ ] `profiles.bin` ships with the addon zip (verify via `scripts/build_blender_addon.py`).
- [ ] `astroray.spectral_profile_names()` returns ≥ 40 names on a default build.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `blender_addon/scenes/ir_vegetation.blend` | Hyperspectral demo: leaves and grass at 700–1000 nm. |
| `blender_addon/scenes/uv_skin.blend` | UV demo: skin surface at 300–400 nm. |
| `blender_addon/scenes/metal_sweep.blend` | Polished Al + Au sphere set, 700–2500 nm. |
| `tests/test_spectral_profile_ui.py` | Stubbed Blender tests asserting the dropdown populates and reflects renderer state. |

### Files to modify

| File | What changes |
|---|---|
| [blender_addon/__init__.py](blender_addon/__init__.py) | Replace `spectral_profile: StringProperty` with `spectral_profile: EnumProperty` whose items callback is `_spectral_profile_items(self, context)` (returns `[(name, name, '')]` from `astroray.spectral_profile_names()`). Add a `MATERIAL_PT_AstroraySpectralPreview` panel with a curve drawn via `gpu.types.batch.draw` calling `astroray.spectral_profile_reflectance(name, λ)` at 32 evenly-spaced λ in the active band. Show the panel only when `wavelength_preset != 'visible'`. |
| `scripts/build_blender_addon.py` | Package `blender_addon/scenes/` into the addon zip. |

### Key design decisions

1. **Items callback, not static list.** Profile DB is loaded at C++ init; the dropdown must reflect what's actually loaded, not a Python-side guess.
2. **Curve preview is read-only.** No editing the profile from Blender — that requires shipping new data files.
3. **Hide the panel for visible-light renders.** Clutter reduction; spectral profiles only matter outside 380–780 nm.
4. **Reference scenes use only built-in profiles.** No external HDRIs or texture files. Each .blend is self-contained and < 5 MB.

---

## Acceptance criteria

- [ ] Dropdown shows the same names as `astroray.spectral_profile_names()`.
- [ ] Selecting a profile and switching wavelength preset to NIR/UV produces a non-black render in the reference scenes.
- [ ] Curve preview matches `astroray.spectral_profile_reflectance(name, λ)` within 1% across 32 sample points.
- [ ] All three reference scenes render successfully on CPU at 32 spp.
- [ ] Tests pass.

---

## Non-goals

- Do not implement on-the-fly profile editing.
- Do not bundle HDRIs (license risk).
- Do not add new spectral profiles to `profiles.bin` — pkg38 owns the DB.

---

## Progress

- [ ] EnumProperty conversion + items callback.
- [ ] Curve preview panel.
- [ ] Reference scenes (3 .blend files).
- [ ] Build script packaging.
- [ ] Tests.

---

## Lessons

*(Fill in after the package is done.)*
