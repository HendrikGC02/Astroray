"""pkg234 (#1215) - Image Texture Interpolation (Closest / Linear / Cubic / Smart) on CPU and GPU.

Layers:

1. CPU contract (native module, no GPU): `sample_named_texture` against a numpy port of Cycles
   `interp_linear` / `interp_cubic` (intern/cycles/kernel/device/cpu/image.h:21-27, 170-311, Blender
   v5.2.0, Apache-2.0) on a 5x3 random texture, all four extensions; Closest (tagged or untagged) is
   today's nearest fetch exactly.
2. CPU vs GPU render twins (GPU leg skips without CUDA): the #1004 `_quad_render` pattern per extension x
   interpolation, plus one case each for the program-input, graph `tex_coord` and sphere-emitter sites.
3. Addon plumbing (stub bpy, no native module): the node's Interpolation reaches `set_texture_interpolation`
   at every Image Texture load site, is part of the texture cache key, an old module is reported, the
   pkg328 "not honoured" line is gone, and an opted-in Texture Cache is reported.
4. Cycles-referenced probes (real Blender + engine, CPU and GPU legs): `img_interp_float` /
   `img_interp_cubic` (scene-linear float images, where Cycles also filters linearly) must track Cycles;
   the 8-bit sRGB `img_interp` must differ from Cycles by exactly the documented filter-order term
   (Cycles filters the sRGB-encoded bytes and decodes afterwards; Phase 1 filters in linear space).
"""
import json
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent))
import test_blender_uv_plumbing as P  # stub loader + recording renderer

import astroray
from base_helpers import create_renderer, render_image, setup_camera

REPO = Path(__file__).resolve().parents[1]
EXTS = ["REPEAT", "EXTEND", "CLIP", "MIRROR"]
INTERPS = ["Linear", "Cubic", "Smart"]


def _have_cuda(r=None):
    r = r or astroray.Renderer()
    return bool(astroray.__features__.get("cuda", False)) and bool(getattr(r, "gpu_available", False))


# =========================================================================== #
# 1. CPU contract: numpy port of Cycles' interp_linear / interp_cubic
# =========================================================================== #
W5, H3 = 5, 3
_IMG = np.random.RandomState(11).uniform(0.0, 1.0, (H3, W5, 3)).astype(np.float32)   # row 0 = top (our storage)


def _wrap(ext, i, n):
    """Cycles wrap_periodic / wrap_clamp / wrap_mirror / read_clip on an integer index (None = clip -> zero)."""
    if ext == "REPEAT":
        return i % n
    if ext == "EXTEND":
        return min(max(i, 0), n - 1)
    if ext == "MIRROR":
        m = abs(i + (1 if i < 0 else 0)) % (2 * n)
        return 2 * n - m - 1 if m >= n else m
    return None if (i < 0 or i >= n) else i            # CLIP


def _texel(ext, ix, iy):
    """Cycles read(): rows count from the bottom, so row iy is our storage row H3 - 1 - iy."""
    x, y = _wrap(ext, ix, W5), _wrap(ext, iy, H3)
    if x is None or y is None:
        return np.zeros(3, np.float64)
    return _IMG[H3 - 1 - y, x].astype(np.float64)


def _frac(x):
    """Cycles frac(x - 0.5): float32 x as the engine computes it (u*w - 0.5f)."""
    xf = np.float32(x) - np.float32(0.5)
    ix = int(np.floor(xf))
    return ix, float(xf - np.float32(ix))


def _cubic_w(t):
    return [(((-1.0 / 6.0) * t + 0.5) * t - 0.5) * t + (1.0 / 6.0),
            ((0.5 * t - 1.0) * t) * t + (2.0 / 3.0),
            ((-0.5 * t + 0.5) * t + 0.5) * t + (1.0 / 6.0),
            (1.0 / 6.0) * t * t * t]


def cycles_linear(ext, u, v):
    x = np.float32(u) * np.float32(W5)
    y = np.float32(v) * np.float32(H3)
    ix, tx = _frac(x)
    iy, ty = _frac(y)
    return ((1 - ty) * ((1 - tx) * _texel(ext, ix, iy) + tx * _texel(ext, ix + 1, iy)) +
            ty * ((1 - tx) * _texel(ext, ix, iy + 1) + tx * _texel(ext, ix + 1, iy + 1)))


