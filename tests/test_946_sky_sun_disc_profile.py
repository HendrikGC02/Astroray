"""#946 -- Nishita sky sun disc: Cycles' bottom->top blend + limb darkening.

Cycles (kernel/svm/sky.h sky_radiance_nishita, Apache-2.0) draws the sun disc as
    L = mix(pixel_bottom, pixel_top, y) * limb,
    y = (elevation(dir) - sun_elevation) / angular_diameter + 0.5,
    limb = 1 - 0.6 (1 - sqrt(1 - (angle_to_sun / half_angular)^2)).
At a 4 deg sun the lower limb is much redder/dimmer than the upper one; the old
uniform disc made the corpus v2_sky_sun disc/glow ROIs read 1.16-1.58x Cycles.
Corpus numbers (CPU seed 278, 64 spp): sun_disc 1.16/1.28/1.58/1.24 -> 1.00/1.00/1.00/1.00,
sun_glow 0.93/0.90/0.86/0.91 -> 1.00 (tests/test_corpus_v2_parity.py).
"""
import importlib.util
import math
import shutil
import sys
import tempfile
import types
from pathlib import Path

import numpy as np
import pytest

import astroray

REPO_ROOT = Path(__file__).resolve().parents[1]
E4 = math.radians(4.0)
SUN_SIZE = math.radians(4.0)
LUM = np.array([0.2126, 0.7152, 0.0722])
K = 1000.0  # disc radiance scale (arbitrary, relative RGB below has lum(mean) = 1)

# Relative disc colours (pixel_bottom, pixel_top)/lum(mean): a red lower limb, a
# paler upper limb. Mean normalised to unit luminance (the addon's convention).
_B, _T = np.array([1.4, 0.35, 0.02]), np.array([1.0, 1.0, 0.5])
_NORM = float(((_B + _T) / 2) @ LUM)
BOTTOM, TOP = _B / _NORM, _T / _NORM


def _model_image(w, h, vfov_deg, toward):
    """Cycles' disc profile evaluated per pixel (relative RGB * K), and the angle
    fraction q = angle / half_angular, for a camera at the origin looking at the sun."""
    f = np.array(toward, dtype=np.float64)
    f /= np.linalg.norm(f)
    right = np.cross(f, [0.0, 0.0, 1.0])
    right /= np.linalg.norm(right)
    up = np.cross(right, f)
    t = math.tan(math.radians(vfov_deg) / 2)
    j, i = np.meshgrid(np.arange(w), np.arange(h))
    u = ((j + 0.5) / w * 2 - 1) * t * (w / h)
    v = (1 - (i + 0.5) / h * 2) * t
    d = f + right * u[..., None] + up * v[..., None]
    d /= np.linalg.norm(d, axis=-1, keepdims=True)
    half = SUN_SIZE / 2
    angle = np.arccos(np.clip(d @ f, -1, 1))
    q = angle / half
    y = (np.arcsin(d[..., 2]) - E4) / SUN_SIZE + 0.5
    limb = 1 - 0.6 * (1 - np.sqrt(np.clip(1 - q * q, 0, 1)))
    rgb = (BOTTOM * (1 - y[..., None]) + TOP * y[..., None]) * (limb[..., None] / 0.8) * K
    return rgb, q


def _render(gpu, nee=True):
    import base_helpers as bh
    r = bh.create_renderer()
    r.set_integrator("path_tracer")
    if not nee:
        r.set_integrator_param("enable_nee", 0)
    if gpu:
        try:
            r.set_use_gpu(True)
        except Exception as e:  # noqa: BLE001 - CPU-only build
            pytest.skip("GPU unavailable: %s" % e)
        if not getattr(r, "gpu_available", False):
            pytest.skip("gpu_available is False")
    elif hasattr(r, "set_use_gpu"):
        r.set_use_gpu(False)
    r.set_seed(946)
    r.set_background_color([0.0, 0.0, 0.0])
    grey = r.create_material("lambertian", [0.5, 0.5, 0.5], {})
    r.add_sphere([0.0, 0.0, -1000.0], 1.0, grey)  # out of view; non-empty BVH
    toward = (0.0, math.cos(E4), math.sin(E4))
    omega = 2.0 * math.pi * (1.0 - math.cos(0.5 * SUN_SIZE))
    mean = (BOTTOM + TOP) / 2
    r.add_sun_light_dedicated([-toward[0], -toward[1], -toward[2]], SUN_SIZE,
                              {'mode': 'rgb', 'color': mean.tolist()}, K * omega, 0, 0,
                              camera_visible=True,
                              disc_bottom=BOTTOM.tolist(), disc_top=TOP.tolist())
    w = h = 48
    vfov = 6.0
    bh.setup_camera(r, look_from=[0, 0, 0], look_at=list(toward), vup=[0, 0, 1],
                    vfov=vfov, width=w, height=h)
    img = np.asarray(bh.render_image(r, samples=16, max_depth=3, apply_gamma=False),
                     dtype=np.float64)
    return img, *_model_image(w, h, vfov, toward)


