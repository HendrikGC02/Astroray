# Astroray Phase 1: HDRI Environment Map Implementation

## Overview

Replace the hardcoded sky gradient with proper HDR environment map loading, importance sampling, and MIS-weighted integration into the existing NEE pipeline. Also support a solid-color background fallback when no HDRI is loaded.

**Files to modify** (in order):
1. `include/raytracer.h` — Add `EnvironmentMap` class, modify `LightList`, `Renderer`, `pathTrace`, `sampleDirect`
2. `module/blender_module.cpp` — Add `load_environment_map()` and `set_background_color()` bindings
3. `blender_addon/__init__.py` — Rewrite `setup_world()` to detect HDRI vs solid background
4. `apps/main.cpp` — Add `--envmap` CLI flag
5. `tests/test_python_bindings.py` — Add environment map tests

**New files:**
- `include/stb_image.h` — Download from https://github.com/nothings/stb (single header, already have stb_image_write.h)

---

## Pre-requisite: Manual Setup (Human task, not Cline)

Before starting Cline tasks, manually:
1. Download `stb_image.h` from https://raw.githubusercontent.com/nothings/stb/master/stb_image.h
2. Place it in `include/stb_image.h`
3. Download a test HDRI (e.g., from polyhaven.com — any 2K .hdr file) and place it in `samples/test_env.hdr`
4. Commit these as a prep commit

---

## Task 1: EnvironmentMap class — loading and lookup

**Goal:** Create the `EnvironmentMap` class in `include/raytracer.h` that loads HDR files and supports direction-to-color lookup. No importance sampling yet.

**Location:** Add ABOVE the `LightList` class in `include/raytracer.h` (after the materials, before LightList).

**What to implement:**

```cpp
class EnvironmentMap {
    std::vector<float> data;     // RGB interleaved: data[3*(y*width+x) + channel]
    int width = 0, height = 0;
    float strength = 1.0f;       // radiance multiplier
    float rotation = 0.0f;       // horizontal rotation in radians

public:
    bool loaded() const { return !data.empty(); }

    bool load(const std::string& path, float str = 1.0f, float rot = 0.0f);
    Vec3 lookup(const Vec3& direction) const;
};
```

**Implementation details for `load()`:**
- Use `stbi_loadf()` with 3 channels (force RGB)
- Add `#define STB_IMAGE_IMPLEMENTATION` in a NEW file `include/stb_image_impl.cpp` — do NOT put the define in the header (it would cause multiple-definition errors since raytracer.h is included in multiple translation units). Alternative: add the define at the top of `apps/main.cpp` before `#include "stb_image.h"`, guarded by `#ifndef STB_IMAGE_IMPLEMENTATION`.
- Store raw float data, set width/height, store strength and rotation
- Print a status line: `printf("Loaded environment map: %s (%dx%d)\n", path.c_str(), width, height);`
- Free the stbi data after copying to the vector

**CRITICAL: stb_image.h include strategy.** Since raytracer.h is a header included by multiple .cpp files, do NOT put `#define STB_IMAGE_IMPLEMENTATION` in raytracer.h. Instead:
- In `raytracer.h`: just `#include "stb_image.h"` (declarations only)
- In `apps/main.cpp` (BEFORE any other includes): add `#define STB_IMAGE_IMPLEMENTATION` then `#include "stb_image.h"`
- In `module/blender_module.cpp` (BEFORE any other includes): add `#define STB_IMAGE_IMPLEMENTATION` — BUT only if NOT already defined. Safest: create a single file `src/stb_impl.cpp` containing only:
```cpp
#define STB_IMAGE_IMPLEMENTATION
#include "stb_image.h"
```
And add it to both CMake targets. This is the cleanest approach.

**Implementation details for `lookup()`:**
- Convert direction to equirectangular (u, v) coordinates:
  ```cpp
  float theta = std::acos(std::clamp(direction.y, -1.0f, 1.0f)); // polar, 0=up
  float phi = std::atan2(direction.z, direction.x);                // azimuthal
  phi += rotation;  // apply horizontal rotation
  float u = 0.5f + phi / (2.0f * M_PI);  // [0, 1]
  float v = theta / M_PI;                 // [0, 1]
  ```
