"""pkg115 chunk 6 (addon dedup) — Blender procedural texture translation tests.

Verifies that the addon's load_procedural_texture method correctly translates
Blender's ShaderNodeTex* nodes onto the engine's create_procedural_texture
factory with Cycles-parity parameters. Complements test_blender_uv_plumbing.py
which tests the Voronoi translation (chunk 5).

Pattern: load the addon with the same stub approach as test_blender_uv_plumbing,
create a fake Blender node with realistic socket defaults, call
load_procedural_texture, and assert the recorded create_procedural_texture call
matches the expected param vector documented in blender_module.cpp.
"""

import importlib.util
import sys
import types
from pathlib import Path


# ---------------------------------------------------------------------------
# Loader (copied from test_blender_uv_plumbing.py)
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
# Node stubs
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


class _RecordingRenderer:
    def __init__(self):
        self.proc_texture_calls = []   # (name, type, params)
        self.coord_mode_calls = []     # (name, mode)
        self.uv_transform_calls = []   # (name, sx, sy, ox, oy, rotation)

    def create_procedural_texture(self, name, ttype, params):
        self.proc_texture_calls.append((name, ttype, list(params)))

    def set_texture_coord_mode(self, name, mode):
        self.coord_mode_calls.append((name, mode))

    def set_texture_uv_transform(self, name, sx, sy, ox, oy, rotation=0.0):
        self.uv_transform_calls.append((name, sx, sy, ox, oy, rotation))


# ---------------------------------------------------------------------------
# TEX_NOISE → noise_perlin (pkg115 chunk 2 + chunk 6)
# ---------------------------------------------------------------------------

def test_noise_translation_param_vector(monkeypatch):
    """ShaderNodeTexNoise → create_procedural_texture('noise_perlin', ...)
    with [scale, detail, roughness, lacunarity, offset, gain, distortion, noise_type, normalize]."""
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    renderer = _RecordingRenderer()
    node = _Node('TEX_NOISE', inputs={
        'Vector': _Socket(),  # unlinked → GENERATED
        'Scale': _Socket(default=6.0),
        'Detail': _Socket(default=3.0),
        'Roughness': _Socket(default=0.7),
        'Lacunarity': _Socket(default=2.5),
        'Offset': _Socket(default=0.1),
        'Gain': _Socket(default=1.2),
        'Distortion': _Socket(default=0.5),
    }, noise_type='RIDGED_MULTIFRACTAL', normalize=False)
    engine.load_procedural_texture(node, renderer, vector_input=node.inputs['Vector'])

    assert len(renderer.proc_texture_calls) == 1
    name, ttype, params = renderer.proc_texture_calls[0]
    assert ttype == 'noise_perlin'
    assert len(params) == 9, f"expected 9 params, got {len(params)}: {params}"
    scale, detail, rough, lac, offset, gain, dist, nt, norm = params
    assert (scale, detail, rough, lac, offset, gain, dist) == (6.0, 3.0, 0.7, 2.5, 0.1, 1.2, 0.5)
    assert nt == 2.0, "RIDGED_MULTIFRACTAL must map to noise_type index 2"
    assert norm == 0.0, "normalize=False must pass 0.0"


def test_noise_type_enum_matches_fractal_h(monkeypatch):
    """Every Blender noise_type value maps to the matching fractal_noise.h index."""
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    expected = {'FBM': 0.0, 'MULTIFRACTAL': 1.0, 'RIDGED_MULTIFRACTAL': 2.0,
                'HYBRID_MULTIFRACTAL': 3.0, 'HETERO_TERRAIN': 4.0}
    for noise_type, idx in expected.items():
        renderer = _RecordingRenderer()
        node = _Node('TEX_NOISE', inputs={
            'Vector': _Socket(),
            'Scale': _Socket(default=5.0),
            'Detail': _Socket(default=2.0),
            'Roughness': _Socket(default=0.5),
            'Lacunarity': _Socket(default=2.0),
            'Offset': _Socket(default=0.0),
            'Gain': _Socket(default=1.0),
            'Distortion': _Socket(default=0.0),
        }, noise_type=noise_type, normalize=True)
        engine.load_procedural_texture(node, renderer, vector_input=node.inputs['Vector'])
        _n, _t, params = renderer.proc_texture_calls[0]
        assert params[7] == idx, f"{noise_type} -> {params[7]}, expected {idx}"