def cycles_cubic(ext, u, v):
    x = np.float32(u) * np.float32(W5)
    y = np.float32(v) * np.float32(H3)
    ix, tx = _frac(x)
    iy, ty = _frac(y)
    wx, wy = _cubic_w(tx), _cubic_w(ty)
    out = np.zeros(3, np.float64)
    for j in range(4):
        row = sum(wx[i] * _texel(ext, ix - 1 + i, iy - 1 + j) for i in range(4))
        out += wy[j] * row
    return out


def engine_closest(ext, u, v):
    """Today's nearest fetch (ImageTexture::value before pkg234), in float32 as the engine does it."""
    u, v = np.float32(u), np.float32(v)
    f32 = np.float32
    if ext == "CLIP":
        if not (u >= 0 and u < 1 and v >= 0 and v < 1):
            return np.zeros(3, np.float64)
    elif ext == "EXTEND":
        u, v = min(max(u, f32(0)), f32(1)), f32(1) - min(max(v, f32(0)), f32(1))
        i, j = min(int(u * f32(W5)), W5 - 1), min(int(v * f32(H3)), H3 - 1)
        return _IMG[j, i].astype(np.float64)
    elif ext == "REPEAT":
        u, v = u - np.floor(u), v - np.floor(v)
    else:                                                      # MIRROR: |u| folded into [0, 1], period 2
        def fold(a):
            a = abs(a)
            m = a - f32(2) * np.floor(a * f32(0.5))
            return f32(2) - m if m >= 1 else m
        u, v = fold(u), fold(v)
    i, iy = min(int(u * f32(W5)), W5 - 1), min(int(v * f32(H3)), H3 - 1)
    return _IMG[H3 - 1 - iy, i].astype(np.float64)


def _uv_points():
    pts = []
    pts += [((i + 0.5) / W5, (j + 0.5) / H3) for i in range(W5) for j in range(H3)]          # texel centres
    pts += [(i / W5, j / H3) for i in range(W5 + 1) for j in range(H3 + 1)]                   # texel edges / borders
    pts += [(a, b) for a in (-0.3, 1.7, -2.7, 2.45) for b in (-0.3, 1.7, -1.9, 3.35)]          # outside [0, 1]
    pts += [(10000.125, 0.4), (-10000.25, -10000.375), (0.3, 10000.5), (9999.875, -9999.75)]   # +-1e4 (dyadic: u*w exact)
    rng = np.random.RandomState(5)
    pts += [tuple(p) for p in rng.uniform(-1.5, 2.5, (40, 2))]
    return pts


def _tex_renderer(ext, interp=None):
    r = astroray.Renderer()
    r.load_texture("t234", np.ascontiguousarray(_IMG, np.float32).reshape(-1).tolist(), W5, H3, "UV")
    r.set_texture_extension("t234", ext)
    if interp is not None:
        r.set_texture_interpolation("t234", interp)
    return r


def _need_binding():
    if not hasattr(astroray.Renderer(), "set_texture_interpolation"):
        pytest.skip("native module predates pkg234 (set_texture_interpolation)")


@pytest.mark.parametrize("ext", EXTS)
@pytest.mark.parametrize("interp,port", [("Linear", cycles_linear), ("Cubic", cycles_cubic), ("Smart", cycles_cubic)])
def test_cpu_filtering_matches_cycles_port(ext, interp, port):
    _need_binding()
    r = _tex_renderer(ext, interp)
    worst = 0.0
    for u, v in _uv_points():
        got = np.array(r.sample_named_texture("t234", float(u), float(v)), np.float64)
        want = port(ext, u, v)
        err = float(np.abs(got - want).max())
        worst = max(worst, err)
        assert err <= 1e-6, f"{ext} {interp} uv=({u!r}, {v!r}): engine {got} vs Cycles port {want}"


