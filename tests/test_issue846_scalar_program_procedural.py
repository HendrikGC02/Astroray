"""#846 — GPU scalar op-VM programs with a PROCEDURAL input.

Noise (Generated coords) -> Map Range -> Roughness / Metallic / IOR /
Transmission on a quad, for the Disney and the native Principled material (the
addon default; it ignored scalar programs on both backends before #846). The
GPU scalar path used to accept only an image input, so these programs were
dropped (constant value) without a report. Now the
scalar input goes through the same upload (image or pkg190 bake) and shade fetch
(gpu_progInputTexel) as base-colour program inputs.

Gate: per-quadrant, per-channel GPU/CPU mean ratio within 3 % (independent RNG
streams -> mean ratio, not SSIM). The CPU leg checks the program changes the
image vs the constant-only material (so a dropped program fails the GPU leg).
GPU legs skip without a CUDA device (CI has none).
"""
import astroray
import numpy as np
import pytest
from base_helpers import create_renderer, render_image, setup_camera

# opcode / sub-op enums (mirror include/astroray/shader_vm.h)
OP_LOAD_TEX, OP_LOAD_CONST, OP_MAP_RANGE = 1, 2, 6
MR_LINEAR = 0

_W = _H = 64
_WINDOW_VFOV = float(np.degrees(2 * np.arctan(0.95 / 3.0)))  # visible [-0.95, 0.95]
_BBOX_MIN = [-1.0, -1.0, -1.3]
_BBOX_SIZE = [2.0, 2.0, 2.0]

# socket -> (program param, constant params, Map Range target [to_min, to_max],
#            point-light position). Constants are far from the mapped range so a
#            dropped program is visible.
_CASES = {
    "roughness": ("roughness_program", {"metallic": 1.0, "roughness": 1.0},
                  (0.3, 0.8), [1.5, 1.0, 2.5]),
    "metallic": ("metallic_program", {"metallic": 1.0, "roughness": 0.5},
                 (0.0, 1.0), [2.0, 1.5, 2.5]),
    "ior": ("ior_program", {"transmission": 1.0, "roughness": 0.4, "ior": 1.1},
            (1.8, 2.8), [0.0, 0.0, 2.9]),
    "transmission": ("transmission_program", {"transmission": 1.0, "roughness": 0.5},
                     (0.0, 1.0), [2.0, 1.5, 2.5]),
}


def _has_cuda_gpu(renderer):
    return bool(astroray.__features__.get("cuda", False)) and \
        bool(getattr(renderer, "gpu_available", False))


def _noise_program(r, name, to_lo, to_hi):
    """Noise (Generated) -> Map Range [0.35, 0.65] -> [to_lo, to_hi]."""
    r.create_procedural_texture(name + "_noise", "noise_perlin",
                                [5.0, 2.0, 0.5, 2.0, 0.0, 1.0, 0.0, 0, 1], "GENERATED")
    r.set_texture_generated_bbox(name + "_noise", _BBOX_MIN, _BBOX_SIZE)
    r.create_program_texture(name, "GENERATED")
    r.program_texture_add_input(name, name + "_noise")
    r.set_texture_generated_bbox(name, _BBOX_MIN, _BBOX_SIZE)
    consts = [0.35, 0.0, 0.0, 0.65, 0.0, 0.0, to_lo, 0.0, 0.0, to_hi, 0.0, 0.0]
    code = [OP_LOAD_TEX,   0, 0, 0, 0, 0, 0, 0,
            OP_LOAD_CONST, 1, 0, 0, 0, 0, 0, 0,
            OP_LOAD_CONST, 2, 0, 0, 0, 0, 0, 1,
            OP_LOAD_CONST, 3, 0, 0, 0, 0, 0, 2,
            OP_LOAD_CONST, 4, 0, 0, 0, 0, 0, 3,
            OP_MAP_RANGE,  5, 0, 1, 2, 3, 4, MR_LINEAR]
    r.set_program_texture_program(name, 1, 5, code, consts, [])


