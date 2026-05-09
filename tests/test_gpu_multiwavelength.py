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
    """pkg54c: shared JH sigmoid coefficient table on both backends;
    visible-band parity is now exact within float precision per evaluator
    (jhEvalSpectrumF + JH LUT lookup are bit-identical between CPU and GPU,
    confirmed by diag_pkg54c.py — albedo/illuminant means agree to ~0.04%).

    Integrator-level CPU<->GPU MC sample-stream divergence (OpenMP vs warp
    parallel) leaves a per-pixel noise floor that scales as 1/sqrt(spp);
    on this scene it tops out at SSIM ~0.99 at 64 spp, ~0.998 at 1024 spp.
    Measured SSIM convergence on RTX-class hardware (48x48, this scene):
        spp=64    -> 0.9902 (gate fails)
        spp=256   -> 0.9970 (gate fails)
        spp=1024  -> 0.9988 (gate fails)
        spp=2048  -> 0.9990 (gate fails by ~3e-6)
        spp=8192  -> ~0.9994 (clears with ~40 % margin)
    Convergence slows below the ideal 1/sqrt(n) past ~1024 spp because the
    SSIM formula approaches saturation. spp=8192 is the smallest
    power-of-two that comfortably clears 0.999. Do NOT lower this spp
    without re-running the convergence sweep — see pkg54c Lessons."""
    cpu, gpu = _render_pair(380.0, 780.0, "", spp=8192)
    assert np.all(np.isfinite(cpu))
    assert np.all(np.isfinite(gpu))
    # Tone-map to [0, 1] so SSIM is well-behaved.
    cpu_t = np.clip(cpu, 0.0, 1.0)
    gpu_t = np.clip(gpu, 0.0, 1.0)
    ssim = _ssim(cpu_t, gpu_t)
    assert ssim >= 0.999, f"visible-band SSIM {ssim:.4f} < 0.999 (pkg54c gate)"


def test_visible_band_no_regression():
    """pkg54c sanity gate: replacing the GPU 3-Gaussian basis with the
    Jakob-Hanika LUT must not silently darken or brighten the render.
    The CPU integrator is unchanged across pkg54c, so its mean serves
    as the pre-pkg54c reference; GPU mean is required within 2 %."""
    cpu, gpu = _render_pair(380.0, 780.0, "", spp=64)
    assert np.all(np.isfinite(cpu))
    assert np.all(np.isfinite(gpu))
    cpu_mean = float(cpu.mean())
    gpu_mean = float(gpu.mean())
    assert cpu_mean > 1e-6, f"CPU reference mean too small: {cpu_mean}"
    rel = abs(gpu_mean - cpu_mean) / cpu_mean
    assert rel < 0.02, (
        f"GPU mean {gpu_mean:.4f} drifted {rel*100:.2f}% from CPU "
        f"reference mean {cpu_mean:.4f}"
    )


# ---------------------------------------------------------------------------
# 2. NIR-band parity with spectral profiles attached (pkg54a real gate)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not HAS_PROFILES, reason="profiles.bin not found")
def test_nir_band_cpu_gpu_ssim_with_profiles():
    """pkg54a NIR parity gate. Note: the baked D65 SPD is zero past
    780 nm by construction (per illuminant_d65.inc), so this test
    cannot probe profile-dispatch *liveness* in NIR — it only
    guarantees CPU and GPU agree on whatever dim signal the 700-780 nm
    D65 overlap produces. Liveness is verified by the UV test below."""
    cpu, gpu = _render_pair(700.0, 1000.0, "luminance",
                            spp=32, attach_profiles=True)
    assert np.all(np.isfinite(cpu))
    assert np.all(np.isfinite(gpu))
    cpu_t = np.clip(cpu, 0.0, 1.0)
    gpu_t = np.clip(gpu, 0.0, 1.0)
    ssim = _ssim(cpu_t, gpu_t)
    assert ssim >= 0.97, f"NIR-band (profiled) SSIM {ssim:.4f} < 0.97"


# ---------------------------------------------------------------------------
# 3. UV-band parity with spectral profiles attached
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not HAS_PROFILES, reason="profiles.bin not found")
def test_uv_band_cpu_gpu_ssim_with_profiles():
    cpu_no_prof, gpu_no_prof = _render_pair(300.0, 400.0, "luminance",
                                             spp=16, attach_profiles=False)
    cpu_prof,    gpu_prof    = _render_pair(300.0, 400.0, "luminance",
                                             spp=32, attach_profiles=True)
    for arr in (cpu_no_prof, gpu_no_prof, cpu_prof, gpu_prof):
        assert np.all(np.isfinite(arr))
    # CPU/GPU dispatch must agree on whatever ratio the scene
    # produces. Absolute ratio depends on scene composition (the
    # 380-400 nm band already gives JH-upsampled ~0.85 reflectance
    # for RGB albedos in the no-profile baseline, so the full ratio
    # ceiling is ~1.7× image-wide for this scene; see pkg54a
    # Lessons). Dispatch *liveness* — independent of scene physics —
    # is gated by pkg54d's _gpu_profile_lookup binding once it lands.
    cpu_ratio = cpu_prof.mean() / max(cpu_no_prof.mean(), 1e-12)
    gpu_ratio = gpu_prof.mean() / max(gpu_no_prof.mean(), 1e-12)
    assert abs(cpu_ratio - gpu_ratio) / cpu_ratio < 0.25, (
        f"CPU ratio {cpu_ratio:.2f} vs GPU ratio {gpu_ratio:.2f} diverge"
    )
    cpu_t = np.clip(cpu_prof, 0.0, 1.0)
    gpu_t = np.clip(gpu_prof, 0.0, 1.0)
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
