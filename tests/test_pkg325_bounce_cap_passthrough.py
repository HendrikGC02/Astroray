"""pkg325: dielectric bounce-cap passthrough (``dielectric_bounce_cap: terminate | passthrough``).

Scene: benchmarks/showcase/spectral/pkg325 (three glass panes + a solid tumbler + diffuse props, white world). A camera
ray through all three panes crosses 6 glass interfaces; under ``terminate`` (Cycles semantics, the
default) a path-depth cap below 7 leaves that region dark. Dead = ROI luminance < 0.25 of the uncapped
white-world reference (1.0), per pixel. ROIs are rectangles whose every pixel crosses exactly 2 / 4 / 6
interfaces (``test_roi_interface_counts``).

The GPU legs need the CUDA build (hold the GPU lock); ``test_terminate_matches_the_pre_change_build``
needs ASTRORAY_PKG325_BASELINE_DIR (a directory with an untouched main build's astroray .pyd).
"""
import os
import subprocess
import sys
import textwrap
import types
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from benchmarks.showcase.spectral.pkg325 import scene_geometry as G  # noqa: E402

W, H = 320, 240
DEAD_BELOW = 0.25


def _roi_stats(img, name):
    x0, y0, x1, y1 = G.rois(W, H)[name]
    lum = img[y0:y1, x0:x1].mean(-1)
    return float((lum < DEAD_BELOW).mean()), float(lum.mean())


def _renderer(backend):
    import runtime_setup
    runtime_setup.configure_test_imports()
    import astroray
    r = astroray.Renderer()
    if backend == "gpu":
        try:
            r.set_use_gpu(True)
        except Exception as e:  # noqa: BLE001 - CPU-only build
            pytest.skip(f"GPU unavailable: {e}")
        if not getattr(r, "gpu_available", False):
            pytest.skip("gpu_available is False")
    return r


def _render(backend, cap, spp=32, seed=325, mode=None, transparent=None):
    from benchmarks.showcase.spectral.pkg325 import engine_scene as E
    r = _renderer(backend)
    E.build(r, W, H)
    if mode is not None:
        r.set_dielectric_bounce_cap(mode)
    # the addon passes the same cap for total / diffuse / glossy / transmission / transparent
    return E.render(r, backend, spp, cap, seed=seed, diffuse_bounces=cap, glossy_bounces=cap,
                    transmission_bounces=cap, volume_bounces=-1,
                    transparent_bounces=cap if transparent is None else transparent)


# --------------------------------------------------------------------------- #
# Scene hygiene (the fails-before test: pkg324's sp07 tumbler had coincident faces, #1160)
# --------------------------------------------------------------------------- #

def test_scene_hygiene():
    h = G.hygiene(G.scene_meshes())
    assert all(v > 0 for v in h["signed_volume"].values()), h["signed_volume"]
    assert h["coincident_pairs"] == []
    assert h["min_gap"] >= G.MIN_GAP - 1e-9


def test_pkg324_sp07_profile_is_the_negative_control():
    """The same hygiene check must flag the pkg324 tumbler: wound inward (signed volume -0.380, as Blender
    left it), base disk coplanar with the plinth top, self-overlapping rim ring."""
    meshes = G.legacy_pkg324_meshes()
    h = G.hygiene(meshes)
    assert h["signed_volume"]["LegacyTumbler"] < 0
    assert len(h["coincident_pairs"]) > 0
    assert h["min_gap"] < G.MIN_GAP


def test_roi_interface_counts():
    meshes = G.scene_meshes()
    for name, expect in (("stack1", 2), ("stack2", 4), ("stack3", 6)):
        x0, y0, x1, y1 = G.rois(W, H)[name]
        xs, ys = np.meshgrid(np.arange(x0, x1), np.arange(y0, y1))
        o, d = G.camera_rays(W, H, xs.ravel(), ys.ravel())
        assert set(G.count_crossings(o, d, meshes).tolist()) == {expect}, name


# --------------------------------------------------------------------------- #
# terminate: the dead region exists at low caps and is gone at 8 / 12 / 64
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("backend", ["cpu", "gpu"])
def test_terminate_has_a_dead_region_at_low_caps(backend):
    for cap in (1, 2, 4):
        dead, _ = _roi_stats(_render(backend, cap), "stack3")
        assert dead > 0.95, (backend, cap, dead)
    for cap in (8, 12, 64):
        dead, mean = _roi_stats(_render(backend, cap), "stack3")
        assert dead < 0.005 and mean > 0.85, (backend, cap, dead, mean)


