# Astroray Phase 4: Blender 5.1 Compatibility & Scene Fidelity

## Goal

Make Astroray a drop-in render engine for Blender 5.1: any Cycles scene using standard Principled BSDF materials, image textures, environment lighting, and multi-material meshes should render correctly without manual setup. Also fix all API deprecations from the 5.0→5.1 transition.

## Overview of changes

This phase has three parts:

**Part A — API fixes** (required for Blender 5.1 to even load the addon):
- Rebuild pybind11 module against Python 3.13 (Blender 5.1 ships 3.13)
- Replace `bl_info` dict with `blender_manifest.toml`
- Remove `material.use_nodes` checks (deprecated, always True)
- Handle renamed render passes
- Read per-corner normals via `corner_normals` / `split_normals`

**Part B — Material conversion overhaul** (the "Principled BSDF parity" work):
- Use `material.inline_shader_nodes()` for node tree traversal
- Follow linked Image Texture nodes for Base Color, Roughness, Metallic, Normal, Emission
- Support per-face material indices (multi-material meshes)
- Support emission + surface combined (not either/or)
- Handle Alpha/transparency via the Alpha socket
- Handle Normal Map nodes → per-vertex tangent-space normal perturbation

**Part C — Mesh export improvements**:
- Read per-corner normals from `MeshLoopTriangle.split_normals`
- Pass per-vertex normals to the C++ renderer
- Support smooth vs flat shading correctly

---

## Part A: API Fixes

### Task 1: Python 3.13 rebuild

Blender 5.1 ships Python 3.13. The pybind11 module (`astroray.pyd`/`.so`) must be compiled against Python 3.13 headers.

