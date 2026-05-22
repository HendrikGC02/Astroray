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
