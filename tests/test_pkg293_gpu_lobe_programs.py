"""pkg293 (#889) — per-hit lobe weights from Metallic/Roughness/Transmission
programs on the GPU, alone and inside a Mix Shader.

Engine legs: a checker program (Fac: 0/1 squares) drives Metallic or
Transmission, a gradient program drives Roughness, on the Disney and native
Principled materials. The GPU must follow the per-hit value, i.e. the lobe mix
(diffuse / specular / glass) is re-derived per hit, not baked from the constant.
Gate: per-square GPU/CPU mean within 5 % (independent RNG streams -> mean ratio,
not SSIM; memory ssim-wrong-gate-for-independent-rng).

Addon legs (bpy-free stub, real renderer): a Principled with a Metallic program
inside a Mix Shader with a Diffuse keeps its program (blend lowering composes a
per-hit Mix op-VM program); a texture-driven Mix Fac becomes per-hit; Checker
Fac vs Color wiring gives different, CPU/GPU-consistent results.
GPU legs skip without a CUDA device (CI has none).
"""
import os
import sys

import astroray
import numpy as np
import pytest
from base_helpers import create_renderer, render_image, setup_camera

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "blender_addon"))
import shader_blending  # real module; the addon stub replaces it in sys.modules
import shader_vm_compiler as C
from test_issue818_procedural_opvm import Link, Node, Sock, _load_addon_stub

OP_LOAD_TEX = 1

_W = _H = 64
_WINDOW_VFOV = float(np.degrees(2 * np.arctan(0.95 / 3.0)))  # visible [-0.95, 0.95]
_BBOX_MIN = [-1.0, -1.0, -1.3]
_BBOX_SIZE = [2.0, 2.0, 2.0]


def _has_cuda_gpu(renderer):
    return bool(astroray.__features__.get("cuda", False)) and \
        bool(getattr(renderer, "gpu_available", False))


def _checker_program(r, name):
    """Checker Fac (1/0 squares, 2x2 over the quad) -> program (one LOAD_TEX)."""
    r.create_procedural_texture(name + "_chk", "checker", [1, 1, 1, 0, 0, 0, 2.0], "GENERATED")
    r.set_texture_generated_bbox(name + "_chk", _BBOX_MIN, _BBOX_SIZE)
    r.create_program_texture(name, "GENERATED")
    r.program_texture_add_input(name, name + "_chk")
    r.set_texture_generated_bbox(name, _BBOX_MIN, _BBOX_SIZE)
    r.set_program_texture_program(name, 1, 0, [OP_LOAD_TEX, 0, 0, 0, 0, 0, 0, 0], [], [])


def _gradient_program(r, name):
    """Linear gradient along x (0 -> 1) -> program."""
    r.create_procedural_texture(name + "_grad", "gradient", [0, 1.0, 0, 0, 0, 1, 1, 1],
                                "GENERATED")
    r.set_texture_generated_bbox(name + "_grad", _BBOX_MIN, _BBOX_SIZE)
    r.create_program_texture(name, "GENERATED")
    r.program_texture_add_input(name, name + "_grad")
    r.set_texture_generated_bbox(name, _BBOX_MIN, _BBOX_SIZE)
    r.set_program_texture_program(name, 1, 0, [OP_LOAD_TEX, 0, 0, 0, 0, 0, 0, 0], [], [])


# case -> (program param, program builder, constant params, light position)
_CASES = {
    "metallic": ("metallic_program", _checker_program,
                 {"metallic": 0.0, "roughness": 0.35}, [1.5, 1.0, 2.5]),
    "metallic_glass": ("metallic_program", _checker_program,
                       {"metallic": 0.0, "roughness": 0.35, "transmission": 1.0},
                       [1.5, 1.0, 2.5]),
    "transmission": ("transmission_program", _checker_program,
                     {"transmission": 0.0, "roughness": 0.35}, [1.5, 1.0, 2.5]),
    "transmission_from_glass": ("transmission_program", _checker_program,
                                {"transmission": 1.0, "roughness": 0.35},
                                [1.5, 1.0, 2.5]),
    "roughness": ("roughness_program", _gradient_program,
                  {"metallic": 1.0, "roughness": 1.0}, [0.0, 0.0, 2.5]),
}
_KINDS = ("disney", "principled")


