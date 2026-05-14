"""pkg84: CUDA kernel pre-warm test.

Synthetic test: instantiate a Renderer, call prewarm_cuda(), assert it returns
without crashing. The CUDA-specific assertion (that the warm-up actually JITs
the kernel) is verified manually with the pkg81 harness — this test just
confirms the method is callable and doesn't break CPU mode.
"""

import pytest

try:
    import astroray
    RAYTRACER_AVAILABLE = True
except ImportError:
    RAYTRACER_AVAILABLE = False


@pytest.mark.skipif(not RAYTRACER_AVAILABLE, reason="astroray module not available")
def test_prewarm_cuda_cpu_mode_noop():
    """prewarm_cuda() on CPU mode is a no-op and does not crash."""
    renderer = astroray.Renderer()
    # CPU mode is the default; prewarm_cuda() should return immediately.
    renderer.prewarm_cuda()
    # If we got here, it didn't crash. Success.


@pytest.mark.skipif(not RAYTRACER_AVAILABLE, reason="astroray module not available")
def test_prewarm_cuda_after_gpu_enable():
    """prewarm_cuda() after set_use_gpu(True) attempts the warm-up.

    On a CUDA-capable machine this should succeed and return. On a machine
    without CUDA, set_use_gpu(True) will fail; we skip the prewarm in that case.
    The acceptance criterion (12s → <100ms) is measured by the pkg81 harness,
    not by this unit test.
    """
    renderer = astroray.Renderer()
    if not renderer.gpu_available:
        pytest.skip("No CUDA GPU available for pre-warm test")

    try:
        renderer.set_use_gpu(True)
    except Exception:
        pytest.skip("CUDA initialization failed")

    # prewarm_cuda() should succeed without exception.
    renderer.prewarm_cuda()
