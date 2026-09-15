# pkg274 — Addon gaps: native device, missing textures, camera clip, holdout

**Pillar:** 3
**Track:** B
**Status:** open
**Estimated effort:** 1 session (~3 h)
**Depends on:** none

---

## Goal

Before: four Blender-native controls are silently ignored or merely warned about —
`scene.cycles.device` only changes the backend through
`custom_raytracer.device_mode` (#722); a missing image/environment file drops the
whole node with no degradation entry and no magenta fallback (#723);
`camera.data.clip_start`/`clip_end` are ignored with a per-render warning (#724);
and `object.is_holdout` cuts no alpha hole (#36). After: `device_mode == 'auto'`
honours the native `scene.cycles.device` (CPU→cpu, GPU→cuda) while an explicit
Astroray override still wins; a missing texture records a DEGRADED entry in the
consolidated report and renders a magenta constant; the engine's primary-ray
t-min/t-max use the Blender camera clip planes; and a holdout object writes alpha
0 (transparent hole, no shading) where the camera ray hits it. All four are
CPU-verified by `tests/test_pkg274_addon_gaps.py`.

---

## Context

Pillar 3 (Blender/DCC integration) is the standing owner priority, and the
ratified steering-wheel contract (pkg176/pkg177) makes Blender's own
Cycles-shaped panels authoritative. `blender_addon/settings_map.py` is the single
translation-policy table, and the 2026-09-07 addon probe filed these four gaps as
tracker-visible mismatches. Without this package the table mis-states
`device_mode` as a SEMANTIC MISMATCH and the clip rows as DROPPED-SILENT, missing
textures stay invisible to the pkg119-C degradation policy, and holdout
compositing is impossible. Each item is independently shippable; they are batched
because all four are small addon-side contracts over the same report/table
machinery.

---

## Evidence

- 2026-09-07 (#722): with `scene.cycles.device = 'CPU'` and `device_mode = 'auto'`,
  F12 still logs `GPU rendering: NVIDIA GeForce RTX 5070 Ti`; only
  `scene.custom_raytracer.device_mode` selects the backend.
- 2026-09-07 (#723): `blender_addon/scenes/metal_sweep.blend` references
  `//../samples/test_env.hdr` (missing); Cycles renders magenta, Astroray renders
  grey with no `Astroray degradation:` line.
- 2026-09-07 (#724): every render prints `Astroray degradation: 0 approximated /
  1 ignored -- ignored camera clip_start/clip_end (near/far clipping ignored)`.
- `blender_addon/settings_map.py:407` — `device_mode` row note still begins
  "SEMANTIC MISMATCH"; `:290-293` — `clip_start`/`clip_end` rows are `dropped` /
  `DROPPED-SILENT` with neutral target `(none)`.
- `blender_addon/native_settings.py:150-154` — the warning source for the clip
  planes.
- `include/raytracer.h:3121` (spectral) and `:3934` (caustic) — primary-ray
  intersection bounds are hard-coded `0.001f, std::numeric_limits<float>::max()`.
- 2026-09-15 (#36): holdout + indirect-only filed; `object.is_holdout`,
  `object.visible_camera`; Cycles `intern/cycles/scene/object.cpp`
  `use_holdout` / `is_shadow_catcher`.

---

## Reference

- Template: `.astroray_plan/packages/TEMPLATE.md`.
- Translation policy / Route-2 discipline:
  `.astroray_plan/docs/dcc-integration-decision-2026-08.md §6`; coverage anchor
  `docs/blender_parity/coverage_matrix.json`.
- Cycles reference (Apache-2.0): `intern/cycles/kernel/integrator/shade_surface.h`
  (holdout), `intern/cycles/scene/object.cpp` (`use_holdout`, `is_shadow_catcher`),
  and the Blender manual pages "Camera Clip Start/End", "Object Holdout", "Image
  Texture" (missing-file magenta).
- Issues: #722, #723, #724, #36.

---

## Prerequisites

- [ ] Build passes on main (`cmake --build build -j`, `ASTRORAY_ENABLE_CUDA=OFF`).
- [ ] Fresh `build/` `.pyd` is present and importable (`pytest tests/test_python_bindings.py -q`).
- [ ] `blender_addon/settings_map.py` lints clean under `tests/test_pkg176_settings_map.py`.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `tests/test_pkg274_addon_gaps.py` | All four items' gates: device resolution, missing-texture degradation + magenta fallback, clip-plane primary-ray bounds, holdout alpha hole. |

### Files to modify

| File | What changes |
|---|---|
| `blender_addon/native_settings.py` | Add `resolve_device_mode(cycles, custom_value)` (mirroring `resolve_light_sampler`): `'auto'` reads native `scene.cycles.device` (CPU→`'cpu'`, GPU→`'gpu'`), an explicit custom `'cpu'`/`'gpu'` wins; wire it into `resolve_native_settings`. Remove the `clip_start`/`clip_end` message from `report_unsupported_native_controls` once honoured. |
| `blender_addon/settings_map.py` | `device_mode` row: `pkg119a` `n/a`→`SUPPORTED`, `status`→`approximated`, note drops the "SEMANTIC MISMATCH" framing and states the auto/override rule. `clip_start`/`clip_end` rows: `status` `dropped`→`direct`, `pkg119a` `DROPPED-SILENT`→`SUPPORTED`, `neutral_param`→`setup_camera (clip near/far)`. |
| `blender_addon/degradation.py` | Add a third disposition `degraded` bucket with a `degraded()` recorder; include it in `summary()`/`messages()`/`text()` so a missing texture surfaces once per render. |
| `blender_addon/__init__.py` | `load_blender_image`/`_load_blender_image_resolved`: detect a missing image file (non-packed `filepath` that does not exist) and register a 1×1 magenta texture + a `degraded(node_name, filepath)` entry instead of returning `None`. `setup_world`: on a missing `hdri_path` add a `degraded` entry and `set_background_color([1, 0, 1])`. Export the camera clip to `setup_camera(..., clip_near=..., clip_far=...)` and the per-object holdout via `renderer.set_object_holdout(index, True)` beside the `is_caustic_caster` upload (`:5404`/`:5520`). |
| `include/raytracer.h` | `Ray` gains `float tMin = 0.001f, tMax = std::numeric_limits<float>::max();` and `Camera::getRay` sets them from new `clipNear`/`clipFar` camera fields; the primary-ray `bvh->hit(ray, 0.001f, FLT_MAX, rec)` sites (`:3121`, `:3934`) pass `ray.tMin`/`ray.tMax`. Add a holdout flag (`setObjectHoldout`, mirroring `setObjectCausticCaster` at `:2732`) and zero the primary sample's color/alpha when `ir.objectIndex` is a holdout. |
| `module/blender_module.cpp` | `setupCamera` and its `setup_camera` binding (`:3625`) gain optional `clip_near`/`clip_far` (defaults `0.001f`/`FLT_MAX`); new `set_object_holdout` binding mirroring `set_object_caustic_caster` (`:3698`). |

### Key design decisions

#### Item 1 — Honour scene.cycles.device when device_mode == 'auto' (#722)

Resolution lives in the translator (`native_settings.py`), not in
`configure_backend`, so `settings_map.py` stays the single source of truth and
the exporter's existing `configure_backend(renderer, settings, ...)` call is
unchanged. Rule: `device_mode == 'auto'` reads native `scene.cycles.device`
(`'CPU'`→`'cpu'`, `'GPU'`→`'gpu'`); an explicit `'cpu'`/`'gpu'` overrides the
native choice and records a visible degradation note. A non-Cycles scene (no
`scene.cycles`) keeps today's `'auto'` safe-fallback. The `settings_map.py` row
keeps the Astroray tri-state (`status: approximated`) with `pkg119a: SUPPORTED`
and a rewritten note (no "SEMANTIC MISMATCH" text).

Acceptance: `tests/test_pkg274_addon_gaps.py::test_native_device_honoured_when_auto`
— native CPU→`'cpu'`, native GPU→`'gpu'`; explicit override wins; the
settings_map row carries no "SEMANTIC MISMATCH".

#### Item 2 — Missing texture adds a DEGRADED entry + magenta fallback (#723)

A missing image/environment file must never silently drop its node. Add a
`degraded` disposition to `DegradationReport` (it currently has only
approximated/ignored) and record `(node name, absolute filepath)`. The fallback
value is a magenta constant (Cycles renders missing images pink): for material
image textures, register a 1×1 magenta texture through `renderer.load_texture` so
the node still has a texture; for the world HDRI path, `set_background_color([1,
0, 1])`. Detection is a non-packed `bpy_image.filepath` (or the resolved HDRI
path) for which `os.path.exists` is False; generated/packed images are untouched.

Acceptance: `tests/test_pkg274_addon_gaps.py::test_missing_texture_degrades_and_magenta`
— the report contains a DEGRADED entry naming the node and path, and the fallback
colour is magenta; an existing file adds no entry.

#### Item 3 — Camera clip_start/clip_end drive primary-ray t bounds (#724)

The engine already bounds every hit with `(tMin, tMax)`; only the camera's
primary ray should consume the Blender clip planes. Add `clipNear`/`clipFar` to
the ray built by `Camera::getRay` (`Ray::tMin`/`tMax`, default `0.001f`/`FLT_MAX`),
so secondary rays are byte-identical to today. `setup_camera` gains optional
`clip_near`/`clip_far` args so existing callers are unaffected; the addon passes
`camera.data.clip_start`/`clip_end`. `report_unsupported_native_controls` stops
warning about the clip planes. **ABI note (lead):** adding fields to `Ray` changes a struct that crosses every TU and the GPU upload path - prefer keeping the bounds on `Camera` and passing them at the primary-ray `hit()` call sites; if `Ray` must change, run `cpp-abi-guard` and check the wavefront `GRay` mirror stays untouched.

Acceptance: `tests/test_pkg274_addon_gaps.py::test_clip_end_hides_geometry` — a
plane beyond `clip_end` is absent (alpha 0 / background) and present once
`clip_end` is raised, CPU only.

#### Item 4 — Holdout objects write alpha 0 where the camera ray hits (#36)

`object.is_holdout` is exported per object (`set_object_holdout`, mirroring
`set_object_caustic_caster`). When the primary camera ray's first hit is a holdout
object, that sample contributes color 0 and alpha 0 (a transparent hole), with no
shading and no change to how other rays (reflections/GI/shadows) see the object.
The camera-ray check uses `SampleResult::objectIndex` (the first-hit object) in
the render accumulation loop; the indirect path is untouched.

Acceptance: `tests/test_pkg274_addon_gaps.py::test_holdout_sphere_alpha_hole` —
with transparent film, a holdout sphere over a background yields alpha 0 at the
sphere and non-zero alpha on the background.

---

## Acceptance criteria

- [ ] **#722**: with `device_mode == 'auto'`, native `scene.cycles.device` selects
      the backend (CPU→cpu, GPU→cuda); an explicit Astroray `cpu`/`gpu` still
      overrides with a degradation note; the `settings_map.py` `device_mode` row is
      `SUPPORTED` with no "SEMANTIC MISMATCH" text. Test:
      `tests/test_pkg274_addon_gaps.py::test_native_device_honoured_when_auto`.
- [ ] **#723**: a missing image/environment file adds a DEGRADED entry (node name +
      file path) to the consolidated degradation report and falls back to magenta;
      `tests/test_pkg274_addon_gaps.py::test_missing_texture_degrades_and_magenta`
      asserts both the report entry and the fallback colour.
- [ ] **#724**: the engine primary ray is bounded by the Blender camera
      `clip_start`/`clip_end`; the `settings_map.py` clip rows are `SUPPORTED`;
      `tests/test_pkg274_addon_gaps.py::test_clip_end_hides_geometry` renders a
      plane beyond `clip_end` and asserts it is absent, then present with a larger
      `clip_end` (CPU only).
- [ ] **#36**: `object.is_holdout` yields alpha 0 where the camera ray hits the
      object (no shading); `tests/test_pkg274_addon_gaps.py::test_holdout_sphere_alpha_hole`
      asserts the alpha hole with transparent film.
- [ ] All four criteria are machine-verifiable via
      `pytest tests/test_pkg274_addon_gaps.py -v`, with no regression in
      `tests/test_pkg176_*.py` or `tests/test_python_bindings.py`.
- [ ] `report_unsupported_native_controls` no longer emits the clip-plane message,
      and the `device_mode`/clip row flips lint clean
      (`pytest tests/test_pkg176_settings_map.py -q`).
- [ ] Default-path output is byte-identical when clip near/far and holdout are at
      their defaults (no holdout object, default clip), proven by a default render
      in the new test.

---

## Non-goals

- **Indirect-only objects** (`object.visible_camera == False`, Cycles
  `is_shadow_catcher` left untouched) are OUT OF SCOPE for this spec — only the
  camera-ray holdout alpha hole is implemented; the #36 indirect-only half is a
  follow-up package.
- No GPU-specific work beyond what the CPU path shares automatically. GPU parity
  of clip planes and holdout is checked by the existing CPU/GPU parity harness; if
  the wavefront kernel needs a separate change (per-pass clip bounds / holdout
  flag upload), file it as a follow-up rather than authoring it here.
- No orthographic/panoramic camera support; `camera.data.type != 'PERSP'` stays a
  reported drop.
- No shadow-catcher compositing, no transparent-film semantics change, no
  `film_transparent` UI work.
- No new image formats, packed-file handling, or colour-management changes.
- No holdout effect on indirect/GI/shadow visibility — the object still renders
  normally to non-camera rays.

---

## Progress

- [ ] Item 1 (#722): translator device resolution + settings_map row flip.
- [ ] Item 2 (#723): DEGRADED disposition + missing-texture magenta fallback.
- [ ] Item 3 (#724): camera clip → primary-ray t bounds + settings_map row flip.
- [ ] Item 4 (#36): holdout flag export → alpha 0 camera-ray hole.
- [ ] `tests/test_pkg274_addon_gaps.py` green; default render byte-identity check.

---

## Lessons

*(Fill in after the package is done.)*
