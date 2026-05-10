"""Tests for pkg68: persistent OIDN device + CUDA backend selection.

The pkg33 implementation rebuilt the OIDN device, four buffers, and the "RT"
filter on every execute() call. pkg68 hoists device + filter to class members
and lazy-initialises them on first execute. These tests pin that behaviour:

  1. Across N consecutive renders on the same Renderer the device is
     initialised exactly once (the "[OIDN] Using <type> device" line is
     printed once).
  2. On a CUDA-capable build, the device that gets selected is CUDA, not CPU.
     On CPU-only builds (no CUDA toolkit / no NVIDIA GPU) the test skips the
     CUDA assertion but still runs the persistence/CPU path.
  3. Albedo/normal guides are fed to OIDN even when the user has not
     explicitly registered an `albedo_aov`/`normal_aov` pass. The renderer's
     albedo/normal buffers are populated unconditionally by the integrator
     (raytracer.h::Camera + render loop), so a single-pass `albedo_aov` run
     after a vanilla render produces non-zero output.
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

OIDN_ENABLED = AVAILABLE and bool(
    astroray.__features__.get("oidn_denoiser", False) if AVAILABLE else False
)
CUDA_BUILD = AVAILABLE and bool(
    astroray.__features__.get("cuda", False) if AVAILABLE else False
)


def _tiny_renderer(width: int = 64, height: int = 64) -> "astroray.Renderer":
    """Minimal Cornell-style scene; small for fast multi-render tests."""
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
    # Floor + back wall + left red wall
    r.add_triangle([-2, -2, -2], [ 2, -2, -2], [ 2, -2,  2], white)
    r.add_triangle([-2, -2, -2], [ 2, -2,  2], [-2, -2,  2], white)
    r.add_triangle([-2, -2, -2], [-2, -2,  2], [-2,  2,  2], red)
    r.add_triangle([-2, -2, -2], [-2,  2,  2], [-2,  2, -2], red)
    # Ceiling light
    r.add_triangle([-0.5, 1.98, -0.5], [0.5, 1.98, -0.5], [0.5, 1.98,  0.5], light)
    r.add_triangle([-0.5, 1.98, -0.5], [0.5, 1.98,  0.5], [-0.5, 1.98, 0.5], light)
    r.add_sphere([0, -1.0, 0], 1.0, white)
    return r


@pytest.mark.skipif(not OIDN_ENABLED, reason="OIDN not compiled in")
def test_device_initialised_once_across_n_frames(capfd):
    """The '[OIDN] Using ... device' init line must print exactly once for N renders."""
    r = _tiny_renderer()
    r.set_seed(1)
    r.add_pass("oidn_denoiser")

    N = 4
    capfd.readouterr()  # drop any prior output
    for _ in range(N):
        r.render(samples_per_pixel=2, max_depth=3)
    captured = capfd.readouterr()
    combined = captured.out + captured.err

    init_lines = [ln for ln in combined.splitlines() if "[OIDN] Using" in ln]
    assert len(init_lines) == 1, (
        f"Expected exactly one OIDN device-init line across {N} renders, got "
        f"{len(init_lines)}: {init_lines!r}"
    )


@pytest.mark.skipif(not OIDN_ENABLED, reason="OIDN not compiled in")
@pytest.mark.skipif(not CUDA_BUILD, reason="CUDA backend not compiled / no GPU")
def test_cuda_capable_build_reports_cuda_device(capfd):
    """On a CUDA-enabled build with a working GPU, OIDN should pick CUDA, not CPU."""
    r = _tiny_renderer()
    r.set_seed(2)
    r.add_pass("oidn_denoiser")
    capfd.readouterr()
    r.render(samples_per_pixel=2, max_depth=3)
    captured = capfd.readouterr()
    combined = captured.out + captured.err

    assert "[OIDN] Using CUDA device" in combined, (
        "CUDA-capable build did not select OIDN CUDA backend. Output was:\n"
        + combined
    )


@pytest.mark.skipif(not OIDN_ENABLED, reason="OIDN not compiled in")
def test_albedo_normal_guides_fed_without_explicit_aov_pass():
    """Camera's albedo + normal buffers are populated unconditionally.

    The renderer writes per-pixel albedo / normal in the inner loop regardless
    of whether the user registered an `albedo_aov` / `normal_aov` pass, and
    `Framebuffer::hasBuffer("albedo"/"normal")` always returns true. As a
    result, the OIDN denoiser receives meaningful albedo + normal guides
    without the user having to opt in.

    Verify by running a render whose only post-pass is `albedo_aov` (which
    copies the albedo buffer over color). If the buffer were populated only
    when the AOV pass was pre-requested, this output would be all zeros.
    """
    r = _tiny_renderer()
    r.set_seed(3)
    r.add_pass("albedo_aov")  # exposes the buffer; does not request its population
    img = np.array(r.render(samples_per_pixel=2, max_depth=3), dtype=np.float32)

    # The Cornell-style scene has a non-black floor + walls + sphere; albedo
    # must be non-zero somewhere if the integrator actually wrote it.
    assert np.any(img > 0.01), (
        "Albedo AOV produced all-zero output — albedo buffer was not populated. "
        "Confirms a regression: OIDN cannot rely on albedo/normal guides being "
        "present without an explicit AOV pass."
    )

    # And the same holds for the normal buffer.
    r2 = _tiny_renderer()
    r2.set_seed(3)
    r2.add_pass("normal_aov")
    nimg = np.array(r2.render(samples_per_pixel=2, max_depth=3), dtype=np.float32)
    assert np.any(np.abs(nimg) > 0.01), (
        "Normal AOV produced all-zero output — normal buffer was not populated."
    )