- Clamp u to [0,1] after wrapping (u may exceed 1 due to rotation)
- Bilinear interpolation on the 4 nearest texels
- Return `pixel_color * strength`

**IMPORTANT coordinate convention:** In Astroray, Y is up (matching Blender). So `direction.y = 1` should map to the top of the equirectangular map (v=0), and `direction.y = -1` to the bottom (v=1). The mapping `theta = acos(direction.y)` gives theta=0 at pole (v=0) and theta=pi at south pole (v=1), which is correct.

**Acceptance criteria:**
- Compiles with no warnings
- `load()` returns true for a valid .hdr file, false for missing file
- `lookup(Vec3(0,1,0))` returns the top-center pixel × strength (zenith)
- `lookup(Vec3(0,-1,0))` returns the bottom-center pixel × strength (nadir)

**Estimated scope:** ~80 lines of C++ code.

---

## Task 2: Importance sampling — 2D CDF construction

**Goal:** Add CDF tables to `EnvironmentMap` for importance sampling proportional to luminance × sin(θ).

**Add these private members to EnvironmentMap:**

```cpp
std::vector<float> conditionalCdf;  // size: width * height (CDF per row)
std::vector<float> conditionalFunc; // size: width * height (un-normalized PDF per row)
std::vector<float> marginalCdf;     // size: height
std::vector<float> marginalFunc;    // size: height (row totals)
float totalPower = 0.0f;
```

**Add a private method `buildCdf()` called at the end of `load()`:**

Algorithm:
1. For each row v (0 to height-1):
   - Compute `sinTheta = sin(M_PI * (v + 0.5f) / height)`
   - For each column u: `func[v*width + u] = luminance(pixel) * sinTheta`
   - Build the conditional CDF for this row: cumulative sum, then normalize
   - Store the row's total (last CDF value before normalization) as `marginalFunc[v]`
2. Build the marginal CDF from `marginalFunc[]`: cumulative sum, normalize
3. Store `totalPower` = sum of all marginalFunc entries (used for PDF normalization)

**Use the existing `luminance()` function** already defined in raytracer.h:
```cpp
inline float luminance(const Vec3& c) { return 0.2126f*c.x + 0.7152f*c.y + 0.0722f*c.z; }
```

**CDF normalization convention:** The CDF array's last element should be 1.0f. Store the un-normalized total separately for PDF calculation.

**Acceptance criteria:**
- `marginalCdf[height-1]` == 1.0f (within floating point tolerance)
- Each row's `conditionalCdf[v*width + width-1]` == 1.0f
- `totalPower > 0` for any non-black HDRI

**Estimated scope:** ~50 lines.

---

## Task 3: sample() and pdf() methods

**Goal:** Add `sample()` to draw importance-sampled directions, and `pdf()` to evaluate the PDF for any direction.

**Add these public methods to EnvironmentMap:**

```cpp
struct EnvSample {
    Vec3 direction;
    Vec3 radiance;
    float pdf;
};

EnvSample sample(std::mt19937& gen) const;
float pdf(const Vec3& direction) const;
```

**`sample()` implementation:**
1. Draw two uniform random numbers ξ₁, ξ₂ ∈ [0,1)
2. Binary-search `marginalCdf` for ξ₁ → find row index `v`
3. Binary-search `conditionalCdf[v*width ... v*width+width-1]` for ξ₂ → find column `u`
4. Compute continuous (u_cont, v_cont) by linear interpolation within the found bin
5. Convert (u_cont, v_cont) to direction:
   ```cpp
   float theta = v_cont * M_PI;
   float phi = (u_cont - 0.5f) * 2.0f * M_PI - rotation;
   Vec3 dir(std::sin(theta)*std::cos(phi), std::cos(theta), std::sin(theta)*std::sin(phi));
   ```
