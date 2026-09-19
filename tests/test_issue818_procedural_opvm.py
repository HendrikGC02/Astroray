"""issue #818 Item 1 — procedural textures as op-VM inputs.

Before this change the op-VM compiler treated ONLY image textures as input
leaves; a procedural input (Noise / Checker / …) was rejected and the whole
downstream Math / Ramp chain constant-folded to grey (memory
`addon-constant-folds-shader-graph`). These tests cover:

  * the compiler now accepts a procedural node as an OP_LOAD_TEX leaf, and
  * the engine's shared HD svm_eval runs the compiled program over a natively
    sampled procedural child, producing a NON-CONSTANT per-texel result on the
    CPU (the same svm_eval the wavefront GPU shade path runs, so the GPU bake
    path is parity-by-construction).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "blender_addon"))
import shader_vm_compiler as C  # noqa: E402


# --- minimal duck-typed Blender node model (shared shape with pkg219b tests) --
class Sock:
    def __init__(self, name, default=0.0, link=None):
        self.name = name
        self.default_value = default
        self._link = link

    @property
    def is_linked(self):
        return self._link is not None

    @property
    def links(self):
        return [self._link] if self._link else []


class Link:
    def __init__(self, from_node, from_socket_name="Color"):
        self.from_node = from_node
        self.from_socket = type("S", (), {"name": from_socket_name})()


class SockList:
    def __init__(self, socks):
        self._socks = socks
        self._by_name = {s.name: s for s in socks}

    def get(self, name):
        return self._by_name.get(name)

    def __getitem__(self, i):
        return self._socks[i]

    def __len__(self):
        return len(self._socks)

    def __iter__(self):
        return iter(self._socks)


class Out:
    def __init__(self, default):
        self.default_value = default


class Node:
    def __init__(self, type, inputs=None, outputs=None, **kw):
        self.type = type
        self.inputs = SockList(inputs or [])
        self.outputs = outputs or [Out(0.0)]
        for k, v in kw.items():
            setattr(self, k, v)


class ColorRamp:
    def evaluate(self, f):
        f = max(0.0, min(1.0, f))
        return (f, 0.0, 0.0, 1.0)


# --------------------------------------------------------------------------- #
# Compiler: a procedural node is a valid input leaf.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("proc_type", sorted(C._PROC_TEX_TYPES))
def test_procedural_leaf_accepted(proc_type):
    proc = Node(proc_type, inputs=[Sock('Vector')])
    math_node = Node('MATH', operation='MULTIPLY',
                     inputs=[Sock('A', 0.0, Link(proc, 'Color')),
                             Sock('B', 2.0)])
    base = Sock('Base Color', [0.5, 0.5, 0.5], Link(math_node, 'Color'))
    compiled = C.compile_chain(base)
    assert compiled is not None
    assert compiled['num_tex'] == 1
    assert compiled['inputs'][0] is proc


def test_noise_math_ramp_headline_chain_compiles():
    # The issue's PRIMARY acceptance topology: Noise -> Math(Multiply) ->
    # Color Ramp -> Base Color.
    noise = Node('TEX_NOISE', inputs=[Sock('Vector')])
    mul = Node('MATH', operation='MULTIPLY',
               inputs=[Sock('A', 0.0, Link(noise, 'Fac')), Sock('B', 2.0)])
    ramp = Node('VALTORGB',
                inputs=[Sock('Fac', 0.0, Link(mul, 'Value'))],
                color_ramp=ColorRamp())
    base = Sock('Base Color', [0.5, 0.5, 0.5], Link(ramp, 'Color'))
    compiled = C.compile_chain(base)
    assert compiled is not None
    assert compiled['num_tex'] == 1
    assert compiled['inputs'][0] is noise
    # OP_LOAD_TEX (op 1) must be present — the procedural is a sampled input.
    ops = [compiled['code_flat'][i] for i in range(0, len(compiled['code_flat']), 8)]
    assert C.OP_LOAD_TEX in ops


def test_bare_procedural_needs_no_vm():
    # A procedural straight into a BSDF socket routes to the native/bake path
    # (get_base_color_texture), NOT the op-VM: compile_chain returns None.
    proc = Node('TEX_CHECKER', inputs=[Sock('Vector')])
    base = Sock('Base Color', [0.5, 0.5, 0.5], Link(proc, 'Color'))
    assert C.compile_chain(base) is None


# --------------------------------------------------------------------------- #
# Engine: svm_eval over a natively sampled procedural child is NON-CONSTANT.
# --------------------------------------------------------------------------- #
def test_engine_program_over_checker_is_nonconstant():
    astroray = pytest.importorskip("astroray")
    # Build: Checker -> Math(Multiply 1.0) -> Base Color, then feed a REAL
    # procedural checker child to the program and sample across UV.
    checker = Node('TEX_CHECKER', inputs=[Sock('Vector')])
    mul = Node('MATH', operation='MULTIPLY',
               inputs=[Sock('A', 0.0, Link(checker, 'Color')), Sock('B', 1.0)])
    base = Sock('Base Color', [0.5, 0.5, 0.5], Link(mul, 'Color'))
    compiled = C.compile_chain(base)
    assert compiled is not None and compiled['num_tex'] == 1

    r = astroray.Renderer()
    # A UV-domain checker so sample_named_texture(u, v) exercises the field.
    r.create_procedural_texture("chk", "checker", [1, 1, 1, 0, 0, 0, 8.0])
    r.set_texture_coord_mode("chk", "UV")
    r.create_program_texture("prog", "UV")
    r.program_texture_add_input("prog", "chk")
    r.set_program_texture_program(
        "prog", compiled['num_tex'], compiled['out_slot'],
        compiled['code_flat'], compiled['consts_flat'], compiled['ramps_flat'])

    samples = []
    for i in range(8):
        u = (i + 0.5) / 8.0
        samples.append(r.sample_named_texture("prog", u, 0.5)[0])
    assert max(samples) - min(samples) > 0.5, samples  # checker toggles 0<->1


# --------------------------------------------------------------------------- #
# GPU: the procedural op-VM input is baked (scene_upload.cu bakeProceduralTexId)
# and renders NON-FLAT + at CPU/GPU parity — the new code path for issue #818.
# Mirrors tests/test_pkg190_gpu_procedural_texture.py (GPU-gated: RTX box only).
# --------------------------------------------------------------------------- #
_BBOX_MIN = [-1.0, -1.0, -1.0]
_BBOX_SIZE = [2.0, 2.0, 2.0]
_C1 = (0.9, 0.1, 0.1)   # red
_C2 = (0.1, 0.1, 0.9)   # blue


def _compiled_checker_passthrough():
    # Checker -> Math(Multiply 1.0) -> Base Color: a real op-VM chain (non-bare)
    # whose Multiply-by-1 keeps the checker colours, so the program render should
    # match a bare-checker render while still exercising svm_eval end to end.
    checker = Node('TEX_CHECKER', inputs=[Sock('Vector')])
    mul = Node('MATH', operation='MULTIPLY',
               inputs=[Sock('A', 0.0, Link(checker, 'Color')), Sock('B', 1.0)])
    base = Sock('Base Color', [0.5, 0.5, 0.5], Link(mul, 'Color'))
    return C.compile_chain(base)


def _build_program_scene(r, use_gpu):
    from base_helpers import setup_camera
    if use_gpu:
        r.set_use_gpu(True)
    r.set_seed(1)
    r.set_background_color([0.8, 0.8, 0.8])
    # Generated-coord checker child of an op-VM ProgramTexture.
    r.create_procedural_texture(
        "chk818", "checker",
        [_C1[0], _C1[1], _C1[2], _C2[0], _C2[1], _C2[2], 4.0], "GENERATED")
    r.set_texture_generated_bbox("chk818", _BBOX_MIN, _BBOX_SIZE)
    compiled = _compiled_checker_passthrough()
    r.create_program_texture("prog818", "GENERATED")
    r.set_texture_generated_bbox("prog818", _BBOX_MIN, _BBOX_SIZE)
    r.program_texture_add_input("prog818", "chk818")
    r.set_program_texture_program(
        "prog818", compiled['num_tex'], compiled['out_slot'],
        compiled['code_flat'], compiled['consts_flat'], compiled['ramps_flat'])
    mat = r.create_material("lambertian", [0.8, 0.8, 0.8], {"texture": "prog818"})
    A, B = [-1, -1, 0], [1, -1, 0]
    Cc, D = [1, 1, 0], [-1, 1, 0]
    n = [0, 0, 1]
    r.add_triangle_layers(A, B, Cc, mat, {"UVMap": [[0, 0], [1, 0], [1, 1]]}, n, n, n)
    r.add_triangle_layers(A, Cc, D, mat, {"UVMap": [[0, 0], [1, 1], [0, 1]]}, n, n, n)
    setup_camera(r, look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0],
                 vfov=45, width=64, height=64)


def _has_cuda_gpu(r):
    import astroray
    return bool(astroray.__features__.get("cuda", False)) and \
        bool(getattr(r, "gpu_available", False))


def test_gpu_procedural_opvm_input_not_flat_and_parity():
    pytest.importorskip("astroray")
    from base_helpers import create_renderer, render_image
    rg = create_renderer()
    if not _has_cuda_gpu(rg):
        pytest.skip("No CUDA GPU — issue #818 GPU leg runs on the RTX box.")
    _build_program_scene(rg, use_gpu=True)
    gpu = render_image(rg, samples=96, max_depth=3, apply_gamma=False)

    rc = create_renderer()
    _build_program_scene(rc, use_gpu=False)
    cpu = render_image(rc, samples=96, max_depth=3, apply_gamma=False)

    import numpy as np
    # 1. GPU render is NON-FLAT: red channel varies spatially (red vs blue cells).
    red = gpu[..., 0]
    assert red.max() - red.min() > 0.1, (
        "GPU op-VM procedural-input render shows no spatial contrast — the "
        "procedural child was dropped (not baked).")
    # 2. CPU/GPU per-channel mean-ratio within band (independent RNG streams:
    #    mean-ratio, NOT SSIM — memory ssim-wrong-gate-for-independent-rng).
    gm = np.array([float(gpu[..., c].mean()) for c in range(3)])
    cm = np.array([float(cpu[..., c].mean()) for c in range(3)])
    assert cm.mean() > 0.02 and gm.mean() > 0.02, (cm, gm)
    ratio = gm / np.maximum(cm, 1e-6)
    for c, rr in enumerate(ratio):
        assert 0.80 <= rr <= 1.25, (
            f"channel {c} CPU/GPU mean-ratio {rr:.3f} out of band; cpu={cm}, gpu={gm}")


# --------------------------------------------------------------------------- #
# Degradation for MULTI-input op-VM programs. PR #821 recorded one for every
# program with >1 texture input (the GPU then sampled only one). #826 samples up
# to VM_MAX_TEX (2) base-colour inputs on the GPU, so the entry now fires only for
# scalar-parameter programs (the GPU scalar path is still single-input); more
# than VM_MAX_TEX inputs is rejected by the compiler (flattened + warned on both
# backends). Uses the addon bpy-stub pattern from tests/test_blender_uv_plumbing.py.
# --------------------------------------------------------------------------- #
def _load_addon_stub(monkeypatch):
    import importlib.util
    import types
    from pathlib import Path
    bpy = types.ModuleType("bpy")
    bt = types.ModuleType("bpy.types")
    bp = types.ModuleType("bpy.props")

    class _B: pass
    class _RE:
        def report(self, *_a, **_k): return None
    bt.Panel = bt.Operator = bt.AddonPreferences = bt.PropertyGroup = _B
    bt.RenderEngine = _RE
    bpy.types = bt
    for n in ("BoolProperty", "IntProperty", "FloatProperty", "StringProperty",
              "PointerProperty", "FloatVectorProperty", "EnumProperty"):
        setattr(bp, n, lambda **_k: None)
    bpy.props = bp
    bpy.path = types.SimpleNamespace(abspath=lambda p: p)
    ar = types.ModuleType("astroray")
    ar.__version__ = "test"
    ar.__features__ = {"cuda": False, "spectral": True}
    ar.__file__ = "/fake/astroray.pyd"
    ar.integrator_registry_names = lambda: ["path_tracer"]
    ar.material_registry_names = lambda: ["lambertian", "disney"]
    ar.pass_registry_names = lambda: []
    sb = types.ModuleType("shader_blending")
    sb.blend_shader_specs = {}
    sb.add_shader_specs = {}
    mu = types.ModuleType("mathutils")
    mu.Vector = lambda v: v
    for name, mod in (("bpy", bpy), ("bpy.types", bt), ("bpy.props", bp),
                      ("astroray", ar), ("shader_blending", sb), ("mathutils", mu)):
        monkeypatch.setitem(sys.modules, name, mod)
    path = Path(__file__).parent.parent / "blender_addon" / "__init__.py"
    spec = importlib.util.spec_from_file_location("astroray_addon_818", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _NoopProgRenderer:
    """Mock renderer exposing the program/texture bindings _maybe_build_program_
    texture probes; every call is a no-op (we only assert the degradation entry)."""
    def __getattr__(self, _name):
        return lambda *a, **k: 1


def _two_noise_mix_socket(socket_name):
    # Two Noise textures into one Mix -> socket: compile_chain yields 2 inputs.
    noise_a = Node('TEX_NOISE', inputs=[Sock('Vector')])
    noise_b = Node('TEX_NOISE', inputs=[Sock('Vector')])
    mix = Node('MIX_RGB', blend_type='MIX',
               inputs=[Sock('Fac', 0.5),
                       Sock('Color1', [0, 0, 0], Link(noise_a, 'Color')),
                       Sock('Color2', [0, 0, 0], Link(noise_b, 'Color'))])
    return Sock(socket_name, [0.5, 0.5, 0.5], Link(mix, 'Color'))


def _degradation_lines(monkeypatch, socket_name, sock):
    addon = _load_addon_stub(monkeypatch)
    eng = addon.CustomRaytracerRenderEngine.__new__(addon.CustomRaytracerRenderEngine)
    eng._current_material_name = "M"
    eng._generated_textures_by_material = {}
    node = Node('BSDF_PRINCIPLED', inputs=[sock])
    try:
        eng._maybe_build_program_texture(sock, node, socket_name, _NoopProgRenderer())
    except Exception:
        pass  # the warning fires before any renderer program call; build outcome irrelevant
    return eng._degradation_report().messages()


def test_multi_input_base_color_program_no_degradation(monkeypatch):
    # #826: flips PR #821's guard (which asserted the entry for ANY 2-input
    # program) — a 2-input base-colour program now renders per-texel on the GPU.
    lines = _degradation_lines(monkeypatch, 'Base Color',
                               _two_noise_mix_socket('Base Color'))
    assert not any("multi-input shader program" in m for m in lines), lines


def test_multi_input_scalar_program_records_degradation(monkeypatch):
    # The GPU scalar-parameter path still samples one input -> stays non-silent.
    lines = _degradation_lines(monkeypatch, 'Roughness',
                               _two_noise_mix_socket('Roughness'))
    assert any("multi-input shader program" in m and "Roughness" in m
               for m in lines), lines


def test_three_input_program_flattened_with_warning(monkeypatch):
    # > VM_MAX_TEX inputs: the compiler rejects the chain -> flattened + warned.
    tex = [Node('TEX_NOISE', inputs=[Sock('Vector')]) for _ in range(3)]
    inner = Node('MIX_RGB', blend_type='MIX',
                 inputs=[Sock('Fac', 0.5),
                         Sock('Color1', [0, 0, 0], Link(tex[1], 'Color')),
                         Sock('Color2', [0, 0, 0], Link(tex[2], 'Color'))])
    outer = Node('MIX_RGB', blend_type='MIX',
                 inputs=[Sock('Fac', 0.5),
                         Sock('Color1', [0, 0, 0], Link(tex[0], 'Color')),
                         Sock('Color2', [0, 0, 0], Link(inner, 'Color'))])
    base = Sock('Base Color', [0.5, 0.5, 0.5], Link(outer, 'Color'))
    with pytest.raises(C.VMCompileError):
        C.compile_chain(base)
    lines = _degradation_lines(monkeypatch, 'Base Color', base)
    assert any("VM_MAX_TEX" in m for m in lines), lines
