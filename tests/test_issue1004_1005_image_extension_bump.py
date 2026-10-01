#!/usr/bin/env python
"""#1004 / #1005 - Image Texture extension (REPEAT) and Bump Height routing.

#1004: a node group Tiling input -> Combine XYZ -> Mapping.Scale -> Image Texture was
reported "ignored". Blender's inline_shader_nodes() already folds the group input
into Mapping.Scale; the real defect was that the engine clamped every image sample
to [0,1] (no REPEAT), so a scale>1 Mapping produced edge streaks, and that the
Normal Map / Bump image uploads dropped their Mapping. Cycles default extension is
REPEAT (intern/cycles/kernel/device/cpu/image.h, Apache-2.0).

#1005: a Bump Height driven by a procedural texture was silently dropped.

Render legs use the native module (CPU always, GPU when a CUDA device exists); the
addon legs use the Blender API stub pattern of test_blender_uv_plumbing.py.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent))
import test_blender_uv_plumbing as P  # stub loader + recording renderer

# ---------------------------------------------------------------------------
# Addon legs (no native module needed)
# ---------------------------------------------------------------------------


class _OldModuleRenderer:
    """A native module that predates #1004: no set_texture_extension."""

    def __init__(self):
        self._inner = P._RecordingRenderer()

    def __getattr__(self, name):
        if name == "set_texture_extension":
            raise AttributeError(name)
        return getattr(self._inner, name)


def test_load_blender_image_sets_repeat_by_default(monkeypatch):
    addon = P._load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    r = P._RecordingRenderer()
    name = engine.load_blender_image(P._FakeImage("a.png"), r)
    assert r.extension_calls == [(name, "REPEAT")]


@pytest.mark.parametrize("ext", ["EXTEND", "CLIP", "MIRROR"])
def test_load_blender_image_passes_node_extension(monkeypatch, ext):
    addon = P._load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    r = P._RecordingRenderer()
    name = engine.load_blender_image(P._FakeImage("b.png"), r, extension=ext)
    assert r.extension_calls == [(name, ext)]
    assert f"::ext={ext}" in name   # same image, different extension: distinct texture


def test_old_module_without_binding_reports_non_extend(monkeypatch):
    addon = P._load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    seen = []
    engine._warn_shader_fallback = lambda *a, **k: seen.append(a)
    engine.load_blender_image(P._FakeImage("c.png"), _OldModuleRenderer())  # no binding
    assert seen and seen[0][0] == "TEX_IMAGE"


def _bump_chain(addon_P, image, height_node, vector=None):
    img_node = P._Node("TEX_IMAGE", inputs={"Vector": vector or P._Socket()}, image=image,
                       extension="MIRROR")
    nmap = P._Node("NORMAL_MAP", inputs={
        "Strength": P._Socket(1.0),
        "Color": P._Socket(linked_to=img_node, output_name="Color")})
    height = height_node if height_node is not None else P._Socket()
    bump = P._Node("BUMP", inputs={
        "Strength": P._Socket(0.5), "Distance": P._Socket(0.02),
        "Height": height, "Normal": P._Socket(linked_to=nmap, output_name="Normal")})
    shader = P._Node("BSDF_PRINCIPLED", inputs={"Normal": P._Socket(linked_to=bump,
                                                                    output_name="Normal")})
    return shader, img_node, bump


def test_normal_inputs_carry_vector_and_extension(monkeypatch):
    addon = P._load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    image = P._FakeImage("n.png")
    vec = P._Socket()
    shader, _, _ = _bump_chain(P, image, None, vector=vec)
    res = engine.get_normal_inputs(shader)
    assert res["normal_image"] is image
    assert res["normal_vector"] is vec           # #1004: Mapping chain no longer dropped
    assert res["normal_extension"] == "MIRROR"


def test_bump_with_procedural_height_is_reported_not_silent(monkeypatch):
    """#1005: a Voronoi Height must leave a DegradationReport entry (was a silent drop)."""
    addon = P._load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    vnode = P._Node("TEX_VORONOI", inputs={"Vector": P._Socket()})
    height = P._Socket(linked_to=vnode, output_name="Distance")
    shader, _, bump = _bump_chain(P, P._FakeImage("n2.png"), height)
    res = engine.get_normal_inputs(shader)
    assert res["bump_image"] is None and res["bump_node"] is bump
    seen = []
    engine._warn_shader_fallback = lambda *a, **k: seen.append(a)
    assert engine.load_bump_height_texture(res, P._RecordingRenderer()) is None
    assert any(a[0] == "BUMP" and "not applied" in a[1] for a in seen), seen


# ---------------------------------------------------------------------------
# Native render legs
# ---------------------------------------------------------------------------

import astroray
from base_helpers import create_renderer, render_image, setup_camera

_SCALE2 = [2.0, 0.0, 0.0, 0.0, 0.0, 2.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0]


