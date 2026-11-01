"""#1238 - Image Texture Color follows Cycles' alpha association rule (CPU and GPU share the addon upload).

Cycles v5.2.0 (all Apache-2.0):
  * intern/cycles/util/image_metadata.cpp:157-169  ImageMetaData::finalize: Straight (UNASSOCIATED) -> associate at load,
    Premultiplied / Channel Packed / None / data colour space -> no association;
  * intern/cycles/util/image_metadata.cpp:489-499  conform_pixels_to_metadata_type: RGB *= alpha;
  * intern/cycles/scene/shader_nodes.cpp:449-457   un-associate only when the node's Alpha output is linked (and not
    data / Channel Packed / None); intern/cycles/kernel/svm/image.h:28-31: r /= alpha where alpha is neither 0 nor 1;
  * intern/cycles/blender/util.h:326-342 image_is_builtin: a file-backed image is read from disk, not from Blender's buffer.

So Color = RGB * alpha (Straight, Alpha unlinked) or RGB / alpha (Premultiplied, Alpha linked); the other two cases keep
the stored RGB. Blender keeps a Straight float buffer premultiplied (probed 5.2), which the addon treats as Premultiplied.

Layers: (1) addon upload with a stub bpy (no engine); (2) Cycles-referenced probes img_alpha* (real Blender + engine,
CPU and GPU legs) from tests/pkg321_probe_blender.py.
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

REPO = Path(__file__).resolve().parents[1]

# straight RGBA texels: translucent, opaque, fully transparent, quarter alpha (one row)
TEXELS = [(0.8, 0.4, 0.2, 0.5), (0.6, 0.3, 0.9, 1.0), (0.9, 0.9, 0.9, 0.0), (0.5, 0.25, 0.125, 0.25)]


class _Pixels(list):
    def foreach_get(self, buf):
        buf[:] = self


class _Img:
    """bpy.types.Image stand-in carrying every attribute the alpha rule reads."""
    def __init__(self, name, mode="STRAIGHT", is_float=False, cs="Linear Rec.709", source="FILE",
                 packed=None, dirty=False, texels=TEXELS):
        self.name = name
        self.size = (len(texels), 1)
        self.has_data = True
        self.filepath = ""
        self.packed_file = packed
        self.is_float = is_float
        self.alpha_mode = mode
        self.source = source
        self.is_dirty = dirty
        self.colorspace_settings = types.SimpleNamespace(name=cs)
        self.pixels = _Pixels(v for t in texels for v in t)

    def reload(self):
        pass


class _Renderer(P._RecordingRenderer):
    def __init__(self):
        super().__init__()
        self.rgb = {}

    def load_texture(self, name, rgb, w, h):
        super().load_texture(name, rgb, w, h)
        self.rgb[name] = np.array(rgb, np.float64).reshape(-1, 3)


def _engine(monkeypatch):
    addon = P._load_blender_addon(monkeypatch)
    return addon.CustomRaytracerRenderEngine()


def _upload(monkeypatch, img, linked):
    engine, r = _engine(monkeypatch), _Renderer()
    name = engine.load_blender_image(img, r, alpha_linked=linked)
    return name, r.rgb[name]


_RGB = np.array([t[:3] for t in TEXELS], np.float64)
_A = np.array([t[3] for t in TEXELS], np.float64)[:, None]
_PREMUL = _RGB * _A
_part = (_A != 0.0) & (_A != 1.0)
_UNPREMUL = np.where(_part, _RGB / np.where(_part, _A, 1.0), _RGB)


# =========================================================================== #
# 1. Addon upload (stub bpy)
# =========================================================================== #
@pytest.mark.parametrize("kw,linked,want", [
    # Straight byte: premultiplied at load; Alpha linked un-premultiplies back to the stored RGB
    (dict(mode="STRAIGHT"), False, _PREMUL),
    (dict(mode="STRAIGHT"), True, _RGB),
    # Premultiplied byte: stored as is; Alpha linked divides by alpha (not by 0 or 1)
    (dict(mode="PREMUL"), False, _RGB),
    (dict(mode="PREMUL"), True, _UNPREMUL),
    # float file in Straight mode: Blender's buffer already carries RGB*alpha (Cycles reads the file) -> behaves as Premultiplied
    (dict(mode="STRAIGHT", is_float=True), False, _RGB),
    (dict(mode="STRAIGHT", is_float=True), True, _UNPREMUL),
    # builtin float (generated / packed / edited): Cycles reads the buffer itself -> the rule applies literally
    (dict(mode="STRAIGHT", is_float=True, source="GENERATED"), False, _PREMUL),
    (dict(mode="STRAIGHT", is_float=True, source="GENERATED"), True, _RGB),
    (dict(mode="STRAIGHT", is_float=True, packed=object()), False, _PREMUL),
    (dict(mode="STRAIGHT", is_float=True, dirty=True), True, _RGB),
    # float EXR default (Premultiplied)
    (dict(mode="PREMUL", is_float=True), False, _RGB),
    (dict(mode="PREMUL", is_float=True), True, _UNPREMUL),
    # no alpha association: Channel Packed, None, data colour spaces
    (dict(mode="CHANNEL_PACKED"), False, _RGB),
    (dict(mode="CHANNEL_PACKED"), True, _RGB),
    (dict(mode="NONE"), False, _RGB),
    (dict(mode="NONE"), True, _RGB),
    (dict(mode="STRAIGHT", cs="Non-Color"), False, _RGB),
    (dict(mode="PREMUL", cs="Raw"), True, _RGB),
])
def test_color_follows_the_cycles_association_rule(monkeypatch, kw, linked, want):
    _name, rgb = _upload(monkeypatch, _Img("rule.png", **kw), linked)
    assert np.allclose(rgb, want, atol=1e-6), (kw, linked, rgb, want)


def test_unknown_alpha_link_keeps_the_stored_rgb(monkeypatch):
    """No node (bump / normal / legacy callers): nothing is guessed."""
    name, rgb = _upload(monkeypatch, _Img("none.png"), None)
    assert np.allclose(rgb, _RGB) and "::alpha=" not in name


def test_srgb_byte_is_associated_in_encoded_space_then_decoded(monkeypatch):
    """Cycles premultiplies the encoded bytes (image_metadata.cpp:489) and the kernel decodes afterwards
    (kernel/svm/image.h:28-38): lin(c * a), not lin(c) * a."""
    dec = lambda x: np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)    # noqa: E731
    _n, un = _upload(monkeypatch, _Img("s.png", cs="sRGB"), False)
    _n, li = _upload(monkeypatch, _Img("s2.png", cs="sRGB"), True)
    assert np.allclose(un, dec(_PREMUL), atol=1e-6) and not np.allclose(un, dec(_RGB) * _A, atol=1e-3)
    assert np.allclose(li, dec(_RGB), atol=1e-6)


def test_opaque_image_keeps_its_plain_name_and_one_upload(monkeypatch):
    engine, r = _engine(monkeypatch), _Renderer()
    img = _Img("opaque.png", texels=[(0.3, 0.4, 0.5, 1.0), (0.1, 0.2, 0.3, 1.0)])
    a = engine.load_blender_image(img, r, alpha_linked=False)
    b = engine.load_blender_image(img, r, alpha_linked=True)
    assert a == b and "::alpha=" not in a and len(r.rgb) == 1


def test_image_without_an_alpha_plane_is_not_scanned(monkeypatch):
    """Image.depth 24 (RGB byte) / 96 (RGB float): no alpha plane, so the buffer's alpha is not an association input."""
    for depth in (24, 96):
        img = _Img("noalpha%d.png" % depth)
        img.depth = depth
        name, rgb = _upload(monkeypatch, img, False)
        assert "::alpha=" not in name and np.allclose(rgb, _RGB)


