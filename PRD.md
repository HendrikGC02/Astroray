# Astroray Rendering Bug Fixes — PRD

## Overview

Three confirmed rendering bugs exist in the Astroray path tracer.
This PRD specifies the root cause, exact fix, and test verification
for each. All fixes are surgical single-line or few-line changes.

---

## Bug 1 — Upside-down images (Python module and standalone)

### Symptom
Images returned by both the Python bindings and the standalone
renderer are vertically flipped. Spheres that sit on the floor appear
at the top; the ceiling light appears at the bottom.

### Root cause
`include/raytracer.h` render loop (around line 804):
```cpp
float v = (y + dist(gen)) / (cam.height - 1);
```
`y = 0` maps to `v = 0` which is the `lowerLeft` of the viewport
(bottom of the scene). The pixel is stored at `cam.pixels[0*width+x]`.
NumPy and image viewers put row 0 at the *top* of the display, so
the scene is inverted.

The standalone PNG/PPM writer (`apps/main.cpp`) tries to compensate
by iterating `y` from `height-1` down to `0`, but this double-flip
causes a mismatch in orientation. The fix is to correct the root
cause in the render loop, then remove the compensating flip in the
writers.

### Fix

**File: `include/raytracer.h`** — inside the per-pixel sampling loop:
```cpp
// BEFORE
float v = (y + dist(gen)) / (cam.height - 1);

// AFTER — flip so row 0 = top of scene
float v = 1.0f - (y + dist(gen)) / (cam.height - 1);
```

**File: `apps/main.cpp`** — both `writePPM` and `writePNG`, change
the y-loop to forward order:
```cpp
// BEFORE (old compensating flip)
for (int y = cam.height - 1; y >= 0; --y)

// AFTER (no flip needed — render loop now stores top-to-bottom)
for (int y = 0; y < cam.height; ++y)
```

The Python module (`module/blender_module.cpp`) already copies pixels
in forward order and requires **no change**.

### Test verification
Add to `test_cornell_box` (Python) and `test_cornell_box_scene`
(standalone):
```python
# Ceiling light is in the top half — top rows must be brighter
top_mean = np.mean(pixels[:pixels.shape[0]//4, :, :])
bot_mean = np.mean(pixels[-pixels.shape[0]//4:, :, :])
assert top_mean > bot_mean, \
    "Image appears upside-down (light should illuminate the top half)"
```

---

## Bug 2 — Perfectly smooth metal renders black

### Symptom
`Metal` material with `roughness < 0.01` (mirror-like) produces a
completely black sphere. Visible in `test_material_comparison.png`
("Metal Smooth" tile) and `test_disney_brdf_grid.png` ("Metal Smooth"
tile).

### Root cause
`include/raytracer.h`, `Metal::eval()`, around line 208:
```cpp
Vec3 perfectRefl = wo - rec.normal * (2 * wo.dot(rec.normal));
```
This computes `wo − 2(wo·n)n = −wi`: the **negative** of the correct
reflection direction. The deviation `(wi − perfectRefl).length()`
therefore equals `|wi − (−wi)| = 2`, which is far above the 0.1
threshold, so `eval()` always returns `Vec3(0)`.

The `sample()` function (around line 232) *correctly* computes:
```cpp
s.wi = rec.normal * (2 * wo.dot(rec.normal)) - wo;
```
but `eval()` has the negated form, causing every evaluation to return
black.

### Fix
**File: `include/raytracer.h`**, `Metal::eval()`:
```cpp
// BEFORE (wrong sign — computes −wi)
Vec3 perfectRefl = wo - rec.normal * (2 * wo.dot(rec.normal));

// AFTER (correct reflection: 2(wo·n)n − wo)
Vec3 perfectRefl = rec.normal * (2 * wo.dot(rec.normal)) - wo;
```

