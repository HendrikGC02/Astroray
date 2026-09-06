"""pkg59 follow-up — Vector input → coord_mode + UV transform plumbing.

The previous PR (#164) routed Image Texture → Principled BSDF Base Color
into a textured Lambertian, fixing the project-owner's missing-texture
screenshot. This package walks the upstream **Vector** input chain on
TEX_IMAGE / procedural texture nodes so that:

- ``Texture Coordinate.UV`` / ``.Generated`` / ``.Object`` is honored via
  ``renderer.set_texture_coord_mode``.
- ``Mapping(Location, Scale)`` is baked into a per-texture UV transform
  via ``renderer.set_texture_uv_transform``.

Mapping rotation and the UV-debug AOV are covered by earlier follow-ups; named
UV layer routing is tested separately.

Tests use the same Blender API stub pattern as the other addon tests.
"""

import importlib.util
import sys
import types
from pathlib import Path


# ---------------------------------------------------------------------------
# Loader (matches test_blender_principled_texture.py / test_blender_viewport_session.py)
# ---------------------------------------------------------------------------

def _load_blender_addon(monkeypatch):
    bpy_module = types.ModuleType("bpy")
    bpy_types_module = types.ModuleType("bpy.types")
    bpy_props_module = types.ModuleType("bpy.props")

    class _Base: pass
    class _RenderEngineBase:
        def report(self, *_a, **_k): return None
        def update_progress(self, *_a, **_k): return None
        def test_break(self): return False
        def bind_display_space_shader(self, *_a, **_k): return None
        def unbind_display_space_shader(self, *_a, **_k): return None

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
    mathutils_module.Vector = lambda values: values

    astroray_module = types.ModuleType("astroray")
    astroray_module.__version__ = "test"
    astroray_module.__features__ = {"cuda": False, "spectral": True}
    astroray_module.__file__ = "/fake/astroray.pyd"
    astroray_module.integrator_registry_names = lambda: ["path_tracer"]
    astroray_module.material_registry_names = lambda: ["lambertian", "disney"]
    astroray_module.pass_registry_names = lambda: []

    monkeypatch.setitem(sys.modules, "bpy", bpy_module)
    monkeypatch.setitem(sys.modules, "bpy.types", bpy_types_module)
    monkeypatch.setitem(sys.modules, "bpy.props", bpy_props_module)
    monkeypatch.setitem(sys.modules, "shader_blending", shader_blending_module)
    monkeypatch.setitem(sys.modules, "mathutils", mathutils_module)
    monkeypatch.setitem(sys.modules, "astroray", astroray_module)

    module_path = Path(__file__).parent.parent / "blender_addon" / "__init__.py"
    spec = importlib.util.spec_from_file_location("astroray_blender_addon_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Stubs for Blender node-tree primitives
# ---------------------------------------------------------------------------

class _Socket:
    def __init__(self, default=0.0, linked_to=None, output_name="Color"):
        self.default_value = default
        self.is_linked = linked_to is not None
        self.links = []
        if linked_to is not None:
            self.links.append(types.SimpleNamespace(
                from_node=linked_to,
                from_socket=types.SimpleNamespace(name=output_name),
            ))


class _Node:
    def __init__(self, ntype, inputs=None, **extra):
        self.type = ntype
        self.inputs = inputs or {}
        for k, v in extra.items():
            setattr(self, k, v)


class _FakeImage:
    def __init__(self, name="tex.png", w=4, h=4):
        self.name = name
        self.size = (w, h)
        self.has_data = True
        self.pixels = [0.5] * (w * h * 4)
    def reload(self): pass


class _RecordingRenderer:
    def __init__(self):
        self.loaded_textures = []
        self.coord_mode_calls = []     # (name, mode)
        self.uv_transform_calls = []   # (name, sx, sy, ox, oy)
        self.mapping_matrix_calls = [] # (name, [12 floats])  pkg219a
        self.uv_layer_calls = []       # (name, layer)
        self.proc_texture_calls = []   # (name, type, params)
        self.created_materials = []
        self._next_id = 1

    def load_texture(self, name, rgb, w, h):
        self.loaded_textures.append((name, w, h))

    def set_texture_coord_mode(self, name, mode):
        self.coord_mode_calls.append((name, mode))

    def set_texture_uv_transform(self, name, sx, sy, ox, oy, rotation=0.0):
        self.uv_transform_calls.append((name, sx, sy, ox, oy, rotation))

    def set_texture_mapping_matrix(self, name, matrix):
        self.mapping_matrix_calls.append((name, list(matrix)))

    def set_texture_uv_layer(self, name, layer):
        self.uv_layer_calls.append((name, layer))

    def create_procedural_texture(self, name, ttype, params):
        self.proc_texture_calls.append((name, ttype, list(params)))

    def create_material(self, mat_type, color, params):
        self.created_materials.append((mat_type, list(color), dict(params)))
        mid = self._next_id
        self._next_id += 1
        return mid


# ---------------------------------------------------------------------------
# 1. _resolve_vector_input — node-graph walks
# ---------------------------------------------------------------------------

def test_resolve_vector_input_unlinked_returns_default(monkeypatch):
    """Unlinked Vector socket → ('UV', (1,1), (0,0))."""
    addon = _load_blender_addon(monkeypatch)
    cls = addon.CustomRaytracerRenderEngine
    socket = _Socket()  # not linked
    coord, scale, offset, rotation, layer = cls._resolve_vector_input(socket)
    assert coord == "UV"
    assert scale == (1.0, 1.0)
    assert offset == (0.0, 0.0)


def test_resolve_vector_input_uv_default(monkeypatch):
    """Texture Coordinate.UV → ('UV', (1,1), (0,0))."""
    addon = _load_blender_addon(monkeypatch)
    cls = addon.CustomRaytracerRenderEngine
    tc = _Node('TEX_COORD')
    socket = _Socket(linked_to=tc, output_name='UV')
    coord, _scale, _offset, _rotation, layer = cls._resolve_vector_input(socket)
    assert coord == "UV"


def test_resolve_vector_input_generated(monkeypatch):
    """Texture Coordinate.Generated → 'GENERATED' coord_mode."""
    addon = _load_blender_addon(monkeypatch)
    cls = addon.CustomRaytracerRenderEngine
    tc = _Node('TEX_COORD')
    socket = _Socket(linked_to=tc, output_name='Generated')
    coord, _scale, _offset, _rotation, layer = cls._resolve_vector_input(socket)
    assert coord == "GENERATED"


def test_resolve_vector_input_object(monkeypatch):
    addon = _load_blender_addon(monkeypatch)
    cls = addon.CustomRaytracerRenderEngine
    tc = _Node('TEX_COORD')
    socket = _Socket(linked_to=tc, output_name='Object')
    coord, _scale, _offset, _rotation, layer = cls._resolve_vector_input(socket)
    assert coord == "OBJECT"


def test_resolve_vector_input_mapping_scale_only(monkeypatch):
    """Mapping(Scale=(2,3,1)) without an upstream coord source → 'UV' coord
    mode + (2,3) scale."""
    addon = _load_blender_addon(monkeypatch)
    cls = addon.CustomRaytracerRenderEngine
    mapping = _Node('MAPPING', inputs={
        'Vector': _Socket(linked_to=_Node('TEX_COORD'), output_name='UV'),  # explicit varying UV coordinates
        'Location': _Socket(default=(0.0, 0.0, 0.0)),
        'Scale': _Socket(default=(2.0, 3.0, 1.0)),
    })
    socket = _Socket(linked_to=mapping, output_name='Vector')
    coord, scale, offset, rotation, layer = cls._resolve_vector_input(socket)
    assert coord == "UV"
    assert scale == (2.0, 3.0)
    assert offset == (0.0, 0.0)


def test_resolve_vector_input_mapping_offset(monkeypatch):
    addon = _load_blender_addon(monkeypatch)
    cls = addon.CustomRaytracerRenderEngine
    mapping = _Node('MAPPING', inputs={
        'Vector': _Socket(linked_to=_Node('TEX_COORD'), output_name='UV'),
        'Location': _Socket(default=(0.5, -0.25, 0.0)),
        'Scale': _Socket(default=(1.0, 1.0, 1.0)),
    })
    socket = _Socket(linked_to=mapping, output_name='Vector')
    _coord, scale, offset, _rotation, layer = cls._resolve_vector_input(socket)
    assert scale == (1.0, 1.0)
    assert offset == (0.5, -0.25)


def test_resolve_vector_input_mapping_chained_with_generated(monkeypatch):
    """Texture Coordinate.Generated → Mapping(Scale=2) → texture must combine
    'GENERATED' coord-mode with the scale transform."""
    addon = _load_blender_addon(monkeypatch)
    cls = addon.CustomRaytracerRenderEngine
    tc = _Node('TEX_COORD')
    mapping = _Node('MAPPING', inputs={
        'Vector':   _Socket(linked_to=tc, output_name='Generated'),
        'Location': _Socket(default=(0.0, 0.0, 0.0)),
        'Scale':    _Socket(default=(2.0, 2.0, 1.0)),
    })
    socket = _Socket(linked_to=mapping, output_name='Vector')
    coord, scale, _offset, _rotation, layer = cls._resolve_vector_input(socket)
    assert coord == "GENERATED"
    assert scale == (2.0, 2.0)


def test_resolve_vector_input_depth_limit(monkeypatch):
    """Pathologically deep Mapping chains return defaults instead of looping
    forever."""
    addon = _load_blender_addon(monkeypatch)
    cls = addon.CustomRaytracerRenderEngine

    # 8-deep Mapping chain. _resolve_vector_input gives up at depth>4.
    inner = None
    for _ in range(8):
        inner = _Node('MAPPING', inputs={
            'Vector': _Socket(linked_to=inner, output_name='Vector') if inner else _Socket(),
            'Location': _Socket(default=(0.0, 0.0, 0.0)),
            'Scale': _Socket(default=(1.0, 1.0, 1.0)),
        })
    socket = _Socket(linked_to=inner, output_name='Vector')
    coord, scale, offset, rotation, layer = cls._resolve_vector_input(socket)
    # The outer-most Mapping still applies its own Scale; deeper ones get
    # cut off, but the outer (depth=0) Scale should still be honored.
    assert coord == "UV"
    assert scale == (1.0, 1.0)
    assert offset == (0.0, 0.0)


# ---------------------------------------------------------------------------
# 2. load_blender_image plumbs the resolved transform through
# ---------------------------------------------------------------------------

def test_load_blender_image_default_no_extra_calls(monkeypatch):
    """No Vector input → no set_texture_coord_mode / set_texture_uv_transform."""
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    renderer = _RecordingRenderer()
    image = _FakeImage(name="plain.png")
    name = engine.load_blender_image(image, renderer)
    assert name == "plain.png"
    assert renderer.loaded_textures == [("plain.png", 4, 4)]
    assert renderer.coord_mode_calls == []
    assert renderer.uv_transform_calls == []


def test_load_blender_image_with_mapping_applies_transform(monkeypatch):
    """pkg219a: a Mapping(Scale=2) on the Vector input now results in a
    set_texture_mapping_matrix call (the full 3-D matrix supersedes the old
    2-D set_texture_uv_transform — see pkg219a). Original intent (pkg59): the
    Mapping transform reaches the C++ side and the cache key is transform-
    distinct so the same image with a different Mapping does not collide."""
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    renderer = _RecordingRenderer()
    image = _FakeImage(name="brick.png")
    mapping = _Node('MAPPING', inputs={
        'Vector':   _Socket(linked_to=_Node('TEX_COORD'), output_name='UV'),  # explicit varying UV coordinates
        'Location': _Socket(default=(0.0, 0.0, 0.0)),
        'Scale':    _Socket(default=(2.0, 2.0, 1.0)),
    })
    vector_inp = _Socket(linked_to=mapping, output_name='Vector')
    name = engine.load_blender_image(image, renderer, vector_input=vector_inp)
    # Transform-distinct cache key, not the bare image name.
    assert name != "brick.png"
    assert "brick.png" in name
    # pkg219a: routes to the full 3-D mapping matrix, not the 2-D transform.
    assert renderer.uv_transform_calls == []
    assert len(renderer.mapping_matrix_calls) == 1
    n, m = renderer.mapping_matrix_calls[0]
    assert n == name
    # M = Translate(0)*Rot(0)*Scale(2,2,1) → diag scale on the top 3x4.
    assert abs(m[0] - 2.0) < 1e-6 and abs(m[5] - 2.0) < 1e-6 and abs(m[10] - 1.0) < 1e-6
    assert abs(m[3]) < 1e-6 and abs(m[7]) < 1e-6 and abs(m[11]) < 1e-6
    # Default coord_mode 'UV' → no set_texture_coord_mode call.
    assert renderer.coord_mode_calls == []


def test_load_blender_image_with_generated_coord(monkeypatch):
    """Texture Coordinate.Generated → set_texture_coord_mode('GENERATED')."""
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    renderer = _RecordingRenderer()
    image = _FakeImage(name="gradient.png")
    tc = _Node('TEX_COORD')
    vector_inp = _Socket(linked_to=tc, output_name='Generated')
    name = engine.load_blender_image(image, renderer, vector_input=vector_inp)
    assert renderer.coord_mode_calls == [(name, "GENERATED")]
    # Identity transform → no UV transform call.
    assert renderer.uv_transform_calls == []


def test_load_blender_image_caches_per_transform(monkeypatch):
    """Same image, two different Mapping nodes → two distinct uploads, two
    distinct cache keys, two distinct C++ texture entries. Same image with
    NO mapping reuses the bare-name cache entry."""
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    renderer = _RecordingRenderer()
    image = _FakeImage(name="albedo.png")

    # First: no Mapping.
    n1 = engine.load_blender_image(image, renderer)
    # Second: Mapping(Scale=2).
    mapping = _Node('MAPPING', inputs={
        'Vector':   _Socket(linked_to=_Node('TEX_COORD'), output_name='UV'),
        'Location': _Socket(default=(0.0, 0.0, 0.0)),
        'Scale':    _Socket(default=(2.0, 2.0, 1.0)),
    })
    n2 = engine.load_blender_image(image, renderer,
                                   vector_input=_Socket(linked_to=mapping, output_name='Vector'))
    # Third: same Mapping(Scale=2) → cache hit; should NOT upload again.
    n3 = engine.load_blender_image(image, renderer,
                                   vector_input=_Socket(linked_to=mapping, output_name='Vector'))
    assert n1 == "albedo.png"
    assert n2 != n1
    assert n3 == n2
    # Two distinct uploads (the third was a cache hit).
    upload_names = [t[0] for t in renderer.loaded_textures]
    assert upload_names == [n1, n2]


# ---------------------------------------------------------------------------
# 3. Mapping rotation (pkg59 finishing-touch)
# ---------------------------------------------------------------------------

def test_resolve_vector_input_mapping_rotation_z(monkeypatch):
    """Mapping(Rotation=(0, 0, pi/4)) must produce rotation=pi/4 radians.
    X and Y components are intentionally ignored — they have no 2D-effective
    meaning on UV coordinates."""
    import math
    addon = _load_blender_addon(monkeypatch)
    cls = addon.CustomRaytracerRenderEngine
    mapping = _Node('MAPPING', inputs={
        'Vector':   _Socket(linked_to=_Node('TEX_COORD'), output_name='UV'),
        'Location': _Socket(default=(0.0, 0.0, 0.0)),
        'Rotation': _Socket(default=(0.0, 0.0, math.pi / 4)),
        'Scale':    _Socket(default=(1.0, 1.0, 1.0)),
    })
    socket = _Socket(linked_to=mapping, output_name='Vector')
    coord, scale, offset, rotation, layer = cls._resolve_vector_input(socket)
    assert coord == "UV"
    assert scale == (1.0, 1.0)
    assert offset == (0.0, 0.0)
    assert abs(rotation - math.pi / 4) < 1e-6


def test_load_blender_image_with_mapping_rotation_passes_through(monkeypatch):
    """pkg219a: a Mapping with Z rotation now routes through
    set_texture_mapping_matrix; the top-left 2x2 of the 3x4 carries the
    rotation (supersedes the old rotation-in-radians 2-D transform arg)."""
    import math
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    renderer = _RecordingRenderer()
    image = _FakeImage(name="rotated.png")
    mapping = _Node('MAPPING', inputs={
        'Vector':   _Socket(linked_to=_Node('TEX_COORD'), output_name='UV'),
        'Location': _Socket(default=(0.0, 0.0, 0.0)),
        'Rotation': _Socket(default=(0.0, 0.0, math.pi / 6)),
        'Scale':    _Socket(default=(1.0, 1.0, 1.0)),
    })
    name = engine.load_blender_image(
        image, renderer,
        vector_input=_Socket(linked_to=mapping, output_name='Vector')
    )
    assert name != "rotated.png"  # rotation is non-default → distinct cache key
    assert renderer.uv_transform_calls == []
    assert len(renderer.mapping_matrix_calls) == 1
    n, m = renderer.mapping_matrix_calls[0]
    assert n == name
    c, s = math.cos(math.pi / 6), math.sin(math.pi / 6)
    # Rz(pi/6) on the top-left 2x2, row-major 3x4.
    assert abs(m[0] - c) < 1e-6 and abs(m[1] + s) < 1e-6
    assert abs(m[4] - s) < 1e-6 and abs(m[5] - c) < 1e-6


def test_resolve_vector_input_mapping_full_combo(monkeypatch):
    """Scale + offset + rotation in a single Mapping node must all flow
    through together."""
    import math
    addon = _load_blender_addon(monkeypatch)
    cls = addon.CustomRaytracerRenderEngine
    mapping = _Node('MAPPING', inputs={
        'Vector':   _Socket(linked_to=_Node('TEX_COORD'), output_name='UV'),
        'Location': _Socket(default=(0.5, -0.25, 0.0)),
        'Rotation': _Socket(default=(0.0, 0.0, math.pi / 2)),
        'Scale':    _Socket(default=(2.0, 3.0, 1.0)),
    })
    socket = _Socket(linked_to=mapping, output_name='Vector')
    coord, scale, offset, rotation, layer = cls._resolve_vector_input(socket)
    assert coord == "UV"
    assert scale == (2.0, 3.0)
    assert offset == (0.5, -0.25)
    assert abs(rotation - math.pi / 2) < 1e-6


def test_apply_texture_transform_skips_identity_with_zero_rotation(monkeypatch):
    """rotation=0 + scale=(1,1) + offset=(0,0) must NOT call
    set_texture_uv_transform. Otherwise we'd pay the call (and a cache-key
    diversion) for every default-mapping texture."""
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    renderer = _RecordingRenderer()
    engine._apply_texture_transform(
        renderer, "tex", "UV", (1.0, 1.0), (0.0, 0.0), 0.0
    )
    assert renderer.uv_transform_calls == []
    assert renderer.coord_mode_calls == []


# ---------------------------------------------------------------------------
# pkg115 item 10 — ShaderNodeTexVoronoi translation
#
# The C++ VoronoiTexture feature enum changed in pkg115 chunk 4 (PR #445):
#   0=F1, 1=Smooth F1, 2=F2, 3=Distance to Edge, 4=N-Sphere Radius.
# These tests pin the addon's feature/metric/normalize mapping and the full
# Cycles-parity param vector so the stale-enum class of regression (which CI
# cannot catch -- no Blender in CI) fails loudly here instead.
# ---------------------------------------------------------------------------

def _voronoi_node(feature='F1', distance='EUCLIDEAN', normalize=False):
    return _Node('TEX_VORONOI', inputs={
        'Vector':     _Socket(),  # unlinked -> GENERATED
        'Scale':      _Socket(default=6.0),
        'Detail':     _Socket(default=3.0),
        'Roughness':  _Socket(default=0.7),
        'Lacunarity': _Socket(default=2.5),
        'Smoothness': _Socket(default=0.8),
        'Exponent':   _Socket(default=1.5),
        'Randomness': _Socket(default=0.9),
    }, feature=feature, distance=distance, normalize=normalize)


def test_voronoi_translation_param_vector(monkeypatch):
    """Full 16-float Cycles-parity vector in the documented order:
       [scale, randomness, dist_metric, feature, smoothness,
        r1,g1,b1, r2,g2,b2, detail, roughness, lacunarity, exponent, normalize]."""
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    renderer = _RecordingRenderer()
    node = _voronoi_node(feature='F2', distance='MINKOWSKI', normalize=True)
    engine.load_procedural_texture(node, renderer, vector_input=node.inputs['Vector'])

    assert len(renderer.proc_texture_calls) == 1
    name, ttype, params = renderer.proc_texture_calls[0]
    assert ttype == 'voronoi'
    assert len(params) == 16, f"expected 16 params, got {len(params)}: {params}"
    scale, rand, dm, feat, smooth = params[0:5]
    colors = params[5:11]
    detail, rough, lac, expo, norm = params[11:16]
    assert (scale, rand, smooth) == (6.0, 0.9, 0.8)
    assert dm == 3.0, "MINKOWSKI must map to metric index 3"
    assert feat == 2.0, "F2 must map to feature index 2 (new enum), not the legacy 1"
    assert colors == [0, 0, 0, 1, 1, 1]
    assert (detail, rough, lac, expo) == (3.0, 0.7, 2.5, 1.5)
    assert norm == 1.0, "normalize=True must pass 1.0"


def test_voronoi_feature_enum_matches_cpp(monkeypatch):
    """Every Blender feature value maps to the matching C++ VoronoiTexture index."""
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    expected = {'F1': 0.0, 'SMOOTH_F1': 1.0, 'F2': 2.0,
                'DISTANCE_TO_EDGE': 3.0, 'N_SPHERE_RADIUS': 4.0}
    for feature, idx in expected.items():
        renderer = _RecordingRenderer()
        node = _voronoi_node(feature=feature)
        engine.load_procedural_texture(node, renderer, vector_input=node.inputs['Vector'])
        _n, _t, params = renderer.proc_texture_calls[0]
        assert params[3] == idx, f"{feature} -> {params[3]}, expected {idx}"