def test_one_image_behind_two_nodes_gets_two_uploads(monkeypatch):
    """Alpha linked on one node, unlinked on the other: distinct cache keys (the #1239 bake cache keys on the texture
    uid + content version), each repeat load is a cache hit."""
    engine, r = _engine(monkeypatch), _Renderer()
    img = _Img("shared.png")
    unl = engine.load_blender_image(img, r, alpha_linked=False)
    lnk = engine.load_blender_image(img, r, alpha_linked=True)
    assert unl != lnk and "::alpha=premul" in unl and "::alpha=" not in lnk
    assert engine.load_blender_image(img, r, alpha_linked=False) == unl
    assert engine.load_blender_image(img, r, alpha_linked=True) == lnk
    assert sorted(r.rgb) == sorted([unl, lnk])
    assert np.allclose(r.rgb[unl], _PREMUL) and np.allclose(r.rgb[lnk], _RGB)


def test_alpha_linked_reads_the_nodes_alpha_output(monkeypatch):
    engine = _engine(monkeypatch)
    linked = types.SimpleNamespace(outputs={"Alpha": P._Socket(linked_to=object())})
    unlinked = types.SimpleNamespace(outputs={"Alpha": P._Socket()})
    assert engine._image_alpha_linked(linked) is True
    assert engine._image_alpha_linked(unlinked) is False
    assert engine._image_alpha_linked(types.SimpleNamespace()) is None
    assert engine._image_alpha_linked(types.SimpleNamespace(outputs=[1])) is None