@pytest.mark.parametrize("ext", EXTS)
def test_cpu_closest_tagged_and_untagged_are_todays_nearest_fetch(ext):
    _need_binding()
    untagged, tagged = _tex_renderer(ext), _tex_renderer(ext, "Closest")
    for u, v in _uv_points():
        a = untagged.sample_named_texture("t234", float(u), float(v))
        b = tagged.sample_named_texture("t234", float(u), float(v))
        assert a == b, (ext, u, v)
        if ext == "EXTEND":
            # (1 - v) * h on an exact texel edge is a rounding tie the compiled engine (main's build too, measured:
            # u=0, v=1/3 picks the other row) resolves differently from numpy float32; Closest is unchanged code,
            # so those points assert only tagged == untagged above.
            x = (1.0 - min(max(float(v), 0.0), 1.0)) * H3
            if abs(x - round(x)) < 1e-5:
                continue
        assert np.array_equal(np.array(a, np.float32), engine_closest(ext, u, v).astype(np.float32)), (ext, u, v, a)


def test_cpu_linear_reproduces_texels_at_centres_and_cubic_does_not():
    _need_binding()
    lin, cub = _tex_renderer("EXTEND", "Linear"), _tex_renderer("EXTEND", "Cubic")
    moved = 0.0
    for i in range(W5):
        for j in range(H3):
            u, v = (i + 0.5) / W5, (j + 0.5) / H3
            want = _IMG[H3 - 1 - j, i]            # v counts from the bottom
            assert np.allclose(lin.sample_named_texture("t234", u, v), want, atol=1e-6)
            moved = max(moved, float(np.abs(np.array(cub.sample_named_texture("t234", u, v)) - want).max()))
    assert moved > 0.01                            # the B-spline smooths: a texel centre is not reproduced


def test_cpu_interpolation_is_not_inert_and_smart_is_cubic():
    _need_binding()
    closest, lin = _tex_renderer("REPEAT", "Closest"), _tex_renderer("REPEAT", "Linear")
    cub, smart = _tex_renderer("REPEAT", "Cubic"), _tex_renderer("REPEAT", "Smart")
    d_lin = d_cub = 0.0
    for u, v in _uv_points()[:60]:
        c = np.array(closest.sample_named_texture("t234", float(u), float(v)))
        d_lin = max(d_lin, float(np.abs(np.array(lin.sample_named_texture("t234", float(u), float(v))) - c).max()))
        d_cub = max(d_cub, float(np.abs(np.array(cub.sample_named_texture("t234", float(u), float(v))) - c).max()))
        assert cub.sample_named_texture("t234", float(u), float(v)) == smart.sample_named_texture("t234", float(u), float(v))
    assert d_lin > 0.05 and d_cub > 0.05
    with pytest.raises(RuntimeError, match="unknown interpolation"):
        closest.set_texture_interpolation("t234", "Bogus")


def test_cpu_filters_preserve_a_constant_image():
    """The Linear and B-spline weights each sum to one: a flat image stays flat under every extension."""
    _need_binding()
    for ext in ("REPEAT", "EXTEND", "MIRROR"):
        for interp in ("Linear", "Cubic"):
            r = astroray.Renderer()
            r.load_texture("flat", np.full((3, 5, 3), 0.37, np.float32).reshape(-1).tolist(), 5, 3, "UV")
            r.set_texture_extension("flat", ext)
            r.set_texture_interpolation("flat", interp)
            for u, v in _uv_points()[:60]:
                assert np.allclose(r.sample_named_texture("flat", float(u), float(v)), 0.37, atol=2e-6), (ext, interp, u, v)


# =========================================================================== #
# 2. CPU vs GPU render twins
# =========================================================================== #
_SCALE2 = [2.0, 0.0, 0.0, 0.0, 0.0, 2.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0]
_IMG2 = np.array([[[0.9, 0.1, 0.1], [0.1, 0.9, 0.1]],
                  [[0.1, 0.1, 0.9], [0.9, 0.9, 0.1]]], dtype=np.float32)