def _check_profile(gpu):
    img, model, q = _render(gpu)
    inner = q < 0.8  # exclude the antialiased rim
    ratio = img[inner] / model[inner]
    # Per-channel level (RGB -> spectral -> RGB roundtrip of saturated colours: 15 %,
    # the tolerance test_903 uses) and flatness: a uniform disc would fail the top/bottom checks below
    # (model upper/lower-half luminance ratio ~1.2, B/R ratio >2x).
    for c in range(3):
        assert ratio[:, c].mean() == pytest.approx(1.0, rel=0.15), (c, ratio[:, c].mean())
        assert ratio[:, c].std() / ratio[:, c].mean() < 0.12, (c, ratio[:, c].std())
    lum = img @ LUM
    top = lum[:24][q[:24] < 0.8].mean()
    bottom = lum[24:][q[24:] < 0.8].mean()
    mtop = (model @ LUM)[:24][q[:24] < 0.8].mean()
    mbottom = (model @ LUM)[24:][q[24:] < 0.8].mean()
    assert top > 1.1 * bottom, (top, bottom)  # brighter upper limb (row 0 = top)
    assert top / bottom == pytest.approx(mtop / mbottom, rel=0.10)
    # Lower limb redder: B/R rises toward the top.
    br = lambda a: a[..., 2].mean() / a[..., 0].mean()  # noqa: E731
    assert br(img[:24][q[:24] < 0.8]) > 1.5 * br(img[24:][q[24:] < 0.8])


@pytest.mark.cpu
def test_cpu_disc_follows_cycles_profile():
    _check_profile(gpu=False)


@pytest.mark.gpu
@pytest.mark.serial
def test_gpu_disc_follows_cycles_profile():
    _check_profile(gpu=True)


# --------------------------------------------------------------------------- #
# Addon: the sky sun hands the engine the relative bottom/top colours.
# --------------------------------------------------------------------------- #
def _load_addon(monkeypatch):
    bpy = types.ModuleType("bpy")
    bpy_types = types.ModuleType("bpy.types")
    bpy_props = types.ModuleType("bpy.props")

    class _Base:
        pass

    class _Engine:
        def report(self, *_a, **_k): return None

    for n in ("Panel", "Operator", "AddonPreferences", "PropertyGroup"):
        setattr(bpy_types, n, _Base)
    bpy_types.RenderEngine = _Engine
    bpy.types = bpy_types
    for n in ("BoolProperty", "IntProperty", "FloatProperty", "StringProperty",
              "PointerProperty", "FloatVectorProperty", "EnumProperty"):
        setattr(bpy_props, n, lambda **_k: None)
    bpy.props = bpy_props
    bpy.path = types.SimpleNamespace(abspath=lambda p: p)
    sb = types.ModuleType("shader_blending")
    sb.blend_shader_specs = {}
    sb.add_shader_specs = {}
    stub = types.ModuleType("astroray")
    stub.__version__ = "test"
    stub.__features__ = {"cuda": False, "spectral": True}
    stub.__file__ = "/fake/astroray.pyd"
    stub.integrator_registry_names = lambda: ["path_tracer"]
    stub.material_registry_names = lambda: ["lambertian"]
    stub.pass_registry_names = list
    stub.nishita_sky = astroray.nishita_sky
    stub.nishita_sun = astroray.nishita_sun
    for name, mod in (("bpy", bpy), ("bpy.types", bpy_types), ("bpy.props", bpy_props),
                      ("shader_blending", sb), ("mathutils", types.ModuleType("mathutils")),
                      ("astroray", stub)):
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.syspath_prepend(str(REPO_ROOT / "blender_addon"))
    spec = importlib.util.spec_from_file_location(
        "astroray_addon_946_test", REPO_ROOT / "blender_addon" / "__init__.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Recorder:
    def __init__(self, tmpdir):
        self.tmpdir = tmpdir
        self.sun = None

    def set_background_color(self, color): pass
    def set_world_volume(self, *a, **k): pass
    def set_world_max_bounces(self, *a, **k): pass

    def load_environment_map(self, path, *a, **k):
        shutil.copyfile(path, self.tmpdir + "/sky.hdr")
        return True

    def add_sun_light_dedicated(self, direction, size, emission, intensity, *a, **k):
        self.sun = {"emission": emission, "intensity": intensity, "kwargs": dict(k)}


@pytest.mark.cpu
def test_addon_passes_disc_profile(monkeypatch):
    addon = _load_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    engine._warn_shader_fallback = lambda *a, **k: None
    sky = types.SimpleNamespace(
        type='TEX_SKY', sky_type='MULTIPLE_SCATTERING', sun_elevation=E4, sun_rotation=0.0,
        altitude=200.0, air_density=1.0, aerosol_density=1.2, ozone_density=1.0,
        sun_disc=True, sun_size=SUN_SIZE, sun_intensity=1.0)
    world = types.SimpleNamespace(node_tree=types.SimpleNamespace(nodes=[sky]), cycles=None)
    tmp = tempfile.mkdtemp(prefix="astroray_946_")
    try:
        rec = _Recorder(tmp)
        engine.setup_world(types.SimpleNamespace(world=world), rec)
        kw = rec.sun["kwargs"]
        bottom, top = np.array(kw["disc_bottom"]), np.array(kw["disc_top"])
        # Same model values the addon used: lower limb dimmer and redder at 4 deg.
        assert bottom @ LUM < top @ LUM
        assert bottom[2] / bottom[0] < top[2] / top[0]
        # Mean of the relative colours == the lamp's (NEE) emission colour, so the
        # energy delivered by NEE is unchanged by the profile.
        color = np.array(rec.sun["emission"]["color"])
        np.testing.assert_allclose((bottom + top) / 2, color, rtol=1e-5)
        assert ((bottom + top) / 2) @ LUM == pytest.approx(1.0, rel=1e-5)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