# --------------------------------------------------------------------------- #
# the option: default terminate, explicit terminate is a no-op, invalid mode rejected
# --------------------------------------------------------------------------- #

def test_default_is_terminate_and_invalid_mode_is_rejected():
    import runtime_setup
    runtime_setup.configure_test_imports()
    import astroray
    r = astroray.Renderer()
    assert r.get_dielectric_bounce_cap() == "terminate"
    r.set_dielectric_bounce_cap("passthrough")
    assert r.get_dielectric_bounce_cap() == "passthrough"
    r.set_dielectric_bounce_cap("terminate")
    assert r.get_dielectric_bounce_cap() == "terminate"
    with pytest.raises(ValueError):
        r.set_dielectric_bounce_cap("refract")


@pytest.mark.parametrize("backend", ["cpu", "gpu"])
def test_explicit_terminate_is_identical_to_default(backend):
    for cap in (4, 12):
        a = _render(backend, cap, spp=8)
        b = _render(backend, cap, spp=8, mode="terminate")
        assert np.abs(a - b).max() <= 1e-6, (backend, cap)


_BASELINE_SNIPPET = textwrap.dedent("""
    import sys, numpy as np
    sys.path.insert(0, {root!r}); sys.path.insert(0, {tests!r})
    import runtime_setup; runtime_setup.configure_test_imports()
    import astroray
    from benchmarks.showcase.spectral.pkg325 import engine_scene as E
    backend, cap, spp, out = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
    r = astroray.Renderer()
    if backend == "gpu":
        r.set_use_gpu(True)
    E.build(r, {w}, {h})
    img = E.render(r, backend, spp, cap, diffuse_bounces=cap, glossy_bounces=cap, transmission_bounces=cap,
                   volume_bounces=-1, transparent_bounces=cap)
    np.save(out, img)
    print(astroray.__file__)
""")


@pytest.mark.parametrize("backend", ["cpu", "gpu"])
def test_terminate_matches_the_pre_change_build(backend, tmp_path):
    """Attribute 'terminate is byte-identical to before' against an untouched build of main: set
    ASTRORAY_PKG325_BASELINE_DIR to a directory holding that build's astroray .pyd (the pre-change
    pyd has no set_dielectric_bounce_cap, so the snippet never calls it)."""
    base = os.environ.get("ASTRORAY_PKG325_BASELINE_DIR")
    if not base:
        pytest.skip("ASTRORAY_PKG325_BASELINE_DIR not set (pre-change build to compare against)")
    cap = 6
    new = _render(backend, cap, spp=8)
    out = tmp_path / "base.npy"
    code = _BASELINE_SNIPPET.format(root=str(ROOT), tests=str(ROOT / "tests"), w=W, h=H)
    env = dict(os.environ, ASTRORAY_BUILD_DIR=base)
    p = subprocess.run([sys.executable, "-c", code, backend, str(cap), "8", str(out)],
                       env=env, capture_output=True, text=True, timeout=600)
    assert p.returncode == 0, p.stderr[-2000:]
    assert os.path.normcase(os.path.abspath(base)) in os.path.normcase(p.stdout), p.stdout  # baseline pyd loaded
    assert np.abs(new - np.load(out)).max() <= 1e-6


# --------------------------------------------------------------------------- #
# passthrough: no dead region at caps 4 / 8 / 12; CPU and GPU agree
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("backend", ["cpu", "gpu"])
def test_passthrough_has_no_dead_region(backend):
    for cap in (4, 8, 12):
        img = _render(backend, cap, mode="passthrough")
        for roi in ("stack1", "stack2", "stack3"):
            dead, mean = _roi_stats(img, roi)
            assert dead < 0.005, (backend, cap, roi, dead)
            assert mean > 0.85, (backend, cap, roi, mean)   # brightness kept: the 1/eta^2 weight is not dropped
    # and it is the option that removed it: terminate at cap 4 is dead on the 6-interface ROI
    assert _roi_stats(_render(backend, 4), "stack3")[0] > 0.95


def test_passthrough_is_bounded_by_the_transparent_limit():
    """Passes count as transparent bounces (#1125 machinery): at cap 4 the 6-interface ROI needs 3
    passes, so a transparent limit of 1 leaves it dead."""
    img = _render("cpu", 4, spp=16, mode="passthrough", transparent=1)
    assert _roi_stats(img, "stack3")[0] > 0.95