_RES, _SPP = 64, 64
# CPU-vs-GPU: mean |8x8 block mean difference| over the frame. The block mean averages the independent MC /
# spectral-sampling noise of the two backends; texture-filter differences (a wrong tap) are structured.
# Measured on b26e8bb6 (sm_120, 64x64 @ 64 spp, all 4 extensions x Closest/Linear/Cubic + program / graph / sphere sites):
# CPU-vs-GPU block diff max 2.6e-4 (sphere emitter; every other site <= 9e-5), so the band is ~4x that.
TWIN_BAND = 0.001
# Linear vs Closest per backend: smallest case used 0.042 (REPEAT base), 0.073 program/graph, 0.236 sphere emitter.
NOT_INERT = 0.02


def _blocks(im):
    h, w, c = im.shape
    return im.reshape(h // 8, 8, w // 8, 8, c).mean(axis=(1, 3))


def _block_diff(a, b):
    return float(np.abs(_blocks(a) - _blocks(b)).mean())


def _new_renderer(use_gpu, bg=(0.5, 0.5, 0.5)):
    r = create_renderer()
    _need_binding()
    if use_gpu:
        if not _have_cuda(r):
            pytest.skip("No CUDA GPU")
        r.set_use_gpu(True)
    r.set_seed(3)
    r.set_background_color(list(bg))
    return r


def _quad(r, mat):
    A, B, C, D, n = [-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0], [0, 0, 1]
    r.add_triangle_layers(A, B, C, mat, {"UVMap": [[0, 0], [1, 0], [1, 1]]}, n, n, n)
    r.add_triangle_layers(A, C, D, mat, {"UVMap": [[0, 0], [1, 1], [0, 1]]}, n, n, n)
    setup_camera(r, look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0], vfov=45, width=_RES, height=_RES)


def _finish(r):
    return np.asarray(render_image(r, samples=_SPP, max_depth=2, apply_gamma=False), np.float32)


def _render_base(ext, interp, use_gpu):
    """Direct base-colour site (shade block): the #1004 scale-2 quad."""
    r = _new_renderer(use_gpu)
    r.load_texture("img234", _IMG2.reshape(-1).tolist(), 2, 2)
    r.set_texture_mapping_matrix("img234", _SCALE2)
    r.set_texture_extension("img234", ext)
    r.set_texture_interpolation("img234", interp)
    _quad(r, r.create_material("lambertian", [1, 1, 1], {"texture": "img234"}))
    return _finish(r)


def _render_program(interp, use_gpu):
    """Program-input site (gpu_progInputTexel): an identity op-VM program over a tagged image child."""
    r = _new_renderer(use_gpu)
    r.load_texture("img234", _IMG2.reshape(-1).tolist(), 2, 2)
    r.set_texture_extension("img234", "REPEAT")
    r.set_texture_interpolation("img234", interp)
    r.create_program_texture("prog234", "UV")
    r.program_texture_add_input("prog234", "img234")
    r.set_program_texture_program("prog234", 1, 0, [1, 0, 0, 0, 0, 0, 0, 0], [], [])
    _quad(r, r.create_material("lambertian", [1, 1, 1], {"texture": "prog234"}))
    return _finish(r)


def _render_graph_coord(interp, use_gpu):
    """Graph tex_coord site: GEOM_UV -> TEX_COORD over a tagged image (stage_graph_eval.cu GpuGraphSvc::tex_coord)."""
    r = _new_renderer(use_gpu)
    r.load_texture("img234", _IMG2.reshape(-1).tolist(), 2, 2)
    r.set_texture_extension("img234", "REPEAT")
    r.set_texture_interpolation("img234", interp)
    GOP_TEX_COORD, GOP_GEOM = 33, 34
    code = [GOP_GEOM, 0, 0, 0, 0, 0, 0, 0, 0,                 # reg0 = hit uv
            GOP_TEX_COORD, 0, 1, 0, 0, 0, 0, 0, 0]            # reg1 = image[0] at reg0.xy
    r.create_graph_program_texture("graph234", 1, 2, 1, code, [], [], [], ["img234"], [1])
    _quad(r, r.create_material("lambertian", [1, 1, 1], {"texture": "graph234"}))
    return _finish(r)


