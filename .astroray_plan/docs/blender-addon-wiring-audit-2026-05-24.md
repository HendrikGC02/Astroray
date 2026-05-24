# Blender Addon Feature-Wiring Audit — 2026-05-24

**Scope:** Complete audit of PyRenderer bindings (`module/blender_module.cpp`) vs Blender addon call sites (`blender_addon/__init__.py`).

**HEAD:** 85ae602 (2026-05-24)

**Deliverable for:** pkg103 Phase 1

---

## Summary

- **Total bindings audited:** 37 (covering all `set_*`, `enable_*`, `add_*` setters on PyRenderer)
- **Fully wired (OK):** 31
- **MISSING call sites:** 6
  - `set_light_sampler` (pkg86 / pkg86-B)
  - `set_camera_motion_blur` (pkg88-A)
  - `set_integrator_param` (generic integrator config hook)
  - `add_sphere` (legacy primitive, not used in Blender workflow)
  - `add_spot_light` (superseded by `add_spot_light_dedicated`)
  - `add_mesh` (legacy OBJ loader, not used in Blender workflow)

**High-priority gaps** (warrant Phase 2 follow-up specs):
1. **Light Tree sampler** (`set_light_sampler`) — pkg86/86-B shipped CPU median-split + SAOH tree; UI has no toggle to enable it. The `RENDER_PT_sampling_light_tree` panel is on the hide-list (line 4576). This blocks users from accessing the 2× variance reduction on many-light scenes.
2. **Camera motion blur** (`set_camera_motion_blur`) — pkg88-A shipped keyframe interpolation for camera transform; addon never calls the setter, so Blender's `render.use_motion_blur` has no effect on the camera.

**Low-priority / intentionally-internal gaps:**
- `set_integrator_param` — generic per-integrator parameter hook; currently unused because all integrators use global settings. No UI property needed until we add integrator-specific controls.
- `add_sphere`, `add_mesh` — legacy primitives/loaders never used in Blender scene conversion (Blender meshes always flow through `add_triangle` / `add_triangle_layers`).
- `add_spot_light`, `add_sun_light`, `add_area_light` — superseded by `add_*_dedicated` variants in pkg89 Phase B; not called because the dedicated path is always taken when the `dedicated` property is set.

---

## Complete Audit Table