def test_passthrough_cpu_vs_gpu_in_mc_band():
    seeds = (11, 12, 13, 14, 15)
    for cap in (4, 8, 12):
        means = {b: {roi: [] for roi in ("stack1", "stack2", "stack3")} for b in ("cpu", "gpu")}
        for b in ("cpu", "gpu"):
            for s in seeds:
                img = _render(b, cap, spp=16, seed=s, mode="passthrough")
                for roi in means[b]:
                    means[b][roi].append(_roi_stats(img, roi)[1])
        for roi in ("stack1", "stack2", "stack3"):
            c, g = np.array(means["cpu"][roi]), np.array(means["gpu"][roi])
            se = np.sqrt(c.var(ddof=1) / len(seeds) + g.var(ddof=1) / len(seeds))
            assert abs(c.mean() - g.mean()) <= 4 * se + 0.01, (cap, roi, c.mean(), g.mean(), se)


# --------------------------------------------------------------------------- #
# addon wiring (stub bpy, same pattern as test_blender_light_sampler_wiring.py)
# --------------------------------------------------------------------------- #

def _wiring_renderer(calls):
    class MockRenderer:
        gpu_available = False
        def clear(self): pass
        def set_adaptive_sampling(self, v): pass
        def set_clamp_direct(self, v): pass
        def set_clamp_indirect(self, v): pass
        def set_filter_glossy(self, v): pass
        def set_use_reflective_caustics(self, v): pass
        def set_use_refractive_caustics(self, v): pass
        def set_light_sampler(self, mode): pass
        def set_film_exposure(self, v): pass
        def set_use_transparent_film(self, v): pass
        def set_transparent_glass(self, v): pass
        def set_seed(self, v): pass
        def set_pixel_filter(self, t, w): pass
        def set_wavelength_range(self, lo, hi): pass
        def set_output_mode(self, m): pass
        def set_integrator(self, name): pass
        def render(self, *a, **kw): return None
        def set_dielectric_bounce_cap(self, mode): calls.append(mode)
    return MockRenderer


def test_addon_final_render_forwards_the_setting(monkeypatch):
    from test_blender_light_sampler_wiring import _load_blender_addon, _make_settings
    calls = []
    R = _wiring_renderer(calls)
    addon = _load_blender_addon(monkeypatch, R)
    engine = addon.CustomRaytracerRenderEngine()
    engine.setup_camera = lambda *a: None
    engine.convert_materials = lambda *a: {}
    engine.convert_objects = lambda *a: None
    engine.convert_lights = lambda *a: None
    engine.setup_world = lambda *a: None
    for value in ("passthrough", "terminate"):
        settings = _make_settings(dielectric_bounce_cap=value)
        scene = types.SimpleNamespace(custom_raytracer=settings, cycles=None, render=None, camera=None)
        engine.convert_scene(types.SimpleNamespace(scene=scene, object_instances=[]), R(), 16, 16)
    assert calls == ["passthrough", "terminate"]


def test_addon_viewport_forwards_the_setting(monkeypatch):
    from test_blender_light_sampler_wiring import _load_blender_addon, _make_settings
    calls = []
    R = _wiring_renderer(calls)
    addon = _load_blender_addon(monkeypatch, R)
    engine = addon.CustomRaytracerRenderEngine()
    settings = _make_settings(dielectric_bounce_cap="passthrough")
    scene = types.SimpleNamespace(custom_raytracer=settings)
    depsgraph = types.SimpleNamespace(scene=scene, view_layer=types.SimpleNamespace(name="ViewLayer"),
                                      object_instances=[])
    context = types.SimpleNamespace(region=types.SimpleNamespace(width=16, height=16))
    engine._setup_viewport_camera = lambda *a: None
    engine.convert_materials = lambda *a: {}
    engine.convert_objects = lambda *a: None
    engine.convert_lights = lambda *a: None
    engine.setup_world = lambda *a: None
    engine._update_viewport_texture = lambda *a: None
    engine.view_update(context, depsgraph)
    assert calls == ["passthrough"]


def test_setting_is_an_astroray_only_row():
    import importlib.util
    spec = importlib.util.spec_from_file_location("pkg325_settings_map", ROOT / "blender_addon" / "settings_map.py")
    sm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sm)
    rows = [e for e in sm.MAPPING if e.native_prop == "dielectric_bounce_cap"]
    assert len(rows) == 1 and rows[0].status == "astroray-only" and rows[0].cycles_path == ""