def _render_sphere_emitter(interp, use_gpu):
    """Sphere-emitter site (gpu_emissionTexel): a 2x2 image on an emissive sphere."""
    r = _new_renderer(use_gpu, bg=(0.0, 0.0, 0.0))
    r.load_texture("img234", _IMG2.reshape(-1).tolist(), 2, 2)
    r.set_texture_extension("img234", "REPEAT")
    r.set_texture_interpolation("img234", interp)
    r.add_sphere([0.0, 0.0, 0.0], 1.0, r.create_material("light", [1, 1, 1], {"intensity": 2.0, "texture": "img234"}))
    setup_camera(r, look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0], vfov=45, width=_RES, height=_RES)
    return _finish(r)


@pytest.mark.parametrize("ext", EXTS)
@pytest.mark.parametrize("interp", ["Closest", "Linear", "Cubic"])
def test_twin_base_colour_cpu_vs_gpu(ext, interp):
    cpu, gpu = _render_base(ext, interp, False), _render_base(ext, interp, True)
    assert _block_diff(cpu, gpu) < TWIN_BAND, (ext, interp, _block_diff(cpu, gpu))


@pytest.mark.parametrize("ext", ["REPEAT"])
def test_filtering_is_not_inert_on_either_backend(ext):
    for use_gpu in (False, True):
        closest, linear = _render_base(ext, "Closest", use_gpu), _render_base(ext, "Linear", use_gpu)
        assert _block_diff(closest, linear) > NOT_INERT, ("gpu" if use_gpu else "cpu")
        cubic = _render_base(ext, "Cubic", use_gpu)
        assert _block_diff(linear, cubic) > 0.002, ("gpu" if use_gpu else "cpu")


@pytest.mark.parametrize("site,render", [("program", _render_program), ("graph_coord", _render_graph_coord),
                                         ("sphere_emitter", _render_sphere_emitter)])
def test_twin_other_sites(site, render):
    for interp in ("Closest", "Linear"):
        cpu, gpu = render(interp, False), render(interp, True)
        assert _block_diff(cpu, gpu) < TWIN_BAND, (site, interp, _block_diff(cpu, gpu))
    # not inert: Linear differs from Closest on both backends at this site
    for use_gpu in (False, True):
        assert _block_diff(render("Closest", use_gpu), render("Linear", use_gpu)) > NOT_INERT, (site, use_gpu)


# =========================================================================== #
# 3. Addon plumbing (stub bpy)
# =========================================================================== #
def _engine(monkeypatch):
    addon = P._load_blender_addon(monkeypatch)
    return addon, addon.CustomRaytracerRenderEngine()


@pytest.mark.parametrize("interp", ["Closest", "Linear", "Cubic", "Smart"])
def test_load_blender_image_passes_the_node_interpolation(monkeypatch, interp):
    _addon, engine = _engine(monkeypatch)
    r = P._RecordingRenderer()
    name = engine.load_blender_image(P._FakeImage("i.png"), r, interpolation=interp)
    assert r.interpolation_calls == [(name, interp)]
    assert ("::interp=%s" % interp in name) == (interp != "Linear")      # Linear is the Cycles default: bare key


def test_same_image_closest_and_linear_are_two_cache_entries(monkeypatch):
    _addon, engine = _engine(monkeypatch)
    r = P._RecordingRenderer()
    img = P._FakeImage("shared.png")
    a = engine.load_blender_image(img, r, interpolation="Linear")
    b = engine.load_blender_image(img, r, interpolation="Closest")
    c = engine.load_blender_image(img, r, interpolation="Linear")
    assert a != b and a == c
    assert [n for n, _w, _h in r.loaded_textures] == [a, b]               # the repeat Linear load is a cache hit
    assert dict(r.interpolation_calls) == {a: "Linear", b: "Closest"}


def test_base_colour_site_reads_the_node(monkeypatch):
    _addon, engine = _engine(monkeypatch)
    r = P._RecordingRenderer()
    tex = P._Node("TEX_IMAGE", inputs={"Vector": P._Socket()}, image=P._FakeImage("bc.png"), extension="REPEAT",
                  interpolation="Cubic")
    bsdf = P._Node("BSDF_PRINCIPLED", inputs={"Base Color": P._Socket((0.8, 0.8, 0.8), linked_to=tex)})
    _fallback, name = engine.get_base_color_texture(bsdf, "Base Color", r)
    assert r.interpolation_calls == [(name, "Cubic")]


