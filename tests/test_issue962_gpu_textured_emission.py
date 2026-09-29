"""#962 — GPU wavefront renders a textured Emission Color per hit, not flat.

Before #962 scene_upload.cu uploaded a TexturedLight as ONE flat colour (the
texture mean, #776), so every corpus-v2 emission proof card rendered as a
uniform swatch on GPU while the CPU showed the pattern. The fix bakes the
emission texture onto the pkg186/pkg190/pkg219b matTexId/program slots and
fetches it per hit in the intersect stage (emissive hit) and the shadow stage
(NEE at the sampled light point), mirroring CPU TexturedLight::emitted and the
#776 NEE evaluation.

Gates (RTX box; CI has no GPU):
  * image / procedural / op-VM emission cards: GPU/CPU per-band, per-channel
    means within 5 % (the pre-fix GPU is flat: band contrast ~0);
  * a textured emitter lighting a floor: GPU NEE on vs off within 1 %
    (NEE and BSDF-hit legs integrate the same emission), and GPU/CPU within 5 %.
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "blender_addon"))
import shader_vm_compiler as C  # noqa: E402

astroray = pytest.importorskip("astroray")

W = H = 96


def _gpu_or_skip():
    r = astroray.Renderer()
    if not (astroray.__features__.get("cuda", False) and getattr(r, "gpu_available", False)):
        pytest.skip("No CUDA GPU — #962 is a GPU-leg fix (RTX box).")


# --- minimal duck-typed node model for the op-VM compiler (as test_issue818) --
class _Sock:
    def __init__(self, name, default=0.0, link=None):
        self.name, self.default_value, self._link = name, default, link

    @property
    def is_linked(self):
        return self._link is not None

    @property
    def links(self):
        return [self._link] if self._link else []


class _Link:
    def __init__(self, from_node, from_socket_name="Color"):
        self.from_node = from_node
        self.from_socket = type("S", (), {"name": from_socket_name})()


class _SockList:
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


class _Out:
    def __init__(self, default):
        self.default_value = default


class _Node:
    def __init__(self, type, inputs=None, **kw):
        self.type = type
        self.inputs = _SockList(inputs or [])
        self.outputs = [_Out(0.0)]
        for k, v in kw.items():
            setattr(self, k, v)


def _stripes():
    img = np.zeros((8, 8, 3), np.float32)
    for i, c in enumerate([(1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 1)]):
        img[:, 2 * i:2 * i + 2] = c
    return img


def _make_tex(r, kind):
    if kind == "image":
        r.load_texture("t", _stripes(), 8, 8, "UV")
    elif kind == "checker":
        r.create_procedural_texture("t", "checker", [0.9, 0.85, 0.2, 0.1, 0.15, 0.6, 4.0], "UV")
    elif kind == "checker_generated":
        r.create_procedural_texture("t", "checker", [0.9, 0.85, 0.2, 0.1, 0.15, 0.6, 4.0],
                                    "GENERATED")
        # z-min -0.8 (not -1): with -1 the z=0 card sits at Generated z=0.5 =
        # checker z-cell boundary, where the 64^3 GPU bake interpolates two
        # parities (pre-existing; a textured lambertian shows the same 0.38x
        # contrast). -0.8 puts the card mid-cell so the gate tests emission.
        r.set_texture_generated_bbox("t", [-1, -1, -0.8], [2, 2, 2])
    elif kind == "program":
        # Checker -> Math(Multiply 0.5): the op-VM result differs from the raw
        # input, so skipping svm_eval on GPU would fail parity.
        r.create_procedural_texture("chk", "checker", [0.9, 0.85, 0.2, 0.1, 0.15, 0.6, 4.0], "UV")
        checker = _Node('TEX_CHECKER', inputs=[_Sock('Vector')])
        mul = _Node('MATH', operation='MULTIPLY',
                    inputs=[_Sock('A', 0.0, _Link(checker, 'Color')), _Sock('B', 0.5)])
        compiled = C.compile_chain(_Sock('Color', [1, 1, 1], _Link(mul, 'Color')))
        assert compiled is not None
        r.create_program_texture("t", "UV")
        r.program_texture_add_input("t", "chk")
        r.set_program_texture_program(
            "t", compiled['num_tex'], compiled['out_slot'],
            compiled['code_flat'], compiled['consts_flat'], compiled['ramps_flat'])
    else:
        raise ValueError(kind)


def _xf(p, transformed):
    # Transformed (non-instanced) emitter: the addon bakes the object matrix
    # into the vertices; rotate 25 deg about Y and shift, so a world-vs-object
    # coordinate mix-up in the UV fetch would misplace the pattern.
    if not transformed:
        return p
    a = np.radians(25.0)
    x, y, z = p
    return [float(np.cos(a) * x + np.sin(a) * z + 0.1), float(y + 0.05),
            float(-np.sin(a) * x + np.cos(a) * z - 0.2)]


def _card(r, kind):
    from base_helpers import setup_camera
    r.set_background_color([0.0, 0.0, 0.0])
    transformed = kind.endswith("_transformed")
    _make_tex(r, kind.replace("_transformed", ""))
    m = r.create_material("light", [1, 1, 1], {"intensity": 2.0, "texture": "t"})
    A, B, Cc, D = (_xf(v, transformed) for v in ([-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0]))
    a = np.radians(25.0) if transformed else 0.0
    n = [float(np.sin(a)), 0.0, float(np.cos(a))]
    r.add_triangle_layers(A, B, Cc, m, {"UVMap": [[0, 0], [1, 0], [1, 1]]}, n, n, n)
    r.add_triangle_layers(A, Cc, D, m, {"UVMap": [[0, 0], [1, 1], [0, 1]]}, n, n, n)
    setup_camera(r, look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0],
                 vfov=45, width=W, height=H)


def _floor(r, nee):
    r.set_background_color([0.0, 0.0, 0.0])
    _make_tex(r, "image")
    white = r.create_material("lambertian", [0.8, 0.8, 0.8], {})
    e = 4.0
    r.add_triangle([-e, -1, -e], [e, -1, -e], [e, -1, e], white)
    r.add_triangle([-e, -1, -e], [e, -1, e], [-e, -1, e], white)
    m = r.create_material("light", [1, 1, 1], {"intensity": 3.0, "texture": "t"})
    le, n = 1.2, [0, -1, 0]
    r.add_triangle_layers([-le, 1.5, -le], [le, 1.5, -le], [le, 1.5, le], m,
                          {"UVMap": [[0, 0], [1, 0], [1, 1]]}, n, n, n)
    r.add_triangle_layers([-le, 1.5, -le], [le, 1.5, le], [-le, 1.5, le], m,
                          {"UVMap": [[0, 0], [1, 1], [0, 1]]}, n, n, n)
    r.set_light_nee(bool(nee))
    r.setup_camera(look_from=[0, 0.5, 0.01], look_at=[0, -1, 0], vup=[0, 0, -1],
                   vfov=50, aspect_ratio=1.0, aperture=0.0, focus_dist=2.0,
                   width=W, height=H)


def _render(build, gpu, spp, seed=7):
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    r.set_seed(seed)
    if gpu:
        r.set_use_gpu(True)
    build(r)
    return np.asarray(r.render(spp, 6, None, False), np.float32).reshape(H, W, 3)


def _bands(px):
    c = px[30:66, 18:78]  # inside the card
    return np.array([c[:, i * 15:(i + 1) * 15].reshape(-1, 3).mean(0) for i in range(4)])


@pytest.mark.gpu
@pytest.mark.parametrize("kind", ["image", "image_transformed", "checker",
                                  "checker_generated", "program"])
def test_gpu_textured_emission_card_matches_cpu(kind):
    _gpu_or_skip()
    g = _render(lambda r: _card(r, kind), True, 32)
    c = _render(lambda r: _card(r, kind), False, 32)
    gc, cc = g[30:66, 18:78], c[30:66, 18:78]
    # Pattern present on GPU (pre-#962: flat, luminance std ~0.02).
    assert gc.mean(2).std() > 0.5 * cc.mean(2).std() > 0.05, (gc.mean(2).std(), cc.mean(2).std())
    # Whole-card luminance + per-channel means within 5 %.
    for ch in range(3):
        assert abs(gc[..., ch].mean() / cc[..., ch].mean() - 1) < 0.05, (ch, gc.mean((0, 1)), cc.mean((0, 1)))
    # Per-band per-channel (spatial pattern, not just the mean).
    gb, cb = _bands(g), _bands(c)
    mask = cb > 0.05
    rel = np.abs(gb[mask] / cb[mask] - 1)
    assert rel.max() < 0.05, (gb, cb)


def _floor_mean(gpu, nee, spp):
    px = _render(lambda r: _floor(r, nee), gpu, spp)
    return px[20:76, 20:76].reshape(-1, 3).mean(0)


@pytest.mark.gpu
def test_gpu_textured_emitter_nee_on_off_and_cpu_parity():
    _gpu_or_skip()
    on = _floor_mean(True, 1, 1024)
    off = _floor_mean(True, 0, 1024)
    cpu = _floor_mean(False, 1, 256)
    lum = np.array([0.2126, 0.7152, 0.0722])
    assert abs(on @ lum / (off @ lum) - 1) < 0.01, (on, off)
    for ch in range(3):
        assert abs(on[ch] / cpu[ch] - 1) < 0.05, (ch, on, cpu)
