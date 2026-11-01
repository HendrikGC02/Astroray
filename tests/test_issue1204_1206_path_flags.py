"""#1204 / #1206: Light Path flags after a transmission, wrapped-material labels, caustic gate.

Cycles v5.2.0 (Apache-2.0):
- ``kernel/integrator/path_state.h`` path_state_next resets the ray visibility every bounce and sets
  DIFFUSE (label DIFFUSE) or GLOSSY (label GLOSSY or SINGULAR) for reflections AND transmissions;
  ``shade_surface.h`` hands that raw visibility to ``svm/light_path.h``. So Is Glossy Ray = 1 behind
  glass and Is Diffuse Ray = 1 behind a translucent sheet (#1204 item 1).
- Metal, Hair and ThinGlass report a glossy label, so a TwoSided / NormalMapped wrapper counts their
  bounces as glossy (#1204 item 2).
- ``svm/closure.h`` drops reflective / refractive closures when the toggle is off and the PREVIOUS
  bounce was diffuse (``ray_visibility & PATH_RAY_VISIBILITY_DIFFUSE``), at any roughness (#1206).
Research note: .astroray_plan/docs/issue1204-1206-path-flags-caustic-gate-research.md.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "blender_addon"))

import shader_vm_compiler as C  # noqa: E402
from test_issue991_light_path import _lp_value, _program, _render, _renderer, _roi  # noqa: E402

BACKENDS = [pytest.param(False, id="cpu"), pytest.param(True, id="gpu", marks=pytest.mark.gpu)]
LUM = np.array([0.2126, 0.7152, 0.0722])
_UV = {"UVMap": [[0, 0], [1, 0], [1, 1]]}


def _quad(r, mat, c, u, v, uv=False):
    """Flat quad: centre c, half-edges u, v, normal u x v. uv: carry a UV layer (program
    textures). (test_issue991's _quad passes the positions as vertex normals.)"""
    p = [[c[i] + su * u[i] + sv * v[i] for i in range(3)]
         for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    for tri in ((p[0], p[1], p[2]), (p[0], p[2], p[3])):
        if uv:
            r.add_triangle_layers(*tri, mat, _UV)
        else:
            r.add_triangle(*tri, mat)


# --------------------------------------------------------------------------- #
# #1204 item 1: Light Path visibility after a transmission
# --------------------------------------------------------------------------- #

def _sheet(r, kind):
    if kind == "translucent":   # the addon's Translucent BSDF lowering (#1084)
        return r.create_material("principled", [0.8, 0.8, 0.8], {
            "thin_wall": 1.0, "subsurface_weight": 1.0, "subsurface_anisotropy": 1.0,
            "ior": 1.0, "specular_ior_level": 0.0})
    rough = 0.3 if kind == "rough_glass" else 0.0
    return r.create_material("principled", [1.0, 1.0, 1.0],
                             {"transmission_weight": 1.0, "ior": 1.5, "roughness": rough})


def _wall_behind(use_gpu, sheet, output):
    """Camera -> sheet -> wall under a white world. The wall's albedo is 0.8 * <output>
    (output None: a constant 0.8). Returns the centre ROI luminance."""
    r = _renderer(use_gpu)
    r.set_background_color([1.0, 1.0, 1.0])
    if output is None:
        wall = r.create_material("principled", [0.8, 0.8, 0.8],
                                 {"roughness": 1.0, "specular_ior_level": 0.0})
    else:
        _program(r, "lp1204", C.compile_chain(_lp_value(output, 1.0)))
        wall = r.create_material("principled", [0.8, 0.8, 0.8],
                                 {"roughness": 1.0, "specular_ior_level": 0.0,
                                  "base_color_texture": "lp1204"})
    sm = _sheet(r, sheet)
    _quad(r, sm, [0, 2.0, 0], [1.0, 0, 0], [0, 0, 1.0])      # front face, normal -y
    if sheet != "translucent":
        _quad(r, sm, [0, 2.2, 0], [0, 0, 1.0], [1.0, 0, 0])  # back face, normal +y (a slab)
    _quad(r, wall, [0, 5, 0], [8.0, 0, 0], [0, 0, 8.0], uv=True)  # normal -y, faces the sheet
    img = _render(r, [0, 0, 0], [0, 1, 0], spp=128, vfov=2)
    return float(_roi(img, 24, 24) @ LUM)


@pytest.mark.parametrize("use_gpu", BACKENDS)
@pytest.mark.parametrize("sheet,output", [
    ("glass", "Is Glossy Ray"),
    ("rough_glass", "Is Glossy Ray"),
    ("translucent", "Is Diffuse Ray"),
])
def test_visibility_after_transmission_matches_cycles(use_gpu, sheet, output):
    """The wall behind the sheet shades like a constant albedo: the transmission sets
    GLOSSY (glass, smooth or rough) or DIFFUSE (translucent), as Cycles path_state_next."""
    prog = _wall_behind(use_gpu, sheet, output)
    const = _wall_behind(use_gpu, sheet, None)
    assert abs(prog / const - 1.0) < 0.06, (sheet, output, prog, const)


@pytest.mark.parametrize("use_gpu", BACKENDS)
@pytest.mark.parametrize("sheet,output", [
    ("glass", "Is Diffuse Ray"),
    ("translucent", "Is Glossy Ray"),
])
def test_visibility_after_transmission_sets_only_its_own_class(use_gpu, sheet, output):
    """The other class stays 0: the wall then adds nothing to what reaches it unshaded."""
    prog = _wall_behind(use_gpu, sheet, output)
    const = _wall_behind(use_gpu, sheet, None)
    assert prog < 0.8 * const, (sheet, output, prog, const)


# --------------------------------------------------------------------------- #
# #1204 item 2: wrapped Metal counts as a glossy bounce
# --------------------------------------------------------------------------- #

def _cycles_box(n_cap, rho, le=1.0):
    """L = Le * sum_{j=0}^{N+1} rho^j for a cap of N (Cycles max_<type>_bounce = N + 1)."""
    return le * sum(rho ** j for j in range(n_cap + 2))


def _wrapped_box_mean(use_gpu, wrapper, diffuse=-1, glossy=-1, spp=64):
    """Closed box of Add(<wrapper>(rough Metal), Emission); camera inside."""
    r = _renderer(use_gpu)
    metal = r.create_material(wrapper, [0.5, 0.5, 0.5], {"inner_type": "metal", "roughness": 0.6})
    emit = r.create_material("emissive", [1.0, 1.0, 1.0], {})
    mat = r.create_add_material(metal, emit)
    c = [np.array([x, y, z], float) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
    for a, b, cc, d in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
        for tri in ((a, b, cc), (a, cc, d)):
            v0, v1, v2 = (c[i] for i in tri)
            if np.dot(np.cross(v1 - v0, v2 - v0), -(v0 + v1 + v2)) < 0:   # wind inward
                v1, v2 = v2, v1
            r.add_triangle(v0.tolist(), v1.tolist(), v2.tolist(), mat)
    r.set_background_color([0.0, 0.0, 0.0])
    r.setup_camera([0, 0, 0], [0, 0, -1], [0, 1, 0], 60.0, 1.0, 0.0, 6.0, 32, 32)
    img = np.asarray(r.render(spp, 64, None, False, diffuse, glossy, -1, -1, -1), dtype=np.float64)
    return float(img.mean())


@pytest.mark.parametrize("use_gpu", [pytest.param(False, id="cpu")])
@pytest.mark.parametrize("wrapper", ["two_sided", "normal_mapped"])
def test_wrapped_metal_bounce_is_glossy(use_gpu, wrapper):
    """A glossy cap of 0 caps the wrapped Metal box; a diffuse cap of 0 leaves it alone.
    CPU only: the GPU unwraps the decorators (two_sided has no GPU lowering; an untextured
    normal_mapped renders black on the GPU, a separate finding) and its plain-metal box
    already counts glossy."""
    free = _wrapped_box_mean(use_gpu, wrapper)
    gcap = _wrapped_box_mean(use_gpu, wrapper, glossy=0)
    dcap = _wrapped_box_mean(use_gpu, wrapper, diffuse=0)
    assert gcap < 0.97 * free, (wrapper, free, gcap, dcap)
    assert abs(dcap / free - 1.0) < 0.01, (wrapper, free, gcap, dcap)


# --------------------------------------------------------------------------- #
# #1206: caustic gate on the previous bounce, at any roughness
# --------------------------------------------------------------------------- #

def _periscope_roi(use_gpu, reflective=True, refractive=True):
    """Floor -> ceiling mirror -> glass sphere -> lamp. The lamp sits inside the sphere and a
    wall hides the sphere from the floor patch, so the patch is lit only through the mirror: a
    refractive caustic whose previous bounce is the mirror, not the floor (Cycles keeps it with
    refractive caustics off and drops it with reflective caustics off)."""
    r = _renderer(use_gpu)
    r.set_background_color([0.0, 0.0, 0.0])
    floor = r.create_material("lambertian", [0.8, 0.8, 0.8], {})
    _quad(r, floor, [0, 0, 0], [3.0, 0, 0], [0, 3.0, 0])                 # z = 0, normal +z
    mirror = r.create_material("principled", [0.95, 0.95, 0.95],
                               {"metallic": 1.0, "roughness": 0.0})
    _quad(r, mirror, [2.0, 0, 3.0], [0, 1.5, 0], [2.5, 0, 0])            # z = 3, normal -z
    wall = r.create_material("lambertian", [0.0, 0.0, 0.0], {})
    _quad(r, wall, [2.0, 0, 0.65], [0, 0, 0.65], [0, 1.5, 0])            # x = 2, z 0..1.3
    glass = r.create_material("dielectric", [1.0, 1.0, 1.0], {"ior": 1.5})
    r.add_sphere([4.0, 0.0, 0.9], 0.8, glass)
    lamp = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 60.0})
    _quad(r, lamp, [4.0, 0, 0.9], [0, 0.3, 0], [-0.21, 0, -0.21])        # faces (-1, 0, 1)
    r.set_use_reflective_caustics(reflective)
    r.set_use_refractive_caustics(refractive)
    img = _render(r, [-2.0, 0.0, 1.2], [0.0, 0.0, 0.0], spp=256, depth=8, vfov=20)
    return float(_roi(img, 24, 24, h=4) @ LUM)


@pytest.mark.parametrize("use_gpu", BACKENDS)
def test_refractive_gate_reads_previous_bounce_not_a_diffuse_ancestor(use_gpu):
    on = _periscope_roi(use_gpu)
    refr_off = _periscope_roi(use_gpu, refractive=False)
    refl_off = _periscope_roi(use_gpu, reflective=False)
    assert on > 1e-3, (on, refr_off, refl_off)
    assert refr_off > 0.9 * on, (on, refr_off, refl_off)    # kept: glass follows the mirror
    assert refl_off < 0.1 * on, (on, refr_off, refl_off)    # dropped: mirror follows the floor


CW, CH = 140, 110


def _over_floor(use_gpu, obj, reflective=True, refractive=True):
    """The #1198 scene: an object over a Lambertian floor under an area light."""
    r = _renderer(use_gpu)
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_seed(1206)
    if obj == "rough_glass":
        m = r.create_material("principled", [1.0, 1.0, 1.0],
                              {"transmission_weight": 1.0, "ior": 1.5, "roughness": 0.2})
    elif obj == "rough_glass_black":   # Cycles' gated glass: transmission tint 0
        m = r.create_material("principled", [0.0, 0.0, 0.0],
                              {"transmission_weight": 1.0, "ior": 1.5, "roughness": 0.2})
    elif obj == "rough_metal":
        m = r.create_material("principled", [0.9, 0.9, 0.9], {"metallic": 1.0, "roughness": 0.3})
    elif obj in ("mix_metal", "mix_black"):   # Mix(Diffuse, rough Metal); gated: Metal dropped
        lam = r.create_material("lambertian", [0.8, 0.8, 0.8], {})
        other = (r.create_material("metal", [0.9, 0.9, 0.9], {"roughness": 0.3}) if obj == "mix_metal"
                 else r.create_material("lambertian", [0.0, 0.0, 0.0], {}))
        m = r.create_mix_material(lam, other, 0.5)
    else:                              # "black": the gated metal absorbs
        m = r.create_material("lambertian", [0.0, 0.0, 0.0], {})
    r.add_sphere([0.0, 0.0, 0.0], 0.6, m)
    fm = r.create_material("lambertian", [0.85, 0.85, 0.85], {})
    r.add_triangle([-3.0, -1.1, -3.0], [4.0, -1.1, -3.0], [4.0, -1.1, 3.0], fm)
    r.add_triangle([-3.0, -1.1, -3.0], [4.0, -1.1, 3.0], [-3.0, -1.1, 3.0], fm)
    light = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 40.0})
    r.add_triangle([-1.0, 2.2, -1.0], [1.0, 2.2, -1.0], [1.0, 2.2, 1.0], light)
    r.add_triangle([-1.0, 2.2, -1.0], [1.0, 2.2, 1.0], [-1.0, 2.2, 1.0], light)
    r.setup_camera(look_from=[0.0, 0.6, 4.2], look_at=[0.0, -0.6, 0.0],
                   vup=[0, 1, 0], vfov=42, aspect_ratio=CW / CH,
                   aperture=0.0, focus_dist=4.0, width=CW, height=CH)
    r.set_use_reflective_caustics(reflective)
    r.set_use_refractive_caustics(refractive)
    r.set_use_gpu(use_gpu)
    img = np.asarray(r.render(256, 8, None, False), dtype=np.float64)
    return img @ LUM


def _floor_rois(lum):
    """Floor under the sphere (the #1198 caustic ROI) and the floor band beside it."""
    return float(lum[66:76, 56:84].mean()), float(lum[80:100, 10:130].mean())


@pytest.mark.parametrize("use_gpu", BACKENDS)
@pytest.mark.parametrize("obj,ref,toggle", [
    ("rough_glass", "rough_glass_black", "refractive"),
    ("rough_metal", "black", "reflective"),
    ("mix_metal", "mix_black", "reflective"),
])
def test_rough_caustic_closure_dropped_after_diffuse(use_gpu, obj, ref, toggle):
    """Toggle off: the floor sees the object as Cycles' gated closure set does, i.e. like
    the reference object that lacks those closures (rendered with the toggles on)."""
    kw = {toggle: False}
    off = _floor_rois(_over_floor(use_gpu, obj, **kw))
    exp = _floor_rois(_over_floor(use_gpu, ref))
    on = _floor_rois(_over_floor(use_gpu, obj))
    for o, e, n in zip(off, exp, on):
        assert abs(o - e) <= 0.05 * e + 1e-3, (obj, off, exp, on)
    assert any(abs(n - e) > 0.1 * e + 2e-3 for n, e in zip(on, exp)), (obj, off, exp, on)