def test_missing_or_unknown_node_interpolation_is_linear(monkeypatch):
    _addon, engine = _engine(monkeypatch)
    assert engine._image_interpolation_mode(types.SimpleNamespace()) == "Linear"
    assert engine._image_interpolation_mode(types.SimpleNamespace(interpolation="Bogus")) == "Linear"


def test_program_child_site_reads_the_node(monkeypatch):
    from test_issue818_procedural_opvm import Link, Node, Sock, _load_addon_stub
    addon = _load_addon_stub(monkeypatch)
    eng = addon.CustomRaytracerRenderEngine.__new__(addon.CustomRaytracerRenderEngine)
    eng._current_material_name = "M234"
    eng._generated_textures_by_material = {}
    img = Node("TEX_IMAGE", inputs=[Sock("Vector")], image=P._FakeImage("pc.png"), extension="REPEAT",
               interpolation="Cubic")
    mul = Node("MATH", operation="MULTIPLY", inputs=[Sock("A", 0.0, Link(img, "Color")), Sock("B", 2.0)])
    sock = Sock("Base Color", [0.5, 0.5, 0.5], Link(mul, "Color"))
    r = P._RecordingRenderer()
    r.create_program_texture = lambda *a, **k: None
    r.program_texture_add_input = lambda *a, **k: None
    r.set_program_texture_program = lambda *a, **k: None
    prog = eng._maybe_build_program_texture(sock, Node("BSDF_PRINCIPLED", inputs=[sock]), "Base Color", r)
    assert prog is not None, eng._degradation_report().messages()
    assert [i for _n, i in r.interpolation_calls] == ["Cubic"]


@pytest.mark.parametrize("kind", ["native", "coord"])
def test_graph_input_site_reads_the_node(monkeypatch, kind):
    _addon, engine = _engine(monkeypatch)
    r = P._RecordingRenderer()
    node = P._Node("TEX_IMAGE", inputs={"Vector": P._Socket()}, image=P._FakeImage("g.png"), extension="REPEAT",
                   interpolation="Smart", name="G")
    name = engine._load_graph_input(node, None, kind, r)
    assert name is not None
    assert r.interpolation_calls == [(name, "Smart")]


def test_bump_and_normal_reads_stay_linear(monkeypatch):
    _addon, engine = _engine(monkeypatch)
    r = P._RecordingRenderer()
    name = engine.load_bump_height_texture({"bump_image": P._FakeImage("bump.png")}, r)
    assert r.interpolation_calls == [(name, "Linear")]


def test_old_module_without_the_binding_reports_a_filtered_mode(monkeypatch):
    class _Old:
        def __init__(self):
            self._inner = P._RecordingRenderer()

        def __getattr__(self, name):
            if name == "set_texture_interpolation":
                raise AttributeError(name)
            return getattr(self._inner, name)

    _addon, engine = _engine(monkeypatch)
    seen = []
    engine._warn_shader_fallback = lambda *a, **k: seen.append(a)
    engine.load_blender_image(P._FakeImage("old1.png"), _Old(), interpolation="Linear")
    assert seen and seen[0][0] == "TEX_IMAGE" and "set_texture_interpolation" in seen[0][1]
    seen.clear()
    engine.load_blender_image(P._FakeImage("old2.png"), _Old(), interpolation="Closest")   # the native default
    assert not [s for s in seen if "set_texture_interpolation" in s[1]]


def test_no_1215_report_remains_for_honoured_modes(monkeypatch):
    _addon, engine = _engine(monkeypatch)
    r = P._RecordingRenderer()
    for interp in ("Linear", "Cubic", "Smart", "Closest"):
        engine.load_blender_image(P._FakeImage("n_%s.png" % interp), r, interpolation=interp)
    texts = [d for _f, d in engine._degradation_report().approximated]
    assert not any("#1215" in t or "not honoured" in t for t in texts), texts


