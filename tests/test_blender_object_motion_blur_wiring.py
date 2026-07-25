"""pkg88 Phase B — object motion blur addon bake.

Verifies that convert_scene captures each real (non-dupli) object's
matrix_world at shutter CLOSE (mirroring how Phase A/pkg103b already
resolves shutter/shutter_position for the camera) and that convert_objects
routes a genuinely moving object through `add_triangles_bulk_motion`
while a static object -- or a dupli/particle instance, which pkg88-B
deliberately does not attempt to motion-bake -- keeps using the
pre-pkg88-B `add_triangles_bulk` path unchanged.

Same mock-bpy pattern as test_blender_camera_motion_blur_wiring.py.
"""

import importlib.util
import sys
import types
from pathlib import Path

import numpy as np
import pytest


IDENTITY_ROWS = [[1.0, 0.0, 0.0, 0.0],
                 [0.0, 1.0, 0.0, 0.0],
                 [0.0, 0.0, 1.0, 0.0],
                 [0.0, 0.0, 0.0, 1.0]]


def _translated_rows(dx=0.0, dy=0.0, dz=0.0):
    return [[1.0, 0.0, 0.0, dx],
            [0.0, 1.0, 0.0, dy],
            [0.0, 0.0, 1.0, dz],
            [0.0, 0.0, 0.0, 1.0]]


class MockMatrix3:
    def __init__(self, rows):
        self._rows = rows

    def inverted_safe(self):
        return self

    def transposed(self):
        return self

    def __array__(self, dtype=None):
        return np.array(self._rows, dtype=dtype or np.float32)


class MockMatrix4:
    """Minimal 4x4 matrix stand-in: supports the [r][c] indexing
    `_matrices_differ` uses, `np.asarray()` conversion (via __array__,
    the protocol `mesh_to_bulk_arrays`/`mesh_world_positions` rely on),
    and `.to_3x3()` for convert_objects' normal-matrix computation."""
    def __init__(self, rows):
        self._rows = [list(r) for r in rows]

    def __getitem__(self, i):
        return self._rows[i]

    def __len__(self):
        return 4

    def __array__(self, dtype=None):
        return np.array(self._rows, dtype=dtype or np.float32)

    def to_3x3(self):
        return MockMatrix3([row[:3] for row in self._rows[:3]])

    def copy(self):
        return MockMatrix4(self._rows)


class _UVLayers:
    active = None

    def __iter__(self):
        return iter([])


class _FakeMesh:
    """Deliberately minimal: convert_objects' geometry EXTRACTION
    (`mesh_to_bulk_arrays` / `mesh_world_positions`) is monkeypatched out
    in these tests, so this stub only needs to survive the surrounding
    convert_objects bookkeeping (calc_loop_triangles, uv_layer scan,
    n_tri via len(loop_triangles))."""
    def __init__(self, n_tri=1):
        self.loop_triangles = list(range(n_tri))
        self.loops = []
        self.uv_layers = _UVLayers()

    def calc_loop_triangles(self):
        pass


class _FakeObj:
    def __init__(self, name, mesh):
        self.name = name
        self.type = 'MESH'
        self.data = mesh
        self.material_slots = []
        self.pass_index = 0


class _FakeInstance:
    def __init__(self, obj, matrix_world, is_instance=False):
        self.object = obj
        self.matrix_world = matrix_world
        self.is_instance = is_instance


