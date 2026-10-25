"""pkg326 (#1136) - Glass BSDF Thin Film Thickness / Thin Film IOR sockets.

Cycles 5.2 svm/closure.h (CLOSURE_BSDF_MICROFACET_*_GLASS_ID, :779-840) loads the two
sockets into fresnel->thin_film of the same FresnelGeneralizedSchlick the Principled
transmission lobe builds (:362-423). The Glass node lowers to the native 'principled'
material (transmission 1), whose film glass already renders on CPU and GPU (pkg178
Stage 4), so the addon only has to forward the sockets (it used to drop them, #1136).

Layers:
  1. addon mapping + report (stub bpy, no engine);
  2. engine truth (CPU, and GPU when available): a bubble built from the Glass node vs
     the same bubble built from the Principled node (MC band), film vs no film
     (the film must move the render), zero thickness vs plain glass (<= 1e-6).
  3. #1162 smooth glass (Roughness <= 0.03, the delta path): the film shows, matches the
     near-delta rough film (independent code path), CPU == GPU, and the white furnace holds.
"""

from __future__ import annotations

import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()

from test_pkg119c_degradation import (  # noqa: E402
    _Node, _RecordingRenderer, _Socket, _engine, _load_blender_addon)

try:
    import astroray  # noqa: E402
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

IOR = 1.45
THICKNESS = 380.0       # nm: strong first/second-order interference
FILM_IOR = 1.33
ROUGHNESS = 0.12        # > 0.03: the rough (microfacet) film path; smooth glass is layer 3
WIDTH = HEIGHT = 96
SAMPLES = 256
MAX_DEPTH = 8
MC_BAND = 0.01          # independent seeds, 256 spp, 96x96 disc mean per channel: measured ~0.2 %
HUE_BAND = 0.004        # G/R and B/R of the disc mean: measured seed noise ~0.1 %
HUE_SHIFT = 0.005       # film vs plain glass: measured G/R, B/R shift ~1 %


def _glass_node(thickness=THICKNESS, film_ior=FILM_IOR, color=(1.0, 1.0, 1.0), roughness=ROUGHNESS):
    inputs = {
        'Color': _Socket(default=(*color, 1.0)),
        'Roughness': _Socket(default=roughness),
        'IOR': _Socket(default=IOR),
    }
    if thickness is not None:
        inputs['Thin Film Thickness'] = _Socket(default=thickness)
        inputs['Thin Film IOR'] = _Socket(default=film_ior)
    return _Node(ntype="BSDF_GLASS", bl_idname="ShaderNodeBsdfGlass", inputs=inputs,
                 distribution="MULTI_GGX")


def _principled_node(thickness=THICKNESS, film_ior=FILM_IOR, roughness=ROUGHNESS):
    return _Node(ntype="BSDF_PRINCIPLED", bl_idname="ShaderNodeBsdfPrincipled", inputs={
        'Base Color': _Socket(default=(1.0, 1.0, 1.0, 1.0)),
        'Metallic': _Socket(default=0.0),
        'Roughness': _Socket(default=roughness),
        'IOR': _Socket(default=IOR),
        'Alpha': _Socket(default=1.0),
        'Transmission Weight': _Socket(default=1.0),
        'Specular IOR Level': _Socket(default=0.5),
        'Specular Tint': _Socket(default=(1.0, 1.0, 1.0, 1.0)),
        'Thin Film Thickness': _Socket(default=thickness),
        'Thin Film IOR': _Socket(default=film_ior),
    }, distribution="MULTI_GGX", subsurface_method="RANDOM_WALK")


def _convert(monkeypatch, node, native=True):
    addon = _load_blender_addon(monkeypatch)
    engine = _engine(addon)
    engine._use_native_principled_flag = native
    renderer = _RecordingRenderer()
    engine.convert_shader_node(node, renderer, node_tree=None)
    assert len(renderer.created_materials) == 1
    return renderer.created_materials[0], engine


def _report_texts(engine):
    r = engine._degradation_report()
    return [f"{f}: {d}" for f, d in r.approximated] + [f"{f}: {d}" for f, d in r.ignored]


# --------------------------------------------------------------------------- #
# layer 1: addon mapping + report (no engine)
# --------------------------------------------------------------------------- #

