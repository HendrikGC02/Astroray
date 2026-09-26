"""#903 — Sky Texture (Multiple Scattering) sun disc + glow vs Cycles.

Two bugs, both fixed here:
  1. The baked sky glow sat at world azimuth = sun_rotation while Cycles' sun
     (and Astroray's dedicated sun, #814) sits at 90deg - sun_rotation, so at
     rotation 0 the glow was 90deg off the sun: no warm glow, bluer view.
  2. The sky's sun disc is a dedicated DistantLight, and dedicated lamps were
     invisible to camera rays. Cycles draws the disc in the background, so the
     sky sun is now camera-visible (Light::cameraVisible, GPU twin).

Cycles reference (Blender 5.2, MS sky, elev 4deg, sun_size 1.2deg, altitude
200 m, aerosol 1.2): disc centre RGB ~(2.19e5, 1.01e5, 1.70e4); limb-darkened
disc mean ~(1.81e5, 8.4e4, 1.4e4). Evidence: astra_run/batchU/f903/.
"""
import importlib.util
import math
import os
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
SUN_SIZE = math.radians(1.2)
ALT, AIR, AER, OZ = 200.0, 1.0, 1.2, 1.0


def _lum(c):
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _disc_radiance():
    """Uniform-disc radiance the addon hands the sky sun (limb average 0.8)."""
    b, t = astroray.nishita_sun("MULTIPLE_SCATTERING", E4, SUN_SIZE, ALT, AIR, AER, OZ)
    return [0.5 * (b[k] + t[k]) * 0.8 for k in range(3)]


# --------------------------------------------------------------------------- #
# Engine: a camera looking at a camera-visible sun sees the disc.
# --------------------------------------------------------------------------- #
def _sun_scene(camera_visible, gpu, integrator="path_tracer", nee=True):
    import base_helpers as bh
    r = bh.create_renderer()
    r.set_integrator(integrator)
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
    r.set_seed(903)
    r.set_background_color([0.0, 0.0, 0.0])
    grey = r.create_material("lambertian", [0.5, 0.5, 0.5], {})
    r.add_sphere([0.0, 0.0, -1000.0], 1.0, grey)  # out of view; non-empty BVH
    toward = (0.0, math.cos(E4), math.sin(E4))    # sun at +Y, 4deg up
    l_disc = _disc_radiance()
    omega = 2.0 * math.pi * (1.0 - math.cos(0.5 * SUN_SIZE))
    s_lum = _lum(l_disc) * omega
    color = [c * omega / s_lum for c in l_disc]
    r.add_sun_light_dedicated([-toward[0], -toward[1], -toward[2]], SUN_SIZE,
                              {'mode': 'rgb', 'color': color}, s_lum, 0, 0,
                              camera_visible=camera_visible)
    bh.setup_camera(r, look_from=[0, 0, 0], look_at=list(toward), vup=[0, 0, 1],
                    vfov=4.0, width=32, height=32)
    img = bh.render_image(r, samples=16, max_depth=4, apply_gamma=False)
    return np.asarray(img, dtype=np.float64), l_disc


def _check_disc(gpu, integrator="path_tracer", nee=True):
    img, l_disc = _sun_scene(True, gpu, integrator, nee)
    centre = img[14:18, 14:18].reshape(-1, 3).mean(axis=0)
    # Radiance order of magnitude + per-channel within 15% (RGB->spectral->RGB).
    for k in range(3):
        assert centre[k] == pytest.approx(l_disc[k], rel=0.15), (k, centre, l_disc)
    # Warm low sun: R > G > B, strongly red.
    assert centre[0] > centre[1] > centre[2], centre
    assert centre[0] / centre[2] > 5.0, centre
    # Disc spans ~1.2/4 of the frame: corners are black background.
    assert float(img[0, 0].max()) == 0.0 and float(img[-1, -1].max()) == 0.0

    hidden, _ = _sun_scene(False, gpu, integrator, nee)
    assert float(hidden[14:18, 14:18].max()) == 0.0, "default lamps stay camera-invisible"


@pytest.mark.cpu
@pytest.mark.parametrize("integrator,nee", [
    ("path_tracer", True),
    ("multiwavelength_path_tracer", True),
    ("multiwavelength_path_tracer", False),   # camera disc is background, not NEE
])
def test_cpu_camera_sees_sky_sun_disc(integrator, nee):
    _check_disc(gpu=False, integrator=integrator, nee=nee)