6. Compute PDF in solid angle measure:
   ```cpp
   float sinTheta = std::sin(theta);
   if (sinTheta < 1e-6f) sinTheta = 1e-6f;  // avoid division by zero at poles
   float pdfUV = conditionalFunc[v*width + u] / (marginalFunc[v] + 1e-10f)
               * marginalFunc[v] / (totalPower + 1e-10f);
   // marginal pdf * conditional pdf in (u,v) space
   // Actually simpler: pdfUV = func_value / totalPower * width * height
   float mapPdf = conditionalFunc[v*width + u] * width * height / (totalPower + 1e-10f);
   float solidAnglePdf = mapPdf / (2.0f * M_PI * M_PI * sinTheta);
   ```
7. Look up radiance: `radiance = lookup(dir)`
8. Return `{dir, radiance, solidAnglePdf}`

**CRITICAL PDF formula:** The conversion from (u,v) PDF to solid-angle PDF is:
```
pdf_ω = pdf_uv / (2π² sin θ)
```
where `pdf_uv = f(u,v) / ∫∫f(u,v) du dv`. The simpler form:
```
pdf_ω = f(u,v) * width * height / (totalPower * 2π² sinθ)
```

**`pdf()` implementation:**
1. Convert direction to (u, v) via the same mapping as `lookup()`
2. Find integer texel (u_i, v_i)
3. Return `conditionalFunc[v_i*width + u_i] * width * height / (totalPower * 2*π² * sinTheta)`

**Use `std::lower_bound` for binary search** — it's fast and correct.

**Acceptance criteria:**
- Sampling directions cluster around bright regions of the HDRI
- `pdf(sample().direction)` approximately equals `sample().pdf` (self-consistency)
- PDF integrates to approximately 1 over the sphere (Monte Carlo test)

**Estimated scope:** ~70 lines.

---

## Task 4: Integrate EnvironmentMap into Renderer — background replacement

**Goal:** Replace the hardcoded sky gradient in `pathTrace()` with environment map lookup, AND add a solid-color fallback.

**Add to the `Renderer` class:**

```cpp
private:
    std::shared_ptr<EnvironmentMap> envMap;
    Vec3 backgroundColor = Vec3(-1);  // negative = use default sky gradient

public:
    void setEnvironmentMap(std::shared_ptr<EnvironmentMap> map) { envMap = map; }
    void setBackgroundColor(const Vec3& color) { backgroundColor = color; }
```

**Modify `pathTrace()`** — find the existing sky gradient code (the `if no hit` block):

```cpp
// CURRENT CODE (replace this):
if (!bvh->hit(ray, 0.001f, ...)) {
    float t = 0.5f * (ray.direction.normalized().y + 1.0f);
    color += throughput * (Vec3(1) * (1 - t) + Vec3(0.5f, 0.7f, 1.0f) * t) * 0.2f;
    break;
}

// NEW CODE:
if (!bvh->hit(ray, 0.001f, ...)) {
    Vec3 envColor;
    if (envMap && envMap->loaded()) {
        envColor = envMap->lookup(ray.direction.normalized());
    } else if (backgroundColor.x >= 0) {
        envColor = backgroundColor;
    } else {
        // Default sky gradient fallback
        float t = 0.5f * (ray.direction.normalized().y + 1.0f);
        envColor = (Vec3(1) * (1 - t) + Vec3(0.5f, 0.7f, 1.0f) * t) * 0.2f;
    }
    // Only add environment for camera rays or specular bounces (matches NEE convention)
    if (bounce == 0 || wasSpecular) {
        color += throughput * envColor;
    }
    break;
}
```

**IMPORTANT:** When an environment map is active AND NEE is sampling it, we must NOT double-count. The `if (bounce == 0 || wasSpecular)` guard prevents adding environment radiance on diffuse bounces where NEE already accounts for it. This exactly mirrors the emissive light handling that already exists in the code.

**Also modify the BSDF-sampling miss path in sampleDirect()** (Task 6 will handle this, but keep the architecture in mind).

**Also update `clear()`** to reset envMap and backgroundColor:
```cpp
void clear() {
    scene.clear(); bvh.reset(); lights = LightList();
    envMap.reset();
    backgroundColor = Vec3(-1);
}
```