def test_glass_thin_film_sockets_reach_the_native_material(monkeypatch):
    (mat_type, _base, params), _ = _convert(monkeypatch, _glass_node())
    assert mat_type == "principled"
    assert params["thin_film_thickness"] == pytest.approx(THICKNESS)
    assert params["thin_film_ior"] == pytest.approx(FILM_IOR)
    assert params["transmission_weight"] == 1.0


def test_glass_thin_film_report_entry_is_gone(monkeypatch):
    _, engine = _convert(monkeypatch, _glass_node())
    assert not [t for t in _report_texts(engine) if "Thin Film" in t], _report_texts(engine)


def test_glass_without_thin_film_sockets_is_unchanged(monkeypatch):
    (_t, _b, params), engine = _convert(monkeypatch, _glass_node(thickness=None))
    assert params["thin_film_thickness"] == 0.0       # below the 0.1 nm film cutoff: film off
    assert not [t for t in _report_texts(engine) if "Thin Film" in t]


def test_legacy_route_still_names_the_drop(monkeypatch):
    # The non-native (Disney) route has no film; it must keep reporting rather than go silent.
    _, engine = _convert(monkeypatch, _glass_node(), native=False)
    assert any("Thin Film Thickness / Thin Film IOR" in t for t in _report_texts(engine))


# --------------------------------------------------------------------------- #
# layer 2: engine truth
# --------------------------------------------------------------------------- #

def _gpu_ok():
    if not AVAILABLE or not astroray.__features__.get("cuda", False):
        return False
    return bool(getattr(astroray.Renderer(), "gpu_available", False))


def _render(base, params, use_gpu, seed):
    """A bubble in front of a dim backdrop with two bright reflected lights: the film shows
    as hue-shifted glints (visible in the saved evidence PNGs)."""
    r = astroray.Renderer()
    r.set_background_color([0.02, 0.02, 0.02])
    r.set_integrator("path_tracer")
    r.set_use_gpu(bool(use_gpu))
    mid = r.create_material("principled", base, params)
    r.add_sphere([0.0, 0.0, 0.0], 1.0, mid)
    r.add_sphere([0.0, 0.0, -8.0], 5.0, r.create_material("light", [1, 1, 1], {"intensity": 0.5}))
    for x in (-1.0, 1.0):
        r.add_sphere([3.5 * x, 2.0, 3.0], 1.0, r.create_material("light", [1, 1, 1], {"intensity": 8.0}))
    r.setup_camera([0, 0, 4], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 4.0, WIDTH, HEIGHT)
    r.set_seed(seed)
    img = np.asarray(r.render(SAMPLES, MAX_DEPTH, None, False), dtype=np.float64)
    assert np.all(np.isfinite(img))
    return img.reshape(HEIGHT, WIDTH, 3)


def _sphere_mean(img):
    """Mean RGB over the central disc (the bubble covers radius ~0.37 of the frame)."""
    yy, xx = np.mgrid[0:HEIGHT, 0:WIDTH]
    m = (xx - WIDTH / 2 + 0.5) ** 2 + (yy - HEIGHT / 2 + 0.5) ** 2 <= (0.30 * WIDTH) ** 2
    return img[m].mean(axis=0)


def _hue(mean):
    """(G/R, B/R) of a channel mean: the film's interference tint, independent of exposure."""
    return np.array([mean[1] / mean[0], mean[2] / mean[0]])


def _native_args(monkeypatch, node):
    addon = _load_blender_addon(monkeypatch)
    engine = _engine(addon)
    engine._use_native_principled_flag = True
    if node.type == "BSDF_PRINCIPLED":
        spec = engine._principled_shader_spec(node, renderer=None)
        renderer = _RecordingRenderer()
        engine._create_material_from_shader_spec(spec, renderer)
    else:
        renderer = _RecordingRenderer()
        engine.convert_shader_node(node, renderer, node_tree=None)
    _t, base, params = renderer.created_materials[0]
    return base, params


LEGS = [pytest.param(False, id="cpu"),
        pytest.param(True, id="gpu", marks=pytest.mark.skipif(
            not _gpu_ok(), reason="needs the CUDA build + a GPU"))]