# ---------------------------------------------------------------------------
# TEX_WAVE → wave (pkg115 chunk 3 + chunk 6)
# ---------------------------------------------------------------------------

def test_wave_translation_param_vector(monkeypatch):
    """ShaderNodeTexWave → create_procedural_texture('wave', ...)
    with [wave_type, bands_direction, rings_direction, profile, scale, distortion,
          detail, detail_scale, detail_roughness, phase_offset, r1,g1,b1, r2,g2,b2]."""
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    renderer = _RecordingRenderer()
    node = _Node('TEX_WAVE', inputs={
        'Vector': _Socket(),  # unlinked → GENERATED
        'Scale': _Socket(default=6.0),
        'Distortion': _Socket(default=0.5),
        'Detail': _Socket(default=3.0),
        'Detail Scale': _Socket(default=1.5),
        'Detail Roughness': _Socket(default=0.7),
        'Phase Offset': _Socket(default=0.25),
    }, wave_type='RINGS', bands_direction='DIAGONAL', rings_direction='SPHERICAL', wave_profile='TRI')
    engine.load_procedural_texture(node, renderer, vector_input=node.inputs['Vector'])

    assert len(renderer.proc_texture_calls) == 1
    name, ttype, params = renderer.proc_texture_calls[0]
    assert ttype == 'wave'
    assert len(params) == 16, f"expected 16 params, got {len(params)}: {params}"
    wt, bd, rd, prof, sc, dist, det, dsc, drough, phase = params[0:10]
    colors = params[10:16]
    assert wt == 1.0, "RINGS must map to wave_type 1"
    assert bd == 3.0, "DIAGONAL must map to bands_direction 3"
    assert rd == 3.0, "SPHERICAL must map to rings_direction 3"
    assert prof == 2.0, "TRI must map to profile 2"
    assert (sc, dist, det, dsc, drough, phase) == (6.0, 0.5, 3.0, 1.5, 0.7, 0.25)
    assert colors == [0,0,0, 1,1,1]


# ---------------------------------------------------------------------------
# TEX_BRICK → brick (pkg115 chunk 3 + chunk 6)
# ---------------------------------------------------------------------------

def test_brick_translation_param_vector(monkeypatch):
    """ShaderNodeTexBrick → create_procedural_texture('brick', ...)
    with [brick1_r,g,b, brick2_r,g,b, mortar_r,g,b, scale, mortar_size, mortar_smooth,
          bias, brick_width, row_height, offset_amount, offset_freq, squash, squash_freq]."""
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    renderer = _RecordingRenderer()
    node = _Node('TEX_BRICK', inputs={
        'Vector': _Socket(),  # unlinked → GENERATED
        'Color1': _Socket(default=(0.9, 0.4, 0.3, 1.0)),
        'Color2': _Socket(default=(0.7, 0.3, 0.2, 1.0)),
        'Color3': _Socket(default=(0.1, 0.1, 0.1, 1.0)),
        'Scale': _Socket(default=6.0),
        'Mortar Size': _Socket(default=0.03),
        'Mortar Smooth': _Socket(default=0.15),
        'Bias': _Socket(default=0.1),
        'Brick Width': _Socket(default=0.6),
        'Row Height': _Socket(default=0.3),
        'Offset': _Socket(default=0.6),
    }, offset_frequency=3, squash=0.8, squash_frequency=4)
    engine.load_procedural_texture(node, renderer, vector_input=node.inputs['Vector'])

    assert len(renderer.proc_texture_calls) == 1
    name, ttype, params = renderer.proc_texture_calls[0]
    assert ttype == 'brick'
    assert len(params) == 19, f"expected 19 params, got {len(params)}: {params}"
    c1 = params[0:3]
    c2 = params[3:6]
    mortar = params[6:9]
    sc, ms, msmooth, bias, bw, rh, offamt, offfreq, sq, sqfreq = params[9:19]
    assert c1 == [0.9, 0.4, 0.3]
    assert c2 == [0.7, 0.3, 0.2]
    assert mortar == [0.1, 0.1, 0.1]
    assert (sc, ms, msmooth, bias, bw, rh, offamt) == (6.0, 0.03, 0.15, 0.1, 0.6, 0.3, 0.6)
    assert (offfreq, sq, sqfreq) == (3.0, 0.8, 4.0)


