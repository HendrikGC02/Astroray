"""#1200 - glass Fresnel tints: Glass BSDF Color with a thin film, and tinted Principled glass.

Cycles v5.2.0 fills the glass lobe's FresnelGeneralizedSchlick two ways:
  * Glass BSDF (svm/closure.h:816-822): f0 = F0(ior) untinted, reflection_tint =
    transmission_tint = Color, so R = F x Color and T = (1 - F) x Color, F the thin-film
    (or plain dielectric) Fresnel (the film's F0 rescale, bsdf_microfacet.h:290-295, is 1).
  * Principled (generalized_schlick_setup, bsdf_microfacet.h:111-124): f0 = F0 x specular_tint,
    reflection_tint 1: R = mix(f0, 1, s), s = saturate((F - F0) / (1 - F0)) (:316-321),
    T = (1 - R) x sqrt(base_color) (:327-328).
Before #1200 a film Glass took the Principled fill (Color entered the F0 rescale: a tinted rim
went white, T low by the same amount) and a film-free tinted Principled glass took the Glass
fill (rim tinted instead of white).

Single interface: a smooth (or rough) glass quad seen at angle theta under a white background.
  reflection probe (black catcher below the quad): pixel = R;
  furnace probe (no catcher): pixel = R + T x eta^2 (the refracted ray stays inside the glass, so
  the engine's eta^2 radiance factor, 1/1.45^2, is not undone by an exit).
Glass legs are ratios against the same scene with Color = 1 and the same seed: a grey Color does
not change any sampling decision, so Cycles' ratio is Color to float precision on the smooth
lobe (the rough lobe adds the MULTI_GGX darkening ratio, ~0.5 % at roughness 0.12).
"""

from __future__ import annotations

import math

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
FILM_IOR = 2.0        # high-index film: R_film ~ 0.2 near the 70 nm quarter-wave peak
THICKNESS = 70.0      # nm
COLOR = 0.5
N = 16
SPP = 1024
SEED = 1200


def _gpu_ok():
    if not AVAILABLE or not astroray.__features__.get("cuda", False):
        return False
    return bool(getattr(astroray.Renderer(), "gpu_available", False))


LEGS = [pytest.param(False, id="cpu"),
        pytest.param(True, id="gpu", marks=pytest.mark.skipif(
            not _gpu_ok(), reason="needs the CUDA build + a GPU"))]


def _glass_node(color, roughness=0.0, thickness=THICKNESS):
    return _Node(ntype="BSDF_GLASS", bl_idname="ShaderNodeBsdfGlass", inputs={
        'Color': _Socket(default=(color, color, color, 1.0)),
        'Roughness': _Socket(default=roughness),
        'IOR': _Socket(default=IOR),
        'Thin Film Thickness': _Socket(default=thickness),
        'Thin Film IOR': _Socket(default=FILM_IOR),
    }, distribution="MULTI_GGX")


def _addon_args(monkeypatch, node):
    addon = _load_blender_addon(monkeypatch)
    engine = _engine(addon)
    engine._use_native_principled_flag = True
    renderer = _RecordingRenderer()
    engine.convert_shader_node(node, renderer, node_tree=None)
    mat_type, base, params = renderer.created_materials[0]
    assert mat_type == "principled"
    return base, params


# --------------------------------------------------------------------------- #
# addon mapping (no engine)
# --------------------------------------------------------------------------- #

def test_glass_node_selects_the_glass_fresnel_fill(monkeypatch):
    base, params = _addon_args(monkeypatch, _glass_node(COLOR))
    assert params["glass_bsdf"] == 1.0
    assert params["specular_tint"] == pytest.approx([COLOR] * 3)
    assert list(base) == pytest.approx([COLOR ** 2] * 3)


# --------------------------------------------------------------------------- #
# engine: single-interface probes
# --------------------------------------------------------------------------- #