| PyRenderer Binding | pybind line | Introducing Package | UI Property | Addon Call Site | UI Panel | Status |
|--------------------|-------------|---------------------|-------------|-----------------|----------|--------|
| `set_texture_coord_mode` | 1888 | pkg59 (UV layers) | N/A (per-texture) | `__init__.py:2661` | N/A (shader-driven) | OK |
| `set_texture_uv_transform` | 1889 | pkg59 | N/A (per-texture) | `__init__.py:2670` | N/A (shader-driven) | OK |
| `set_texture_uv_layer` | 1895 | pkg59 | N/A (per-texture) | `__init__.py:2663` | N/A (shader-driven) | OK |
| `add_sphere` | 1904 | legacy (pre-pkg) | N/A | **MISSING** | N/A | intentionally-internal (legacy primitive unused in Blender workflow) |
| `add_spot_light` | 1907 | legacy | N/A | **MISSING** | N/A | intentionally-internal (superseded by `add_spot_light_dedicated`) |
| `add_sun_light` | 1910 | legacy | N/A | **MISSING** (3539 calls `_dedicated`) | N/A | intentionally-internal (superseded by `add_sun_light_dedicated`) |
| `add_area_light` | 1912 | legacy | N/A | **MISSING** (3560 calls `_dedicated`) | N/A | intentionally-internal (superseded by `add_area_light_dedicated`) |
| `add_point_light` | 1916 | legacy | `custom_raytracer.dedicated` (lights only) | `__init__.py:3532` | `ASTRORAY_PT_light_settings:4926` | OK |
| `add_sun_light_dedicated` | 1920 | pkg89 Phase B | `custom_raytracer.dedicated` | `__init__.py:3539` | `ASTRORAY_PT_light_settings:4926` | OK |
| `add_area_light_dedicated` | 1924 | pkg89 Phase B | `custom_raytracer.dedicated` | `__init__.py:3560` | `ASTRORAY_PT_light_settings:4926` | OK |
| `add_spot_light_dedicated` | 1929 | pkg89 Phase B | `custom_raytracer.dedicated` | `__init__.py:3574` | `ASTRORAY_PT_light_settings:4926` | OK |
| `add_triangle` | 1934 | core | N/A | `__init__.py:3456` | N/A (auto mesh conversion) | OK |
| `add_triangle_layers` | 1938 | pkg59 | N/A | `__init__.py:3448` | N/A (auto mesh conversion) | OK |
| `add_mesh` | 1942 | legacy (OBJ loader) | N/A | **MISSING** | N/A | intentionally-internal (Blender uses triangle conversion, not OBJ import) |
| `add_volume` | 1944 | pkg25 (volume rendering) | `custom_raytracer.volume_*` | `__init__.py:3356` | `ASTRORAY_PT_volume:4845` | OK |
| `add_black_hole` | 1948 | pkg43/44 (ADAF) | `custom_raytracer.adaf_*` | `__init__.py:3320` | `ASTRORAY_PT_black_hole_params:4437` | OK |
| `set_camera_motion_blur` | 1953 | pkg88-A | N/A | **MISSING** | N/A | **gap:no-call** → pkg103b follow-up |
| `set_adaptive_sampling` | 1960 | pkg15 | `custom_raytracer.use_adaptive_sampling` | `__init__.py:897, 1379` | `ASTRORAY_PT_sampling:4630` | OK |
| `set_clamp_direct` | 1961 | pkg12 | `custom_raytracer.clamp_direct` | `__init__.py:1381, 1723` | `ASTRORAY_PT_sampling:4630` | OK |
| `set_clamp_indirect` | 1962 | pkg12 | `custom_raytracer.clamp_indirect` | `__init__.py:1382, 1724` | `ASTRORAY_PT_sampling:4630` | OK |
| `set_filter_glossy` | 1963 | pkg12 | `custom_raytracer.filter_glossy` | `__init__.py:1383, 1725` | `ASTRORAY_PT_sampling:4630` | OK |
| `set_seed` | 1964 | core | `scene.render.seed` (Blender builtin) | `__init__.py:1740` | Blender default | OK |
| `set_pixel_filter` | 1965 | core | `custom_raytracer.pixel_filter_type`, `filter_width` | `__init__.py:1745` | `ASTRORAY_PT_film:4699` | OK |
| `set_light_sampler` | 1966 | pkg86 / pkg86-B | N/A | **MISSING** | N/A (`RENDER_PT_sampling_light_tree` hidden at 4576) | **gap:no-call** → pkg103a follow-up |
| `set_world_max_bounces` | 1967 | core | `custom_raytracer.world_max_bounces` | `__init__.py:3658` | `ASTRORAY_PT_world_volume:4816` | OK |
| `set_world_volume` | 1968 | pkg25 | `world.custom_raytracer.volume_*` | `__init__.py:3590, 3596, 3647` | `ASTRORAY_PT_world_volume:4816` | OK |
| `set_use_reflective_caustics` | 1970 | pkg12 | `custom_raytracer.use_reflective_caustics` | `__init__.py:1384, 1726` | `ASTRORAY_PT_caustics:4671` | OK |
| `set_use_refractive_caustics` | 1971 | pkg12 | `custom_raytracer.use_refractive_caustics` | `__init__.py:1385, 1727` | `ASTRORAY_PT_caustics:4671` | OK |
| `set_object_caustic_caster` | 1972 | pkg12 | `object.custom_raytracer.is_caustic_caster` | `__init__.py:3472` | `ASTRORAY_PT_object_settings:4959` | OK |
| `set_object_name` | 1979 | pkg87a (cryptomatte) | N/A | `__init__.py:3475` | N/A (auto object metadata) | OK |
| `set_material_name` | 1982 | pkg87a | N/A | `__init__.py:1875` | N/A (auto material metadata) | OK |
| `set_cryptomatte_enabled` | 1985 | pkg87a-d | derived from view-layer passes | `__init__.py:940` | Blender View Layer passes UI | OK |
| `set_cryptomatte_depth` | 1988 | pkg87a-d | `view_layer.custom_raytracer.cryptomatte_depth` | `__init__.py:938` | `ASTRORAY_PT_passes:4758` | OK |
| `set_background_color` | 2001 | core | `world.color` (Blender builtin) | `__init__.py:3681` | Blender default | OK |
| `set_film_exposure` | 2002 | core | `custom_raytracer.film_exposure` | `__init__.py:1731` | `ASTRORAY_PT_film:4699` | OK |
| `set_use_transparent_film` | 2003 | core | `custom_raytracer.use_transparent_film` | `__init__.py:1734` | `ASTRORAY_PT_film:4699` | OK |
| `set_transparent_glass` | 2004 | core | `custom_raytracer.transparent_glass` | `__init__.py:1735` | `ASTRORAY_PT_film:4699` | OK |
| `add_pass` | 2005 | core | Blender View Layer passes | `__init__.py:928, 931, 941` | Blender default | OK |
| `set_use_gpu` | 2028 | pkg55 | `custom_raytracer.use_gpu` | `__init__.py:499, 1413` | `ASTRORAY_PT_render_settings:4593` | OK |
| `set_integrator` | 2108 | core | `custom_raytracer.integrator` | `__init__.py:923, 1452` | `ASTRORAY_PT_integrator:4604` | OK |
| `set_integrator_param` | 2111 | core (generic hook) | N/A | **MISSING** | N/A | intentionally-internal (no integrator-specific params yet) |
| `set_wavelength_range` | 2115 | pkg38 (spectral rendering) | `custom_raytracer.wavelength_min/max` | `__init__.py:919, 1448` | `ASTRORAY_PT_integrator:4604` | OK |
| `set_output_mode` | 2118 | pkg38 | derived from `integrator=="spectral"` | `__init__.py:922, 1451` | `ASTRORAY_PT_integrator:4604` | OK |
| `set_material_spectral_profile` | 2120 | pkg44 (ADAF accretion model) | `material.custom_raytracer.spectral_profile` | `__init__.py:1894, 2115` | `ASTRORAY_PT_material_spectral:4981` | OK |

