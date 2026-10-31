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


@pytest.mark.parametrize("on_gpu", [False, True], ids=["cpu", "gpu"])
def test_bump_with_procedural_height_is_bound_and_reported_on_gpu(monkeypatch, on_gpu):
    """#1005: a Voronoi Height is loaded as a texture (the CPU differences it). A CPU
    render needs no report; a GPU render reports it (the GPU bump samples images only)."""
    addon = P._load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    vnode = P._Node("TEX_VORONOI", inputs={"Vector": P._Socket()})
    height = P._Socket(linked_to=vnode, output_name="Distance")
    shader, _, bump = _bump_chain(P, P._FakeImage("n2.png"), height)
    res = engine.get_normal_inputs(shader)
    assert res["bump_image"] is None and res["bump_node"] is bump
    seen = []
    engine._warn_shader_fallback = lambda *a, **k: seen.append(a)
    engine._bump_render_on_gpu = lambda renderer: on_gpu
    tex = engine.load_bump_height_texture(res, P._RecordingRenderer())
    assert tex is not None and "voronoi" in tex
    bump_msgs = [a[1] for a in seen if a[0] == "BUMP"]
    if on_gpu:
        assert bump_msgs and "CPU only" in bump_msgs[0], seen
    else:
        assert not bump_msgs, seen


def test_bump_with_unloadable_height_is_reported(monkeypatch):
    addon = P._load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    vnode = P._Node("TEX_VORONOI", inputs={"Vector": P._Socket()})
    shader, _, _ = _bump_chain(P, P._FakeImage("n3.png"), P._Socket(linked_to=vnode, output_name="Distance"))
    res = engine.get_normal_inputs(shader)
    seen = []
    engine._warn_shader_fallback = lambda *a, **k: seen.append(a)
    engine.get_base_color_texture = lambda node, name, renderer: ([0.8, 0.8, 0.8], None)
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


# ---------------------------------------------------------------------------
# #1004 residual: the image bump under a Mapping, and where its relief sits
# ---------------------------------------------------------------------------

_SUN = np.array([-1.0, 0.0, -0.4]) / np.linalg.norm([-1.0, 0.0, -0.4])


def _image_bump_quad(height_rows, use_gpu, mapping=None, dist=0.5, res=48, spp=64):
    """Sun-lit Lambertian quad (world x in [-1, 1] <-> UV u in [0, 1]) bumped by an image."""
    r = create_renderer()
    if use_gpu:
        if not (bool(astroray.__features__.get("cuda", False)) and
                bool(getattr(r, "gpu_available", False))):
            pytest.skip("No CUDA GPU")
        r.set_use_gpu(True)
    r.set_seed(5)
    r.set_background_color([0.0, 0.0, 0.0])
    h, w = height_rows.shape
    img = np.repeat(height_rows[:, :, None], 3, axis=2).astype(np.float32)
    r.load_texture("h_img", img, w, h, "UV")
    if mapping is not None:
        r.set_texture_mapping_matrix("h_img", mapping)
    params = {"bump_map_texture": "h_img", "bump_distance": dist, "bump_strength": 1.0}
    mat = r.create_material("lambertian", [0.8, 0.8, 0.8], params)
    A, B, C, D, n = [-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0], [0, 0, 1]
    r.add_triangle_layers(A, B, C, mat, {"UVMap": [[0, 0], [1, 0], [1, 1]]}, n, n, n)
    r.add_triangle_layers(A, C, D, mat, {"UVMap": [[0, 0], [1, 1], [0, 1]]}, n, n, n)
    r.add_sun_light_dedicated(_SUN.tolist(), 0.02, {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 3.0)
    setup_camera(r, look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0],
                 vfov=45, width=res, height=res)
    return np.asarray(render_image(r, samples=spp, max_depth=1, apply_gamma=False), np.float32)


@pytest.mark.parametrize("use_gpu", [False, True], ids=["cpu", "gpu"])
@pytest.mark.parametrize("scale", [0.5, 0.25])
def test_mapped_image_bump_slope_follows_mapping_scale(scale, use_gpu):
    """#1004: a Mapping Scale s on the Height image scales the slope by s (Cycles offsets
    the coordinate BEFORE the Mapping). The old post-Mapping tap paired a texture-space
    step with a mesh-UV dP, so the slope ignored s (prod_pbr_group: Scale 3, bump 3x weak)."""
    n_tex = 64
    ramp = (np.arange(n_tex, dtype=np.float32) + 0.5) / n_tex   # h(u_tex) = u_tex between texel centres
    im = _image_bump_quad(np.repeat(ramp[None, :], n_tex, axis=0), use_gpu,
                          mapping=[scale, 0, 0, 0, 0, scale, 0, 0, 0, 0, 1, 0])
    g = scale * 0.5                       # dh/dx: u_tex per world x = s / 2
    nb = np.array([-0.5 * g, 0.0, 1.0])
    nb /= np.linalg.norm(nb)
    expected = 0.8 / np.pi * 3.0 * max(0.0, float(-_SUN @ nb))   # Lambert under a sun of 3 W/m^2
    measured = float(im[16:32, 16:32].mean())
    assert abs(measured / expected - 1.0) < 0.03, (measured, expected)