def _render(base, params, theta_deg, use_gpu, catcher, seed=SEED):
    r = astroray.Renderer()
    r.set_use_gpu(bool(use_gpu))
    r.set_integrator("path_tracer")
    r.set_adaptive_sampling(False)
    r.set_background_color([1.0, 1.0, 1.0])
    glass = r.create_material("principled", list(base), dict(params))
    L = 50.0
    r.add_triangle([-L, -L, 0.0], [L, -L, 0.0], [L, L, 0.0], glass)   # normal +z
    r.add_triangle([-L, -L, 0.0], [L, L, 0.0], [-L, L, 0.0], glass)
    if catcher:  # swallows the refracted rays: the pixel is R alone
        black = r.create_material("lambertian", [0.0, 0.0, 0.0], {})
        r.add_triangle([-L, -L, -1.0], [L, -L, -1.0], [L, L, -1.0], black)
        r.add_triangle([-L, -L, -1.0], [L, L, -1.0], [-L, L, -1.0], black)
    th = math.radians(theta_deg)
    eye = [0.0, -4.0 * math.sin(th), 4.0 * math.cos(th)]
    up = [0.0, 1.0, 0.0] if theta_deg < 45.0 else [0.0, 0.0, 1.0]
    r.setup_camera(eye, [0.0, 0.0, 0.0], up, 2.0, 1.0, 0.0, 4.0, N, N)
    r.set_seed(seed)
    img = np.asarray(r.render(SPP, 4, None, False), dtype=np.float64).reshape(N, N, 3)
    assert np.all(np.isfinite(img))
    return img.reshape(-1, 3).mean(axis=0)


def _fresnel(cosi, eta):
    """Exact unpolarised dielectric Fresnel, eta = n_t / n_i (Cycles fresnel_dielectric_cos)."""
    sint2 = (1.0 - cosi * cosi) / (eta * eta)
    cost = math.sqrt(1.0 - sint2)
    rs = (cosi - eta * cost) / (cosi + eta * cost)
    rp = (eta * cosi - cost) / (eta * cosi + cost)
    return 0.5 * (rs * rs + rp * rp)


def _principled_R(theta_deg, tint):
    """Cycles generalized_schlick_fresnel, exponent < 0 branch, f0 = F0 x tint."""
    F = _fresnel(math.cos(math.radians(theta_deg)), IOR)
    F0 = ((IOR - 1.0) / (IOR + 1.0)) ** 2
    s = min(max((F - F0) / (1.0 - F0), 0.0), 1.0)
    f0 = min(F0 * tint, 1.0)
    return f0 + (1.0 - f0) * s


@pytest.mark.skipif(not AVAILABLE, reason="astroray not built")
@pytest.mark.parametrize("use_gpu", LEGS)
@pytest.mark.parametrize("theta", [0.0, 60.0])
@pytest.mark.parametrize("catcher", [True, False], ids=["R", "furnace"])
def test_smooth_film_glass_scales_with_color(monkeypatch, use_gpu, theta, catcher):
    """R = F_film x Color (catcher) and R + T eta^2 = Color (F_film + (1 - F_film) eta^2)
    (furnace): both are Color x the Color = 1 render. Failed before #1200 (Color entered the
    F0 rescale, R = F_film (1 + (Color - 1) s)): main 000cd943 ratios, CPU and GPU alike,
    R 0.58-0.60 (0 deg) / 0.61 (60 deg), furnace 0.56-0.57 / 0.58."""
    t_base, t_params = _addon_args(monkeypatch, _glass_node(COLOR))
    w_base, w_params = _addon_args(monkeypatch, _glass_node(1.0))
    tinted = _render(t_base, t_params, theta, use_gpu, catcher)
    white = _render(w_base, w_params, theta, use_gpu, catcher)
    ratio = tinted / white
    print(f"[i1200] film glass gpu={use_gpu} theta={theta} catcher={catcher} "
          f"tinted={tinted} white={white} ratio={ratio}")
    assert np.all(white > 0.0)
    assert np.all(np.abs(ratio - COLOR) < 0.01), (tinted, white, ratio)


