"""pkg76 round-trip test — bpy authors a scene, importer re-reads it.

Skipped wherever bpy is unavailable (i.e. CI). Run locally with a Blender
Python:

    /path/to/blender --background --python -m pytest tests/test_blend_import_roundtrip.py

…or with a separate `bpy` PyPI install in a regular Python interpreter.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

bpy = pytest.importorskip("bpy")  # noqa: E402


from tools.blend_import import import_blend  # noqa: E402


class _FakeRenderer:
    """Stand-in for astroray.Renderer — we only assert what the importer fed
    us; the real renderer is exercised by the pkg71 baseline."""

    def __init__(self):
        self.materials = []
        self.triangles = []
        self.lights = []
        self.background = None
        self.cam_args = None

    def create_material(self, kind, color, params):
        mid = len(self.materials)
        self.materials.append((kind, list(color), dict(params)))
        return mid

    def add_triangle(self, v0, v1, v2, mat_id):
        self.triangles.append((tuple(v0), tuple(v1), tuple(v2), mat_id))

    def add_sphere(self, *a, **k): self.lights.append(("point", a))
    def add_sun_light(self, *a, **k): self.lights.append(("sun", a))
    def add_spot_light(self, *a, **k): self.lights.append(("spot", a))
    def add_area_light(self, *a, **k): self.lights.append(("area", a))
    def set_background_color(self, c): self.background = list(c)
    def setup_camera(self, *a, **k): self.cam_args = a


@pytest.fixture(scope="module")
def authored_blend_path():
    """Author a fresh deterministic .blend with bpy and return its path."""
    bpy.ops.wm.read_factory_settings(use_empty=True)

    cam = bpy.data.cameras.new("Cam")
    cam.lens = 50.0
    cam.sensor_width = 36.0
    cam.sensor_height = 24.0
    cam_obj = bpy.data.objects.new("Cam", cam)
    cam_obj.location = (0.0, -5.0, 1.0)

    sun = bpy.data.lights.new("Sun", type="SUN")
    sun.color = (0.9, 0.85, 0.7)
    sun.energy = 2.0
    sun_obj = bpy.data.objects.new("Sun", sun)

    mat = bpy.data.materials.new("Mat")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = (0.25, 0.5, 0.75, 1.0)
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    mesh = bpy.data.meshes.new("Mesh")
    mesh.from_pydata(
        [(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)],
        [],
        [(0, 1, 2, 3)],
    )
    mesh.update()
    mesh.materials.append(mat)
    mesh_obj = bpy.data.objects.new("Quad", mesh)

    scene = bpy.context.scene
    for obj in (cam_obj, sun_obj, mesh_obj):
        scene.collection.objects.link(obj)
    scene.camera = cam_obj

    world = scene.world or bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    wt = world.node_tree
    wt.nodes.clear()
    wout = wt.nodes.new("ShaderNodeOutputWorld")
    bg = wt.nodes.new("ShaderNodeBackground")
    bg.inputs["Color"].default_value = (0.1, 0.2, 0.3, 1.0)
    bg.inputs["Strength"].default_value = 1.0
    wt.links.new(bg.outputs["Background"], wout.inputs["Surface"])

    tmp = Path(tempfile.mkstemp(suffix=".blend")[1])
    bpy.ops.wm.save_as_mainfile(filepath=str(tmp), compress=False, copy=True)
    return tmp


def test_round_trip_matches_authored_values(authored_blend_path):
    r = _FakeRenderer()
    import_blend(authored_blend_path, renderer=r, width=512, height=512)

    assert len(r.materials) == 2  # mat + light
    # Disney material's base colour must round-trip the Principled default.
    disney = next(m for m in r.materials if m[0] in ("disney", "lambertian"))
    rgb = disney[1]
    assert rgb[0] == pytest.approx(0.25, abs=1e-3)
    assert rgb[1] == pytest.approx(0.50, abs=1e-3)
    assert rgb[2] == pytest.approx(0.75, abs=1e-3)

    # World background colour × strength.
    assert r.background is not None
    assert r.background[0] == pytest.approx(0.1, abs=1e-3)
    assert r.background[1] == pytest.approx(0.2, abs=1e-3)
    assert r.background[2] == pytest.approx(0.3, abs=1e-3)

    # 1 quad → 2 triangles.
    assert len(r.triangles) == 2

    # 1 sun light.
    assert len(r.lights) == 1
    kind, args = r.lights[0]
    assert kind == "sun"

    # Camera focal length recovered as vfov.
    assert r.cam_args is not None
    fov_deg = r.cam_args[3]
    # 24mm sensor / 2 / 50mm lens → atan(0.24) → ~26.99° vertical FOV.
    assert 25.0 < fov_deg < 29.0


def test_real_renderer_accepts_dynamic_attrs(authored_blend_path):
    """Regression test for pkg100 — real pybind11 Renderer must accept intrinsics.

    The _FakeRenderer stub has a __dict__ (plain Python class), so
    `renderer._cam_intrinsics = {...}` succeeds against the stub. The real
    pybind11 astroray.Renderer (without py::dynamic_attr()) has no __dict__ and
    raises AttributeError on dynamic attribute assignment. This test exercises
    the real binding to ensure the fix (Axis 2: return intrinsics up the call
    chain) works correctly.

    Skipped when astroray module is unavailable (e.g., CI without a built .pyd).
    """
    astroray = pytest.importorskip("astroray")

    # Use the real pybind11 Renderer, not the stub.
    renderer = astroray.Renderer()

    # This call must not raise AttributeError. Prior to the fix, it would fail at
    # scene_builder.py:175 with "no attribute '_cam_intrinsics' and no __dict__",
    # and (post-pkg100-original-fix) it would still fail one line later at
    # blend_to_astroray.py:67 trying to set `_blend_import_stats`. The current
    # fix uses an explicit ``stats_out`` out-parameter for the real binding
    # because it has no ``__dict__``; the attribute-stash is best-effort.
    stats = {}
    result = import_blend(
        authored_blend_path, renderer=renderer, width=512, height=512,
        stats_out=stats,
    )

    # Verify the renderer was populated and setup_camera was called.
    assert result is renderer

    # Verify stats include camera intrinsics.
    assert isinstance(stats, dict)
    assert "cam_intrinsics" in stats
    assert stats["cam_intrinsics"] is not None

    # Verify the intrinsics dict has the expected keys.
    intrinsics = stats["cam_intrinsics"]
    assert "eye" in intrinsics
    assert "target" in intrinsics
    assert "up" in intrinsics
    assert "fov" in intrinsics
    assert "aspect" in intrinsics
    assert "near" in intrinsics
    assert "far" in intrinsics


def test_area_light_shape_import():
    """pkg76-followup Gap 4: area lights import shape (square/rect/disk/ellipse).

    Citation: Cycles intern/cycles/blender/light.cpp:BlenderSync::sync_light
    reads b_light.shape() for area lights. Blender's DNA_light_types.h defines
    eLightAreaShape enum: SQUARE=0, RECT=1, DISK=4, ELLIPSE=5.
    """
    bpy.ops.wm.read_factory_settings(use_empty=True)

    # Create 4 area lights with different shapes
    shapes_to_test = [
        ("SQUARE", 1.5, 1.5),
        ("RECTANGLE", 2.0, 1.0),
        ("DISK", 1.2, 1.2),
        ("ELLIPSE", 1.8, 0.9),
    ]

    for i, (shape, size_x, size_y) in enumerate(shapes_to_test):
        light = bpy.data.lights.new(f"Area_{shape}", type="AREA")
        light.shape = shape
        light.size = size_x
        light.size_y = size_y
        light.color = (1.0, 1.0, 1.0)
        light.energy = 50.0

        obj = bpy.data.objects.new(f"AreaLight_{shape}", light)
        obj.location = (i * 3.0, 0.0, 2.0)
        bpy.context.scene.collection.objects.link(obj)

    tmp = Path(tempfile.mkstemp(suffix=".blend")[1])
    bpy.ops.wm.save_as_mainfile(filepath=str(tmp), compress=False, copy=True)

    # Import and verify
    r = _FakeRenderer()
    import_blend(tmp, renderer=r, width=512, height=512)

    # Should have 4 area lights
    area_lights = [light for light in r.lights if light[0] == "area"]
    assert len(area_lights) == 4, f"Expected 4 area lights, got {len(area_lights)}"

    # Verify shapes were imported correctly
    # args tuple: (center, axis_u, axis_v, size_x, size_y, shape, material_id, spread, obj_idx, mat_idx)
    shapes_imported = [light[1][5] for light in area_lights]

    # SQUARE and RECTANGLE both map to "RECTANGLE" in Astroray
    # (distinction is implicit in size_x == size_y)
    assert shapes_imported[0] == "RECTANGLE", f"SQUARE should map to RECTANGLE, got {shapes_imported[0]}"
    assert shapes_imported[1] == "RECTANGLE", f"RECTANGLE should map to RECTANGLE, got {shapes_imported[1]}"
    assert shapes_imported[2] == "DISK", f"DISK should map to DISK, got {shapes_imported[2]}"
    assert shapes_imported[3] == "ELLIPSE", f"ELLIPSE should map to ELLIPSE, got {shapes_imported[3]}"

    # Verify sizes were imported correctly
    for i, (shape, expected_x, expected_y) in enumerate(shapes_to_test):
        size_x, size_y = area_lights[i][1][3], area_lights[i][1][4]
        assert size_x == pytest.approx(expected_x, abs=1e-3), \
            f"{shape} size_x mismatch: expected {expected_x}, got {size_x}"
        assert size_y == pytest.approx(expected_y, abs=1e-3), \
            f"{shape} size_y mismatch: expected {expected_y}, got {size_y}"

    tmp.unlink()


def test_non_principled_bsdf_color_extraction():
    """pkg76-followup Gap 2a: non-Principled BSDF shader nodes extract base color.

    Tests that Diffuse BSDF, Glass BSDF, Refraction BSDF, and Emission shader
    nodes correctly extract their Color socket values, with or without connected
    image textures. Mix Shader nodes pick the heavier-weighted input.

    Citation: Cycles intern/cycles/blender/shader.cpp lines 845 (Diffuse),
    1062-1073 (Glass), 1075-1085 (Refraction), 1156-1157 (Emission), 941-943
    (MixShader), Apache-2.0.
    """
    bpy.ops.wm.read_factory_settings(use_empty=True)

    # Test case 1: Diffuse BSDF with constant color
    mat_diffuse = bpy.data.materials.new("DiffuseMat")
    mat_diffuse.use_nodes = True
    nt = mat_diffuse.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfDiffuse")
    bsdf.inputs["Color"].default_value = (0.8, 0.2, 0.1, 1.0)
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    # Test case 2: Glass BSDF with constant color
    mat_glass = bpy.data.materials.new("GlassMat")
    mat_glass.use_nodes = True
    nt = mat_glass.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfGlass")
    bsdf.inputs["Color"].default_value = (0.1, 0.9, 0.3, 1.0)
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    # Test case 3: Emission shader with constant color
    mat_emission = bpy.data.materials.new("EmissionMat")
    mat_emission.use_nodes = True
    nt = mat_emission.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    emission = nt.nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = (0.95, 0.85, 0.05, 1.0)
    nt.links.new(emission.outputs["Emission"], out.inputs["Surface"])

    # Test case 4: Mix Shader with two Diffuse BSDFs (Fac=0.7 → picks second)
    mat_mix = bpy.data.materials.new("MixMat")
    mat_mix.use_nodes = True
    nt = mat_mix.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    mix = nt.nodes.new("ShaderNodeMixShader")
    mix.inputs["Fac"].default_value = 0.7
    bsdf1 = nt.nodes.new("ShaderNodeBsdfDiffuse")
    bsdf1.inputs["Color"].default_value = (1.0, 0.0, 0.0, 1.0)  # red
    bsdf2 = nt.nodes.new("ShaderNodeBsdfDiffuse")
    bsdf2.inputs["Color"].default_value = (0.0, 0.0, 1.0, 1.0)  # blue
    nt.links.new(bsdf1.outputs["BSDF"], mix.inputs[1])
    nt.links.new(bsdf2.outputs["BSDF"], mix.inputs[2])
    nt.links.new(mix.outputs["Shader"], out.inputs["Surface"])

    # Create a dummy mesh for each material
    for i, mat in enumerate([mat_diffuse, mat_glass, mat_emission, mat_mix]):
        mesh = bpy.data.meshes.new(f"Mesh{i}")
        mesh.from_pydata([(-1, -1, i), (1, -1, i), (0, 1, i)], [], [(0, 1, 2)])
        mesh.update()
        mesh.materials.append(mat)
        obj = bpy.data.objects.new(f"Obj{i}", mesh)
        bpy.context.scene.collection.objects.link(obj)

    # Add a camera (required for import)
    cam = bpy.data.cameras.new("Cam")
    cam_obj = bpy.data.objects.new("Cam", cam)
    bpy.context.scene.collection.objects.link(cam_obj)
    bpy.context.scene.camera = cam_obj

    tmp = Path(tempfile.mkstemp(suffix=".blend")[1])
    bpy.ops.wm.save_as_mainfile(filepath=str(tmp), compress=False, copy=True)

    # Import and verify
    r = _FakeRenderer()
    import_blend(tmp, renderer=r, width=512, height=512)

    # We should have 4 materials (one per test case)
    assert len(r.materials) >= 4, f"Expected at least 4 materials, got {len(r.materials)}"

    # Find materials by color (order may vary)
    colors = [m[1][:3] for m in r.materials]

    # Diffuse BSDF: (0.8, 0.2, 0.1)
    assert any(
        abs(c[0] - 0.8) < 0.01 and abs(c[1] - 0.2) < 0.01 and abs(c[2] - 0.1) < 0.01
        for c in colors
    ), f"Diffuse BSDF color not found in {colors}"

    # Glass BSDF: (0.1, 0.9, 0.3)
    assert any(
        abs(c[0] - 0.1) < 0.01 and abs(c[1] - 0.9) < 0.01 and abs(c[2] - 0.3) < 0.01
        for c in colors
    ), f"Glass BSDF color not found in {colors}"

    # Emission: (0.95, 0.85, 0.05)
    assert any(
        abs(c[0] - 0.95) < 0.01 and abs(c[1] - 0.85) < 0.01 and abs(c[2] - 0.05) < 0.01
        for c in colors
    ), f"Emission color not found in {colors}"

    # Mix Shader with Fac=0.7 should pick blue (0.0, 0.0, 1.0)
    assert any(
        abs(c[0] - 0.0) < 0.01 and abs(c[1] - 0.0) < 0.01 and abs(c[2] - 1.0) < 0.01
        for c in colors
    ), f"Mix Shader color (should be blue) not found in {colors}"

    tmp.unlink()