def test_texture_cache_opt_in_is_reported(monkeypatch):
    """Blender 5.2 RNA names (read headless, 2026-11-01): render.use_texture_cache (default True) and
    render.use_auto_generate_texture_cache (default False). Only mipmapped (generated) images take the Cycles
    mip path, so the report needs both."""
    _addon, engine = _engine(monkeypatch)
    off = types.SimpleNamespace(render=types.SimpleNamespace(use_texture_cache=True, use_auto_generate_texture_cache=False))
    engine._report_texture_cache(off)
    assert not engine._degradation_report().approximated
    on = types.SimpleNamespace(render=types.SimpleNamespace(use_texture_cache=True, use_auto_generate_texture_cache=True))
    engine._report_texture_cache(on)
    assert any("Texture Cache" in d for _f, d in engine._degradation_report().approximated)


# =========================================================================== #
# 4. Cycles-referenced probes (real Blender + engine)
# =========================================================================== #
PROBE_IDS = ["img_interp", "img_interp_float", "img_interp_cubic"]


def _find_blender():
    exe = os.environ.get("BLENDER_EXE", "")
    cands = [Path(exe)] if exe else []
    cands += [Path(r"C:\Program Files\Blender Foundation\Blender %s\blender.exe" % v) for v in ("5.2", "5.1")]
    return next((c for c in cands if c.is_file()), None)


def _pyd_dir():
    d = Path(os.environ.get("ASTRORAY_PYD_DIR", REPO / "build_cuda"))
    return d if list(d.glob("astroray*.pyd")) else None


def _run_leg(tag, engine, device):
    """One probe leg; always a fresh directory (renders are never reused across builds)."""
    blender, pyd = _find_blender(), _pyd_dir()
    if blender is None or pyd is None:
        pytest.skip("needs Blender 5.x and an engine .pyd (ASTRORAY_PYD_DIR)")
    if device == "gpu" and not _have_cuda():
        pytest.skip("No CUDA GPU")
    root = os.environ.get("PKG234_WORK")
    out = Path(tempfile.mkdtemp(prefix="pkg234_%s_" % tag, dir=root))
    env = dict(os.environ, ASTRORAY_PYD_DIR=str(pyd), OMP_NUM_THREADS="8", PKG321_DEVICE=device,
               PKG328_ENGINE=engine)
    if device == "cpu":
        env["CUDA_VISIBLE_DEVICES"] = "-1"
    proc = subprocess.run([str(blender), "--background", "--factory-startup", "--python",
                           str(REPO / "tests" / "pkg321_probe_blender.py"), "--", str(out), *PROBE_IDS],
                          capture_output=True, text=True, timeout=1500, env=env, check=False)
    assert "PKG321_PROBES_DONE" in proc.stdout, proc.stdout[-2000:] + proc.stderr[-2000:]
    res = json.loads((out / "results.json").read_text(encoding="utf-8"))
    return out, res


@pytest.fixture(scope="module")
def legs():
    return {"cycles": _run_leg("cycles", "CYCLES", "cpu"),
            "cpu": _run_leg("cpu", "CUSTOM_RAYTRACER", "cpu"),
            "gpu": _run_leg("gpu", "CUSTOM_RAYTRACER", "gpu")}


def _mad(a, b):
    return float(np.abs(a - b).mean())


@pytest.mark.serial
@pytest.mark.parametrize("probe", ["img_interp_float", "img_interp_cubic"])
@pytest.mark.parametrize("leg", ["cpu", "gpu"])
def test_float_probe_tracks_cycles(legs, probe, leg):
    cdir, cres = legs["cycles"]
    adir, ares = legs[leg]
    c, a = cres[probe], ares[probe]
    assert "error" not in a and "error" not in c, (a, c)
    ratio = a["d_ab"] / c["d_ab"]
    assert 0.85 <= ratio <= 1.15, f"{probe}/{leg}: Astroray d_ab {a['d_ab']:.4g} vs Cycles {c['d_ab']:.4g}"
    ld = lambda d, v: np.load(d / f"{probe}_{v}.npy")                        # noqa: E731
    m_a = _mad(ld(adir, "A"), ld(cdir, "A"))
    m_b = _mad(ld(adir, "B"), ld(cdir, "B"))
    assert m_a <= m_b + 2 * a["d_aa"], f"{probe}/{leg}: filtered variant {m_a:.4g} vs Closest variant {m_b:.4g} (+2 d_aa)"


