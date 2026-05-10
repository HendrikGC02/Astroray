"""Tests for pkg70: NVIDIA OptiX AI denoiser backend.

Skips cleanly when the build was compiled without OptiX (the most common
case in CI — OptiX SDK is not bundled), or when no CUDA device is visible
at runtime. When the backend IS available, mirrors the shape of
test_oidn_denoiser_persistence.py: persistent context across N renders,
"[OptiX] Using ..." log line printed exactly once, OptiX denoiser
actually reduces noise on a synthetic noisy image.

OptiX SDK + CUDA hardware verification of these tests is pending — they
are written so a verifier session can run them as-is once the SDK is
installed and CUDA is enabled.
"""
import math
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

OPTIX_BUILD = AVAILABLE and bool(
    astroray.__features__.get("optix_denoiser", False) if AVAILABLE else False
)


def _optix_runtime_available() -> bool:
    if not OPTIX_BUILD:
        return False
    try:
        return bool(astroray.gpu_optix_available())
    except Exception:
        return False


OPTIX_AVAILABLE = _optix_runtime_available()


def _tiny_renderer(width: int = 64, height: int = 64) -> "astroray.Renderer":
    """Minimal Cornell-style scene; small for fast multi-render tests.
    Mirrors test_oidn_denoiser_persistence._tiny_renderer.
    """
    r = astroray.Renderer()
    r.setup_camera(
        look_from=[0, 0, 5.5], look_at=[0, 0, 0], vup=[0, 1, 0],
        vfov=40, aspect_ratio=width / height, aperture=0.0, focus_dist=5.5,
        width=width, height=height,
    )
    r.set_background_color([0.0, 0.0, 0.0])
    white = r.create_material("lambertian", [0.73, 0.73, 0.73], {})
    red   = r.create_material("lambertian", [0.65, 0.05, 0.05], {})
    light = r.create_material("light",      [1.0, 0.9, 0.8],    {"intensity": 15.0})
    r.add_triangle([-2, -2, -2], [ 2, -2, -2], [ 2, -2,  2], white)
    r.add_triangle([-2, -2, -2], [ 2, -2,  2], [-2, -2,  2], white)
    r.add_triangle([-2, -2, -2], [-2, -2,  2], [-2,  2,  2], red)
    r.add_triangle([-2, -2, -2], [-2,  2,  2], [-2,  2, -2], red)
    r.add_triangle([-0.5, 1.98, -0.5], [0.5, 1.98, -0.5], [0.5, 1.98,  0.5], light)
    r.add_triangle([-0.5, 1.98, -0.5], [0.5, 1.98,  0.5], [-0.5, 1.98, 0.5], light)
    r.add_sphere([0, -1.0, 0], 1.0, white)
    return r


@pytest.mark.skipif(not OPTIX_BUILD, reason="OptiX denoiser not compiled in")
def test_optix_pass_registered_when_compiled_in():
    """The plugin must register itself under 'optix_denoiser'."""
    assert "optix_denoiser" in astroray.pass_registry_names()


@pytest.mark.skipif(not OPTIX_BUILD, reason="OptiX denoiser not compiled in")
def test_gpu_optix_available_returns_bool():
    """gpu_optix_available is a cheap probe — must always return a bool,
    never raise, regardless of whether a CUDA device is present.
    """
    assert isinstance(astroray.gpu_optix_available(), bool)


@pytest.mark.skipif(not OPTIX_AVAILABLE, reason="OptiX denoiser unavailable at runtime (SDK or CUDA missing)")
def test_optix_context_initialised_once_across_n_frames(capfd):
    """Persistent context: '[OptiX] Using ...' should print exactly once
    across N renders on the same Renderer (mirrors pkg68 OIDN test)."""
    r = _tiny_renderer()
    r.set_seed(1)
    r.add_pass("optix_denoiser")

    N = 4
    capfd.readouterr()
    for _ in range(N):
        r.render(samples_per_pixel=2, max_depth=3)
    captured = capfd.readouterr()
    combined = captured.out + captured.err

    init_lines = [ln for ln in combined.splitlines() if "[OptiX] Using" in ln]
    assert len(init_lines) == 1, (
        f"Expected exactly one OptiX init line across {N} renders, got "
        f"{len(init_lines)}: {init_lines!r}"
    )


@pytest.mark.skipif(not OPTIX_AVAILABLE, reason="OptiX denoiser unavailable at runtime (SDK or CUDA missing)")
def test_optix_denoise_reduces_noise_on_synthetic_input():
    """End-to-end: render a small Cornell scene at low spp to introduce
    noticeable noise, then assert the OptiX-denoised output has lower
    per-pixel variance than an undenoised reference at the same spp.
    """
    r_ref   = _tiny_renderer()
    r_ref.set_seed(7)
    ref     = np.array(r_ref.render(samples_per_pixel=2, max_depth=3),
                       dtype=np.float32)

    r_dnz = _tiny_renderer()
    r_dnz.set_seed(7)
    r_dnz.add_pass("optix_denoiser")
    dnz   = np.array(r_dnz.render(samples_per_pixel=2, max_depth=3),
                     dtype=np.float32)

    assert np.all(np.isfinite(dnz)), "OptiX output contains non-finite pixels"

    # Local 3x3 variance is the standard noise-floor proxy.
    def local_var(img):
        from numpy.lib.stride_tricks import sliding_window_view
        # Treat each channel independently, then average.
        v_total = 0.0
        for c in range(img.shape[2]):
            w = sliding_window_view(img[..., c], (3, 3))
            v_total += w.var(axis=(-1, -2)).mean()
        return v_total / img.shape[2]

    v_ref = local_var(ref)
    v_dnz = local_var(dnz)
    assert v_dnz < v_ref * 0.5, (
        f"OptiX-denoised noise floor not meaningfully lower than reference: "
        f"ref={v_ref:.6f}, denoised={v_dnz:.6f}"
    )