**Acceptance criteria:**
- Without envmap: renders look identical to before (sky gradient)
- With `setBackgroundColor(Vec3(0))`: scene has black background
- With envmap loaded: scene is lit by the HDRI

**Estimated scope:** ~30 lines of changes.

---

## Task 5: Environment map NEE — light sampling strategy

**Goal:** Add environment map sampling to `sampleDirect()` with proper MIS weights, combining with existing area light NEE.

This is the most delicate task. The existing `sampleDirect()` samples area lights only. We need to add environment sampling as a second light strategy.

**Strategy: Stochastic light source selection.** Each NEE call randomly picks either the environment map OR area lights (probability based on estimated power), then samples that source. This keeps `sampleDirect()` to one shadow ray per call.

**Add to the Renderer class (private):**

```cpp
float envSelectProb() const {
    if (!envMap || !envMap->loaded()) return 0.0f;
    if (lights.empty()) return 1.0f;
    // Heuristic: environment gets 50% selection probability
    // (Could be refined based on envMap->totalPower vs lights total)
    return 0.5f;
}
```

**Modify `sampleDirect()`:**

```cpp
Vec3 sampleDirect(const HitRecord& rec, const Ray& ray, std::mt19937& gen) {
    if ((lights.empty() && (!envMap || !envMap->loaded())) || rec.isDelta) return Vec3(0);
    Vec3 wo = -ray.direction.normalized(), direct(0);
    std::uniform_real_distribution<float> dist01(0, 1);

    float pEnv = envSelectProb();
    bool sampleEnv = dist01(gen) < pEnv;

    if (sampleEnv && envMap && envMap->loaded()) {
        // === Environment map light sampling ===
        auto es = envMap->sample(gen);
        if (es.pdf > 0) {
            Vec3 wi = es.direction;
            HitRecord shadow;
            // Shadow ray: must NOT hit any geometry (ray escapes to infinity)
            if (!bvh->hit(Ray(rec.point, wi), 0.001f, 1e30f, shadow)) {
                Vec3 f = rec.material->eval(rec, wo, wi);
                float bsdfPdf = rec.material->pdf(rec, wo, wi);
                float combinedLightPdf = pEnv * es.pdf;
                float wt = powerHeuristic(combinedLightPdf, bsdfPdf);
                direct += f * es.radiance * wt / (combinedLightPdf + 0.001f);
            }
        }
    } else if (!lights.empty()) {
        // === Existing area light sampling (unchanged) ===
        float pArea = 1.0f - pEnv;
        LightSample ls = lights.sample(rec.point, gen);
        if (ls.pdf > 0) {
            Vec3 wi = (ls.position - rec.point).normalized();
            HitRecord shadow;
            if (!bvh->hit(Ray(rec.point, wi), 0.001f, ls.distance - 0.001f, shadow)) {
                Vec3 f = rec.material->eval(rec, wo, wi);
                float bsdfPdf = rec.material->pdf(rec, wo, wi);
                float combinedLightPdf = pArea * ls.pdf;
                float wt = powerHeuristic(combinedLightPdf, bsdfPdf);
                direct += f * ls.emission * wt / (combinedLightPdf + 0.001f);
            }
        }
    }

    // === BSDF sampling (check both area lights AND environment) ===
    BSDFSample bs = rec.material->sample(rec, wo, gen);
    if (bs.pdf > 0 && !bs.isDelta) {
        HitRecord bRec;
        if (bvh->hit(Ray(rec.point, bs.wi), 0.001f, 1e30f, bRec)) {
            // Hit geometry — check if it's an emissive light
            Vec3 Le = bRec.material->emitted(bRec);
            if (Le != Vec3(0)) {
                float lightPdf = (1.0f - pEnv) * lights.pdfValue(rec.point, bs.wi);
                direct += bs.f * Le * powerHeuristic(bs.pdf, lightPdf) / (bs.pdf + 0.001f);
            }
        } else {
            // Miss — hit the environment map
            if (envMap && envMap->loaded()) {
                Vec3 Le = envMap->lookup(bs.wi.normalized());
                float lightPdf = pEnv * envMap->pdf(bs.wi.normalized());
                direct += bs.f * Le * powerHeuristic(bs.pdf, lightPdf) / (bs.pdf + 0.001f);
            }
        }
    }

    return direct;
}
```