@pytest.mark.skipif(not AVAILABLE, reason="astroray not built")
@pytest.mark.parametrize("use_gpu", LEGS)
@pytest.mark.parametrize("theta", [0.0, 60.0])
def test_rough_film_glass_reflection_scales_with_color(monkeypatch, use_gpu, theta):
    """The microfacet film lobe: R(Color) / R(1) = Color x darkening(Color) / darkening(1),
    within 2 % of Color at roughness 0.12. Failed before #1200 (same rescale bug): main
    000cd943 ratios 0.58-0.60 (0 deg) / 0.61 (60 deg) on CPU and GPU."""
    t_base, t_params = _addon_args(monkeypatch, _glass_node(COLOR, roughness=0.12))
    w_base, w_params = _addon_args(monkeypatch, _glass_node(1.0, roughness=0.12))
    tinted = _render(t_base, t_params, theta, use_gpu, catcher=True)
    white = _render(w_base, w_params, theta, use_gpu, catcher=True)
    ratio = tinted / white
    print(f"[i1200] rough film glass gpu={use_gpu} theta={theta} tinted={tinted} "
          f"white={white} ratio={ratio}")
    assert np.all(np.abs(ratio - COLOR) < 0.02), (tinted, white, ratio)


@pytest.mark.skipif(not AVAILABLE, reason="astroray not built")
@pytest.mark.parametrize("use_gpu", LEGS)
@pytest.mark.parametrize("theta", [0.0, 60.0])
@pytest.mark.parametrize("catcher", [True, False], ids=["R", "furnace"])
def test_smooth_tinted_principled_glass_matches_generalized_schlick(use_gpu, theta, catcher):
    """Film-free Principled glass, specular_tint 0.5, base white: R = mix(F0 x 0.5, 1, s)
    (analytic), furnace R + (1 - R) eta^2. Main 000cd943 measured (CPU, GPU alike): R at 60
    degrees 0.0405 vs 0.0647 (R = F x 0.5); furnace 0.4764 / 0.4775 vs 0.4845 / 0.5096 at 0 / 60
    degrees (T = (1 - F), not (1 - R)). R at normal incidence is F0 x 0.5 either way (guard).
    Bands: R is a Bernoulli estimate (pick F ~ 0.03-0.08; ~1 % sd at 1024 spp), the furnace
    is nearly noise-free."""
    params = {"transmission_weight": 1.0, "ior": IOR, "roughness": 0.0,
              "specular_tint": [COLOR] * 3}
    got = _render([1.0, 1.0, 1.0], params, theta, use_gpu, catcher)
    R = _principled_R(theta, COLOR)
    want = R if catcher else R + (1.0 - R) / IOR ** 2
    print(f"[i1200] principled glass gpu={use_gpu} theta={theta} catcher={catcher} "
          f"got={got} want={want:.5f}")
    assert np.all(np.abs(got / want - 1.0) < (0.04 if catcher else 0.005)), (got, want)


@pytest.mark.skipif(not AVAILABLE, reason="astroray not built")
@pytest.mark.parametrize("use_gpu", LEGS)
def test_rough_tinted_principled_glass_furnace(use_gpu):
    """The MULTI_GGX twin of the smooth furnace above (roughness 0.05, the alpha floor): the
    microfacet lobe must carry the same generalized-Schlick R and T = (1 - R) sqrt(base)."""
    params = {"transmission_weight": 1.0, "ior": IOR, "roughness": 0.05,
              "specular_tint": [COLOR] * 3}
    got = _render([1.0, 1.0, 1.0], params, 60.0, use_gpu, catcher=False)
    R = _principled_R(60.0, COLOR)
    want = R + (1.0 - R) / IOR ** 2
    print(f"[i1200] rough principled glass furnace gpu={use_gpu} got={got} want={want:.5f}")
    assert np.all(np.abs(got / want - 1.0) < 0.015), (got, want)