@pytest.mark.skipif(not AVAILABLE, reason="astroray not built")
@pytest.mark.parametrize("use_gpu", LEGS)
def test_glass_bubble_matches_principled_bubble(monkeypatch, use_gpu):
    g_base, g_params = _native_args(monkeypatch, _glass_node())
    p_base, p_params = _native_args(monkeypatch, _principled_node())
    glass = _sphere_mean(_render(g_base, g_params, use_gpu, seed=326_01))
    princ = _sphere_mean(_render(p_base, p_params, use_gpu, seed=326_02))
    ratio = glass / princ
    print(f"[pkg326] gpu={use_gpu} glass={glass} principled={princ} ratio={ratio}"
          f" hue glass={_hue(glass)} principled={_hue(princ)}")
    assert np.all(np.abs(ratio - 1.0) < MC_BAND), (glass, princ, ratio)
    assert np.all(np.abs(_hue(glass) / _hue(princ) - 1.0) < HUE_BAND), (glass, princ)


@pytest.mark.skipif(not AVAILABLE, reason="astroray not built")
@pytest.mark.parametrize("use_gpu", LEGS)
def test_glass_film_moves_the_render(monkeypatch, use_gpu):
    """Fails before pkg326: the sockets were dropped, so film == plain glass."""
    f_base, f_params = _native_args(monkeypatch, _glass_node())
    n_base, n_params = _native_args(monkeypatch, _glass_node(thickness=0.0))
    film = _sphere_mean(_render(f_base, f_params, use_gpu, seed=326_03))
    plain = _sphere_mean(_render(n_base, n_params, use_gpu, seed=326_04))
    shift = np.abs(_hue(film) / _hue(plain) - 1.0)
    print(f"[pkg326] gpu={use_gpu} film={film} plain={plain} hue shift={shift}")
    assert shift.max() > HUE_SHIFT, (film, plain, shift)


@pytest.mark.skipif(not AVAILABLE, reason="astroray not built")
@pytest.mark.parametrize("use_gpu", LEGS)
def test_zero_thickness_glass_equals_plain_glass(monkeypatch, use_gpu):
    z_base, z_params = _native_args(monkeypatch, _glass_node(thickness=0.0))
    n_base, n_params = _native_args(monkeypatch, _glass_node(thickness=None))
    n_params = {k: v for k, v in n_params.items() if not k.startswith("thin_film")}  # truly film-free
    zero = _render(z_base, z_params, use_gpu, seed=326_05)
    none = _render(n_base, n_params, use_gpu, seed=326_05)
    diff = float(np.max(np.abs(zero - none)))
    assert diff <= 1e-6, diff


# --------------------------------------------------------------------------- #
# layer 3: #1162 smooth glass. Cycles applies the film on the singular lobe too
# (v5.2.0 bsdf_microfacet.h:795-917); before #1162 the delta path used plain Fresnel.
# --------------------------------------------------------------------------- #

@pytest.mark.skipif(not AVAILABLE, reason="astroray not built")
@pytest.mark.parametrize("use_gpu", LEGS)
def test_smooth_glass_bubble_shows_film(monkeypatch, use_gpu):
    """Failed before #1162 (film == plain glass bit for bit on the delta path)."""
    f_base, f_params = _native_args(monkeypatch, _glass_node(roughness=0.0))
    n_base, n_params = _native_args(monkeypatch, _glass_node(thickness=0.0, roughness=0.0))
    film = _sphere_mean(_render(f_base, f_params, use_gpu, seed=326_06))
    plain = _sphere_mean(_render(n_base, n_params, use_gpu, seed=326_07))
    shift = np.abs(_hue(film) / _hue(plain) - 1.0)
    print(f"[i1162] gpu={use_gpu} film={film} plain={plain} hue shift={shift}")
    assert shift.max() > HUE_SHIFT, (film, plain, shift)