**CRITICAL CORRECTNESS NOTES:**
- The selection probability `pEnv` must appear in BOTH the light-sampling PDF AND the BSDF-sampling MIS weight. When evaluating the "other strategy" PDF for MIS, include the selection probability.
- The BSDF sampling branch now has TWO outcomes: hit geometry (existing code) or miss geometry (new: lookup environment). Both need proper MIS weighting.
- The `pathTrace()` miss condition (Task 4) must use `if (bounce == 0 || wasSpecular)` to avoid double-counting with the NEE environment contribution.
- Shadow rays for the environment use `tMax = 1e30f` (effectively infinity) — if they hit ANYTHING, the environment is occluded.

**Acceptance criteria:**
- Cornell box with HDRI: walls show colored reflections from the environment through the open side
- Open scene with HDRI: sphere is properly lit from all directions, soft shadows visible
- Scene with BOTH area lights AND HDRI: both contribute, no fireflies, no dark patches
- Removing the HDRI returns to previous behavior (sky gradient or solid color)

**Estimated scope:** ~60 lines of changes (replacing existing sampleDirect).

---

## Task 6: Python bindings

**Goal:** Expose environment map loading through pybind11.

**Add to `PyRenderer` class in `module/blender_module.cpp`:**

```cpp
private:
    std::shared_ptr<EnvironmentMap> envMap;

public:
    bool loadEnvironmentMap(const std::string& path, float strength, float rotation) {
        envMap = std::make_shared<EnvironmentMap>();
        if (envMap->load(path, strength, rotation)) {
            renderer.setEnvironmentMap(envMap);
            return true;
        }
        envMap.reset();
        return false;
    }

    void setBackgroundColor(const std::vector<float>& color) {
        renderer.setBackgroundColor(Vec3(color[0], color[1], color[2]));
    }
```

**Add to the pybind11 module definition (inside `PYBIND11_MODULE`):**

```cpp
.def("load_environment_map", &PyRenderer::loadEnvironmentMap,
     "path"_a, "strength"_a = 1.0f, "rotation"_a = 0.0f)
.def("set_background_color", &PyRenderer::setBackgroundColor, "color"_a)
```

**Also update `clear()`** in PyRenderer to reset envMap.

**Handle stb_image implementation:** Add `src/stb_impl.cpp` to the CMake targets:
```cmake
# In the sources list for both targets, add:
add_library(stb_impl STATIC src/stb_impl.cpp)
target_include_directories(stb_impl PRIVATE ${CMAKE_SOURCE_DIR}/include)
# Link to both targets
target_link_libraries(raytracer_standalone PRIVATE stb_impl)
target_link_libraries(raytracer_blender PRIVATE stb_impl)
```

**Acceptance criteria:**
- `renderer.load_environment_map("samples/test_env.hdr")` returns True
- `renderer.load_environment_map("nonexistent.hdr")` returns False
- Rendering with a loaded env map produces illuminated scene

**Estimated scope:** ~30 lines of C++, ~10 lines of CMake.

---

## Task 7: Update Blender addon setup_world()

**Goal:** Rewrite `setup_world()` to detect Environment Texture nodes and pass the HDRI path to the renderer, instead of creating a giant emissive sphere.

**Replace the current `setup_world()` in `blender_addon/__init__.py`:**

