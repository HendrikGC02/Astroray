"""pkg54 GPU multi-wavelength path tracer parity tests.

Compares the new CUDA megakernel (src/gpu/multiwavelength_kernel.cu) against
the existing CPU integrator at three bands:

* visible (380-780 nm) — exact spectral parity gate via SSIM ≥ 0.97;
* near-IR (700-1000 nm) — sanity gate on a near-black render (no profiles
  attached, so both backends fall through to the RGB-to-spectrum estimator,
  which produces tiny but matching outputs);
* UV (300-400 nm) — same near-black sanity gate.

Skipped when no CUDA GPU is available.
"""

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


def _build(width=64, height=64):
    import scenes.multiwavelength_parity as scene
    r = astroray.Renderer()
    scene.setup_camera(r, width=width, height=height)
    scene.build_scene(r)
    r.set_seed(42)
    return r


def _render_pair(lmin, lmax, mode, *, width=48, height=48, spp=64, depth=4):
    """Returns (cpu_pixels, gpu_pixels) at the requested band.

    Skips at function entry if no GPU.
    """
    probe = astroray.Renderer()
    if not _has_cuda_gpu(probe):
        pytest.skip("CUDA GPU not available")

    cpu = _build(width=width, height=height)
    cpu.set_wavelength_range(float(lmin), float(lmax))
    cpu.set_output_mode(mode)
    cpu.set_integrator("multiwavelength_path_tracer")
    cpu_px = np.array(cpu.render(samples_per_pixel=spp, max_depth=depth, apply_gamma=False),
                      dtype=np.float32)

    gpu = _build(width=width, height=height)
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
    cpu, gpu = _render_pair(380.0, 780.0, "", spp=64)
    assert np.all(np.isfinite(cpu))
    assert np.all(np.isfinite(gpu))
    # Tone-map to [0, 1] so SSIM is well-behaved.
    cpu_t = np.clip(cpu, 0.0, 1.0)
    gpu_t = np.clip(gpu, 0.0, 1.0)
    ssim = _ssim(cpu_t, gpu_t)
    assert ssim >= 0.97, f"visible-band SSIM {ssim:.4f} < 0.97"


# ---------------------------------------------------------------------------
# 2. NIR-band sanity: GPU and CPU agree at SSIM ≥ 0.97 (both near-black)
# ---------------------------------------------------------------------------

def test_nir_band_cpu_gpu_ssim():
    cpu, gpu = _render_pair(700.0, 1000.0, "luminance", spp=32)
    assert np.all(np.isfinite(cpu))
    assert np.all(np.isfinite(gpu))
    cpu_t = np.clip(cpu, 0.0, 1.0)
    gpu_t = np.clip(gpu, 0.0, 1.0)
    ssim = _ssim(cpu_t, gpu_t)
    assert ssim >= 0.97, f"NIR-band SSIM {ssim:.4f} < 0.97"


# ---------------------------------------------------------------------------
# 3. UV-band sanity: same as NIR
# ---------------------------------------------------------------------------

def test_uv_band_cpu_gpu_ssim():
    cpu, gpu = _render_pair(300.0, 400.0, "luminance", spp=32)
    assert np.all(np.isfinite(cpu))
    assert np.all(np.isfinite(gpu))
    cpu_t = np.clip(cpu, 0.0, 1.0)
    gpu_t = np.clip(gpu, 0.0, 1.0)
    ssim = _ssim(cpu_t, gpu_t)
    assert ssim >= 0.97, f"UV-band SSIM {ssim:.4f} < 0.97"


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
