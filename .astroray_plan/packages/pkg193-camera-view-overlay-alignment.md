# pkg193 — Camera-view overlay vs preview-render misalignment

**Pillar:** 5 / integration-first
**Track:** A
**Status:** open (filed 2026-08-12 from owner hands-on addon feedback —
memory [[owner-addon-feedback-2026-08-12]], finding #4)
**Estimated effort:** M

**Depends on:** none hard; isolated to the viewport camera translation
(`_setup_viewport_camera` / `_apply_camera`). Independent of pkg191/pkg192.

---

## Symptom (owner, first-hand)

In **camera view** (numpad 0), Blender's GUI overlays — the selected-object
outline / wireframe — "don't exactly line up with the preview render. Close but
not exact." A small, consistent projection offset between where Blender draws the
overlay and where Astroray renders the geometry. This also undermines
**final-render compositing trust** (an F12 render that is a few px off from the
viewport framing composites wrong).

---

## MANDATORY FIRST STEP — reproduce on a freshly built current addon

Dated-addon caveat ([[owner-addon-feedback-2026-08-12]]). Before any change:
build addon `.pyd` against current `main`, verify mtime/`__file__`
([[stale_pyd_locations]]), stage into Blender 5.1
([[blender-5-1-installed-locally]], [[addon-packaging-file-list]]), and confirm
the misalignment still reproduces. A prior "BUG-08" pass (see below) already
touched this exact code; verify what its state is on current `main` before
attributing a new bug.

---

## Where the camera translation lives (verified line refs, current `main`)

`blender_addon/__init__.py`:

- `_setup_viewport_camera` (`__init__.py:1589-1655`) is the viewport camera
  builder. Two branches:
  - **CAMERA view** (`__init__.py:1605-1613`): applies `view_camera_zoom` via
    `_camera_view_zoom_scale` (`__init__.py:1578-1587`) and passes
    `view_camera_offset` as `viewport_shift` into `_apply_camera`.
  - **PERSP/ORTHO** (`__init__.py:1615-1655`): derives vfov from
    `rv3d.window_matrix[1][1]`.
- `_apply_camera` (`__init__.py:1877-1935+`) builds lookFrom/lookAt/vup from
  `matrix_world` and, when `rv3d` is present, sets
  **`vfov = 2·atan(1/window_matrix[1][1])`** (`__init__.py:1916-1920`) — a
  **symmetric-frustum** extraction. It then passes a scalar `vfov`, `aspect`,
  and an image-plane `shift` to the C++ `renderer.setup_camera(...)`
  (final call analogous to `__init__.py:1654`).
- `_compute_vfov_degrees` (`__init__.py:1848-1875`) is the datablock fallback
  (sensor_fit HORIZONTAL/VERTICAL/AUTO → vfov), used for F12/rv3d-absent.

### The prime hypothesis — asymmetric frustum / principal point dropped

Blender's camera-view `window_matrix` is generally an **off-center (asymmetric)
frustum**. The principal point shifts away from image center due to:
- camera `shift_x` / `shift_y` (lens shift),
- `view_camera_offset` (CAMERA-view pan) and `view_camera_zoom`,
- the **sensor-fit letterboxing**: when the render aspect ≠ the viewport region
  aspect, Blender fits the camera frame inside the region (the passepartout),
  which offsets/rescales the projected frame.

The GUI overlay is drawn with Blender's **exact** `window_matrix` (off-center
terms `window_matrix[2][0]`, `window_matrix[2][1]` and the top/bottom/left/right
asymmetry included). But `_apply_camera` reads **only `[1][1]`** and reduces the
projection to a **symmetric vfov + a single shift scalar** (`__init__.py:1916-1920`).
Any asymmetry Blender has that isn't captured by that one shift term becomes a
**constant pixel offset** — exactly the "close but not exact" the owner sees.
The most likely concrete culprit is the **film-fit / region-vs-render aspect**
mismatch (sensor_fit AUTO + a viewport region whose aspect differs from the
render output aspect), followed by lens-shift double-counting between
`viewport_shift` and any datablock `shift_x/shift_y`.

Secondary: the C++ `setup_camera` may only accept a symmetric vfov+aspect(+shift)
and be **structurally unable** to represent an arbitrary asymmetric frustum. If
so, the fix is to extract the full frustum extents (l/r/t/b) from
`window_matrix` and either (a) extend `setup_camera` to take asymmetric extents,
or (b) compute the exact symmetric-vfov-plus-shift that reproduces Blender's
frame for the common (aspect-mismatch, lens-shift) cases. Decide by measurement.