# ---------------------------------------------------------------------------
# TEX_CHECKER → checker (no change from chunk 1, but test for completeness)
# ---------------------------------------------------------------------------

def test_checker_translation_param_vector(monkeypatch):
    """ShaderNodeTexChecker → create_procedural_texture('checker', ...)
    with [r1,g1,b1, r2,g2,b2, scale]."""
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    renderer = _RecordingRenderer()
    node = _Node('TEX_CHECKER', inputs={
        'Vector': _Socket(),  # unlinked → GENERATED
        'Color1': _Socket(default=(0.9, 0.9, 0.9, 1.0)),
        'Color2': _Socket(default=(0.1, 0.1, 0.1, 1.0)),
        'Scale': _Socket(default=8.0),
    })
    engine.load_procedural_texture(node, renderer, vector_input=node.inputs['Vector'])

    assert len(renderer.proc_texture_calls) == 1
    name, ttype, params = renderer.proc_texture_calls[0]
    assert ttype == 'checker'
    assert len(params) == 7, f"expected 7 params, got {len(params)}: {params}"
    c1, c2 = params[0:3], params[3:6]
    scale = params[6]
    assert c1 == [0.9, 0.9, 0.9]
    assert c2 == [0.1, 0.1, 0.1]
    assert scale == 8.0


# ---------------------------------------------------------------------------
# TEX_GRADIENT / TEX_MAGIC / TEX_MUSGRAVE (no change, but test for completeness)
# ---------------------------------------------------------------------------

def test_gradient_translation_param_vector(monkeypatch):
    """ShaderNodeTexGradient → create_procedural_texture('gradient', ...)
    with [grad_type, scale, r1,g1,b1, r2,g2,b2]."""
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    renderer = _RecordingRenderer()
    node = _Node('TEX_GRADIENT', inputs={'Vector': _Socket()}, gradient_type='SPHERICAL')
    engine.load_procedural_texture(node, renderer, vector_input=node.inputs['Vector'])

    assert len(renderer.proc_texture_calls) == 1
    name, ttype, params = renderer.proc_texture_calls[0]
    assert ttype == 'gradient'
    assert len(params) == 8
    assert params[0] == 4.0, "SPHERICAL must map to gradient type 4"


def test_magic_translation_param_vector(monkeypatch):
    """ShaderNodeTexMagic → create_procedural_texture('magic', ...)
    with [depth, scale, distortion, r1,g1,b1, r2,g2,b2]."""
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    renderer = _RecordingRenderer()
    node = _Node('TEX_MAGIC', inputs={
        'Vector': _Socket(),
        'Scale': _Socket(default=7.0),
        'Distortion': _Socket(default=1.5),
    }, turbulence_depth=5)
    engine.load_procedural_texture(node, renderer, vector_input=node.inputs['Vector'])

    assert len(renderer.proc_texture_calls) == 1
    name, ttype, params = renderer.proc_texture_calls[0]
    assert ttype == 'magic'
    assert len(params) == 9
    depth, scale, dist = params[0:3]
    assert (depth, scale, dist) == (5.0, 7.0, 1.5)


def test_musgrave_translation_param_vector(monkeypatch):
    """ShaderNodeTexMusgrave → create_procedural_texture('musgrave', ...)
    with [musgrave_type, scale, detail, dimension, lacunarity, gain, r1,g1,b1, r2,g2,b2]."""
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    renderer = _RecordingRenderer()
    node = _Node('TEX_MUSGRAVE', inputs={
        'Vector': _Socket(),
        'Scale': _Socket(default=6.0),
        'Detail': _Socket(default=3.5),
        'Dimension': _Socket(default=2.5),
        'Lacunarity': _Socket(default=2.2),
    }, musgrave_type='HETERO_TERRAIN')
    engine.load_procedural_texture(node, renderer, vector_input=node.inputs['Vector'])

    assert len(renderer.proc_texture_calls) == 1
    name, ttype, params = renderer.proc_texture_calls[0]
    assert ttype == 'musgrave'
    assert len(params) == 12
    mt, scale, detail, dim, lac, gain = params[0:6]
    assert mt == 3.0, "HETERO_TERRAIN must map to musgrave type 3"
    assert (scale, detail, dim, lac, gain) == (6.0, 3.5, 2.5, 2.2, 1.0)