```python
def setup_world(self, scene, renderer):
    world = scene.world
    if not world:
        return

    # Check for node tree (note: use_nodes is deprecated in 5.x, always True)
    node_tree = getattr(world, 'node_tree', None)
    if not node_tree:
        return

    # Look for Environment Texture → Background → World Output chain
    hdri_path = None
    strength = 1.0
    rotation = 0.0
    bg_color = None

    for node in node_tree.nodes:
        if node.type == 'TEX_ENVIRONMENT' and node.image:
            hdri_path = bpy.path.abspath(node.image.filepath)
        elif node.type == 'BACKGROUND':
            strength = float(node.inputs['Strength'].default_value)
            # If Color input is not linked, it's a solid background color
            color_input = node.inputs.get('Color')
            if color_input and not color_input.is_linked:
                bg_color = list(color_input.default_value[:3])
        elif node.type == 'MAPPING':
            rot_input = node.inputs.get('Rotation')
            if rot_input:
                rotation = float(rot_input.default_value[2])  # Z rotation

    # Try loading HDRI first
    if hdri_path and os.path.exists(hdri_path):
        success = renderer.load_environment_map(hdri_path, strength, rotation)
        if success:
            print(f"Loaded HDRI: {hdri_path} (strength={strength}, rotation={rotation:.2f})")
            return
        else:
            print(f"Failed to load HDRI: {hdri_path}")

    # Fallback: solid background color
    if bg_color and strength > 0.01:
        scaled_color = [c * strength for c in bg_color]
        renderer.set_background_color(scaled_color)
        print(f"Set background color: {scaled_color}")
```

**Key differences from old code:**
- No longer creates a giant emissive sphere (this was a hack)
- Properly extracts HDRI file path via `bpy.path.abspath()`
- Handles Mapping node rotation (common in Blender scenes)
- Falls back gracefully to solid color or default sky

**Acceptance criteria:**
- Blender scene with Environment Texture → renders using HDRI
- Blender scene with Background color only (no texture) → solid color background
- Blender scene with no world → default sky gradient
- Verify the HDRI path is resolved correctly (absolute path, not relative)

**Estimated scope:** ~40 lines replacing ~15 lines.

---

## Task 8: Standalone CLI support

**Goal:** Add `--envmap` flag to `apps/main.cpp`.

**Add to the CLI parser:**

```cpp
std::string envmap = "";
// In the arg parsing loop:
else if (arg == "--envmap" && i+1 < argc) envmap = argv[++i];
```

**Add after renderer setup, before render:**

```cpp
if (!envmap.empty()) {
    auto env = std::make_shared<EnvironmentMap>();
    if (env->load(envmap)) {
        renderer.setEnvironmentMap(env);
        printf("Using environment map: %s\n", envmap.c_str());
    } else {
        printf("Warning: Failed to load environment map: %s\n", envmap.c_str());
    }
}
```

**Update the `--help` text** to include `--envmap FILE`.

**Estimated scope:** ~15 lines.

---

## Task 9: Tests

**Goal:** Add environment map tests to the test suite.

**Add to `tests/test_python_bindings.py`:**

```python
def test_environment_map_loading():
    """Test that environment maps can be loaded."""
    r = create_renderer()
    # Should fail gracefully for missing file
    result = r.load_environment_map("nonexistent.hdr")
    assert result == False

    # Should succeed for test HDRI (if available)
    test_hdr = os.path.join(os.path.dirname(__file__), '..', 'samples', 'test_env.hdr')
    if os.path.exists(test_hdr):
        result = r.load_environment_map(test_hdr, 1.0, 0.0)
        assert result == True


def test_environment_map_renders_brighter_than_black():
    """An HDRI-lit scene should be brighter than a black background scene."""
    test_hdr = os.path.join(os.path.dirname(__file__), '..', 'samples', 'test_env.hdr')
    if not os.path.exists(test_hdr):
        pytest.skip("No test HDRI available")

    # Render with black background
    r1 = create_renderer()
    r1.set_background_color([0, 0, 0])
    mat = r1.create_material('lambertian', [0.8, 0.8, 0.8], {})
    r1.add_sphere([0, 0, 0], 1.0, mat)
    setup_camera(r1, width=W, height=H)
    pixels_dark = render_image(r1, samples=SAMPLES_FAST)

    # Render with HDRI
    r2 = create_renderer()
    r2.load_environment_map(test_hdr, 1.0, 0.0)
    mat2 = r2.create_material('lambertian', [0.8, 0.8, 0.8], {})
    r2.add_sphere([0, 0, 0], 1.0, mat2)
    setup_camera(r2, width=W, height=H)
    pixels_hdri = render_image(r2, samples=SAMPLES_FAST)

    dark_mean = float(np.mean(pixels_dark))
    hdri_mean = float(np.mean(pixels_hdri))
    assert hdri_mean > dark_mean + 0.05, \
        f"HDRI scene ({hdri_mean:.3f}) should be significantly brighter than black bg ({dark_mean:.3f})"

    save_image(pixels_hdri, os.path.join(OUTPUT_DIR, 'test_hdri_lit.png'))
    save_image(pixels_dark, os.path.join(OUTPUT_DIR, 'test_black_bg.png'))


def test_solid_background_color():
    """Setting a background color should replace the sky gradient."""
    r = create_renderer()
    r.set_background_color([1.0, 0.0, 0.0])  # pure red background
    setup_camera(r, look_from=[0, 0, 5], look_at=[0, 0, 0], width=W, height=H)
    # No objects — should see pure background
    pixels = render_image(r, samples=4)
    # Red channel should dominate
    mean_r = float(np.mean(pixels[:, :, 0]))
    mean_g = float(np.mean(pixels[:, :, 1]))
    mean_b = float(np.mean(pixels[:, :, 2]))
    assert mean_r > 0.3, f"Red channel too low: {mean_r:.3f}"
    assert mean_r > mean_g * 2, f"Red ({mean_r:.3f}) should dominate green ({mean_g:.3f})"
    assert mean_r > mean_b * 2, f"Red ({mean_r:.3f}) should dominate blue ({mean_b:.3f})"
```