@pytest.mark.parametrize("use_gpu", [False, True], ids=["cpu", "gpu"])
def test_image_bump_relief_is_centred_on_the_height_step(use_gpu):
    """#1004: Cycles differences the Linear-interpolated Height, so the relief of a height
    step sits on the texel boundary. The old nearest-sampled forward difference over 1.5
    texels put the whole band on the low side (0.75 texel = 2.25 px early here), lighting
    the wrong material next to every step (prod_pbr_group left ROI)."""
    n_tex, res = 16, 48                   # quad spans the frame width ~exactly: 3 px per texel
    step = np.where(np.arange(n_tex) >= n_tex // 2, 1.0, 0.0).astype(np.float32)
    bumped = _image_bump_quad(np.repeat(step[None, :], n_tex, axis=0), use_gpu, dist=0.05, res=res)
    flat = _image_bump_quad(np.zeros((n_tex, n_tex), np.float32), use_gpu, dist=0.05, res=res)
    prof = np.abs(bumped[12:36].mean(axis=(0, 2)) - flat[12:36].mean(axis=(0, 2)))
    assert prof.max() > 0.02, prof
    cols = np.arange(res) + 0.5
    # the quad edge (x = +-1) lands at a few pixels from the frame edge; locate u = 0.5 from
    # the flat render's lit extent rather than assuming the projection.
    lit = np.nonzero(flat[24].mean(axis=1) > 0.05)[0]
    centre = 0.5 * (lit[0] + lit[-1] + 1)
    centroid = float((prof * cols).sum() / prof.sum())
    assert abs(centroid - centre) < 1.0, (centroid, centre, prof.round(3))


@pytest.mark.parametrize("use_gpu", [False, True], ids=["cpu", "gpu"])
def test_normal_map_image_is_read_linear(use_gpu):
    """#1004: the Normal Map image is read Linear (Cycles' Image Texture default), so between
    a +x-tilted and a -x-tilted texel the normal blends through the flat normal. A nearest
    read jumps from one tilt to the other at u = 0.5 (prod_pbr_group centre/right 3-6 % off)."""
    r = create_renderer()
    if use_gpu:
        if not (bool(astroray.__features__.get("cuda", False)) and
                bool(getattr(r, "gpu_available", False))):
            pytest.skip("No CUDA GPU")
        r.set_use_gpu(True)
    r.set_seed(5)
    r.set_background_color([0.0, 0.0, 0.0])
    a = np.radians(40.0)
    left, right = np.array([np.sin(a), 0, np.cos(a)]), np.array([-np.sin(a), 0, np.cos(a)])
    img = np.array([[left, right], [left, right]], np.float32) * 0.5 + 0.5   # 2x2 tangent-space map
    r.load_texture("n_img", img, 2, 2, "UV")
    mat = r.create_material("lambertian", [0.8, 0.8, 0.8],
                            {"normal_map_texture": "n_img", "normal_strength": 1.0})
    A, B, C, D, n = [-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0], [0, 0, 1]
    r.add_triangle_layers(A, B, C, mat, {"UVMap": [[0, 0], [1, 0], [1, 1]]}, n, n, n)
    r.add_triangle_layers(A, C, D, mat, {"UVMap": [[0, 0], [1, 1], [0, 1]]}, n, n, n)
    r.add_sun_light_dedicated(_SUN.tolist(), 0.02, {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 3.0)
    setup_camera(r, look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0], vfov=45, width=48, height=48)
    im = np.asarray(render_image(r, samples=64, max_depth=1, apply_gamma=False), np.float32)
    lam = lambda nn: 0.8 / np.pi * 3.0 * max(0.0, float(-_SUN @ nn))   # noqa: E731
    centre = float(im[16:32, 23:25].mean())   # u = 0.5: the two texel centres blend to flat
    assert abs(centre / lam(np.array([0.0, 0.0, 1.0])) - 1.0) < 0.05, (centre, lam(np.array([0.0, 0.0, 1.0])))
    # nearest would give the mean of the two tilts, about cos(40 deg) = 0.77 of flat
    assert abs(centre / (0.5 * (lam(left) + lam(right))) - 1.0) > 0.15


# ---------------------------------------------------------------------------
# #1005: a Bump on the Principled Normal leaves the coat on sd->N
# ---------------------------------------------------------------------------

def _coat_quad(bump, use_gpu, coat_follows=False):
    """Black-base Principled with a clear coat (only the coat reflects), a sun at the
    mirror direction of the flat quad, and optionally a steep image-ramp bump."""
    r = create_renderer()
    if use_gpu:
        if not (bool(astroray.__features__.get("cuda", False)) and
                bool(getattr(r, "gpu_available", False))):
            pytest.skip("No CUDA GPU")
        r.set_use_gpu(True)
    r.set_seed(5)
    r.set_background_color([0.0, 0.0, 0.0])
    params = {"metallic": 0.0, "roughness": 0.5, "specular_ior_level": 0.0,
              "coat_weight": 1.0, "coat_roughness": 0.25, "coat_ior": 1.5}
    if bump:
        n_tex = 64
        ramp = (np.arange(n_tex, dtype=np.float32) + 0.5) / n_tex
        img = np.repeat(np.repeat(ramp[None, :, None], n_tex, axis=0), 3, axis=2)
        r.load_texture("h_coat", img, n_tex, n_tex, "UV")
        params.update({"bump_map_texture": "h_coat", "bump_distance": 1.0, "bump_strength": 1.0})
        if coat_follows:
            params["coat_follows_bump"] = 1.0
    mat = r.create_material("principled", [0.0, 0.0, 0.0], params)
    A, B, C, D, n = [-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0], [0, 0, 1]
    r.add_triangle_layers(A, B, C, mat, {"UVMap": [[0, 0], [1, 0], [1, 1]]}, n, n, n)
    r.add_triangle_layers(A, C, D, mat, {"UVMap": [[0, 0], [1, 1], [0, 1]]}, n, n, n)
    r.add_sun_light_dedicated([0.0, 0.0, -1.0], 0.05, {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 3.0)
    setup_camera(r, look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0], vfov=30, width=32, height=32)
    return np.asarray(render_image(r, samples=128, max_depth=1, apply_gamma=False), np.float32)


@pytest.mark.parametrize("use_gpu", [False, True], ids=["cpu", "gpu"])  # GPU: #1153
def test_bump_on_principled_normal_leaves_the_coat_smooth(use_gpu):
    """#1005: Cycles shades the coat on Coat Normal, whose unlinked default is sd->N
    (svm/closure.h; LINK_NORMAL), so a Bump into Principled Normal does not move the
    clear-coat highlight. Bumping the coat too broke up prod_car_paint's coat reflection
    (lit_front B 1.25x / upper_flake B 0.66x of Cycles with the flake bump applied)."""
    flat, bumped = _coat_quad(False, use_gpu), _coat_quad(True, use_gpu)
    c = (slice(10, 22), slice(10, 22))
    assert flat[c].mean() > 0.02, flat[c].mean()
    # a 27 deg bump tilt moves a roughness-0.25 coat highlight far off the sun direction
    assert abs(bumped[c].mean() / flat[c].mean() - 1.0) < 0.05, (bumped[c].mean(), flat[c].mean())


@pytest.mark.parametrize("use_gpu", [False, True], ids=["cpu", "gpu"])  # GPU: #1153
def test_coat_follows_a_bump_that_cycles_routes_through_sd_n(use_gpu):
    """#1005 review: an Output Displacement bump sets sd->N in Cycles (svm_node_set_normal)
    and a Coat Normal wired to the same node bumps the coat too. coat_follows_bump=1 keeps
    the coat on the perturbed normal, so its highlight moves off the sun like the base."""
    flat = _coat_quad(False, use_gpu)
    bumped = _coat_quad(True, use_gpu, coat_follows=True)
    c = (slice(10, 22), slice(10, 22))
    assert bumped[c].mean() < 0.5 * flat[c].mean(), (bumped[c].mean(), flat[c].mean())


def test_output_displacement_bump_marks_the_coat_to_follow(monkeypatch):
    addon = P._load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    seen = {}
    engine._shader_spec_from_node = lambda node, renderer, tree: {'type': 'principled'}
    engine.load_bump_height_texture = lambda spec, renderer: "h_disp"
    engine._create_material_from_shader_spec = lambda spec, renderer: seen.update(spec) or 7
    disp = {'bump_image': None, 'bump_node': object(), 'bump_strength': 1.0, 'bump_distance': 0.1}
    assert engine.convert_shader_node(P._Node("BSDF_PRINCIPLED"), P._RecordingRenderer(), None, disp) == 7
    assert seen.get('bump_map_texture') == "h_disp" and seen.get('coat_follows_bump') == 1.0


@pytest.mark.parametrize("same", [True, False], ids=["same_node", "other_node"])
def test_linked_coat_normal_follows_the_normal_chain(monkeypatch, same):
    """#1005 review: Coat Normal wired to the same Bump / Normal Map as Normal is honoured
    (coat follows the bump, no report); a different Coat Normal chain stays reported."""
    addon = P._load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    bump = P._Node("BUMP", inputs={})
    other = P._Node("NORMAL_MAP", inputs={})
    node = P._Node("BSDF_PRINCIPLED", inputs={
        "Normal": P._Socket(linked_to=bump, output_name="Normal"),
        "Coat Normal": P._Socket(linked_to=bump if same else other, output_name="Normal")})
    assert engine._coat_normal_follows_normal(node) is same
    gaps = engine._native_principled_gaps(node, {})
    assert any("Coat Normal" in g for g in gaps) is (not same), gaps
