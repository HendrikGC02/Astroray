"""pkg199 Stage 2 (CPU) — homogeneous scattering world medium acceptance oracle.

Stage 2 adds genuine volumetric scattering to the homogeneous world medium:
analytic exponential free-flight distance sampling (PBRT-v3
HomogeneousMedium::Sample, per-channel selection), Henyey-Greenstein in-scatter
(HG 1941 / PBRT-v3 HenyeyGreenstein), and NEE-through-medium with phase/light
MIS. Scattering strength is the single-scattering albedo alpha in [0,1]
(set_world_volume's new trailing `scatter` arg): sigma_t = upsample(color)*density
(unchanged from Stage 1), sigma_s = alpha*sigma_t, sigma_a = (1-alpha)*sigma_t.

Gates (all CPU, apply_gamma=False / LINEAR — gamma clamps [0,1] and would hide an
energy GAIN, memory gamma-furnace-cannot-detect-energy-gain):
  * ALPHA=0 STAGE-1 PARITY — scatter=0.0 must reproduce Stage-1 Beer-Lambert
    absorption exactly (the estimator is not engaged; same RNG stream). Deterministic
    bit-reproducibility + analytic exp(-sigma_t*d) transmittance on an emissive wall.
  * ANALYTIC SINGLE-SCATTER — with max_depth=1 (exactly one scatter event, NEE to a
    delta point light, no multi-scatter), a narrow-FOV pixel matches the single-scatter
    integral S(density) = INT sigma_s*exp(-sigma_t*t)*exp(-sigma_t*r(t))/r(t)^2 dt to a
    single global radiometric scale k across a density sweep (a wrong phase/
    transmittance/distance-sampling breaks the density SHAPE, which no single k fits).
    Plus linearity in alpha (single scatter is proportional to sigma_s = alpha*sigma_t).
  * FORWARD/BACK SCATTER — a light directly behind the fog (cosTheta = -1) gives a
    strong forward-scatter halo: mean(g=+0.7) must clearly exceed mean(g=-0.7). PNGs
    saved for the mandatory visual inspection.
  * SUM-TO-BEAUTY — with the volume passes included, Sigma(passes) == beauty in linear
    sRGB on a scattering scene (pkg198 invariant extended to PASS_VOLUME_*).
  * ENERGY BOUNDS — in-scatter ADDS light (mean increases with alpha) but never
    unphysically (bounded).
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()
sys.path.insert(0, os.path.dirname(__file__))

from base_helpers import save_image

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

SEED = 199222


@pytest.fixture
def test_results_dir():
    d = os.path.join(os.path.dirname(__file__), "..", "test_results")
    os.makedirs(d, exist_ok=True)
    return os.path.abspath(d)


def _render_cpu(r, spp, max_depth, w, h):
    """CPU render (never enable GPU), apply_gamma=False -> LINEAR."""
    img = np.asarray(r.render(spp, max_depth, None, False), dtype=np.float64)
    if img.ndim == 1:
        img = img.reshape(h, w, 3)
    return img


# ---------------------------------------------------------------------------
# ALPHA = 0 -> Stage-1 Beer-Lambert absorption (the estimator is NOT engaged).
# ---------------------------------------------------------------------------

def _wall_scene(density, scatter, dist=5.0, w=32, h=32):
    """Emissive wall at `dist`, camera head-on through white world fog. With no
    surface between camera and wall, the centre transmittance = exp(-sigma_t*dist),
    sigma_t = upsample([1,1,1])*density ~= density. Self-calibrated by the clear
    render (ratio is unit-free)."""
    r = astroray.Renderer()
    r.set_seed(SEED)
    r.set_background_color([0.0, 0.0, 0.0])
    wall = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 1.0})
    r.add_triangle([-20, -20, -dist], [20, -20, -dist], [20, 20, -dist], wall)
    r.add_triangle([-20, -20, -dist], [20, 20, -dist], [-20, 20, -dist], wall)
    if density is not None:
        r.set_world_volume(density, [1.0, 1.0, 1.0], 0.0, scatter)
    r.setup_camera([0.0, 0.0, 0.001], [0.0, 0.0, -dist], [0.0, 1.0, 0.0],
                   20.0, w / h, 0.0, dist, w, h)
    r.set_integrator("path_tracer")
    r.set_integrator_param("max_depth", 2)
    return r


def _center_mean(img):
    h, w = img.shape[:2]
    return float(img[h // 2 - 4:h // 2 + 4, w // 2 - 4:w // 2 + 4, :].mean())


def test_alpha_zero_is_beer_lambert_absorption():
    """scatter=0.0 must reproduce Stage-1 absorption: the measured wall
    transmittance equals the analytic exp(-sigma_t*dist), and NO in-scatter energy
    is added (the scattering estimator is gated off at alpha=0)."""
    dist = 5.0
    clear = _center_mean(_render_cpu(_wall_scene(None, 0.0, dist), 128, 2, 32, 32))
    for dens in (0.1, 0.2):
        foggy = _center_mean(_render_cpu(_wall_scene(dens, 0.0, dist), 128, 2, 32, 32))
        measured_tr = foggy / max(clear, 1e-9)
        analytic_tr = float(np.exp(-dens * dist))
        print(f"[pkg199-s2 alpha=0 Beer-Lambert] dens={dens} dist={dist}: "
              f"measured Tr={measured_tr:.4f} analytic={analytic_tr:.4f}")
        # White upsample gives sigma_t ~= density (a few % off 1.0); allow for that
        # plus MC noise. The key: pure absorption (Tr<=1, no in-scatter brightening).
        assert measured_tr <= 1.02, (
            f"alpha=0 ADDED energy (Tr={measured_tr:.4f}>1) — scattering leaked into "
            f"the absorption limit")
        assert abs(measured_tr - analytic_tr) < 0.06, (
            f"alpha=0 transmittance {measured_tr:.4f} != analytic {analytic_tr:.4f}")


def test_alpha_zero_deterministic():
    """Fixed seed, alpha=0: two renders are bit-identical (the estimator consumes
    no RNG in the absorption limit)."""
    a = _render_cpu(_wall_scene(0.15, 0.0), 64, 2, 32, 32)
    b = _render_cpu(_wall_scene(0.15, 0.0), 64, 2, 32, 32)
    assert np.array_equal(a, b), "alpha=0 render is not deterministic under a fixed seed"


# ---------------------------------------------------------------------------
# ANALYTIC SINGLE-SCATTER — max_depth=1 isolates one scatter + NEE.
# ---------------------------------------------------------------------------

# Camera ray geometry (narrow FOV -> all pixels ~= the centre ray).
_CAM = np.array([0.0, 0.0, 6.0])
_LOOK = np.array([0.0, 0.0, 0.0])
_DIR = (_LOOK - _CAM) / np.linalg.norm(_LOOK - _CAM)   # (0,0,-1)
_PL = np.array([2.0, 0.0, 0.0])                        # off-axis point light


def _single_scatter_scene(density, alpha, g=0.0, w=24, h=24):
    r = astroray.Renderer()
    r.set_seed(SEED)
    r.set_background_color([0.0, 0.0, 0.0])          # black bg -> no un-scattered term
    r.set_world_volume(density, [1.0, 1.0, 1.0], g, alpha)   # grey medium
    r.add_point_light(_PL.tolist(), {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 50.0)
    r.setup_camera(_CAM.tolist(), _LOOK.tolist(), [0.0, 1.0, 0.0],
                   2.0, w / h, 0.0, 6.0, w, h)          # 2 deg FOV
    r.set_integrator("path_tracer")
    r.set_integrator_param("max_depth", 1)              # EXACTLY single scatter
    return r


def _single_scatter_integral(density, alpha, tmax=80.0, n=40000):
    """S(density) = INT_0^inf sigma_s exp(-sigma_t t) exp(-sigma_t r(t))/r(t)^2 dt,
    the isotropic (g=0) single-scatter response along the centre camera ray for a
    delta point light. sigma_t = density (white grey), sigma_s = alpha*sigma_t."""
    sigma_t = density
    sigma_s = alpha * density
    t = np.linspace(1e-4, tmax, n)
    x = _CAM[None, :] + t[:, None] * _DIR[None, :]
    r = np.linalg.norm(x - _PL[None, :], axis=1)
    integrand = sigma_s * np.exp(-sigma_t * t) * np.exp(-sigma_t * r) / (r * r)
    return float(np.trapz(integrand, t))


def test_single_scatter_matches_analytic_density_shape():
    """The single-scatter density SHAPE matches the analytic integral to one global
    radiometric scale k (fit across the sweep). A wrong transmittance / phase /
    distance-sampling breaks the density dependence, which no single k can absorb."""
    alpha = 0.4
    densities = [0.05, 0.10, 0.20, 0.35]
    measured, analytic = [], []
    for dens in densities:
        img = _render_cpu(_single_scatter_scene(dens, alpha, g=0.0), 512, 1, 24, 24)
        measured.append(float(img.mean()))
        analytic.append(_single_scatter_integral(dens, alpha))
    measured = np.array(measured)
    analytic = np.array(analytic)
    k = float((measured / analytic).mean())          # single global scale
    pred = k * analytic
    resid = np.abs(measured - pred) / np.maximum(pred, 1e-9)
    print(f"[pkg199-s2 single-scatter] dens={densities}")
    print(f"  measured ={np.round(measured, 6)}")
    print(f"  analytic ={np.round(analytic, 6)}  k={k:.5g}")
    print(f"  k*analytic={np.round(pred, 6)}  max_resid={resid.max():.4f}")
    assert resid.max() < 0.10, (
        f"single-scatter density shape off analytic by {resid.max():.3f} "
        f"(no single scale fits) — transmittance/phase/distance-sampling bug")


def test_single_scatter_linear_in_alpha():
    """Single scatter is proportional to sigma_s = alpha*sigma_t: L/alpha ~= const at
    small alpha (validates the alpha->sigma_s mapping and the estimator prefactor)."""
    dens = 0.12
    ratios = []
    for alpha in (0.1, 0.2, 0.4):
        img = _render_cpu(_single_scatter_scene(dens, alpha, g=0.0), 512, 1, 24, 24)
        ratios.append(float(img.mean()) / alpha)
    ratios = np.array(ratios)
    spread = ratios.std() / max(ratios.mean(), 1e-9)
    print(f"[pkg199-s2 alpha-linearity] L/alpha={np.round(ratios, 6)} spread={spread:.4f}")
    assert spread < 0.06, f"single scatter not linear in alpha (spread {spread:.3f})"


# ---------------------------------------------------------------------------
# FORWARD / BACK SCATTER — g sign asymmetry + visual gate.
# ---------------------------------------------------------------------------

def _halo_scene(g, w=64, h=64):
    """Point light directly BEHIND the fog along the view axis (cosTheta=-1 at the
    scatter points), so forward scattering (g>0) throws a bright halo toward the
    camera and back scattering (g<0) does not."""
    r = astroray.Renderer()
    r.set_seed(SEED)
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_world_volume(0.15, [1.0, 1.0, 1.0], g, 0.6)
    r.add_point_light([0.0, 0.0, -4.0], {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 80.0)
    r.setup_camera([0.0, 0.0, 6.0], [0.0, 0.0, -4.0], [0.0, 1.0, 0.0],
                   35.0, w / h, 0.0, 10.0, w, h)
    r.set_integrator("path_tracer")
    r.set_integrator_param("max_depth", 4)
    return r


def test_forward_back_scatter_asymmetry(test_results_dir):
    fwd = _render_cpu(_halo_scene(0.7), 256, 4, 64, 64)
    bwd = _render_cpu(_halo_scene(-0.7), 256, 4, 64, 64)
    fm, bm = float(fwd.mean()), float(bwd.mean())
    print(f"[pkg199-s2 fwd/back scatter] mean(g=+0.7)={fm:.5f} mean(g=-0.7)={bm:.5f} "
          f"ratio={fm / max(bm, 1e-9):.3f}")
    save_image(fwd.astype(np.float32), os.path.join(test_results_dir,
              "pkg199_s2_forward_scatter.png"))
    save_image(bwd.astype(np.float32), os.path.join(test_results_dir,
              "pkg199_s2_back_scatter.png"))
    assert fm > bm * 1.5, (
        f"forward scatter (g=+0.7, {fm:.5f}) must clearly exceed back scatter "
        f"(g=-0.7, {bm:.5f}) for a light behind the fog — HG sign/frame bug")


# ---------------------------------------------------------------------------
# SUM-TO-BEAUTY with the volume passes included (pkg198 invariant, extended).
# ---------------------------------------------------------------------------

_ALL_PASSES = [
    "diffuse_direct", "diffuse_indirect",
    "glossy_direct", "glossy_indirect",
    "transmission_direct", "transmission_indirect",
    "volume_direct", "volume_indirect",
    "emission", "environment",
]


def _scatter_beauty_scene(w=48, h=48):
    r = astroray.Renderer()
    r.set_seed(SEED)
    r.set_background_color([0.03, 0.04, 0.06])
    r.set_world_volume(0.14, [0.9, 0.9, 1.0], 0.3, 0.7)   # scattering fog
    diffuse = r.create_material("lambertian", [0.7, 0.7, 0.7], {})
    r.add_sphere([0.0, -0.3, -1.0], 1.0, diffuse)
    r.add_point_light([2.5, 3.0, 2.0], {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 70.0)
    r.setup_camera([0.0, 0.0, 6.0], [0.0, -0.3, -1.0], [0.0, 1.0, 0.0],
                   40.0, w / h, 0.0, 7.0, w, h)
    r.set_integrator("path_tracer")
    r.set_integrator_param("max_depth", 6)
    return r


def test_sum_to_beauty_with_volume_passes(test_results_dir):
    r = _scatter_beauty_scene()
    beauty = _render_cpu(r, 96, 6, 48, 48)
    total = None
    for name in _ALL_PASSES:
        buf = np.array(r.get_render_pass_buffer(name), dtype=np.float64)
        total = buf if total is None else total + buf
    beauty_mean = beauty.reshape(-1, 3).mean(axis=0)
    passes_mean = total.reshape(-1, 3).mean(axis=0)
    ratio = passes_mean / np.maximum(beauty_mean, 1e-6)
    denom = np.maximum(np.abs(beauty).sum(), 1e-6)
    rel_l1 = np.abs(total - beauty).sum() / denom
    vol = np.array(r.get_render_pass_buffer("volume_direct"), dtype=np.float64) \
        + np.array(r.get_render_pass_buffer("volume_indirect"), dtype=np.float64)
    print(f"[pkg199-s2 sum-to-beauty] ratio={np.round(ratio, 5)} rel_L1={rel_l1:.4f} "
          f"volume_mean={vol.mean():.5f}")
    assert np.allclose(ratio, 1.0, atol=0.03), f"Sigma(passes)/beauty off: {ratio}"
    assert rel_l1 < 0.03, f"pixelwise rel_L1 too high: {rel_l1:.4f}"
    assert vol.mean() > 1e-5, "volume passes are empty on a scattering scene"


# ---------------------------------------------------------------------------
# ENERGY BOUNDS — in-scatter adds light with alpha, bounded.
# ---------------------------------------------------------------------------

def test_scatter_adds_energy_monotonic():
    """More scattering albedo -> more in-scattered light reaching the camera
    (floor) but bounded (ceiling: not a runaway gain)."""
    means = []
    for alpha in (0.0, 0.3, 0.6, 0.9):
        r = astroray.Renderer()
        r.set_seed(SEED)
        r.set_background_color([0.0, 0.0, 0.0])
        r.set_world_volume(0.15, [1.0, 1.0, 1.0], 0.5, alpha)
        r.add_point_light([0.0, 0.0, -4.0], {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 80.0)
        r.setup_camera([0.0, 0.0, 6.0], [0.0, 0.0, -4.0], [0.0, 1.0, 0.0],
                       35.0, 1.0, 0.0, 10.0, 48, 48)
        r.set_integrator("path_tracer")
        r.set_integrator_param("max_depth", 4)
        means.append(float(_render_cpu(r, 128, 4, 48, 48).mean()))
    means = np.array(means)
    print(f"[pkg199-s2 energy vs alpha] means={np.round(means, 5)}")
    assert means[0] < means[1] < means[2] < means[3], (
        f"in-scatter must increase with alpha: {means}")
    assert means[-1] < 10.0, f"runaway energy gain at alpha=0.9: {means[-1]}"