---

## Diagnosis-first — reproduce → MEASURE → localize → fix

### Reproduce with a quantitative measurement (not eyeballing)
Build a **wireframe-aligned test scene**: a single axis-aligned cube (or a quad
with known-UV corners) centered in camera view, on a plain background. Render the
Astroray preview to an image and, in the same Blender state, capture the camera
overlay / project the cube's world-space corners through Blender's
`window_matrix @ view_matrix` to expected pixel coords. **Measure the pixel
offset** (and any scale/aspect error) between the projected corners and the
rendered cube edges. This must be a repeatable number, headlessly if possible
(`bpy_extras.object_utils.world_to_camera_view` or an explicit
`window_matrix @ view_matrix` projection gives the reference pixel coords without
a GUI). Record offset in px at several conditions:
- render aspect == region aspect vs render aspect != region aspect (isolates
  film-fit);
- `shift_x/shift_y` = 0 vs nonzero (isolates lens shift);
- `view_camera_zoom`/`offset` = 0 vs nonzero (isolates viewport zoom/pan);
- sensor_fit AUTO vs HORIZONTAL vs VERTICAL.

The condition(s) where the offset appears pin the cause.

### Localize
Attribute the measured offset to one of: (i) aspect/film-fit fit-inside-region
scaling, (ii) principal-point / asymmetric-frustum terms dropped by the
`[1][1]`-only vfov extraction, (iii) lens-shift double-count or sign error
between `viewport_shift` and datablock `shift`, (iv) a half-pixel / pixel-center
convention mismatch between the C++ film sampling and Blender's. Cite the Cycles
reference for the correct fit math: `intern/cycles/blender/camera.cpp`
`blender_camera_sync` / `blender_camera_border` / the `sensor_fit` +
`view_camera_zoom`/`offset` handling (Apache-2.0) — this is the canonical
"how Blender maps camera → film window" and the addon should match it
([[cycles-parity]] discipline; do not invent the fit math, borrow it,
per the cite-algorithm rule).

### Fix
Correct the localized term so projected overlay corners and rendered edges agree
to sub-pixel (or ≤1 px) on the test scene, for all four condition axes above.
Prefer reproducing Blender's exact frustum (full l/r/t/b extents from
`window_matrix`) over patching a single shift scalar, IF the C++ camera can
accept it; otherwise document precisely which asymmetry cases are covered and
which remain approximated, and why.

---

## Acceptance criteria

- [ ] **Reproduced on a freshly built current-`main` addon** with a
      **quantitative pixel-offset measurement** (not eyeballing) BEFORE any fix;
      dated-addon caveat discharged in writing.
- [ ] The offset is attributed to a specific cause (film-fit / principal-point /
      lens-shift / pixel-center convention) with the per-condition measurement
      table recorded in Lessons.
- [ ] After the fix, a **wireframe-aligned cube's** projected corners
      (Blender `window_matrix @ view_matrix`) and the Astroray-rendered edges
      agree within **≤1 px** across the four condition axes (aspect-match/mismatch,
      lens-shift on/off, viewport zoom/pan on/off, sensor_fit AUTO/H/V), gated by
      a headless test.
- [ ] The camera-view overlay visually lines up with the preview render —
      **owner-visual note** with a before/after capture.
- [ ] **F12 final render** framing is verified consistent with the corrected
      viewport framing (the compositing-trust angle) — same cube, F12 vs
      viewport, corners agree.

## Hard non-goals

- **No orthographic-camera projection rewrite.** `_compute_vfov_degrees` returns
  a placeholder 40° for non-PERSP (`__init__.py:1856-1860`); ORTHO alignment is
  a separate, pre-existing gap — note it, do not fix it here unless the test
  scene is PERSP-only and ORTHO is out of the measured conditions.
- **No DoF / bokeh alignment work** — aperture is orthogonal to the framing
  offset.
- **No viewport-perf or progressive-loop changes** (pkg191/pkg192 own those);
  this package changes only the camera projection/translation math.
- **No unilateral C++ `setup_camera` ABI change** without an ABI-reachability
  check ([[cpp-abi-guard]], addon target reachable) — if asymmetric extents
  require a signature change, sweep all call sites (F12 `render`, tests, the
  PERSP branch) in the same change.