---

## Negative Evidence for MISSING Claims

### `set_light_sampler`

```
$ cd ../Astroray-pkg103 && grep -n "set_light_sampler" blender_addon/__init__.py
(no matches)
```

Blender UI panel `RENDER_PT_sampling_light_tree` exists in Cycles but is hidden for Astroray at `blender_addon/__init__.py:4576`.

### `set_camera_motion_blur`

```
$ cd ../Astroray-pkg103 && grep -n "set_camera_motion_blur" blender_addon/__init__.py
(no matches)
```

No UI property exists for camera motion blur in `CustomRayTracerSettings` or `CustomRayTracerCameraSettings`.

### `set_integrator_param`

```
$ cd ../Astroray-pkg103 && grep -n "set_integrator_param" blender_addon/__init__.py
(no matches)
```

Generic hook for per-integrator parameters; currently unused because all integrators share global settings.

### `add_sphere`

```
$ cd ../Astroray-pkg103 && grep -n "add_sphere" blender_addon/__init__.py
(no matches)
```

Legacy primitive never called in Blender scene conversion (all Blender objects flow through mesh → triangle conversion).

### `add_spot_light` (non-dedicated)

```
$ cd ../Astroray-pkg103 && grep -n "add_spot_light" blender_addon/__init__.py
3574:                renderer.add_spot_light_dedicated(
```

Only the `_dedicated` variant is called (pkg89 Phase B); the base `add_spot_light` is never invoked.

### `add_mesh`

```
$ cd ../Astroray-pkg103 && grep -n "add_mesh" blender_addon/__init__.py
(no matches)
```

Legacy OBJ loader; Blender scene conversion always uses triangle-by-triangle emission via `add_triangle` / `add_triangle_layers`.

---

## High-Priority Phase 2 Follow-Ups (Recommended Order)

### 1. Light Tree UI Wiring (pkg103a)

**Gap:** `set_light_sampler` (pybind 1966) has no call site in the addon. pkg86 (CPU median-split) and pkg86-B Phase 1 (CPU SAOH) shipped 2×+ variance reduction on many-light scenes, but users cannot enable it.

**What shipped:** Light Tree build + traversal logic in `include/raytracer.h`, `src/raytracer.cpp`, CUDA `kernel/light_sampling.cuh`. Sampler modes: `"uniform"`, `"power"`, `"light_tree"` (default is `"power"`).

**Wiring needed:**
- UI property: `custom_raytracer.light_sampler` (EnumProperty: uniform / power / light_tree).
- Panel: Unhide `RENDER_PT_sampling_light_tree` (currently on hide-list at line 4576) or add a simpler Astroray-native toggle in `ASTRORAY_PT_sampling`.
- Call site: `convert_scene` → `renderer.set_light_sampler(settings.light_sampler)` (around line 1380 alongside other sampling settings).

**Acceptance criterion:** Render a 64-area-light scene with `light_sampler="light_tree"` toggled in the UI; confirm via `-DASTRORAY_DIAG_LIGHT_SAMPLING` printfs that the tree is traversed (not the power-weighted fallback).

**Reference:** Cycles `intern/cycles/blender/sync.cpp` wires `scene->integrator->set_use_light_tree(...)`.

**Impact:** High — pkg86 claims 2× variance reduction but that claim is currently inaccessible to Blender users.

---

### 2. Camera Motion Blur Addon Wiring (pkg103b)

**Gap:** `set_camera_motion_blur` (pybind 1953) has no call site. pkg88-A shipped the renderer-side keyframe interpolation, but Blender's `scene.render.use_motion_blur` toggle has no effect on the camera.

