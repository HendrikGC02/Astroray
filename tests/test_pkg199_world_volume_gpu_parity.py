"""pkg199 Stage 1 — GPU wavefront homogeneous world volume (Beer-Lambert
absorption) acceptance oracle.

Stage 1 brings the homogeneous world volume (worldVolumeDensity/Color) to the GPU
wavefront as pure Beer-Lambert absorption `exp(-sigma_t·d)` per wavelength, at
parity with the CPU spectral path_tracer (Renderer::worldTransmittanceSpectral,
roles 1-3). There is NO in-scatter / HG phase in Stage 1 — fog only darkens and
desaturates with distance (worldVolumeAnisotropy is inert, reserved for Stage 2).

Gates:
  * FURNACE / ENERGY (CPU, CI-runnable) — absorption can only REMOVE energy, so
    the foggy linear mean must be strictly below the clear mean AND never exceed
    it (an upper bound: a sign/gain bug would brighten). Rendered apply_gamma=
    False (gamma clamps [0,1] and hides energy GAIN — memory
    gamma-furnace-cannot-detect-energy-gain).
  * CPU/GPU PARITY (GPU) — per-channel mean-ratio on a COLORED fog scene (NOT
    SSIM: independent MC streams, memory ssim-wrong-gate-for-independent-rng).
  * VACUUM BYTE-IDENTITY (GPU) — a density-0 world volume must render identically
    to no world volume (the c_worldVolume hasVolume==0 skip path); guards the
    "vacuum renders unchanged" acceptance criterion.
  * VISUAL FOG (GPU) — a depth-staggered colored-fog scene saved to PNG for the
    mandatory human/parent inspection (numeric gates can pass on noise).

GPU legs skip when CUDA is absent (CI has no GPU); /verify runs them on the RTX.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()
sys.path.insert(0, os.path.dirname(__file__))

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

WIDTH = HEIGHT = 64
SAMPLES = 128
MAX_DEPTH = 6
SEED = 199199

# A reddish-grey fog: distinct per-channel sigma_t (blue absorbed most) so the
# parity gate exercises the spectral upsample path, not just a grey scalar.
FOG_COLOR = [0.85, 0.55, 0.35]
FOG_DENSITY = 0.06


def _gpu_available() -> bool:
    return AVAILABLE and astroray.__features__.get("cuda", False) \
        and astroray.Renderer().gpu_available


def _make_fog_scene(use_gpu: bool, density: float | None, color=None,
                    z_sphere: float = -3.0, w: int = WIDTH, h: int = HEIGHT):
    """A grey diffuse sphere lit by a bright lamp, seen through the world medium.
    Larger camera→sphere and sphere→lamp distances make the Beer-Lambert falloff
    the dominant visible effect."""
    r = astroray.Renderer()
    r.set_seed(SEED)
    r.set_background_color([0.02, 0.02, 0.03])
    if density is not None:
        r.set_world_volume(density, color if color is not None else FOG_COLOR, 0.0)
    lamp = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 60.0})
    diffuse = r.create_material("lambertian", [0.80, 0.80, 0.80], {})
    r.add_sphere([0.0, 2.6, z_sphere + 1.2], 0.7, lamp)
    r.add_sphere([0.0, -0.2, z_sphere], 1.0, diffuse)
    r.setup_camera([0.0, 0.0, 8.0], [0.0, -0.2, z_sphere], [0.0, 1.0, 0.0],
                   30.0, w / h, 0.0, 8.0, w, h)
    r.set_integrator("path_tracer")
    r.set_integrator_param("max_depth", MAX_DEPTH)
    if use_gpu:
        r.set_use_gpu(True)
        r.set_wavelength_range(380.0, 780.0)
        r.set_output_mode("srgb")
    return r


def _render(r, samples: int = SAMPLES, w: int = WIDTH, h: int = HEIGHT) -> np.ndarray:
    # 4th positional arg is applyGamma=False → LINEAR output (furnace discipline).
    img = np.asarray(r.render(samples, MAX_DEPTH, None, False), dtype=np.float64)
    if img.ndim == 1:
        img = img.reshape(h, w, 3)
    return img


def _means(img):
    return np.array([float(img[..., c].mean()) for c in range(3)])


# ---------------------------------------------------------------------------
# FURNACE / ENERGY — CPU, CI-runnable. Absorption removes energy; never adds.
# ---------------------------------------------------------------------------

def test_world_volume_absorption_only_removes_energy_cpu():
    clear = _means(_render(_make_fog_scene(False, None)))
    foggy = _means(_render(_make_fog_scene(False, FOG_DENSITY)))
    print(f"\n[pkg199 CPU furnace] clear={np.round(clear,4)} foggy={np.round(foggy,4)} "
          f"foggy/clear={np.round(foggy/np.maximum(clear,1e-6),4)}")
    clear_m, foggy_m = clear.mean(), foggy.mean()
    # Upper bound: absorption can only attenuate — foggy must not exceed clear
    # (a +sigma sign / product-upsample bug would brighten). Tiny MC slack.
    assert foggy_m <= clear_m * 1.02, (
        f"world-volume absorption ADDED energy (foggy {foggy_m:.4f} > clear "
        f"{clear_m:.4f}) — sign/gain bug in worldTransmittanceSpectral")
    # And it must visibly darken at this density.
    assert foggy_m < clear_m * 0.97, (
        f"world-volume absorption produced no visible attenuation "
        f"(foggy {foggy_m:.4f} vs clear {clear_m:.4f})")
    # Colored fog: worldVolumeColor IS the sigma_t tint, so the channel with the
    # LARGEST color component has the HIGHEST extinction and transmits LEAST.
    # FOG_COLOR=[0.85,0.55,0.35] → red sigma_t highest → red attenuated MOST
    # (atten[R] smallest). A product-upsample or grey-scalar bug breaks this.
    atten = foggy / np.maximum(clear, 1e-6)
    assert atten[0] < atten[2], (
        f"sigma_t tint {FOG_COLOR}: RED (highest sigma_t) must attenuate MORE than "
        f"BLUE (atten R={atten[0]:.4f} B={atten[2]:.4f}) — spectral upsample wrong")


# ---------------------------------------------------------------------------
# CPU/GPU PARITY — per-channel mean-ratio on the colored fog scene.
# ---------------------------------------------------------------------------

def test_world_volume_cpu_gpu_parity():
    if not _gpu_available():
        pytest.skip("CUDA GPU not available on this machine")
    gpu = _means(_render(_make_fog_scene(True, FOG_DENSITY)))
    cpu = _means(_render(_make_fog_scene(False, FOG_DENSITY)))
    ratio = gpu / np.maximum(cpu, 1e-6)
    print(f"\n[pkg199 CPU/GPU fog parity] GPU={np.round(gpu,4)} CPU={np.round(cpu,4)} "
          f"GPU/CPU={np.round(ratio,4)}")
    for c, ch in enumerate("RGB"):
        assert 0.85 <= ratio[c] <= 1.18, (
            f"pkg199 CPU/GPU fog parity FAILED ch {ch}: GPU/CPU mean-ratio "
            f"{ratio[c]:.4f} outside [0.85, 1.18] (GPU {gpu[c]:.4f}, CPU {cpu[c]:.4f})")


def _beer_lambert_scene(density: float | None, dist: float, w: int = 48, h: int = 48):
    """Single-segment analytic furnace: a bright emissive wall at distance `dist`
    viewed head-on through white world fog. With no surface between camera and
    wall, the measured centre transmittance must equal exp(-sigma_t·dist) with
    sigma_t = upsample([1,1,1])·density ≈ density — a direct Beer-Lambert check
    that is NOT confounded by scene lighting/indirect bounces."""
    r = astroray.Renderer()
    r.set_seed(SEED)
    r.set_background_color([0.0, 0.0, 0.0])
    wall = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 1.0})
    r.add_triangle([-20, -20, -dist], [20, -20, -dist], [20, 20, -dist], wall)
    r.add_triangle([-20, -20, -dist], [20, 20, -dist], [-20, 20, -dist], wall)
    if density is not None:
        r.set_world_volume(density, [1.0, 1.0, 1.0], 0.0)   # white → sigma≈density
    r.setup_camera([0.0, 0.0, 0.001], [0.0, 0.0, -dist], [0.0, 1.0, 0.0],
                   20.0, w / h, 0.0, dist, w, h)
    r.set_integrator("path_tracer")
    r.set_integrator_param("max_depth", 2)
    r.set_use_gpu(True)
    r.set_wavelength_range(380.0, 780.0)
    r.set_output_mode("srgb")
    return r


def _center_mean(img):
    h, w = img.shape[:2]
    return float(img[h // 2 - 4:h // 2 + 4, w // 2 - 4:w // 2 + 4, :].mean())


def test_world_volume_gpu_analytic_beer_lambert():
    """GPU transmittance must match the analytic exp(-sigma_t·dist) Beer-Lambert
    law for white fog — the rigorous, unconfounded distance/density gate. This
    also bounds energy from above (Tr <= 1: absorption never brightens)."""
    if not _gpu_available():
        pytest.skip("CUDA GPU not available on this machine")
    import math
    for dist in (5.0, 10.0):
        clear = _center_mean(_render(_beer_lambert_scene(None, dist)))
        for dens in (0.1, 0.2):
            fog = _center_mean(_render(_beer_lambert_scene(dens, dist)))
            measured = fog / max(clear, 1e-8)
            analytic = math.exp(-dens * 1.0 * dist)
            print(f"\n[pkg199 GPU Beer-Lambert] dist={dist} dens={dens}: "
                  f"measured Tr={measured:.4f} analytic={analytic:.4f}")
            assert measured <= 1.02, (
                f"absorption brightened (Tr={measured:.4f} > 1) — sign/gain bug")
            assert abs(measured - analytic) < 0.02, (
                f"GPU transmittance {measured:.4f} != analytic exp(-{dens}·{dist})="
                f"{analytic:.4f} (dist={dist}) — Beer-Lambert law violated")


# ---------------------------------------------------------------------------
# VACUUM BYTE-IDENTITY — density-0 volume == no volume (the hasVolume==0 skip).
# ---------------------------------------------------------------------------

def test_world_volume_zero_density_gpu_byte_identical():
    """A density-0 world volume must render identically to NO world volume: both
    publish hasVolume==0, so intersectPathSlot/stageShadowKernel skip the
    transmittance branch entirely. Because two separate GPU renders differ by a
    tiny atomic-add nondeterminism floor (float-add non-associativity in NEE/color
    accumulation), the acceptance is that the zero-density-vs-no-volume diff stays
    WITHIN that noise floor — i.e. adds no systematic change, unlike a real fog
    leak (density 0.06 shifts pixels by ~0.3, four orders of magnitude larger)."""
    if not _gpu_available():
        pytest.skip("CUDA GPU not available on this machine")
    a = _render(_make_fog_scene(True, None))     # no volume
    b = _render(_make_fog_scene(True, None))     # same scene again → noise floor
    c = _render(_make_fog_scene(True, 0.0))      # density-0 volume (hasVolume==0)
    noise = float(np.max(np.abs(a - b)))
    diff = float(np.max(np.abs(a - c)))
    print(f"\n[pkg199 GPU vacuum byte-identity] no-vol self-noise={noise:.2e} "
          f"zero-density diff={diff:.2e}")
    assert diff <= max(noise * 2.0, 1e-4), (
        f"GPU density-0 world volume diverged from no-volume beyond the GPU "
        f"nondeterminism floor (diff {diff:.2e} vs noise {noise:.2e}); the "
        f"c_worldVolume hasVolume==0 skip must leave vacuum renders untouched")


# ---------------------------------------------------------------------------
# VISUAL FOG — depth-staggered colored fog, saved to PNG (human/parent check).
# ---------------------------------------------------------------------------

def test_world_volume_gpu_visual(test_results_dir):
    if not _gpu_available():
        pytest.skip("CUDA GPU not available on this machine")
    from base_helpers import save_image

    w = h = 220

    def scene(density):
        r = astroray.Renderer()
        r.set_seed(SEED)
        r.set_background_color([0.02, 0.02, 0.04])
        lamp = r.create_material("light", [1.0, 0.96, 0.9], {"intensity": 80.0})
        r.add_sphere([2.4, 3.0, 2.0], 0.7, lamp)
        grey = r.create_material("lambertian", [0.82, 0.82, 0.82], {})
        # A receding row of spheres: each farther one is fogged more.
        for i, z in enumerate([2.0, -1.0, -4.0, -7.0, -10.0]):
            r.add_sphere([(-2.0 + i * 1.0), -0.3, z], 0.9, grey)
        if density is not None:
            r.set_world_volume(density, FOG_COLOR, 0.0)
        r.setup_camera([0.0, 0.6, 9.0], [0.0, -0.3, -4.0], [0.0, 1.0, 0.0],
                       40.0, w / h, 0.0, 9.0, w, h)
        r.set_integrator("path_tracer")
        r.set_integrator_param("max_depth", MAX_DEPTH)
        r.set_use_gpu(True)
        r.set_wavelength_range(380.0, 780.0)
        r.set_output_mode("srgb")
        img = np.asarray(r.render(512, MAX_DEPTH, None, True), dtype=np.float32)
        return img.reshape(h, w, 3) if img.ndim == 1 else img

    clear_png = os.path.join(test_results_dir, "pkg199_gpu_fog_clear.png")
    foggy_png = os.path.join(test_results_dir, "pkg199_gpu_fog_dense.png")
    save_image(scene(None), clear_png)
    save_image(scene(FOG_DENSITY), foggy_png)
    print(f"\n[pkg199 GPU visual]\n  CLEAR PNG: {clear_png}\n  FOGGY PNG: {foggy_png}\n"
          f"  PARENT: open both — the foggy render's distant spheres should fade "
          f"into the medium (darker + desaturated toward the reddish fog tint) "
          f"while the near sphere stays crisp. No god-rays in Stage 1 (absorption "
          f"only); that is expected.")
    # The PNGs are the artifact for the human/parent visual check; assert they
    # were written (the numeric distance-falloff gate above is the metric).
    assert os.path.exists(clear_png) and os.path.exists(foggy_png)