def _quad_render(ext, use_gpu):
    r = create_renderer()
    if not hasattr(r, "set_texture_extension"):
        pytest.skip("native module predates #1004 (set_texture_extension)")
    if use_gpu:
        if not (bool(astroray.__features__.get("cuda", False)) and
                bool(getattr(r, "gpu_available", False))):
            pytest.skip("No CUDA GPU")
        r.set_use_gpu(True)
    r.set_seed(3)
    r.set_background_color([0.5, 0.5, 0.5])
    img = np.array([[[0.9, 0.1, 0.1], [0.1, 0.9, 0.1]],
                    [[0.1, 0.1, 0.9], [0.9, 0.9, 0.1]]], dtype=np.float32)
    r.load_texture("ext_img", img.reshape(-1).tolist(), 2, 2)
    r.set_texture_mapping_matrix("ext_img", _SCALE2)
    if ext is not None:
        r.set_texture_extension("ext_img", ext)
    mat = r.create_material("lambertian", [1, 1, 1], {"texture": "ext_img"})
    A, B, C, D, n = [-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0], [0, 0, 1]
    r.add_triangle_layers(A, B, C, mat, {"UVMap": [[0, 0], [1, 0], [1, 1]]}, n, n, n)
    r.add_triangle_layers(A, C, D, mat, {"UVMap": [[0, 0], [1, 1], [0, 1]]}, n, n, n)
    setup_camera(r, look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0],
                 vfov=45, width=64, height=64)
    return render_image(r, samples=32, max_depth=2, apply_gamma=False)


def _quadrants(im):
    """Mean colour of the four quadrants of the quad (inner 40 % crop, off the edges)."""
    h, w = im.shape[:2]
    out = []
    for ys in (slice(h // 2 - h // 5 - 6, h // 2 - 4), slice(h // 2 + 4, h // 2 + h // 5 + 6)):
        for xs in (slice(w // 2 - w // 5 - 6, w // 2 - 4), slice(w // 2 + 4, w // 2 + w // 5 + 6)):
            out.append(im[ys, xs].reshape(-1, 3).mean(axis=0))
    return np.array(out)


@pytest.mark.parametrize("use_gpu", [False, True], ids=["cpu", "gpu"])
def test_repeat_tiles_scale2_but_extend_streaks(use_gpu):
    """Scale-2 Mapping: REPEAT shows the 2x2 image in every quadrant (equal means);
    the old clamp (EXTEND) smears one texel across the outer quadrants."""
    rep = _quadrants(_quad_render("REPEAT", use_gpu))
    ext = _quadrants(_quad_render("EXTEND", use_gpu))
    assert rep.mean() > 0.05
    spread = lambda q: float(np.abs(q - q.mean(axis=0)).max())  # noqa: E731
    # clamped: far quadrants are single-texel flats, clearly different colours
    assert spread(ext) > 0.10
    # repeat: every quadrant sees all four texels (crop-sampling residue only)
    assert spread(rep) < 0.65 * spread(ext)


@pytest.mark.parametrize("use_gpu", [False, True], ids=["cpu", "gpu"])
def test_mirror_matches_repeat_average_and_clip_goes_black(use_gpu):
    mir = _quadrants(_quad_render("MIRROR", use_gpu))
    assert np.abs(mir - mir.mean(axis=0)).max() < 0.5 * 0.3
    clip = _quadrants(_quad_render("CLIP", use_gpu))
    # CLIP: scale 2 puts the image in the lower-left quadrant only; the rest is zero
    # albedo (Cycles EXTENSION_CLIP returns zero), i.e. much darker than the image quadrant.
    lum = clip @ np.array([0.2126, 0.7152, 0.0722])
    assert lum.max() > 3.0 * np.sort(lum)[-2], lum


# ---------------------------------------------------------------------------
# #1005 CPU: a procedural Height in Object coordinates perturbs the normal
# ---------------------------------------------------------------------------

def _bump_quad(proc, use_image_ramp):
    """Quad with a +U height ramp. Image ramp (UV) vs Object-coord Gradient ramp with the
    same slope: Mapping maps object x in [-1,1] onto [0,1], so height = u in both."""
    r = create_renderer()
    r.set_seed(5)
    r.set_background_color([0.0, 0.0, 0.0])
    if use_image_ramp:
        col = np.arange(64, dtype=np.float32) / 63.0
        img = np.repeat(np.repeat(col[None, :, None], 64, axis=0), 3, axis=2)
        r.load_texture("h_ramp", img, 64, 64, "UV")
    else:
        r.create_procedural_texture("h_ramp", "gradient", [0, 1.0, 0, 0, 0, 1, 1, 1])
        r.set_texture_coord_mode("h_ramp", "OBJECT")
        r.set_texture_mapping_matrix("h_ramp", [0.5, 0, 0, 0.5, 0, 0.5, 0, 0.5, 0, 0, 1, 0])
    params = {"bump_map_texture": "h_ramp", "bump_distance": 0.5, "bump_strength": 1.0}
    mat = r.create_material("lambertian", [0.8, 0.8, 0.8], params)
    A, B, C, D, n = [-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0], [0, 0, 1]
    r.add_triangle_layers(A, B, C, mat, {"UVMap": [[0, 0], [1, 0], [1, 1]]}, n, n, n)
    r.add_triangle_layers(A, C, D, mat, {"UVMap": [[0, 0], [1, 1], [0, 1]]}, n, n, n)
    d = np.array([-1.0, 0.0, -0.4])
    r.add_sun_light_dedicated((d / np.linalg.norm(d)).tolist(), 0.02,
                              {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 3.0)
    setup_camera(r, look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0],
                 vfov=45, width=48, height=48)
    return np.asarray(render_image(r, samples=64, max_depth=2, apply_gamma=False), np.float32)


def test_cpu_procedural_bump_matches_equivalent_image_ramp():
    img = _bump_quad(False, True)
    proc = _bump_quad(True, False)
    assert img.mean() > 0.02
    assert abs(proc.mean() / img.mean() - 1.0) < 0.12, (proc.mean(), img.mean())