### Test verification
Add a dedicated test or extend `test_metal_render`:
```python
# Metal with roughness=0 (mirror) must NOT be black
mat = r.create_material('metal', [0.9, 0.9, 0.9], {'roughness': 0.0})
r.add_sphere([0, -0.5, 0], 1.0, mat)
# ...render...
assert np.mean(pixels) > 0.10, \
    "Smooth metal rendered black — Metal::eval reflection sign bug"
```
Also assert in `test_material_comparison_grid` that the "Metal Smooth"
tile mean brightness exceeds 0.10.

---

## Bug 3 — Middle sphere overexposure / glow (double-cosine in NEE)

### Symptom
In the Cornell box scene the Disney BRDF sphere (and to a lesser
extent all diffuse surfaces) appear severely overexposed. Direct
illumination is systematically too large.

### Root cause
`include/raytracer.h`, `Renderer::sampleDirect()`, around line 714
(NEE / light-sampling branch):
```cpp
direct += f * ls.emission * std::abs(wi.dot(rec.normal)) * wt / (ls.pdf + 0.001f);
```
`f` is the return value of `rec.material->eval(rec, wo, wi)`.
**Every material's `eval()` already multiplies by `NdotL`** (the
cosine factor). Multiplying by `std::abs(wi.dot(rec.normal))` a
second time double-counts the cosine, making the NEE contribution
scale as `NdotL²` instead of the physically correct `NdotL`.

For the bright Cornell box light (intensity 15) this causes
systematic ≈2× overexposure at direct angles. The effect is most
visible on the Disney BRDF sphere because its high-frequency specular
lobe makes it the brightest surface in the scene.

The BSDF-sampling branch of `sampleDirect` (around line 724)
correctly omits the extra cosine factor:
```cpp
direct += bs.f * Le * powerHeuristic(bs.pdf, lightPdf) / (bs.pdf + 0.001f);
```
This confirms the convention: `eval()` returns `brdf × cos(θ)`.

### Fix
**File: `include/raytracer.h`**, `Renderer::sampleDirect()`:
```cpp
// BEFORE (double-cosine — NdotL applied twice)
direct += f * ls.emission * std::abs(wi.dot(rec.normal)) * wt / (ls.pdf + 0.001f);

// AFTER (eval already contains NdotL — remove the redundant factor)
direct += f * ls.emission * wt / (ls.pdf + 0.001f);
```

### Test verification
Add to `test_cornell_box`:
```python
# No region of the Cornell box should be blown out
overall_mean = float(np.mean(pixels))
assert overall_mean < 0.75, \
    f"Cornell box overexposed (mean={overall_mean:.3f}); likely double-cosine in NEE"
```

---

## Acceptance Criteria (all bugs)

After applying all three fixes and rebuilding:

1. `pytest tests/ -x -q` passes all existing 28 tests.
2. New orientation assertion passes: top 25 % of Cornell box image
   is brighter than bottom 25 %.
3. New metal assertion passes: Metal Smooth mean > 0.10.
4. New overexposure assertion passes: Cornell box mean < 0.75.
5. Visual inspection of saved PNGs in `test_results/` confirms:
   - Spheres sit on the floor, light rectangle visible at top.
   - "Metal Smooth" tile is silver/mirror-like, not black.
   - Cornell box has balanced, non-blown-out illumination.

---

## Files to Modify

| File | What changes |
|------|-------------|
| `include/raytracer.h` | 3 edits: flip `v` in render loop; fix `Metal::eval` sign; remove extra cosine in `sampleDirect` |
| `apps/main.cpp` | 2 edits: change y-loop direction in `writePPM` and `writePNG` |
| `tests/test_python_bindings.py` | Add orientation + overexposure + metal brightness assertions |
| `tests/test_standalone_renderer.py` | Add orientation assertion to `test_cornell_box_scene` |

No changes required to `module/blender_module.cpp` or
`include/advanced_features.h`.

---

## Non-goals

- Do not change the Disney BRDF energy-conservation reductions
  (0.8× Fresnel, 0.5× sheen/clearcoat) — these are intentional.
- Do not change the throughput firefly clamp (10×).
- Do not refactor the material interface or rendering pipeline
  beyond the four targeted file edits listed above.
- Do not modify test files except to add the new assertions listed
  in each bug's "Test verification" section.