def _setup_quad(r, mat, light):
    A, B, C, D = [-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0]
    n = [0, 0, 1]
    r.add_triangle_layers(A, B, C, mat, {"UVMap": [[0, 0], [1, 0], [1, 1]]}, n, n, n)
    r.add_triangle_layers(A, C, D, mat, {"UVMap": [[0, 0], [1, 1], [0, 1]]}, n, n, n)
    # A dim diffuse backdrop so glass squares transmit something measurable.
    back = r.create_material("lambertian", [0.6, 0.6, 0.6], {})
    E, F, G, H = [-3, -3, -1.5], [3, -3, -1.5], [3, 3, -1.5], [-3, 3, -1.5]
    r.add_triangle(E, F, G, back)
    r.add_triangle(E, G, H, back)
    r.add_point_light(light, {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 1000.0, 0.05)
    r.add_point_light([0.0, 0.0, -1.0], {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 100.0, 0.05)
    setup_camera(r, look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0],
                 vfov=_WINDOW_VFOV, width=_W, height=_H)


def _renderer(use_gpu):
    r = create_renderer()
    if use_gpu:
        if not _has_cuda_gpu(r):
            pytest.skip("No CUDA GPU — pkg293 GPU leg runs on the RTX box.")
        r.set_use_gpu(True)
    r.set_seed(1)
    r.set_background_color([0.0, 0.0, 0.0])
    return r


def _render(case, use_gpu, kind, with_program=True, samples=256):
    param, build, consts, light = _CASES[case]
    r = _renderer(use_gpu)
    params = dict(consts)
    if kind == "principled" and "transmission" in params:
        params["transmission_weight"] = params.pop("transmission")
    if with_program:
        build(r, "p293_" + case)
        params[param] = "p293_" + case
    mat = r.create_material(kind, [0.8, 0.5, 0.3], params)
    _setup_quad(r, mat, light)
    return render_image(r, samples=samples, max_depth=4, apply_gamma=False)


def _squares(img):
    """Per-square (2x2 checker cell) mean RGB, avoiding the cell borders."""
    H, W = img.shape[:2]
    out = []
    for ya, yb in ((0.08, 0.42), (0.58, 0.92)):
        for xa, xb in ((0.08, 0.42), (0.58, 0.92)):
            roi = img[int(ya * H):int(yb * H), int(xa * W):int(xb * W)]
            out.append(roi.reshape(-1, 3).mean(axis=0))
    return np.array(out)


def _assert_parity(cpu, gpu, label):
    ratio = gpu / np.maximum(cpu, 1e-4)
    assert cpu.min() > 0.005, f"{label}: CPU square too dark to gate:\n{cpu}"
    assert np.allclose(ratio, 1.0, atol=0.05), (
        f"{label}: GPU/CPU per-square ratio outside 5 %:\n{ratio}\ncpu={cpu}\ngpu={gpu}")


@pytest.mark.parametrize("program", ["metallic_program", "transmission_program", None])
def test_pkg293_disney_glass_with_lobe_program_lowers_to_one_closure(program):
    """Disney glass (transmission 1) lowers to diffuse + dielectric closures whose
    weights are baked at upload and which carry no metallic at all. A Metallic or
    Transmission program needs the single monolithic closure (per-hit lobe mix)."""
    r = create_renderer()
    params = {"transmission": 1.0, "roughness": 0.35}
    if program:
        _checker_program(r, "p293_lower")
        params[program] = "p293_lower"
    mat = r.create_material("disney", [0.8, 0.5, 0.3], params)
    graph = r.get_material_closure_graph(mat)
    if program:
        assert [c["type"] for c in graph] == ["ggx_conductor"], graph
        assert graph[0]["transmission"] == 1.0 and graph[0]["metallic"] == 0.0, graph
    else:
        assert "ggx_conductor" not in [c["type"] for c in graph], graph  # glass split kept


@pytest.mark.parametrize("kind", _KINDS)
@pytest.mark.parametrize("case", sorted(_CASES))
def test_pkg293_cpu_program_changes_squares(case, kind):
    """Scene check: the program visibly changes the CPU render vs the constant."""
    prog = _squares(_render(case, False, kind))
    const = _squares(_render(case, False, kind, with_program=False))
    rel = np.abs(prog - const).mean() / max(float(const.mean()), 1e-4)
    assert rel > 0.1, f"{kind} {case}: program barely changes the image ({rel:.3f})"


@pytest.mark.parametrize("kind", _KINDS)
@pytest.mark.parametrize("case", sorted(_CASES))
def test_pkg293_gpu_lobe_program_parity(case, kind):
    cpu = _squares(_render(case, False, kind))
    gpu = _squares(_render(case, True, kind))
    _assert_parity(cpu, gpu, f"{kind} {case}")


# --------------------------------------------------------------------------- #
# Compiler: the wired procedural output (Fac vs Color) is honoured (#889 item 3).
# --------------------------------------------------------------------------- #


class _Socks:
    """Blender-like input collection: .get(name), [name] and [index]."""
    def __init__(self, socks):
        self._socks = list(socks)
        self._by_name = {s.name: s for s in socks}

    def get(self, name):
        return self._by_name.get(name)

    def __getitem__(self, key):
        return self._by_name[key] if isinstance(key, str) else self._socks[key]

    def __iter__(self):
        return iter(self._socks)

    def __len__(self):
        return len(self._socks)


def _node(ntype, name, socks=(), **kw):
    n = Node(ntype, name=name, **kw)
    n.inputs = _Socks(list(socks))
    return n


def _checker(name="Chk"):
    return _node('TEX_CHECKER', name, [Sock('Vector'), Sock('Scale', 2.0),
                                       Sock('Color1', [0.8, 0.8, 0.8, 1.0]),
                                       Sock('Color2', [0.2, 0.2, 0.2, 1.0])])


@pytest.mark.parametrize("out_name,variant", [("Fac", "fac"), ("Factor", "fac"),  # Blender 5
                                              ("Color", None)])
def test_pkg293_checker_output_selects_load_variant(out_name, variant):
    chk = _checker()
    sock = Sock('Metallic', 0.0, Link(chk, out_name))
    compiled = C.compile_chain(sock, allow_leaf=True)
    assert compiled['inputs'] == [chk]
    assert compiled['input_variants'] == [variant]


def test_pkg293_noise_fac_broadcasts_for_colour_consumer():
    noise = _node('TEX_NOISE', 'N', [Sock('Vector')])
    colour = Sock('Color1', [0.0, 0.0, 0.0], Link(noise, 'Fac'))  # untyped mock = non-VALUE
    b = C.ProgramBuilder()
    C.compile_socket(colour, b)
    assert [ins[0] for ins in b.code] == [C.OP_LOAD_TEX, C.OP_SEP_COLOR]
    scalar = Sock('Roughness', 0.5, Link(noise, 'Fac'))
    scalar.type = 'VALUE'
    scalar._link.from_socket.type = 'VALUE'
    b = C.ProgramBuilder()
    C.compile_socket(scalar, b)
    assert [ins[0] for ins in b.code] == [C.OP_LOAD_TEX]  # scalar ops read .x == Fac


# --------------------------------------------------------------------------- #
# Addon: Mix Shader lowering keeps / composes the scalar programs (#889 item 2).
# --------------------------------------------------------------------------- #
def _principled(name, metallic=0.0, roughness=0.5, metallic_link=None):
    return _node('BSDF_PRINCIPLED', name, [
        Sock('Base Color', [0.8, 0.5, 0.3, 1.0]),
        Sock('Metallic', metallic, metallic_link),
        Sock('Roughness', roughness)])


def _diffuse(name="Dif"):
    return _node('BSDF_DIFFUSE', name, [Sock('Color', [0.8, 0.5, 0.3, 1.0]),
                                        Sock('Roughness', 0.0)])


def _mix(fac, a, b, fac_link=None):
    return _node('MIX_SHADER', 'Mix', [Sock('Fac', fac, fac_link),
                                       Sock('Shader', None, Link(a, 'BSDF')),
                                       Sock('Shader_001', None, Link(b, 'BSDF'))])


def _graph(case, chk_out='Fac', linked=True):
    """Shader graphs of the addon legs. Returns the output shader node.
    linked=False: the same graph with the checker unplugged (constant socket)."""
    link = Link(_checker(), chk_out) if linked else None
    if case == "principled_program":
        return _principled("P", roughness=0.3, metallic_link=link)
    if case == "mix_program":  # Principled(Metallic program) inside a Mix with a Diffuse
        return _mix(0.25, _principled("P", roughness=0.3, metallic_link=link), _diffuse())
    if case == "mix_textured_fac":  # constant branches, Checker Fac drives the Mix
        return _mix(0.5, _principled("P", metallic=1.0, roughness=0.3), _diffuse(),
                    fac_link=link)
    raise KeyError(case)


class _Recorder:
    """Real renderer proxy that records create_material calls."""
    def __init__(self, r):
        self._r = r
        self.materials = []

    def create_material(self, kind, color, params):
        self.materials.append((kind, dict(params)))
        return self._r.create_material(kind, color, params)

    def __getattr__(self, name):
        return getattr(self._r, name)


def _addon_engine(monkeypatch, native):
    addon = _load_addon_stub(monkeypatch)
    addon.blend_shader_specs = shader_blending.blend_shader_specs
    addon.add_shader_specs = shader_blending.add_shader_specs
    eng = addon.CustomRaytracerRenderEngine.__new__(addon.CustomRaytracerRenderEngine)
    eng._current_material_name = "M293"
    eng._generated_textures_by_material = {}
    eng._use_native_principled = lambda: native
    return eng


def _addon_material(monkeypatch, r, case, native, chk_out='Fac', linked=True):
    eng = _addon_engine(monkeypatch, native)
    rec = _Recorder(r)
    spec = eng._shader_spec_from_node(_graph(case, chk_out, linked), rec, None)
    mat = eng._create_material_from_shader_spec(spec, rec)
    for name in eng._generated_textures_by_material.get("M293", []):
        r.set_texture_generated_bbox(name, _BBOX_MIN, _BBOX_SIZE)
    return mat, rec.materials[-1], eng._degradation_report().messages()


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("case", ["mix_program", "mix_textured_fac"])
def test_pkg293_mix_shader_carries_metallic_program(monkeypatch, case, native):
    """Before pkg293 the Principled+Principled blend dropped scalar_programs and
    read a textured Fac as its 0.5 default: no metallic_program reached the engine."""
    _, (kind, params), lines = _addon_material(monkeypatch, create_renderer(), case, native)
    assert kind == ('principled' if native else 'disney'), kind
    assert params.get('metallic_program'), (params, lines)
    if case == "mix_textured_fac":
        # roughness differs (0.3 vs 0) -> also per-hit; nothing else differs
        # (base colours match), so no constant-mix report.
        assert params.get('roughness_program'), params
        assert not any('MIX_SHADER' in m for m in lines), lines


def _render_addon(monkeypatch, case, use_gpu, native, chk_out='Fac', samples=256,
                  linked=True):
    r = _renderer(use_gpu)
    mat, _, _ = _addon_material(monkeypatch, r, case, native, chk_out, linked)
    _setup_quad(r, mat, [1.5, 1.0, 2.5])
    return render_image(r, samples=samples, max_depth=4, apply_gamma=False)


_ADDON_CASES = ["principled_program", "mix_program", "mix_textured_fac"]


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("case", _ADDON_CASES)
def test_pkg293_addon_program_is_per_hit_cpu(monkeypatch, case, native):
    """The checker must change the CPU render vs the same graph with the checker
    unplugged (a dropped program / constant-folded Fac renders identically)."""
    prog = _squares(_render_addon(monkeypatch, case, False, native))
    const = _squares(_render_addon(monkeypatch, case, False, native, linked=False))
    rel = np.abs(prog - const).mean() / max(float(const.mean()), 1e-4)
    assert rel > 0.1, f"{case}: checker program has no effect (rel {rel:.3f})"


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("case", _ADDON_CASES)
def test_pkg293_addon_program_gpu_parity(monkeypatch, case, native):
    cpu = _squares(_render_addon(monkeypatch, case, False, native))
    gpu = _squares(_render_addon(monkeypatch, case, True, native))
    _assert_parity(cpu, gpu, f"{'native' if native else 'disney'} {case}")


@pytest.mark.parametrize("use_gpu", [False, True])
def test_pkg293_checker_fac_vs_color_differ(monkeypatch, use_gpu):
    """Metallic <- Checker Fac (1/0) vs Checker Color (0.8/0.2 grey): different
    per-square metallic, so different renders, on either backend."""
    fac = _squares(_render_addon(monkeypatch, "principled_program", use_gpu, True, 'Fac'))
    col = _squares(_render_addon(monkeypatch, "principled_program", use_gpu, True, 'Color'))
    rel = np.abs(fac - col).mean() / max(float(col.mean()), 1e-4)
    assert rel > 0.05, f"Fac and Color wiring render alike (rel {rel:.3f})"


# --------------------------------------------------------------------------- #
# Review items: no silent approximation in the blend lowering.
# --------------------------------------------------------------------------- #
def _lines_for(monkeypatch, out_node, native=True):
    _, _, lines = _addon_material_node(monkeypatch, create_renderer(), out_node, native)
    return lines


def _addon_material_node(monkeypatch, r, out_node, native):
    eng = _addon_engine(monkeypatch, native)
    rec = _Recorder(r)
    spec = eng._shader_spec_from_node(out_node, rec, None)
    mat = eng._create_material_from_shader_spec(spec, rec)
    return mat, rec.materials[-1], eng._degradation_report().messages()


def test_pkg293_two_input_composed_program_reports_gpu_constant(monkeypatch):
    """Textured Fac + a branch program = 2 texture inputs; the GPU scalar upload
    samples one, so the GPU keeps the constant and must say so."""
    mix = _mix(0.5, _principled("P", roughness=0.3,
                                metallic_link=Link(_checker("ChkA"), 'Fac')),
               _diffuse(), fac_link=Link(_checker("ChkB"), 'Fac'))
    lines = _lines_for(monkeypatch, mix)
    assert any('multi-input shader program' in m and 'Metallic' in m
               and 'GPU uses the constant' in m for m in lines), lines


def test_pkg293_add_shader_of_two_bsdfs_reports_dropped_branch(monkeypatch):
    add = _node('ADD_SHADER', 'Add', [Sock('Shader', None, Link(_principled("P"), 'BSDF')),
                                      Sock('Shader_001', None, Link(_diffuse(), 'BSDF'))])
    lines = _lines_for(monkeypatch, add)
    assert any('ADD_SHADER' in m and 'second shader' in m for m in lines), lines


def test_pkg293_textured_fac_reports_native_only_socket(monkeypatch):
    def pr(name, coat_ior):
        n = _principled(name, metallic=1.0, roughness=0.3)
        n.inputs = _Socks(list(n.inputs) + [Sock('Coat IOR', coat_ior)])
        return n
    mix = _mix(0.5, pr("P1", 1.5), pr("P2", 2.0), fac_link=Link(_checker(), 'Fac'))
    lines = _lines_for(monkeypatch, mix)
    assert any('MIX_SHADER' in m and 'coat_ior' in m for m in lines), lines
