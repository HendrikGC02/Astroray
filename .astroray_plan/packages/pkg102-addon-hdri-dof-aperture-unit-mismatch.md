# pkg102 — Blender addon DOF aperture unit mismatch causes "HDRI blur"

**Pillar:** 5 (addon)
**Track:** A (correctness, small Python-only fix)
**Codex-paste-ready:** yes
**Status:** done (PR #369, 2026-05-24 — aperture 4.5mm vs 45mm, tests green)
**Depends on:** none
**Estimated effort:** small (<½ day; few-line fix + regression test)

---

## Goal

**Before:** Adding an HDRI to a Blender scene renders the HDRI as
heavily blurred even when DOF was not intentionally configured.
Owner-reported 2026-05-24: *"when I added an HDRI, it was completely
blurry, presumably because of some DOF bug."*

**After:** With Blender's camera DOF disabled the rendered HDRI is
sharp. With DOF enabled the aperture maps to a physically reasonable
lens radius in scene units (meters) — i.e. an f/5.6 50mm lens
produces a ~4.5 mm radius lens, not a 0.089 m radius.

---

## The defect (verified on HEAD 24b5701, 2026-05-24)

`blender_addon/__init__.py:1843-1850` computes:

```python
aperture, focus_dist = 0.0, 10.0
if camera.dof.use_dof:
    if camera.dof.aperture_fstop > 0:
        aperture = 1.0 / (2 * camera.dof.aperture_fstop)
    ...
```

`aperture` is then passed to `Renderer.setup_camera(...)` and ends up
as `lensRadius = aperture / 2` in `include/raytracer.h:1854` — i.e.
the lens **radius in scene units (meters)**.

For an f/5.6 setting this produces `lensRadius = 1/(2·5.6)/2 ≈ 0.045
m = 45 mm` — a lens 90mm across. Combined with a typical
`focus_distance` of a few meters this produces a circle-of-confusion
on the order of centimeters at object distance, which appears as
extreme blur on anything not exactly at the focus plane (the HDRI is
at infinity → maximum blur).

The correct relation is the photographic one used by Cycles
(`intern/cycles/blender/camera.cpp`, `BlenderCamera::sync`):
`aperture_radius = (focal_length / fstop) / 2` with `focal_length` in
**meters** (Blender's `camera.lens` is in millimetres → multiply by
1e-3).

**Two bugs in one expression:**

1. The fstop relation is missing the focal length entirely
   (`aperture_radius = focal_length / (2 · fstop)`).
2. The result is then halved again at the C++ side (`lensRadius =
   aperture/2`), so the addon must pass **diameter**, not radius.

**Note on default state:** Blender 4.x defaults `camera.dof.use_dof =
False` on new scenes, so the bug only manifests when a user enables
DOF (or imports a scene that has it on). A second-order question is
whether `aperture_fstop`'s default of `2.8` should ever render this
heavily blurred for `use_dof=False` — it should not, and the
`use_dof` guard prevents that. If the owner reports blur with DOF
off, that is a separate defect (likely camera-data scoping inside
the live-viewport update loop).

---

## Reference

### Internal
- `blender_addon/__init__.py:1843-1858` — the buggy expression and the
  `setup_camera` call.
- `include/raytracer.h:1854` — `lensRadius = aperture / 2`. The addon
  must pass **diameter in meters**.
- `tools/blend_import/scene_builder.py` — the importer does not
  currently extract DOF at all (`aperture=0, focus_dist=10` hardcoded
  by the harness). Out of scope for this package.

### External
- Cycles `intern/cycles/blender/camera.cpp` `BlenderCamera::sync` (Apache-2.0):
  ```
  bcam->aperturesize = (b_camera.dof().aperture_fstop() > 0.0f) ?
      (b_camera.lens() * 1e-3f) / (2.0f * b_camera.dof().aperture_fstop()) :
      0.0f;
  ```
  `aperturesize` is the **radius in meters**. The addon should mirror
  this expression exactly, then pass `2 * aperturesize` to
  `setup_camera` so the C++ `lensRadius = aperture/2` yields the
  intended radius.
- PBRT-v4 `RealisticCamera` (BSD-3): same physical lens-radius
  derivation. Cite Cycles as the closer reference.

CLAUDE.md §6: cite Cycles' `camera.cpp` expression directly in the
fix; this is a physical-units formula, not a novel algorithm.

---

## Fix

```python
aperture, focus_dist = 0.0, 10.0
if camera.dof.use_dof:
    if camera.dof.aperture_fstop > 0:
        # Cycles intern/cycles/blender/camera.cpp::BlenderCamera::sync (Apache-2.0):
        # aperture_radius = (focal_length_m) / (2 * fstop). camera.lens is in mm.
        focal_length_m = float(camera.lens) * 1e-3
        aperture_radius = focal_length_m / (2.0 * float(camera.dof.aperture_fstop))
        # C++ Camera takes diameter (lensRadius = aperture/2), so pass 2x.
        aperture = 2.0 * aperture_radius
    if camera.dof.focus_object:
        focus_dist = (loc - camera.dof.focus_object.matrix_world.translation).length
    else:
        focus_dist = camera.dof.focus_distance
```

---

## Acceptance criteria

- [ ] Pytest in `tests/test_addon_dof_aperture.py` constructs a stub
      Blender camera (lens=50mm, fstop=5.6, use_dof=True) and asserts
      the value passed to `Renderer.setup_camera` for `aperture` is
      within 1% of `2 * (0.050 / (2*5.6)) ≈ 0.00893`. Also asserts
      that with `use_dof=False`, `aperture == 0.0`. Test must fail on
      HEAD, pass after fix.
- [ ] Manual RTX visual: load any HDRI in a Blender scene with `Camera
      → Depth of Field` unchecked (default); the rendered HDRI is
      sharp. Then enable DOF at f/5.6 50mm focused on a 2 m subject;
      the HDRI shows visible but moderate (~physically plausible) blur,
      not the previous extreme blur.
- [ ] CI green.

## Hard non-goals

- No refactor of `_apply_camera`. Touch only the aperture lines.
- No change to C++ `Camera` semantics. The addon passes
  diameter-in-meters; the C++ continues to halve.
- No new DOF features (`focus_object` chains, `aperture_blades`,
  `aperture_ratio` already-passed paths — out of scope).

---

## Provenance

Owner-reported 2026-05-24: *"when I added an HDRI, it was completely
blurry, presumably because of some DOF bug."* Architect verified the
units error against Cycles' reference expression.