_KINDS = ("disney", "principled")


def _render(socket, use_gpu, with_program=True, samples=256, kind="disney"):
    param, consts, (lo, hi), light = _CASES[socket]
    r = create_renderer()
    if use_gpu:
        if not _has_cuda_gpu(r):
            pytest.skip("No CUDA GPU — #846 GPU leg runs on the RTX box.")
        r.set_use_gpu(True)
    r.set_seed(1)
    r.set_background_color([0.0, 0.0, 0.0])
    params = dict(consts)
    if with_program:
        _noise_program(r, "p846_" + socket, lo, hi)
        params[param] = "p846_" + socket
    mat = r.create_material(kind, [0.8, 0.5, 0.3], params)
    A, B, C, D = [-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0]
    n = [0, 0, 1]
    r.add_triangle_layers(A, B, C, mat, {"UVMap": [[0, 0], [1, 0], [1, 1]]}, n, n, n)
    r.add_triangle_layers(A, C, D, mat, {"UVMap": [[0, 0], [1, 1], [0, 1]]}, n, n, n)
    r.add_point_light(light, {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 1000.0, 0.05)
    setup_camera(r, look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0],
                 vfov=_WINDOW_VFOV, width=_W, height=_H)
    return render_image(r, samples=samples, max_depth=3, apply_gamma=False)


def _quadrants(img):
    H, W = img.shape[:2]
    out = []
    for ya, yb in ((0.05, 0.45), (0.55, 0.95)):
        for xa, xb in ((0.05, 0.45), (0.55, 0.95)):
            roi = img[int(ya * H):int(yb * H), int(xa * W):int(xb * W)]
            out.append(roi.reshape(-1, 3).mean(axis=0))
    return np.array(out)


@pytest.mark.parametrize("kind", _KINDS)
@pytest.mark.parametrize("socket", sorted(_CASES))
def test_846_cpu_program_changes_image(socket, kind):
    """Scene check: the program visibly changes the CPU render vs the constant."""
    prog = _render(socket, False, kind=kind)
    const = _render(socket, False, with_program=False, kind=kind)
    assert _quadrants(prog).min() > 0.01, f"{socket}: CPU program render too dark to gate"
    rel = np.abs(prog - const).mean() / max(float(const.mean()), 1e-4)
    assert rel > 0.25, f"{socket}: program barely changes the image (rel L1 {rel:.3f})"


@pytest.mark.parametrize("kind", _KINDS)
@pytest.mark.parametrize("socket", sorted(_CASES))
def test_846_gpu_scalar_procedural_program_parity(socket, kind):
    cpu = _quadrants(_render(socket, False, kind=kind))
    gpu = _quadrants(_render(socket, True, kind=kind))
    ratio = gpu / np.maximum(cpu, 1e-4)
    ok = np.allclose(ratio, 1.0, atol=0.03)
    if (kind, socket) == ("disney", "metallic"):
        # Pre-existing (pkg219d): the GPU lowers Disney to the closure graph with
        # lobe weights baked from the CONSTANT metallic, so the program has no
        # effect there (GPU program render == constant render, also on main with
        # an image input). The addon reports it; native Principled passes. Strict.
        assert not ok, "Disney metallic now within 3 % - remove this xfail branch"
        pytest.xfail("Disney GPU closure graph bakes the metallic lobe mix")
    assert ok, (
        f"{kind} {socket}: GPU/CPU quadrant ratio outside 3 %:\n{ratio}\ncpu={cpu}\ngpu={gpu}")


# --------------------------------------------------------------------------- #
# Addon (bpy-free): the LIVE Principled path (_principled_shader_spec ->
# _create_material_from_shader_spec) attaches scalar programs on both routes.
# Before #846 only the uncalled convert_principled_bsdf_v2 did, so Blender
# dropped every scalar chain silently. Reuses the #818 bpy stub + node mocks.
# --------------------------------------------------------------------------- #
from test_issue818_procedural_opvm import Link, Node, Sock, _load_addon_stub  # noqa: E402