def test_base_colour_site_reads_the_alpha_link(monkeypatch):
    engine = _engine(monkeypatch)
    for linked, want in ((False, _PREMUL), (True, _RGB)):
        r = _Renderer()
        out = {"Alpha": P._Socket(linked_to=object()) if linked else P._Socket()}
        tex = P._Node("TEX_IMAGE", inputs={"Vector": P._Socket()}, image=_Img("bc%d.png" % linked),
                      extension="REPEAT", interpolation="Closest", outputs=out)
        bsdf = P._Node("BSDF_PRINCIPLED", inputs={"Base Color": P._Socket((0.8, 0.8, 0.8), linked_to=tex)})
        _fb, name = engine.get_base_color_texture(bsdf, "Base Color", r)
        assert np.allclose(r.rgb[name], want), (linked, r.rgb[name])


def test_program_child_and_graph_sites_read_the_alpha_link(monkeypatch):
    from test_issue818_procedural_opvm import Link, Node, Sock, _load_addon_stub
    addon = _load_addon_stub(monkeypatch)
    eng = addon.CustomRaytracerRenderEngine.__new__(addon.CustomRaytracerRenderEngine)
    eng._current_material_name = "M1238"
    eng._generated_textures_by_material = {}
    got = {}
    for linked in (False, True):
        img = Node("TEX_IMAGE", inputs=[Sock("Vector")], image=_Img("pc%d.png" % linked), extension="REPEAT",
                   interpolation="Closest",
                   outputs={"Alpha": P._Socket(linked_to=object()) if linked else P._Socket()})
        mul = Node("MATH", operation="MULTIPLY", inputs=[Sock("A", 0.0, Link(img, "Color")), Sock("B", 2.0)])
        sock = Sock("Base Color", [0.5, 0.5, 0.5], Link(mul, "Color"))
        r = _Renderer()
        r.create_program_texture = lambda *a, **k: None
        r.program_texture_add_input = lambda *a, **k: None
        r.set_program_texture_program = lambda *a, **k: None
        prog = eng._maybe_build_program_texture(sock, Node("BSDF_PRINCIPLED", inputs=[sock]), "Base Color", r)
        assert prog is not None, eng._degradation_report().messages()
        got[linked] = next(iter(r.rgb.values()))
        # graph input site (native + coordinate kinds)
        for kind in ("native", "coord"):
            gimg = Node("TEX_IMAGE", inputs=[Sock("Vector")], image=_Img("g%d%s.png" % (linked, kind)),
                        extension="REPEAT", interpolation="Closest", name="G",
                        outputs={"Alpha": P._Socket(linked_to=object()) if linked else P._Socket()})
            gr = _Renderer()
            gname = eng._load_graph_input(gimg, None, kind, gr)
            assert np.allclose(gr.rgb[gname], _RGB if linked else _PREMUL), (kind, linked)
    assert np.allclose(got[False], _PREMUL) and np.allclose(got[True], _RGB)