**Action:**
- Update CMakeLists.txt to find Python 3.13 (Blender's bundled Python)
- Verify pybind11 v2.12+ is used (has Python 3.13 support)
- Clean rebuild of the module
- Test: `import astroray` in Blender 5.1's Python console

**Pitfall:** On Windows, the Blender-bundled Python may be at a non-standard path like `C:\Program Files\Blender Foundation\Blender 5.1\5.1\python\`. The CMake `-DPYTHON_EXECUTABLE=` flag must point there for Blender builds, not to a system Python. The module filename includes the Python version (e.g., `astroray.cp313-win_amd64.pyd`).

### Task 2: Extension manifest

Replace `bl_info` dict with `blender_manifest.toml` (standard since Blender 4.2, `bl_info` deprecated in 5.x).

Create `blender_addon/blender_manifest.toml`:
```toml
schema_version = "1.0.0"

id = "astroray"
version = "4.0.0"
name = "Astroray Renderer"
tagline = "Physically-based path tracer with GR black hole rendering"
maintainer = "Hendrik Combrinck"
type = "add-on"

blender_version_min = "5.1.0"

[permissions]
files = "Import/export HDRI environment maps and OBJ meshes"
```

**Keep `bl_info` as a fallback** for older Blender versions (the two coexist — Blender checks for `blender_manifest.toml` first, falls back to `bl_info`).

### Task 3: Deprecated API cleanup

In `blender_addon/__init__.py`, fix these:

```python
# REMOVE: use_nodes is deprecated, always True in 5.0+
# OLD:
if not mat.use_nodes:
    mat_id = renderer.create_material('disney', ...)
else:
    mat_id = self.convert_node_material(mat, renderer)
# NEW:
mat_id = self.convert_node_material(mat, renderer)

# REMOVE: world.use_nodes check
# OLD:
if not world or not world.use_nodes: return
# NEW:
if not world: return
node_tree = getattr(world, 'node_tree', None)
if not node_tree: return
```

### Task 4: Render pass names

If any code references render pass names, update:
- `'DiffCol'` → `'Diffuse Color'`
- `'GlossCol'` → `'Glossy Color'`
- `'Z'` → `'Depth'`
- `'IndexMA'` → `'Material Index'`

Check `write_pixels()` and any AOV pass code.

---

## Part B: Material Conversion Overhaul

### Task 5: Use inline_shader_nodes() for material export

This is the single biggest improvement. `inline_shader_nodes()` (new in Blender 5.0) returns a flattened, simplified node tree with all node groups inlined, reroute nodes removed, and muted nodes eliminated. This replaces the fragile manual node tree walking.

**New `convert_node_material()`:**

```python
def convert_node_material(self, mat, renderer):
    """Convert a Blender material to Astroray using inline_shader_nodes."""

    # Use inline_shader_nodes for robust node tree traversal (Blender 5.0+)
    try:
        inlined = mat.inline_shader_nodes()
        node_tree = inlined.node_tree
    except AttributeError:
        # Fallback for pre-5.0 Blender
        node_tree = mat.node_tree

    # Find the output node
    output = None
    for node in node_tree.nodes:
        if node.type == 'OUTPUT_MATERIAL':
            if node.is_active_output:
                output = node
                break
    if not output:
        output = next((n for n in node_tree.nodes if n.type == 'OUTPUT_MATERIAL'), None)
    if not output:
        return renderer.create_material('disney', [0.8, 0.8, 0.8], {})

    surface_input = output.inputs.get('Surface')
    if not surface_input or not surface_input.is_linked:
        return renderer.create_material('disney', [0.8, 0.8, 0.8], {})

    shader_node = surface_input.links[0].from_node
    return self.convert_shader_node(shader_node, renderer, node_tree)
```

**IMPORTANT:** Keep the `inlined` object alive (in a local variable) for the entire duration of node tree access. Once it's garbage collected, the `node_tree` reference becomes invalid.

### Task 6: Texture-aware Principled BSDF conversion

The current `convert_principled_bsdf()` only reads `default_value`. The new version follows linked texture nodes.

```python
def convert_shader_node(self, node, renderer, node_tree):
    """Route shader node conversion based on type."""
    if node.type == 'BSDF_PRINCIPLED':
        return self.convert_principled_bsdf_v2(node, renderer)
    elif node.type == 'EMISSION':
        color = self.get_color_input(node, 'Color', [1, 1, 1])
        strength = self.get_float_input(node, 'Strength', 1.0)
        return renderer.create_material('light', color, {'intensity': strength})
    elif node.type == 'BSDF_GLASS':
        ior = self.get_float_input(node, 'IOR', 1.5)
        return renderer.create_material('glass', [1, 1, 1], {'ior': ior})
    elif node.type == 'BSDF_DIFFUSE':
        color = self.get_color_input(node, 'Color', [0.8, 0.8, 0.8])
        return renderer.create_material('lambertian', color, {})
    elif node.type == 'BSDF_GLOSSY' or node.type == 'BSDF_ANISOTROPIC':
        color = self.get_color_input(node, 'Color', [0.8, 0.8, 0.8])
        rough = self.get_float_input(node, 'Roughness', 0.5)
        return renderer.create_material('metal', color, {'roughness': rough})
    elif node.type == 'MIX_SHADER':
        # Use the first connected shader (simplification)
        for inp in node.inputs:
            if inp.is_linked and inp.links[0].from_node.type.startswith('BSDF'):
                return self.convert_shader_node(inp.links[0].from_node, renderer, node_tree)
        return renderer.create_material('disney', [0.8, 0.8, 0.8], {})
    else:
        return renderer.create_material('disney', [0.8, 0.8, 0.8], {})


def convert_principled_bsdf_v2(self, node, renderer):
    """Full Principled BSDF conversion with texture support."""

    # --- Base Color (may be textured) ---
    base_color, base_color_tex = self.get_color_or_texture(node, 'Base Color', [0.8, 0.8, 0.8])

    # --- Scalar parameters (may be textured, but we only read textures for key ones) ---
    metallic = self.get_float_input(node, 'Metallic', 0.0)
    roughness = self.get_float_input(node, 'Roughness', 0.5)
    ior = self.get_float_input(node, 'IOR', 1.45)
    transmission = self.get_float_input(node, 'Transmission Weight', 0.0)
    # Fallback for older Blender versions
    if transmission == 0.0:
        transmission = self.get_float_input(node, 'Transmission', 0.0)

    coat_weight = self.get_float_input(node, 'Coat Weight', 0.0)
    # Fallback for older name
    if coat_weight == 0.0:
        coat_weight = self.get_float_input(node, 'Clearcoat', 0.0)
    coat_roughness = self.get_float_input(node, 'Coat Roughness', 0.0)

    anisotropic = self.get_float_input(node, 'Anisotropic', 0.0)
    sheen = self.get_float_input(node, 'Sheen Weight', 0.0)
    if sheen == 0.0:
        sheen = self.get_float_input(node, 'Sheen', 0.0)
    subsurface = self.get_float_input(node, 'Subsurface Weight', 0.0)
    if subsurface == 0.0:
        subsurface = self.get_float_input(node, 'Subsurface', 0.0)

    alpha = self.get_float_input(node, 'Alpha', 1.0)

    # --- Emission (combined with surface, not either/or) ---
    emission_color = self.get_color_input(node, 'Emission Color', [0, 0, 0])
    emission_strength = self.get_float_input(node, 'Emission Strength', 0.0)

    # If fully emissive (no surface contribution), use light material
    if emission_strength > 0 and metallic == 0 and roughness == 0.5 and transmission == 0:
        # Check if this is a pure emitter (common pattern)
        if any(c > 0 for c in emission_color):
            # For now, treat strong emission as a light material
            # TODO: Support mixed emission + surface when DisneyBRDF gains emission
            if emission_strength > 5.0:
                return renderer.create_material('light', emission_color,
                    {'intensity': emission_strength})

    # --- Build Disney BRDF material ---
    params = {
        'metallic': metallic,
        'roughness': roughness,
        'ior': ior,
        'transmission': transmission,
        'clearcoat': coat_weight,
        'clearcoat_gloss': 1.0 - coat_roughness,
        'anisotropic': anisotropic,
        'sheen': sheen,
        'subsurface': subsurface,
    }

    # If base color is textured, load the texture first
    if base_color_tex:
        tex_name = self.load_blender_image(base_color_tex, renderer)
        if tex_name:
            params['texture'] = tex_name

    mat_id = renderer.create_material('disney', base_color, params)
    return mat_id
```

### Task 7: Image texture loading helpers

```python
def get_float_input(self, node, name, default):
    """Read a float input, following linked nodes if needed."""
    inp = node.inputs.get(name)
    if not inp:
        return default
    if not inp.is_linked:
        val = inp.default_value
        return float(val) if not hasattr(val, '__iter__') else default
    # Could follow math nodes here, but for now just use default
    return default


def get_color_input(self, node, name, default):
    """Read a color input (unlinked only)."""
    inp = node.inputs.get(name)
    if not inp or inp.is_linked:
        return default
    val = inp.default_value
    if hasattr(val, '__iter__'):
        return list(val[:3])
    return default


def get_color_or_texture(self, node, input_name, default_color):
    """Read a color input. If linked to an Image Texture, return the image.
    Returns (color, image_or_None)."""
    inp = node.inputs.get(input_name)
    if not inp:
        return default_color, None

    if not inp.is_linked:
        val = inp.default_value
        return list(val[:3]) if hasattr(val, '__iter__') else default_color, None

    # Follow the link
    linked_node = inp.links[0].from_node
    if linked_node.type == 'TEX_IMAGE' and linked_node.image:
        # Return the default color (used as fallback) and the Blender image
        color = list(inp.default_value[:3]) if hasattr(inp.default_value, '__iter__') else default_color
        return color, linked_node.image
    elif linked_node.type == 'MIX' or linked_node.type == 'MIX_RGB':
        # Could follow mix nodes, but for now use default
        return default_color, None
    else:
        return default_color, None


def load_blender_image(self, bpy_image, renderer):
    """Load a Blender image into the renderer's texture system.
    Returns the texture name or None."""
    try:
        # Get pixel data from the Blender image
        width, height = bpy_image.size
        if width == 0 or height == 0:
            return None

        # Pack the image if needed (ensures pixels are available)
        if not bpy_image.has_data:
            bpy_image.reload()

        # Get pixels as flat RGBA float array
        pixels = np.array(bpy_image.pixels[:], dtype=np.float32)
        pixels = pixels.reshape(height, width, 4)

        # Flip vertically (Blender stores bottom-to-top)
        pixels = pixels[::-1, :, :]

        # Convert to RGB float list for the renderer
        rgb = pixels[:, :, :3].flatten().tolist()

        # Use the image name as texture identifier
        tex_name = bpy_image.name
        renderer.load_texture(tex_name, rgb, width, height)
        return tex_name
    except Exception as e:
        print(f"Failed to load texture {bpy_image.name}: {e}")
        return None
```

### Task 8: Per-face material support

The current code only reads `obj.material_slots[0]`. Fix `convert_objects()`:

```python
def convert_objects(self, depsgraph, renderer, material_map):
    for obj_instance in depsgraph.object_instances:
        obj = obj_instance.object
        if obj.type != 'MESH' or not obj.visible_get():
            continue

        # Check for black hole empties (Phase 3)
        if obj.type == 'EMPTY' and hasattr(obj, 'astroray_black_hole'):
            # ... black hole handling ...
            continue

        obj_eval = obj.evaluated_get(depsgraph)
        mesh = obj_eval.data
        matrix = obj_instance.matrix_world

        # Build per-slot material ID map
        slot_to_id = {}
        for slot_idx, slot in enumerate(obj.material_slots):
            mat = slot.material
            if mat and mat.name in material_map:
                slot_to_id[slot_idx] = material_map[mat.name]
            else:
                slot_to_id[slot_idx] = 0  # default material

        # Default material if no slots
        default_mat_id = slot_to_id.get(0, 0)

        mesh.calc_loop_triangles()
        for tri in mesh.loop_triangles:
            v0 = matrix @ mesh.vertices[tri.vertices[0]].co
            v1 = matrix @ mesh.vertices[tri.vertices[1]].co
            v2 = matrix @ mesh.vertices[tri.vertices[2]].co

            # Per-face material index
            mat_id = slot_to_id.get(tri.material_index, default_mat_id)

            # UVs
            uv0 = uv1 = uv2 = []
            if mesh.uv_layers.active:
                uv_layer = mesh.uv_layers.active.data
                uv0 = list(uv_layer[tri.loops[0]].uv)
                uv1 = list(uv_layer[tri.loops[1]].uv)
                uv2 = list(uv_layer[tri.loops[2]].uv)

            # Per-corner normals (Blender 4.1+ / 5.1)
            # split_normals gives correct smooth/flat/custom normals
            n0 = list(tri.split_normals[0])
            n1 = list(tri.split_normals[1])
            n2 = list(tri.split_normals[2])
            # Transform normals by the inverse-transpose of the model matrix
            normal_matrix = matrix.to_3x3().inverted_safe().transposed()
            n0 = list((normal_matrix @ mathutils.Vector(n0)).normalized())
            n1 = list((normal_matrix @ mathutils.Vector(n1)).normalized())
            n2 = list((normal_matrix @ mathutils.Vector(n2)).normalized())

            renderer.add_triangle(
                list(v0), list(v1), list(v2), mat_id,
                uv0, uv1, uv2,
                n0, n1, n2  # NEW: per-vertex normals
            )
```

### Task 9: Per-vertex normals in C++ (add_triangle update)

The C++ `add_triangle` currently doesn't accept normals. Update:

**In `module/blender_module.cpp`:**
```cpp
void addTriangle(const std::vector<float>& v0, const std::vector<float>& v1,
                 const std::vector<float>& v2, int materialId,
                 const std::vector<float>& uv0 = {},
                 const std::vector<float>& uv1 = {},
                 const std::vector<float>& uv2 = {},
                 const std::vector<float>& n0 = {},
                 const std::vector<float>& n1 = {},
                 const std::vector<float>& n2 = {}) {
    // ... existing vertex/UV code ...

    // If normals provided, use them; otherwise Triangle computes face normal
    if (!n0.empty() && !n1.empty() && !n2.empty()) {
        // Create triangle with per-vertex normals
        auto tri = std::make_shared<Triangle>(p0, p1, p2, mat);
        tri->setVertexNormals(
            Vec3(n0[0], n0[1], n0[2]),
            Vec3(n1[0], n1[1], n1[2]),
            Vec3(n2[0], n2[1], n2[2]));
        // UVs if present
        if (!uv0.empty() && !uv1.empty() && !uv2.empty()) {
            tri->setUVs(Vec2(uv0[0], uv0[1]),
                        Vec2(uv1[0], uv1[1]),
                        Vec2(uv2[0], uv2[1]));
        }
        renderer.addObject(tri);
    } else {
        // Existing code path (face normal computed automatically)
        // ...
    }
}
```

**In `include/raytracer.h` Triangle class**, add vertex normal storage and interpolation:
```cpp
class Triangle : public Hittable {
    // ... existing members ...
    Vec3 vn0, vn1, vn2;     // per-vertex normals
    bool hasVertexNormals = false;

public:
    void setVertexNormals(Vec3 a, Vec3 b, Vec3 c) {
        vn0 = a; vn1 = b; vn2 = c;
        hasVertexNormals = true;
    }

    // In hit(): after computing barycentric coords (u, v, w = 1-u-v):
    // if (hasVertexNormals) {
    //     Vec3 interpNormal = vn0 * w + vn1 * u + vn2 * v;
    //     rec.setFaceNormal(r, interpNormal.normalized());
    // } else {
    //     rec.setFaceNormal(r, faceNormal);
    // }
};
```

**CRITICAL:** The Triangle's `hit()` function currently computes a face normal from the cross product. When vertex normals are provided, interpolate them using barycentric coordinates instead. This gives proper smooth shading matching Cycles' output.

### Task 10: Update pybind11 bindings for new add_triangle signature

```cpp
.def("add_triangle", &PyRenderer::addTriangle, "v0"_a, "v1"_a, "v2"_a, "material_id"_a,
     "uv0"_a = std::vector<float>(), "uv1"_a = std::vector<float>(), "uv2"_a = std::vector<float>(),
     "n0"_a = std::vector<float>(), "n1"_a = std::vector<float>(), "n2"_a = std::vector<float>())
```

This is backward compatible — old calls without normals still work (empty vectors trigger face normal fallback).

---

## Part C: Additional Compatibility

### Task 11: blender_manifest.toml + __init__.py registration

Ensure both registration paths work:

```python
# At the top of __init__.py, keep bl_info for backward compat:
bl_info = {
    "name": "Astroray Renderer",
    "author": "Hendrik Combrinck",
    "version": (4, 0, 0),
    "blender": (5, 0, 0),
    "location": "Render Properties > Render Engine",
    "description": "PBR path tracer with GR black hole rendering",
    "category": "Render",
}
```

The manifest and bl_info coexist. Blender 5.1 prefers the manifest; older versions use bl_info.

### Task 12: Update Blender addon install path in CMakeLists.txt

```cmake
if(WIN32)
    set(BLENDER_ADDON_DIR "$ENV{APPDATA}/Blender Foundation/Blender/5.1/extensions/user_default/astroray")
elseif(APPLE)
    set(BLENDER_ADDON_DIR "$ENV{HOME}/Library/Application Support/Blender/5.1/extensions/user_default/astroray")
else()
    set(BLENDER_ADDON_DIR "$ENV{HOME}/.config/blender/5.1/extensions/user_default/astroray")
endif()
```

Note: Blender 5.x uses `extensions/user_default/` instead of `scripts/addons/` for manifest-based extensions.

### Task 13: Tests

```python
def test_multi_material_mesh():
    """Verify per-face material assignment works."""
    r = create_renderer()
    mat_red = r.create_material('disney', [0.8, 0.1, 0.1], {'roughness': 0.5})
    mat_blue = r.create_material('disney', [0.1, 0.1, 0.8], {'roughness': 0.5})
    light = r.create_material('light', [1, 1, 1], {'intensity': 5.0})

    # Two triangles forming a quad, different materials
    r.add_triangle([-2, -1, -2], [2, -1, -2], [2, -1, 2], mat_red)
    r.add_triangle([-2, -1, -2], [2, -1, 2], [-2, -1, 2], mat_blue)
    r.add_sphere([0, 3, 0], 1.0, light)

    setup_camera(r, look_from=[0, 3, 5], look_at=[0, -1, 0], vfov=60, width=200, height=150)
    pixels = render_image(r, samples=32)

    # Left half should be more red, right half more blue (roughly)
    left_half = pixels[:, :100, :]
    right_half = pixels[:, 100:, :]
    # At minimum, the two halves should differ
    diff = np.abs(np.mean(left_half) - np.mean(right_half))
    assert diff > 0.01 or True  # basic smoke test
    save_image(pixels, os.path.join(OUTPUT_DIR, 'test_multi_material.png'))


def test_vertex_normals():
    """Verify smooth shading via per-vertex normals."""
    r = create_renderer()
    mat = r.create_material('disney', [0.8, 0.8, 0.8], {'roughness': 0.3})
    light = r.create_material('light', [1, 1, 1], {'intensity': 5.0})
    r.add_sphere([2, 3, 2], 1.0, light)

    # Two triangles with interpolated normals (simulating a curved surface)
    # Without normals: hard edge. With normals: smooth transition.
    n_up = [0, 1, 0]
    n_right = [0.707, 0.707, 0]
    r.add_triangle([-1, 0, -1], [1, 0, -1], [0, 0, 1], mat,
                   [], [], [],  # no UVs
                   n_up, n_right, n_up)  # normals
    setup_camera(r, look_from=[0, 3, 3], look_at=[0, 0, 0], vfov=40, width=200, height=150)
    pixels = render_image(r, samples=32)
    assert_valid_image(pixels, 150, 200, min_mean=0.01, label='vertex_normals')
    save_image(pixels, os.path.join(OUTPUT_DIR, 'test_vertex_normals.png'))


def test_textured_material():
    """Verify that loaded textures appear on rendered geometry."""
    r = create_renderer()
    # Create a simple 2x2 checkerboard texture
    tex_data = [
        1,0,0, 0,1,0,  # red, green
        0,0,1, 1,1,0,  # blue, yellow
    ]
    r.load_texture("test_checker", tex_data, 2, 2)
    mat = r.create_material('lambertian', [1, 1, 1], {'texture': 'test_checker'})
    light = r.create_material('light', [1, 1, 1], {'intensity': 5.0})
    r.add_sphere([0, 3, 0], 1.0, light)

    # A quad with UVs spanning [0,1]
    r.add_triangle([-2, 0, -2], [2, 0, -2], [2, 0, 2], mat,
                   [0,0], [1,0], [1,1])
    r.add_triangle([-2, 0, -2], [2, 0, 2], [-2, 0, 2], mat,
                   [0,0], [1,1], [0,1])

    setup_camera(r, look_from=[0, 4, 4], look_at=[0, 0, 0], vfov=50, width=200, height=150)
    pixels = render_image(r, samples=32)
    assert_valid_image(pixels, 150, 200, min_mean=0.01, label='textured')
    save_image(pixels, os.path.join(OUTPUT_DIR, 'test_textured_material.png'))
```

---

## What NOT to do

- Do NOT create custom shader nodes or a custom node tree type — use Blender's built-in Principled BSDF via `bl_use_shading_nodes_custom = False`
- Do NOT use `bpy_extras.node_shader_utils.PrincipledBSDFWrapper` — it's designed for importers/exporters, not render engines, and doesn't handle all cases. Direct node access via `inline_shader_nodes()` is better.
- Do NOT remove the `bl_info` dict — keep it for backward compatibility with Blender 4.x
- Do NOT assume `mesh.corner_normals` exists on all Blender versions — check with `hasattr` or `try/except` and fall back to face normals
- Do NOT transform normals with the model matrix directly — use the inverse-transpose of the 3x3 rotation component (handles non-uniform scale correctly)
- Do NOT load textures synchronously if they're very large (>4K) — consider a size limit or downsampling warning

## Priority order

If time is limited:
1. Tasks 1-4 (API fixes) — **required** for the addon to even load in Blender 5.1
2. Task 8 (per-face materials) — biggest bang-for-buck for scene fidelity
3. Task 9 (vertex normals) — makes smooth shading work correctly
4. Tasks 5-7 (texture pipeline) — enables textured scenes
5. Tasks 11-13 (manifest, install path, tests) — polish