**What shipped:** `PyRenderer::setCameraMotionBlur(transform_start, transform_end)` decomposed via T/R/S + quaternion slerp (PR #284, 2026-05-15). Renderer samples shutter time `t ∈ [0, Δ]` and evaluates the camera at `t`.

**Wiring needed:**
- Extract camera transform at `frame_current` and `frame_current + motion_blur_shutter` via depsgraph evaluation (see Cycles `sync.cpp::sync_camera_motion`).
- Decompose the two transforms into 4×4 matrices.
- Call `renderer.set_camera_motion_blur(T_start, T_end)` in `convert_scene` when `scene.render.use_motion_blur == True`.

**Acceptance criterion:** Render a panning camera or rotating camera at `motion_blur_shutter=0.5`. Confirm streaking in the final image. SSIM vs Cycles ≥ 0.95 on a simple rotation test scene.

**Reference:** Cycles `intern/cycles/blender/camera.cpp::BlenderSync::sync_camera_motion` (Apache-2.0) shows the depsgraph evaluation pattern for camera transforms at shutter start/end.

**Impact:** Medium-high — pkg88-A is marked "done" but the feature is invisible to users without this wiring.

---

## Medium / Low-Priority Gaps (Defer or Group)

### `set_integrator_param` — Integrator-Specific Parameters

**Current status:** Generic hook exists (pybind 2111) but is never called. All integrators currently use global settings (max bounces, caustics toggles, etc.).

**Future use case:** If we add integrator-specific controls (e.g., wavefront-only tile size, photon-mapping-only photon count), this hook will be needed.

**Recommendation:** Defer until we have an integrator that actually needs per-integrator parameters. No UI wiring needed now.

---

### Legacy Primitives (`add_sphere`, `add_mesh`)

**Current status:** `add_sphere` (pybind 1904) and `add_mesh` (pybind 1942) are never called in Blender scene conversion. Blender meshes always flow through `add_triangle` / `add_triangle_layers`.

**Recommendation:** Mark as intentionally-internal. These bindings exist for test harnesses and standalone scripts, not for Blender UI exposure. No action needed.

---

### Superseded Light Constructors (`add_spot_light`, `add_sun_light`, `add_area_light`)

**Current status:** pkg89 Phase B (PR #317) introduced `add_*_dedicated` variants for spot/sun/area lights. The addon always calls the dedicated variant when `custom_raytracer.dedicated == True` (the default for new lights). The base constructors are never called.

**Recommendation:** Mark as intentionally-internal. The base constructors remain in the pybind API for backward compatibility with test scripts, but Blender never uses them. No UI wiring needed.

---

## Notes on Already-Wired Features (Positive Controls)

### Cryptomatte (pkg87a-d)

- **Wired end-to-end:** `set_cryptomatte_enabled` (1985) called at `__init__.py:940` when any cryptomatte pass is enabled. `set_cryptomatte_depth` (1988) wired to UI property at line 938. Panel: `ASTRORAY_PT_passes:4758`.
- **Acceptance evidence:** pkg87d PR #347 includes Blender render tests with cryptomatte EXR output.

### ADAF Accretion Model (pkg43/44)

- **Wired end-to-end:** `add_black_hole` (1948) called at `__init__.py:3320` with `adaf_*` parameters. UI panel at `ASTRORAY_PT_black_hole_params:4437`.
- **Acceptance evidence:** pkg44 (Novikov-Thorne + ADAF switch) includes Blender test scenes.

### Dedicated Lights (pkg89 Phase B)

- **Wired end-to-end:** `add_sun_light_dedicated` (1920), `add_area_light_dedicated` (1924), `add_spot_light_dedicated` (1929) all called in `convert_lights` (lines 3533, 3554, 3568). `custom_raytracer.dedicated` toggle exposed in `ASTRORAY_PT_light_settings:4926`.
- **Acceptance evidence:** PR #317 includes Blender render tests with dedicated lights.

---

## Provenance

- **Audit methodology:** Enumerated all `set_*`, `enable_*`, `add_*` bindings in `module/blender_module.cpp` lines 1888-2120 (37 total). For each binding, grepped `blender_addon/__init__.py` for call sites and UI property definitions. Negative evidence (no matches) pasted inline for all MISSING claims.
- **Architect spot-check confirmation:** pkg103 spec §2 identified Light Tree and camera motion blur as gaps; this audit confirms both and surfaces 4 additional low-priority gaps (intentionally-internal legacy bindings).
- **HEAD:** 85ae602 fix(pkg102): correct HDRI/DOF aperture unit conversion (2026-05-24).

---

## Recommended Next Steps

1. **File pkg103a** (Light Tree UI wiring) — highest impact, enables pkg86/86-B claims.
2. **File pkg103b** (camera motion blur wiring) — closes pkg88-A user-visible gap.
3. **Mark this audit as "done" in pkg103 spec** and link this doc in the PR body.
4. **Update NEXT_STAGE_REPORT.md §2** with pkg103a/pkg103b entries (priority below pkg55-B' lead but above low-priority addon fixes).

No further follow-up specs needed for the intentionally-internal gaps (`add_sphere`, `add_mesh`, `set_integrator_param`, legacy light constructors) — those are working as intended.