@pytest.mark.skipif(not AVAILABLE, reason="astroray not built")
@pytest.mark.parametrize("use_gpu", LEGS)
def test_smooth_film_glass_continues_the_rough_limit(monkeypatch, use_gpu):
    """The delta film (sampler) must agree with the near-delta rough film (microfacet eval, an
    independent code path; roughness 0.05 sits on the alpha floor). CPU measured: hue ratio
    within 0.07 % after #1162, ~1 % off before (the delta path ignored the film)."""
    s_base, s_params = _native_args(monkeypatch, _glass_node(roughness=0.0))
    r_base, r_params = _native_args(monkeypatch, _glass_node(roughness=0.05))
    smooth = _sphere_mean(_render(s_base, s_params, use_gpu, seed=326_08))
    rough = _sphere_mean(_render(r_base, r_params, use_gpu, seed=326_09))
    print(f"[i1162] gpu={use_gpu} smooth={smooth} rough={rough} hue {_hue(smooth)} vs {_hue(rough)}")
    assert np.all(np.abs(smooth / rough - 1.0) < MC_BAND), (smooth, rough)
    assert np.all(np.abs(_hue(smooth) / _hue(rough) - 1.0) < HUE_BAND), (smooth, rough)


@pytest.mark.skipif(not _gpu_ok(), reason="needs the CUDA build + a GPU")
def test_smooth_film_glass_cpu_gpu_twin(monkeypatch):
    """3-seed means per backend. The smooth sphere's per-seed hue scatter is larger than the
    rough one's (HUE_BAND's 0.1 %): lead probe, seeds 326_10..13, sd (G/R, B/R) CPU (0.0005,
    0.0016), GPU (0.0008, 0.0011); means CPU (1.0103, 1.0064), GPU (1.0109, 1.0072). The mean of
    3 brings the ratio sd to ~0.1 %, so HUE_BAND 0.004 is ~3 sigma."""
    base, params = _native_args(monkeypatch, _glass_node(roughness=0.0))
    cpu = np.mean([_sphere_mean(_render(base, params, False, seed=s)) for s in (326_10, 326_11, 326_12)],
                  axis=0)
    gpu = np.mean([_sphere_mean(_render(base, params, True, seed=s)) for s in (326_13, 326_14, 326_15)],
                  axis=0)
    print(f"[i1162] cpu={cpu} gpu={gpu} hue {_hue(cpu)} vs {_hue(gpu)}")
    assert np.all(np.abs(gpu / cpu - 1.0) < MC_BAND), (cpu, gpu)
    assert np.all(np.abs(_hue(gpu) / _hue(cpu) - 1.0) < HUE_BAND), (cpu, gpu)


def _smooth_film_furnace(thickness, ior, film_ior, use_gpu):
    """Smooth film sphere in a uniform white field (linear): R + T = 1 per channel / per
    wavelength, so the sphere is invisible. A regression guard on the f/pdf weights."""
    r = astroray.Renderer()
    r.set_background_color([1.0, 1.0, 1.0])
    r.set_integrator("path_tracer")
    r.set_use_gpu(bool(use_gpu))
    mid = r.create_material("principled", [1.0, 1.0, 1.0], {
        "roughness": 0.0, "ior": ior, "transmission_weight": 1.0,
        "thin_film_thickness": thickness, "thin_film_ior": film_ior})
    r.add_sphere([0.0, 0.0, 0.0], 1.0, mid)
    r.setup_camera([0, 0, 4], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 4.0, 80, 80)
    r.set_seed(7)
    img = np.asarray(r.render(64, 32, None, False), dtype=np.float64).reshape(80, 80, 3)
    return img[20:60, 20:60].reshape(-1, 3).mean(axis=0)


@pytest.mark.skipif(not AVAILABLE, reason="astroray not built")
@pytest.mark.parametrize("use_gpu", LEGS)
@pytest.mark.parametrize("thickness,ior,film_ior", [(380.0, 1.45, 1.33), (250.0, 1.5, 2.0),
                                                    (600.0, 2.0, 1.33)])
def test_smooth_film_glass_furnace(use_gpu, thickness, ior, film_ior):
    # CPU measured (64 spp): within 0.3 % of 1 on every channel.
    m = _smooth_film_furnace(thickness, ior, film_ior, use_gpu)
    assert np.all(np.abs(m - 1.0) < 0.02), m


def test_smooth_glass_film_is_not_reported(monkeypatch):
    # #1162 removed the per-render "Thin Film is not rendered on a smooth Glass BSDF" report.
    for roughness in (0.0, ROUGHNESS):
        _, engine = _convert(monkeypatch, _glass_node(roughness=roughness))
        assert not [t for t in _report_texts(engine) if "Thin Film" in t], _report_texts(engine)