@pytest.mark.gpu
@pytest.mark.serial
def test_gpu_camera_sees_sky_sun_disc():
    _check_disc(gpu=True)


# --------------------------------------------------------------------------- #
# Addon: the baked glow and the dedicated sun share Cycles' azimuth.
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
    stub.nishita_sky = astroray.nishita_sky   # real engine sky model
    stub.nishita_sun = astroray.nishita_sun
    for name, mod in (("bpy", bpy), ("bpy.types", bpy_types), ("bpy.props", bpy_props),
                      ("shader_blending", sb), ("mathutils", types.ModuleType("mathutils")),
                      ("astroray", stub)):
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.syspath_prepend(str(REPO_ROOT / "blender_addon"))
    spec = importlib.util.spec_from_file_location(
        "astroray_addon_903_test", REPO_ROOT / "blender_addon" / "__init__.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Recorder:
    def __init__(self, tmpdir):
        self.tmpdir = tmpdir
        self.hdr = None
        self.sun = None

    def set_background_color(self, color): pass
    def set_world_volume(self, *a, **k): pass
    def set_world_max_bounces(self, *a, **k): pass

    def load_environment_map(self, path, *a, **k):
        self.hdr = os.path.join(self.tmpdir, "sky.hdr")
        shutil.copyfile(path, self.hdr)   # addon deletes its temp file after
        return True

    def add_sun_light_dedicated(self, direction, size, emission, intensity, *a, **k):
        self.sun = {"direction": list(direction), "kwargs": dict(k)}


@pytest.mark.cpu
@pytest.mark.parametrize("rot_deg", [0.0, 60.0])
def test_addon_sky_glow_coincides_with_sun(monkeypatch, rot_deg):
    addon = _load_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    engine._warn_shader_fallback = lambda *a, **k: None
    sky = types.SimpleNamespace(
        type='TEX_SKY', sky_type='MULTIPLE_SCATTERING', sun_elevation=E4,
        sun_rotation=math.radians(rot_deg), altitude=ALT, air_density=AIR,
        aerosol_density=AER, ozone_density=OZ, sun_disc=True, sun_size=SUN_SIZE,
        sun_intensity=1.0)
    world = types.SimpleNamespace(node_tree=types.SimpleNamespace(nodes=[sky]), cycles=None)
    tmp = tempfile.mkdtemp(prefix="astroray_903_")
    try:
        rec = _Recorder(tmp)
        engine.setup_world(types.SimpleNamespace(world=world), rec)
        assert rec.hdr is not None and rec.sun is not None
        assert rec.sun["kwargs"].get("camera_visible") is True
        # Dedicated sun at Cycles' azimuth 90 - rotation (#814).
        toward = [-c for c in rec.sun["direction"]]
        az = math.degrees(math.atan2(toward[1], toward[0]))
        assert abs(((az - (90.0 - rot_deg)) + 180.0) % 360.0 - 180.0) < 0.5, az

        import base_helpers as bh

        def env(az_deg, el_deg=2.0):
            """Mean radiance of a small CPU camera view of the loaded sky."""
            a, e = math.radians(az_deg), math.radians(el_deg)
            r = bh.create_renderer()
            if hasattr(r, "set_use_gpu"):
                r.set_use_gpu(False)
            assert r.load_environment_map(rec.hdr, 1.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, True)
            grey = r.create_material("lambertian", [0.5, 0.5, 0.5], {})
            r.add_sphere([0.0, 0.0, -1000.0], 1.0, grey)
            bh.setup_camera(r, look_from=[0, 0, 0], vup=[0, 0, 1], vfov=2.0,
                            look_at=[math.cos(e) * math.cos(a), math.cos(e) * math.sin(a),
                                     math.sin(e)], width=8, height=8)
            img = bh.render_image(r, samples=4, max_depth=2, apply_gamma=False)
            return np.asarray(img, dtype=np.float64).reshape(-1, 3).mean(axis=0)

        sun_az = 90.0 - rot_deg
        near = env(sun_az + 3.0)       # just beside the disc: forward-scatter glow
        side = env(sun_az + 90.0)
        # Cycles (same params): toward-sun sky is warm and far brighter than the
        # 90deg-off sky. Pre-fix the glow sat 90deg off -> near was the blue side.
        assert _lum(near) > 4.0 * _lum(side), (near, side)
        assert near[0] > near[2], ("glow beside a 4deg sun must be warm", near)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