# =========================================================================== #
# 2. Cycles-referenced probes (real Blender + engine; CPU and GPU legs)
# =========================================================================== #
PROBE_IDS = ["img_alpha", "img_alpha_premul", "img_alpha_exr", "img_alpha_float", "img_alpha_genfloat",
             "img_alpha_data"]


def _find_blender():
    exe = os.environ.get("BLENDER_EXE", "")
    cands = [Path(exe)] if exe else []
    cands += [Path(r"C:\Program Files\Blender Foundation\Blender %s\blender.exe" % v) for v in ("5.2", "5.1")]
    return next((c for c in cands if c.is_file()), None)


def _pyd_dir():
    d = Path(os.environ.get("ASTRORAY_PYD_DIR", REPO / "build_cuda"))
    return d if list(d.glob("astroray*.pyd")) else None


def _have_cuda():
    astroray = pytest.importorskip("astroray")
    return bool(astroray.__features__.get("cuda", False)) and bool(getattr(astroray.Renderer(), "gpu_available", False))


def _run_leg(tag, engine, device):
    blender, pyd = _find_blender(), _pyd_dir()
    if blender is None or pyd is None:
        pytest.skip("needs Blender 5.x and an engine .pyd (ASTRORAY_PYD_DIR)")
    if device == "gpu" and not _have_cuda():
        pytest.skip("No CUDA GPU")
    out = Path(tempfile.mkdtemp(prefix="i1238_%s_" % tag, dir=os.environ.get("I1238_WORK")))
    env = dict(os.environ, ASTRORAY_PYD_DIR=str(pyd), OMP_NUM_THREADS="8", PKG321_DEVICE=device,
               PKG328_ENGINE=engine)
    if device == "cpu":
        env["CUDA_VISIBLE_DEVICES"] = "-1"
    proc = subprocess.run([str(blender), "--background", "--factory-startup", "--python",
                           str(REPO / "tests" / "pkg321_probe_blender.py"), "--", str(out), *PROBE_IDS],
                          capture_output=True, text=True, timeout=900, env=env, check=False)
    assert "PKG321_PROBES_DONE" in proc.stdout, proc.stdout[-2000:] + proc.stderr[-2000:]
    return json.loads((out / "results.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def legs():
    return {"cycles": _run_leg("cycles", "CYCLES", "cpu"),
            "cpu": _run_leg("cpu", "CUSTOM_RAYTRACER", "cpu"),
            "gpu": _run_leg("gpu", "CUSTOM_RAYTRACER", "gpu")}


@pytest.mark.serial
@pytest.mark.parametrize("probe", PROBE_IDS)
@pytest.mark.parametrize("leg", ["cpu", "gpu"])
def test_probe_tracks_cycles(legs, probe, leg):
    """Alpha unlinked (A) and linked (B) each match Cycles' mean colour within 1.5 % per channel (the residual is
    Cycles' 8-bit premultiplied storage), and moving the link moves Astroray as far as it moves Cycles (the data-space
    probe: neither moves)."""
    c, a = legs["cycles"][probe], legs[leg][probe]
    assert "error" not in a and "error" not in c, (a, c)
    for v in ("A", "B"):
        cm, am = np.array(c["mean_" + v]), np.array(a["mean_" + v])
        assert np.all(np.abs(am - cm) <= 0.015 * cm), (probe, leg, v, am, cm)
    if probe == "img_alpha_data":
        assert a["d_ab"] < 1e-6 and c["d_ab"] < 1e-6
    else:
        assert 0.9 <= a["d_ab"] / c["d_ab"] <= 1.1, (probe, leg, a["d_ab"], c["d_ab"])
