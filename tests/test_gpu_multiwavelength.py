"""pkg54 / pkg54a GPU multi-wavelength path tracer parity tests.

Compares the CUDA megakernel (src/gpu/multiwavelength_kernel.cu) against
the CPU integrator at three bands:

* visible (380-780 nm) — spectral parity gate via SSIM ≥ 0.97;
* near-IR (700-1000 nm) — non-degenerate parity with spectral profiles
  attached (vegetation profile bright, water profile dark);
* UV (300-400 nm) — same, with the aluminium profile carrying the back wall.

Skipped when no CUDA GPU is available, or when profiles.bin is missing.
"""

import os

import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray module not available")

REPO_ROOT    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILES_BIN = os.path.join(REPO_ROOT, "data", "spectral_profiles", "profiles.bin")
HAS_PROFILES = os.path.exists(PROFILES_BIN)


def _has_cuda_gpu(renderer):
    return (
        bool(astroray.__features__.get("cuda", False))
        and bool(getattr(renderer, "gpu_available", False))
    )


def _ssim(a, b):
    """SSIM with a numpy fallback if scikit-image is unavailable."""
    try:
        from skimage.metrics import structural_similarity
        return float(structural_similarity(a, b, channel_axis=2, data_range=1.0))
    except ImportError:
        a = a.astype(np.float64)
        b = b.astype(np.float64)
        c1 = 0.01 ** 2
        c2 = 0.03 ** 2
        mu_a = np.mean(a); mu_b = np.mean(b)
        var_a = np.var(a); var_b = np.var(b)
        cov = np.mean((a - mu_a) * (b - mu_b))
        return float(((2 * mu_a * mu_b + c1) * (2 * cov + c2))
                     / ((mu_a * mu_a + mu_b * mu_b + c1) * (var_a + var_b + c2)))


def _build(width=64, height=64, *, attach_profiles=False):
    import scenes.multiwavelength_parity as scene
    r = astroray.Renderer()
    scene.setup_camera(r, width=width, height=height)
    scene.build_scene(r, attach_profiles=attach_profiles)
    r.set_seed(42)
    return r


def _render_pair(lmin, lmax, mode, *,
                 width=48, height=48, spp=64, depth=4,
                 attach_profiles=False):
    """Returns (cpu_pixels, gpu_pixels) at the requested band.

    Skips at function entry if no GPU.
    """
    probe = astroray.Renderer()
    if not _has_cuda_gpu(probe):
        pytest.skip("CUDA GPU not available")

    cpu = _build(width=width, height=height, attach_profiles=attach_profiles)
    cpu.set_wavelength_range(float(lmin), float(lmax))
    cpu.set_output_mode(mode)
    cpu.set_integrator("multiwavelength_path_tracer")
    cpu_px = np.array(cpu.render(samples_per_pixel=spp, max_depth=depth, apply_gamma=False),
                      dtype=np.float32)

    gpu = _build(width=width, height=height, attach_profiles=attach_profiles)
    gpu.set_use_gpu(True)
    gpu.set_wavelength_range(float(lmin), float(lmax))
    gpu.set_output_mode(mode)
    gpu.set_integrator("multiwavelength_path_tracer")
    gpu_px = np.array(gpu.render(samples_per_pixel=spp, max_depth=depth, apply_gamma=False),
                      dtype=np.float32)

    return cpu_px, gpu_px


# ---------------------------------------------------------------------------
# 1. Visible-band SSIM ≥ 0.97 — the hard parity gate
# ---------------------------------------------------------------------------

def test_visible_band_cpu_gpu_ssim():
    """pkg54b: same CIE 1964 10° CMF table on both sides → tighter gate."""
    cpu, gpu = _render_pair(380.0, 780.0, "", spp=64)
    assert np.all(np.isfinite(cpu))
    assert np.all(np.isfinite(gpu))
    # Tone-map to [0, 1] so SSIM is well-behaved.
    cpu_t = np.clip(cpu, 0.0, 1.0)
    gpu_t = np.clip(gpu, 0.0, 1.0)
    ssim = _ssim(cpu_t, gpu_t)
    assert ssim >= 0.99, f"visible-band SSIM {ssim:.4f} < 0.99 (pkg54b gate)"


# ---------------------------------------------------------------------------
# 2. NIR-band parity with spectral profiles attached (pkg54a real gate)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not HAS_PROFILES, reason="profiles.bin not found")
def test_nir_band_cpu_gpu_ssim_with_profiles():
    cpu, gpu = _render_pair(700.0, 1000.0, "luminance",
                            spp=32, attach_profiles=True)
    assert np.all(np.isfinite(cpu))
    assert np.all(np.isfinite(gpu))
    # Vegetation profile should make the render non-degenerate (Wood effect).
    assert cpu.mean() > 0.005, (
        f"CPU NIR render too dark (mean={cpu.mean():.4f}) — profile dispatch broken?"
    )
    assert gpu.mean() > 0.005, (
        f"GPU NIR render too dark (mean={gpu.mean():.4f}) — pkg54a profile "
        f"dispatch not active on GPU?"
    )
    cpu_t = np.clip(cpu, 0.0, 1.0)
    gpu_t = np.clip(gpu, 0.0, 1.0)
    ssim = _ssim(cpu_t, gpu_t)
    assert ssim >= 0.97, f"NIR-band (profiled) SSIM {ssim:.4f} < 0.97"


# ---------------------------------------------------------------------------
# 3. UV-band parity with spectral profiles attached
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not HAS_PROFILES, reason="profiles.bin not found")
def test_uv_band_cpu_gpu_ssim_with_profiles():
    cpu, gpu = _render_pair(300.0, 400.0, "luminance",
                            spp=32, attach_profiles=True)
    assert np.all(np.isfinite(cpu))
    assert np.all(np.isfinite(gpu))
    cpu_t = np.clip(cpu, 0.0, 1.0)
    gpu_t = np.clip(gpu, 0.0, 1.0)
    ssim = _ssim(cpu_t, gpu_t)
    assert ssim >= 0.97, f"UV-band (profiled) SSIM {ssim:.4f} < 0.97"


# ---------------------------------------------------------------------------
# 3b. NIR no-profile fallback parity (still degenerate but must agree).
# ---------------------------------------------------------------------------

def test_nir_band_cpu_gpu_no_profile_fallback():
    cpu, gpu = _render_pair(700.0, 1000.0, "luminance",
                            spp=16, attach_profiles=False)
    assert np.all(np.isfinite(cpu))
    assert np.all(np.isfinite(gpu))
    cpu_t = np.clip(cpu, 0.0, 1.0)
    gpu_t = np.clip(gpu, 0.0, 1.0)
    ssim = _ssim(cpu_t, gpu_t)
    assert ssim >= 0.97, f"NIR fallback SSIM {ssim:.4f} < 0.97"


# ---------------------------------------------------------------------------
# 4. GPU MW kernel produces finite, non-degenerate output
# ---------------------------------------------------------------------------

def test_gpu_mw_kernel_runs_and_is_finite():
    probe = astroray.Renderer()
    if not _has_cuda_gpu(probe):
        pytest.skip("CUDA GPU not available")
    gpu = _build(width=32, height=32)
    gpu.set_use_gpu(True)
    gpu.set_wavelength_range(380.0, 780.0)
    gpu.set_integrator("multiwavelength_path_tracer")
    pix = np.array(gpu.render(samples_per_pixel=8, max_depth=3, apply_gamma=False),
                   dtype=np.float32)
    assert np.all(np.isfinite(pix))
    assert np.any(pix > 0.0), "GPU MW kernel produced an all-black image"
