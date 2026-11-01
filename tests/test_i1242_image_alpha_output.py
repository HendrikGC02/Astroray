"""#1242 - the Image Texture Alpha OUTPUT is delivered (op-VM / graph program) and drives Principled Alpha.

Cycles v5.2.0 (Apache-2.0): kernel/svm/image.h svm_node_tex_image stores the texel's alpha (f.w) as its own float output,
straight, saved before the Color output is un-associated (:28-31); scene/shader_nodes.cpp:449-457 sets the un-associate
flag only when the Alpha output is linked; util/image_metadata.cpp (conform_pixels_to_metadata_type) sets alpha to one for
an image with no alpha channel and for alpha mode None (ALPHA_IGNORE, probed on 5.2: img_alpha_none). A Principled Alpha
< 1 is a Transparent closure weighted 1 - alpha (kernel/svm/closure.h).

Astroray: the Alpha output is the 'alpha' input variant of an op-VM / graph-program texture leaf, uploaded as the straight
alpha plane broadcast to grey (an everywhere-opaque image uploads one white texel). A linked Principled Alpha becomes a graph
program on the native Principled (CPU PrincipledPlugin::substituted / shadowAlpha; GPU graph slot GRAPH_SLOT_ALPHA).

Layers: (1) addon with a stub bpy (no engine); (2) Cycles-referenced probes (real Blender + engine, CPU and GPU legs).
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
from test_i1238_image_alpha_association import (TEXELS, _Img, _Renderer, _engine, _find_blender, _pyd_dir,
                                                _have_cuda)
from test_issue818_procedural_opvm import C, Link, Node, Sock, _load_addon_stub

REPO = Path(__file__).resolve().parents[1]
_A = np.array([t[3] for t in TEXELS], np.float64)


def _alpha_names(r):
    return [n for n in r.rgb if "::out=alpha" in n]


# =========================================================================== #
# 1. Addon (stub bpy)
# =========================================================================== #
@pytest.mark.parametrize("kw", [
    dict(mode="STRAIGHT"), dict(mode="PREMUL"), dict(mode="CHANNEL_PACKED"),
    dict(mode="STRAIGHT", cs="sRGB"),                       # alpha is data: never sRGB-decoded
    dict(mode="STRAIGHT", is_float=True), dict(mode="PREMUL", cs="Non-Color"),
])
def test_alpha_output_is_the_straight_alpha_plane(monkeypatch, kw):
    engine, r = _engine(monkeypatch), _Renderer()
    name = engine.load_blender_image(_Img("a.png", **kw), r, alpha_linked=True, alpha_output=True)
    assert name.endswith("::out=alpha")
    assert np.allclose(r.rgb[name], np.repeat(_A[:, None], 3, axis=1), atol=1e-6), r.rgb[name]


@pytest.mark.parametrize("make", [
    lambda: _Img("n.png", mode="NONE"),                      # Cycles ALPHA_IGNORE: alpha 1 everywhere
    lambda: _Img("o.png", texels=[(0.3, 0.4, 0.5, 1.0), (0.1, 0.2, 0.3, 1.0)]),
    lambda: _with_depth(_Img("d24.png"), 24),                # no alpha plane
    lambda: _with_depth(_Img("d96.png"), 96),
])
def test_opaque_image_alpha_is_one_white_texel(monkeypatch, make):
    engine, r = _engine(monkeypatch), _Renderer()
    name = engine.load_blender_image(make(), r, alpha_linked=True, alpha_output=True)
    assert r.rgb[name].shape == (1, 3) and np.all(r.rgb[name] == 1.0)
    assert [(w, h) for n, w, h in r.loaded_textures if n == name] == [(1, 1)]


def _with_depth(img, depth):
    img.depth = depth
    return img


def test_color_and_alpha_of_one_image_are_two_uploads(monkeypatch):
    engine, r = _engine(monkeypatch), _Renderer()
    img = _Img("both.png")
    color = engine.load_blender_image(img, r, alpha_linked=True)
    alpha = engine.load_blender_image(img, r, alpha_linked=True, alpha_output=True)
    assert color != alpha and sorted(r.rgb) == sorted([color, alpha])
    assert engine.load_blender_image(img, r, alpha_linked=True, alpha_output=True) == alpha   # cached
    assert len(r.rgb) == 2


def test_unlinked_image_uploads_no_alpha_texture(monkeypatch):
    """Pre-change behaviour: a Color-only image is one RGB upload with the unchanged name."""
    engine, r = _engine(monkeypatch), _Renderer()
    name = engine.load_blender_image(_Img("c.png", texels=[(0.3, 0.4, 0.5, 1.0)]), r, alpha_linked=False)
    assert "::out=" not in name and len(r.rgb) == 1


def _img_node(img, alpha_linked=True, name="Img"):
    return Node("TEX_IMAGE", inputs=[Sock("Vector")], image=img, extension="REPEAT", interpolation="Closest",
                name=name, outputs={"Alpha": P._Socket(linked_to=object()) if alpha_linked else P._Socket()})


def test_compiler_routes_the_alpha_output_to_the_alpha_variant(monkeypatch):
    img = _img_node(_Img("v.png"))
    for out_name, variant in (("Alpha", "alpha"), ("Color", None)):
        mul = Node("MATH", operation="MULTIPLY", inputs=[Sock("A", 0.0, Link(img, out_name)), Sock("B", 2.0)])
        compiled = C.compile_chain(Sock("X", 0.0, Link(mul, "Value")))
        assert compiled["input_variants"] == [variant], (out_name, compiled["input_variants"])
    both = Node("MATH", operation="ADD", inputs=[Sock("A", 0.0, Link(img, "Color")), Sock("B", 0.0, Link(img, "Alpha"))])
    assert C.compile_chain(Sock("X", 0.0, Link(both, "Value")))["input_variants"] == [None, "alpha"]


def _build_program(eng, sock, r):
    r.create_program_texture = lambda *a, **k: None
    r.program_texture_add_input = lambda *a, **k: None
    r.set_program_texture_program = lambda *a, **k: None
    return eng._maybe_build_program_texture(sock, Node("BSDF_PRINCIPLED", inputs=[sock]), "Base Color", r)


def _bare_engine(monkeypatch):
    addon = _load_addon_stub(monkeypatch)
    eng = addon.CustomRaytracerRenderEngine.__new__(addon.CustomRaytracerRenderEngine)
    eng._current_material_name = "M1242"
    eng._generated_textures_by_material = {}
    return eng


def test_op_vm_child_and_graph_sites_upload_the_alpha_plane(monkeypatch):
    eng = _bare_engine(monkeypatch)
    img = _img_node(_Img("pc.png"))
    mul = Node("MATH", operation="MULTIPLY", inputs=[Sock("A", 0.0, Link(img, "Alpha")), Sock("B", 2.0)])
    r = _Renderer()
    assert _build_program(eng, Sock("Base Color", [0.5] * 3, Link(mul, "Value")), r) is not None
    assert [np.allclose(v, np.repeat(_A[:, None], 3, axis=1)) for v in r.rgb.values()] == [True]
    for kind in ("native", "coord"):
        gr = _Renderer()
        gname = eng._load_graph_input(_img_node(_Img("g%s.png" % kind), name="G" + kind), "alpha", kind, gr)
        assert "::out=alpha" in gname and np.allclose(gr.rgb[gname], np.repeat(_A[:, None], 3, axis=1)), kind


def test_direct_alpha_into_a_colour_socket_reads_the_alpha_plane(monkeypatch):
    engine, r = _engine(monkeypatch), _Renderer()
    tex = P._Node("TEX_IMAGE", inputs={"Vector": P._Socket()}, image=_Img("dc.png"), extension="REPEAT",
                  interpolation="Closest", outputs={"Alpha": P._Socket(linked_to=object())})
    link_sock = P._Socket((0.8, 0.8, 0.8), linked_to=tex, output_name="Alpha")
    bsdf = P._Node("BSDF_PRINCIPLED", inputs={"Base Color": link_sock})
    _fb, name = engine.get_base_color_texture(bsdf, "Base Color", r)
    assert "::out=alpha" in name and np.allclose(r.rgb[name], np.repeat(_A[:, None], 3, axis=1))


# ---- Principled Alpha -------------------------------------------------------
class _GraphRenderer(_Renderer):
    """Records the graph programs a Principled spec registers."""
    def __init__(self):
        super().__init__()
        self.graphs = {}

    def create_graph_program_texture(self, name, version, num_slots, out_slot, code, consts, tables, table_data,
                                     inputs, kinds):
        self.graphs[name] = list(inputs)


def _principled(alpha_src=None, alpha_out="Alpha"):
    alpha = Sock("Alpha", 1.0, Link(alpha_src, alpha_out) if alpha_src is not None else None)
    return Node("BSDF_PRINCIPLED", name="Principled", inputs=[alpha])


def test_principled_alpha_from_an_image_becomes_a_graph_program(monkeypatch):
    eng = _bare_engine(monkeypatch)
    r = _GraphRenderer()
    spec = eng._principled_shader_spec(_principled(_img_node(_Img("leaf.png"))), r)
    prog = spec["scalar_programs"]["alpha_program"]
    assert prog in r.graphs and any("::out=alpha" in n for n in r.graphs[prog]), r.graphs
    # the constant the GPU's per-material paths read is the image's mean coverage
    assert spec["native_params"]["alpha"] == pytest.approx(float(_A.mean()))
    assert any("Alpha" in m for m in eng._degradation_report().messages())      # GPU shadow constant is reported


def test_principled_alpha_from_a_chain_uses_the_half_coverage_hint(monkeypatch):
    eng = _bare_engine(monkeypatch)
    r = _GraphRenderer()
    mul = Node("MATH", operation="MULTIPLY", inputs=[Sock("A", 0.0, Link(_img_node(_Img("m.png")), "Alpha")),
                                                     Sock("B", 0.5)])
    spec = eng._principled_shader_spec(_principled(mul, "Value"), r)
    assert "alpha_program" in spec["scalar_programs"] and spec["native_params"]["alpha"] == 0.5


@pytest.mark.parametrize("make", [
    lambda: _Img("o1.png", mode="NONE"),
    lambda: _Img("o2.png", texels=[(0.3, 0.4, 0.5, 1.0), (0.1, 0.2, 0.3, 1.0)]),
    lambda: _with_depth(_Img("o3.png"), 24),
])
def test_principled_alpha_from_an_opaque_image_is_the_unlinked_material(monkeypatch, make):
    """No alpha plane (or alpha 1 everywhere): no program, no new texture, the spec equals the unlinked one - the render
    is bit-identical to the pre-change behaviour (and to Cycles, where Alpha reads 1)."""
    eng, r = _bare_engine(monkeypatch), _GraphRenderer()
    linked = eng._principled_shader_spec(_principled(_img_node(make())), r)
    unlinked = eng._principled_shader_spec(_principled(None), r)
    assert "scalar_programs" not in linked and not r.graphs and not r.rgb
    assert linked == unlinked


def test_engine_without_graph_programs_reports_the_constant_alpha(monkeypatch):
    eng = _bare_engine(monkeypatch)
    spec = eng._principled_shader_spec(_principled(_img_node(_Img("ng.png"))), _Renderer())
    assert "scalar_programs" not in spec and spec["native_params"]["alpha"] == 1.0
    assert any("Alpha" in m for m in eng._degradation_report().messages())


# =========================================================================== #
# 2. Cycles-referenced probes (real Blender + engine; CPU and GPU legs)
# =========================================================================== #
PROBE_IDS = ["img_alpha_mixfac", "img_alpha_cutout", "img_alpha_opaque", "img_alpha_none"]


def _run_leg(tag, engine, device):
    blender, pyd = _find_blender(), _pyd_dir()
    if blender is None or pyd is None:
        pytest.skip("needs Blender 5.x and an engine .pyd (ASTRORAY_PYD_DIR)")
    if device == "gpu" and not _have_cuda():
        pytest.skip("No CUDA GPU")
    out = Path(tempfile.mkdtemp(prefix="i1242_%s_" % tag, dir=os.environ.get("I1242_WORK")))
    env = dict(os.environ, ASTRORAY_PYD_DIR=str(pyd), OMP_NUM_THREADS="8", PKG321_DEVICE=device,
               PKG328_ENGINE=engine)
    if device == "cpu":
        env["CUDA_VISIBLE_DEVICES"] = "-1"
    proc = subprocess.run([str(blender), "--background", "--factory-startup", "--python",
                           str(REPO / "tests" / "pkg321_probe_blender.py"), "--", str(out), *PROBE_IDS],
                          capture_output=True, text=True, timeout=900, env=env, check=False)
    assert "PKG321_PROBES_DONE" in proc.stdout, proc.stdout[-2000:] + proc.stderr[-2000:]
    return json.loads((out / "results.json").read_text(encoding="utf-8")), out


@pytest.fixture(scope="module")
def legs():
    return {"cycles": _run_leg("cycles", "CYCLES", "cpu"),
            "cpu": _run_leg("cpu", "CUSTOM_RAYTRACER", "cpu"),
            "gpu": _run_leg("gpu", "CUSTOM_RAYTRACER", "gpu")}


def _render(legs, leg, probe, variant):
    return np.load(legs[leg][1] / ("%s_%s.npy" % (probe, variant)))


def _rel_l1(a, ref):
    return float(np.abs(a - ref).mean() / ref.mean())


@pytest.mark.serial
@pytest.mark.gpu
@pytest.mark.parametrize("probe", ["img_alpha_mixfac", "img_alpha_cutout"])
@pytest.mark.parametrize("leg", ["cpu", "gpu"])
def test_alpha_driven_render_tracks_cycles(legs, probe, leg):
    """A (Alpha linked) and B (the unchanged control) each match the Cycles render pixelwise (relative L1: the 64-spp MC
    noise + the RGB-vs-spectral residual set the B floor), and linking the Alpha moves Astroray as far as it moves Cycles.
    mixfac: a Mix factor driven by the image alpha; cutout: a leaf card whose Principled Alpha is the image alpha (the
    holes show the backdrop and the sun's shadow)."""
    cj, aj = legs["cycles"][0][probe], legs[leg][0][probe]
    assert "error" not in aj and "error" not in cj, (aj, cj)
    floor = _rel_l1(_render(legs, leg, probe, "B"), _render(legs, "cycles", probe, "B"))
    err = _rel_l1(_render(legs, leg, probe, "A"), _render(legs, "cycles", probe, "A"))
    assert err <= max(0.06, 2.0 * floor + 0.02), (probe, leg, err, floor)
    assert 0.8 <= aj["d_ab"] / cj["d_ab"] <= 1.25, (probe, leg, aj["d_ab"], cj["d_ab"])


@pytest.mark.serial
@pytest.mark.gpu
@pytest.mark.parametrize("probe", ["img_alpha_opaque", "img_alpha_none"])
@pytest.mark.parametrize("leg", ["cpu", "gpu"])
def test_image_without_alpha_changes_nothing(legs, probe, leg):
    """opaque: an image with no alpha plane into Principled Alpha; none: alpha mode None into a Mix factor. Cycles reads
    alpha 1, so linking changes nothing (d_ab ~ 0); Astroray must be bit-identical to the unlinked control (d_ab == 0)
    and still match Cycles' brightness."""
    a, c = legs[leg][0][probe], legs["cycles"][0][probe]
    assert "error" not in a and "error" not in c, (a, c)
    assert c["d_ab"] < 1e-6 or c["d_ab"] < 0.5 * c["d_aa"]
    assert a["d_ab"] == 0.0, (probe, leg, a["d_ab"])
    for v in ("A", "B"):
        cm, am = np.array(c["mean_" + v]), np.array(a["mean_" + v])
        assert np.all(np.abs(am - cm) <= 0.04 * cm), (probe, leg, v, am, cm)