def _load_blender_addon(monkeypatch, renderer_cls):
    """Same pattern as test_blender_camera_motion_blur_wiring.py /
    test_blender_light_sampler_wiring.py."""
    bpy_module = types.ModuleType("bpy")
    bpy_types_module = types.ModuleType("bpy.types")
    bpy_props_module = types.ModuleType("bpy.props")

    class _Base:
        pass

    class _RenderEngineBase:
        def report(self, *_args, **_kwargs):
            return None
        def update_progress(self, *_args, **_kwargs):
            return None
        def test_break(self):
            return False

    bpy_types_module.Panel = _Base
    bpy_types_module.Operator = _Base
    bpy_types_module.AddonPreferences = _Base
    bpy_types_module.PropertyGroup = _Base
    bpy_types_module.RenderEngine = _RenderEngineBase
    bpy_module.types = bpy_types_module

    for name in ("BoolProperty", "IntProperty", "FloatProperty", "StringProperty",
                 "PointerProperty", "FloatVectorProperty", "EnumProperty"):
        setattr(bpy_props_module, name, lambda **_kwargs: None)

    bpy_module.props = bpy_props_module
    bpy_module.path = types.SimpleNamespace(abspath=lambda p: p)

    shader_blending_module = types.ModuleType("shader_blending")
    shader_blending_module.blend_shader_specs = {}
    shader_blending_module.add_shader_specs = {}

    mathutils_module = types.ModuleType("mathutils")
    mathutils_module.Vector = lambda xyz: xyz
    mathutils_module.Quaternion = lambda wxyz: wxyz
    mathutils_module.Matrix = MockMatrix4

    astroray_module = types.ModuleType("astroray")
    astroray_module.__version__ = "test"
    astroray_module.__features__ = {"cuda": False, "spectral": True}
    astroray_module.__file__ = "/fake/astroray.pyd"
    astroray_module.Renderer = renderer_cls
    astroray_module.integrator_registry_names = lambda: ["path_tracer"]
    astroray_module.integrator_capabilities = lambda name: {
        "gpuSupported": False, "gpuFallbackReason": "test",
    }
    astroray_module.material_registry_names = lambda: ["lambertian"]
    astroray_module.pass_registry_names = lambda: []

    monkeypatch.setitem(sys.modules, "bpy", bpy_module)
    monkeypatch.setitem(sys.modules, "bpy.types", bpy_types_module)
    monkeypatch.setitem(sys.modules, "bpy.props", bpy_props_module)
    monkeypatch.setitem(sys.modules, "shader_blending", shader_blending_module)
    monkeypatch.setitem(sys.modules, "mathutils", mathutils_module)
    monkeypatch.setitem(sys.modules, "astroray", astroray_module)

    module_path = Path(__file__).parent.parent / "blender_addon" / "__init__.py"
    spec = importlib.util.spec_from_file_location("astroray_blender_addon_test_pkg88b", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _make_renderer_cls(calls):
    class MockRenderer:
        gpu_available = False
        def clear(self): pass
        def set_clamp_direct(self, v): pass
        def set_clamp_indirect(self, v): pass
        def set_filter_glossy(self, v): pass
        def set_use_reflective_caustics(self, v): pass
        def set_use_refractive_caustics(self, v): pass
        def set_light_sampler(self, mode): pass
        def set_film_exposure(self, v): pass
        def set_use_transparent_film(self, v): pass
        def set_transparent_glass(self, v): pass
        def set_seed(self, v): pass
        def set_pixel_filter(self, t, w): pass
        def set_camera_motion_blur(self, *a, **k): pass
        def add_triangles_bulk(self, *args):
            calls.append(('static', args))
        def add_triangles_bulk_motion(self, *args):
            calls.append(('motion', args))
    return MockRenderer


_STATIC_ARRAYS = (
    np.zeros((1, 3, 3), dtype=np.float32),   # positions
    np.zeros((1,), dtype=np.int32),          # material_ids
    np.zeros((1,), dtype=np.int32),          # material_pass_indices
    np.zeros((0,), dtype=np.float32),        # uvs
    [],                                      # uv_names
    np.zeros((0,), dtype=np.float32),        # normals
)
# Distinguishable per-matrix markers, so a test can prove WHICH pose each
# emitted array was built from (the pkg88-B regression was positions_start
# silently being the current-frame pose instead of the shutter-open pose).
_START_POSE_POSITIONS = np.full((1, 3, 3), 7.0, dtype=np.float32)
_END_POSE_POSITIONS = np.full((1, 3, 3), 9.0, dtype=np.float32)


def _patch_geometry_stubs(addon, monkeypatch, motion_should_be_called):
    monkeypatch.setattr(addon, 'mesh_to_bulk_arrays', lambda *a, **k: _STATIC_ARRAYS)

    def _mesh_world_positions(mesh, matrix, *a, **k):
        assert motion_should_be_called, "mesh_world_positions must not run for a static/skip object"
        # Key off the matrix's x-translation so the caller can assert that
        # positions_start came from the START matrix, not the current pose.
        return _END_POSE_POSITIONS if matrix[0][3] > 0.5 else _START_POSE_POSITIONS
    monkeypatch.setattr(addon, 'mesh_world_positions', _mesh_world_positions)


# ---------------------------------------------------------------------------
# convert_objects dispatch: static vs motion, and the dupli/instance guard.
# ---------------------------------------------------------------------------

def test_convert_objects_static_object_uses_bulk_not_motion(monkeypatch):
    calls = []
    RendererCls = _make_renderer_cls(calls)
    addon = _load_blender_addon(monkeypatch, RendererCls)
    _patch_geometry_stubs(addon, monkeypatch, motion_should_be_called=False)
    engine = addon.CustomRaytracerRenderEngine()

    mesh = _FakeMesh()
    obj = _FakeObj('Cube', mesh)
    inst = _FakeInstance(obj, MockMatrix4(IDENTITY_ROWS), is_instance=False)
    depsgraph = types.SimpleNamespace(object_instances=[inst])

    # Identical pose at both shutter boundaries -> no motion (Requirement 2:
    # zero behavioural change for static objects).
    start_matrices = {'Cube': MockMatrix4(IDENTITY_ROWS)}
    end_matrices = {'Cube': MockMatrix4(IDENTITY_ROWS)}
    engine.convert_objects(depsgraph, RendererCls(), {}, start_matrices, end_matrices)

    assert [c[0] for c in calls] == ['static'], (
        f"static object must use add_triangles_bulk only, got {[c[0] for c in calls]}"
    )


def test_convert_objects_no_motion_dict_uses_bulk_not_motion(monkeypatch):
    """motion_*_matrices=None/{} (motion blur off, or the exporter.py
    viewport-sync call site which never passes them) must reproduce the
    exact pre-pkg88-B call, regardless of object animation."""
    calls = []
    RendererCls = _make_renderer_cls(calls)
    addon = _load_blender_addon(monkeypatch, RendererCls)
    _patch_geometry_stubs(addon, monkeypatch, motion_should_be_called=False)
    engine = addon.CustomRaytracerRenderEngine()

    mesh = _FakeMesh()
    obj = _FakeObj('Cube', mesh)
    inst = _FakeInstance(obj, MockMatrix4(IDENTITY_ROWS), is_instance=False)
    depsgraph = types.SimpleNamespace(object_instances=[inst])

    engine.convert_objects(depsgraph, RendererCls(), {})  # defaulted motion dicts

    assert [c[0] for c in calls] == ['static']


def test_convert_objects_moving_object_uses_bulk_motion(monkeypatch):
    calls = []
    RendererCls = _make_renderer_cls(calls)
    addon = _load_blender_addon(monkeypatch, RendererCls)
    _patch_geometry_stubs(addon, monkeypatch, motion_should_be_called=True)
    engine = addon.CustomRaytracerRenderEngine()

    mesh = _FakeMesh()
    obj = _FakeObj('Cube', mesh)
    inst = _FakeInstance(obj, MockMatrix4(IDENTITY_ROWS), is_instance=False)
    depsgraph = types.SimpleNamespace(object_instances=[inst])

    # Shutter-open pose is NOT the current pose (identity) -- it is its own
    # sampled matrix. This is the regression guard: the first implementation
    # passed mesh_to_bulk_arrays' current-frame `positions` as positions_start.
    start_matrices = {'Cube': MockMatrix4(_translated_rows(dx=-0.6))}
    end_matrices = {'Cube': MockMatrix4(_translated_rows(dx=1.2))}
    engine.convert_objects(depsgraph, RendererCls(), {}, start_matrices, end_matrices)

    assert [c[0] for c in calls] == ['motion'], (
        f"moving object must use add_triangles_bulk_motion, got {[c[0] for c in calls]}"
    )
    _, args = calls[0]
    positions_start, positions_end = args[0], args[1]
    np.testing.assert_array_equal(positions_start, _START_POSE_POSITIONS)
    np.testing.assert_array_equal(positions_end, _END_POSE_POSITIONS)
    assert not np.array_equal(positions_start, _STATIC_ARRAYS[0]), (
        "positions_start must be built from the SHUTTER-OPEN matrix, not from "
        "mesh_to_bulk_arrays' current-frame positions"
    )


def test_convert_objects_dupli_instance_not_motion_baked(monkeypatch):
    """Requirement 3: an animated (matrix differs at shutter close) object
    that is a dupli/particle instance (is_instance=True) must NOT be
    motion-baked by pkg88-B -- see convert_objects' docstring for why
    (reliably re-evaluating per-dupli identity at a different frame is out
    of scope for v1; pkg114 instancing owns/limits that surface)."""
    calls = []
    RendererCls = _make_renderer_cls(calls)
    addon = _load_blender_addon(monkeypatch, RendererCls)
    _patch_geometry_stubs(addon, monkeypatch, motion_should_be_called=False)
    engine = addon.CustomRaytracerRenderEngine()

    mesh = _FakeMesh()
    obj = _FakeObj('Particle', mesh)
    inst = _FakeInstance(obj, MockMatrix4(IDENTITY_ROWS), is_instance=True)
    depsgraph = types.SimpleNamespace(object_instances=[inst])

    # Even though 'Particle' has differing shutter poses, is_instance=True
    # must short-circuit before the lookup.
    start_matrices = {'Particle': MockMatrix4(IDENTITY_ROWS)}
    end_matrices = {'Particle': MockMatrix4(_translated_rows(dx=5.0))}
    engine.convert_objects(depsgraph, RendererCls(), {}, start_matrices, end_matrices)

    assert [c[0] for c in calls] == ['static'], (
        f"dupli instance must never be motion-baked by pkg88-B, got {[c[0] for c in calls]}"
    )


# ---------------------------------------------------------------------------
# convert_scene wiring: shutter-close snapshot capture + frame restore.
# ---------------------------------------------------------------------------

def _make_settings(**kwargs):
    defaults = {
        "device_mode": "auto", "wavelength_preset": "visible",
        "wavelength_min": 380.0, "wavelength_max": 780.0, "colourmap": "grayscale",
        "integrator_type": "path_tracer", "last_render_stats": "",
        "use_adaptive_sampling": False, "preview_samples": 1, "samples": 16,
        "max_bounces": 4, "clamp_direct": 0.0, "clamp_indirect": 0.0,
        "filter_glossy": 0.0, "use_reflective_caustics": True,
        "use_refractive_caustics": True, "diffuse_bounces": 2, "glossy_bounces": 2,
        "transmission_bounces": 2, "volume_bounces": 0, "transparent_bounces": 2,
        "light_sampler": "power",
    }
    defaults.update(kwargs)
    return types.SimpleNamespace(**defaults)


class _MovingSceneObj:
    """A depsgraph.objects entry whose matrix_world tracks
    `scene.frame_current + scene.frame_subframe` live, so re-evaluating it
    after a mock frame_set() actually changes value -- the same mechanism a
    real Blender depsgraph re-cook provides (Blender splits fractional
    frames into an int frame_current + a frame_subframe remainder)."""
    def __init__(self, name, scene):
        self.name = name
        self.type = 'MESH'
        self._scene = scene

    @property
    def matrix_world(self):
        f = float(self._scene.frame_current) + float(getattr(self._scene, 'frame_subframe', 0.0))
        return MockMatrix4(_translated_rows(dx=f))


def _make_convert_scene_stub_engine(monkeypatch, use_motion_blur, motion_blur_position='CENTER',
                                    motion_blur_shutter=0.5, frame_current=10):
    calls = []
    RendererCls = _make_renderer_cls([])
    addon = _load_blender_addon(monkeypatch, RendererCls)
    engine = addon.CustomRaytracerRenderEngine()

    settings = _make_settings()
    scene = types.SimpleNamespace(
        custom_raytracer=settings, cycles=None,
        render=types.SimpleNamespace(
            use_motion_blur=use_motion_blur,
            motion_blur_shutter=motion_blur_shutter,
            motion_blur_position=motion_blur_position,
        ),
        camera=None,  # isolate: no camera-transform mocking needed
        frame_current=frame_current,
        frame_subframe=0.0,
    )

    def _frame_set(frame, subframe):
        scene.frame_current = frame
        scene.frame_subframe = subframe
    scene.frame_set = _frame_set

    moving_obj = _MovingSceneObj('Cube', scene)
    depsgraph = types.SimpleNamespace(
        scene=scene, object_instances=[], objects=[moving_obj], update=lambda: None,
    )

    engine.setup_camera = lambda *a: None
    engine.convert_materials = lambda *a: {}
    engine.convert_objects = lambda *a: calls.append(a)
    engine.convert_lights = lambda *a: None
    engine.setup_world = lambda *a: None

    return engine, depsgraph, scene, calls


def test_convert_scene_no_motion_blur_yields_empty_motion_matrices(monkeypatch):
    engine, depsgraph, scene, calls = _make_convert_scene_stub_engine(
        monkeypatch, use_motion_blur=False)

    engine.convert_scene(depsgraph, _make_renderer_cls([])(), 16, 16)

    assert len(calls) == 1
    motion_start_matrices, motion_end_matrices = calls[0][3], calls[0][4]
    assert not motion_start_matrices, "use_motion_blur=False must not populate start matrices"
    assert not motion_end_matrices, "use_motion_blur=False must not populate end matrices"


@pytest.mark.parametrize("position,expected_start,expected_end", [
    ('START',  10.0,  10.5),
    ('CENTER',  9.75, 10.25),
    ('END',     9.5,  10.0),
])
def test_convert_scene_captures_both_shutter_boundaries(monkeypatch, position,
                                                        expected_start, expected_end):
    """BOTH shutter boundaries must be sampled at their own sub-frame time,
    for every shutter position. The stubbed _MovingSceneObj bakes its
    x-translation from frame_current + frame_subframe, so each captured
    matrix reveals exactly which instant it was sampled at.

    Regression guard: the first implementation sampled only t_end and reused
    the CURRENT pose as the shutter-open pose. That is wrong for CENTER
    (t_start = frame - shutter/2, not frame) and catastrophic for END, where
    t_end == frame makes the sampled matrix identical to the current pose so
    nothing ever registers as moving."""
    engine, depsgraph, scene, calls = _make_convert_scene_stub_engine(
        monkeypatch, use_motion_blur=True, motion_blur_position=position,
        motion_blur_shutter=0.5, frame_current=10)

    engine.convert_scene(depsgraph, _make_renderer_cls([])(), 16, 16)

    assert len(calls) == 1
    motion_start_matrices, motion_end_matrices = calls[0][3], calls[0][4]
    assert 'Cube' in motion_start_matrices and 'Cube' in motion_end_matrices
    got_start = motion_start_matrices['Cube'][0][3]
    got_end = motion_end_matrices['Cube'][0][3]
    assert got_start == expected_start, (
        f"{position}: shutter-OPEN pose must be sampled at t_start="
        f"{expected_start}, got {got_start}"
    )
    assert got_end == expected_end, (
        f"{position}: shutter-CLOSE pose must be sampled at t_end="
        f"{expected_end}, got {got_end}"
    )
    # The two boundary poses must differ, otherwise the object would never
    # register as moving (this is precisely how END silently no-op'd).
    assert got_start != got_end, (
        f"{position}: the two shutter poses are identical -- motion blur "
        "would be a silent no-op"
    )
    # Frame state must be restored (matches _get_camera_transform_at_time's
    # existing restore contract).
    assert scene.frame_current == 10
    assert scene.frame_subframe == 0.0