def _decode(q):
    return np.where(q <= 0.04045, q / 12.92, ((q + 0.055) / 1.055) ** 2.4)


def _bilinear_repeat(tex, u, v):
    """Cycles interp_linear with REPEAT on a (h, w, 3) bottom-first array; u, v arrays."""
    h, w = tex.shape[:2]
    x, y = u * w - 0.5, v * h - 0.5
    ix, iy = np.floor(x).astype(int), np.floor(y).astype(int)
    tx, ty = (x - ix)[..., None], (y - iy)[..., None]
    g = lambda i, j: tex[j % h, i % w]                                         # noqa: E731
    return (1 - ty) * ((1 - tx) * g(ix, iy) + tx * g(ix + 1, iy)) + ty * ((1 - tx) * g(ix, iy + 1) + tx * g(ix + 1, iy + 1))


def _order_term(uv, cyc_b):
    """Predicted (Astroray Linear, linear-space filter) minus (Cycles, encoded-space filter then decode) of the
    probe's visible albedo, relative to the Cycles albedo, weighted by the Cycles shading estimated per 8x8 block."""
    a = np.random.RandomState(7).uniform(0.05, 0.95, (4, 4, 3)).astype(np.float32)
    q = np.round(a * 255.0) / 255.0                                            # the 8-bit PNG bytes / 255
    hit = np.isfinite(uv[..., 0])
    u, v = np.where(hit, uv[..., 0], 0.0), np.where(hit, uv[..., 1], 0.0)
    lin_order = _bilinear_repeat(_decode(q).astype(np.float64), u, v)
    cyc_order = _decode(_bilinear_repeat(q.astype(np.float64), u, v))
    rho_b = _decode(q.astype(np.float64))[np.floor((v % 1.0) * 4).astype(int) % 4, np.floor((u % 1.0) * 4).astype(int) % 4]
    h, w = hit.shape
    bl = lambda x: x.reshape(h // 8, 8, w // 8, 8, *x.shape[2:]).sum(axis=(1, 3))      # noqa: E731
    shade = bl(np.where(hit[..., None], cyc_b, 0.0).mean(-1)) / np.maximum(bl(np.where(hit, rho_b.mean(-1), 0.0)), 1e-9)
    wgt = np.repeat(np.repeat(shade, 8, 0), 8, 1) * hit
    return float((wgt * (lin_order - cyc_order).mean(-1)).sum() / (wgt * cyc_order.mean(-1)).sum())


@pytest.mark.serial
@pytest.mark.parametrize("leg", ["cpu", "gpu"])
def test_srgb_probe_moves_and_differs_from_cycles_by_the_filter_order_term(legs, leg):
    """img_interp (8-bit sRGB): Astroray now moves; its residual against Cycles is the documented Phase 1
    colour-space order term (Phase 2 would close it), measured on the filtered variant net of the Closest
    variant's own engine offset, within +-25 % of the numpy prediction."""
    cdir, cres = legs["cycles"]
    adir, ares = legs[leg]
    a = ares["img_interp"]
    assert a["d_ab"] > 3 * a["d_aa"], a
    uv_path = adir / "img_interp_uv.npy"
    assert uv_path.is_file(), "the probe driver writes the visible-hit UV map"
    uv = np.load(uv_path)
    ld = lambda d, v: np.load(d / f"img_interp_{v}.npy")                       # noqa: E731
    cyc_a, cyc_b, ast_a, ast_b = ld(cdir, "A"), ld(cdir, "B"), ld(adir, "A"), ld(adir, "B")
    hit = np.isfinite(uv[..., 0])
    rel = lambda x, y: float((x[hit] - y[hit]).mean() / y[hit].mean())          # noqa: E731
    measured = rel(ast_a, cyc_a) - rel(ast_b, cyc_b)
    predicted = _order_term(uv, cyc_b)
    assert predicted > 0.02, predicted          # real on this texture: linear-space filtering is BRIGHTER than Cycles' encoded-space
    assert abs(measured - predicted) <= 0.25 * abs(predicted), (measured, predicted)