class _RecRenderer:
    """Records create_material calls; every other binding is a no-op."""
    def __init__(self):
        self.materials = []

    def create_material(self, kind, color, params):
        self.materials.append((kind, dict(params)))
        return len(self.materials)

    def __getattr__(self, _name):
        return lambda *a, **k: 1


def _principled_node(roughness_sock, base_color_sock=None):
    socks = [roughness_sock]
    if base_color_sock is not None:
        socks.append(base_color_sock)
    return Node('BSDF_PRINCIPLED', inputs=socks, name='P')


def _noise_map_range_roughness():
    noise = Node('TEX_NOISE', inputs=[Sock('Vector')])
    mr = Node('MAP_RANGE', interpolation_type='LINEAR',
              inputs=[Sock('Value', 0.0, Link(noise, 'Fac')),
                      Sock('From Min', 0.35), Sock('From Max', 0.65),
                      Sock('To Min', 0.3), Sock('To Max', 0.8)])
    return Sock('Roughness', 0.5, Link(mr, 'Value'))


def _convert(monkeypatch, node, native):
    addon = _load_addon_stub(monkeypatch)
    eng = addon.CustomRaytracerRenderEngine.__new__(addon.CustomRaytracerRenderEngine)
    eng._current_material_name = "M"
    eng._generated_textures_by_material = {}
    eng._use_native_principled = lambda: native
    r = _RecRenderer()
    spec = eng._principled_shader_spec(node, r)
    eng._create_material_from_shader_spec(spec, r)
    return r.materials[-1], eng._degradation_report().messages()


@pytest.mark.parametrize("native", [True, False])
def test_846_addon_principled_attaches_roughness_program(monkeypatch, native):
    (kind, params), _ = _convert(
        monkeypatch, _principled_node(_noise_map_range_roughness()), native)
    assert kind == ('principled' if native else 'disney'), kind
    assert params.get('roughness_program'), params


def test_846_addon_bare_texture_on_roughness_attaches(monkeypatch):
    noise = Node('TEX_NOISE', inputs=[Sock('Vector')])
    sock = Sock('Roughness', 0.5, Link(noise, 'Fac'))
    (kind, params), _ = _convert(monkeypatch, _principled_node(sock), True)
    assert kind == 'principled' and params.get('roughness_program'), (kind, params)


def test_846_addon_textured_base_colour_reports_dropped_program(monkeypatch):
    chk = Node('TEX_CHECKER', inputs=[Sock('Vector')])
    base = Sock('Base Color', [0.8, 0.8, 0.8], Link(chk, 'Color'))
    (kind, _), lines = _convert(
        monkeypatch, _principled_node(_noise_map_range_roughness(), base), True)
    assert kind == 'lambertian', kind
    assert any('roughness_program dropped' in m for m in lines), lines


def test_846_addon_disney_metallic_program_reports_gpu_gap(monkeypatch):
    noise = Node('TEX_NOISE', inputs=[Sock('Vector')])
    mr = Node('MAP_RANGE', interpolation_type='LINEAR',
              inputs=[Sock('Value', 0.0, Link(noise, 'Fac')),
                      Sock('From Min', 0.35), Sock('From Max', 0.65),
                      Sock('To Min', 0.0), Sock('To Max', 1.0)])
    node = _principled_node(Sock('Metallic', 0.0, Link(mr, 'Value')))
    (kind, params), lines = _convert(monkeypatch, node, False)
    assert kind == 'disney' and params.get('metallic_program'), (kind, params)
    assert any('per-texel Metallic on the Disney material' in m for m in lines), lines
    _, lines = _convert(monkeypatch, node, True)
    assert not any('per-texel Metallic' in m for m in lines), lines