**Estimated scope:** ~60 lines.

---

## Task Execution Order and Dependencies

```
Task 1 (EnvironmentMap load/lookup)
  └── Task 2 (CDF construction)
        └── Task 3 (sample/pdf methods)
              └── Task 5 (NEE integration)
  └── Task 4 (pathTrace integration — can start after Task 1)
        └── Task 5 (NEE integration — needs Tasks 3+4)
              └── Task 6 (pybind11 bindings)
                    └── Task 7 (Blender addon)
                    └── Task 8 (Standalone CLI)
                    └── Task 9 (Tests)
```

**Recommended Cline execution:** Tasks 1→2→3 as a batch (EnvironmentMap class), then Task 4 (pathTrace), then Task 5 (NEE), then Tasks 6+7+8+9 as a batch.

---

## Build & Test Commands (for .clinerules)

```bash
# Build (Windows with MSVC)
cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
cmake --build . --config Release

# Build (Linux/Mac)
cd build && cmake .. -DCMAKE_BUILD_TYPE=Release && make -j8

# Test
pytest tests/test_python_bindings.py -v -k "environment_map or background_color"
pytest tests/test_python_bindings.py -v  # full suite

# Quick visual verification (standalone)
./build/bin/raytracer --scene 1 --envmap samples/test_env.hdr --output test_hdri.png
```

---

## Common Pitfalls for the Agent

1. **DO NOT put `#define STB_IMAGE_IMPLEMENTATION` in a header file.** It must go in exactly ONE .cpp file.
2. **DO NOT apply gamma correction to the HDRI data** — HDR files are already in linear space. Gamma is applied once at the end in the render loop.
3. **The PDF conversion requires `2*π²*sinθ` in the denominator**, not `2*π*sinθ` or `4*π`. The factor is `2π²` because the solid angle element is `dω = sinθ dθ dφ` and we're mapping from (u,v) ∈ [0,1]² where `θ = πv` and `φ = 2πu`, so the Jacobian is `|∂(θ,φ)/∂(u,v)| = 2π²`.
4. **Do not multiply by NdotL in the NEE environment contribution** — `eval()` already includes the cosine term (this is documented in renderer-internals.md).
5. **Binary search with `std::lower_bound`** — make sure to handle edge cases where ξ=0 or ξ≈1.
6. **Environment map rotation** should be a subtraction in the sample→direction conversion and an addition in the direction→UV lookup, or vice versa — be consistent.
7. **When both area lights and env map exist**, the BSDF sampling branch in sampleDirect must check BOTH outcomes (hit geometry → check emissive, miss geometry → check environment).
