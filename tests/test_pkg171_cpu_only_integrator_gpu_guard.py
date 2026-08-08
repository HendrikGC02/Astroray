#!/usr/bin/env python
"""pkg171 — CPU-only integrators must fail LOUDLY on GPU, not render near-black.

The #540 HW verification forced `light_tracer_caustic` (pkg106, CPU-only, no GPU
kernel) onto the GPU and got a near-black frame (peak 0.019 vs CPU 0.500) with NO
error — the raw PyRenderer binding (set_use_gpu + set_integrator + render) bypasses
the Blender addon's Python-layer guard (configure_backend).

The fix is a backstop in module/blender_module.cpp render(): before dispatching to
the wavefront pipeline, it queries the selected integrator's
capabilities().gpuSupported (the same enumeration integrator_capabilities() and the
addon read — no hardcoded name) and raises when it is False.

GPU-gated: the guard only fires inside the `useGPU && cudaRenderer->isAvailable()`
branch, so it needs a real CUDA device. This test skips on CI (no GPU) and is the
one RTX leg /verify runs. The CI-runnable dispatch-logic legs live in
tests/test_blender_backend_policy.py (addon) and tests/test_integrator_capabilities.py
(enumeration).
"""

import pytest
from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray module not available")


def _gpu_renderer():
    r = astroray.Renderer()
    if not bool(astroray.__features__.get("cuda", False)) or not r.gpu_available:
        pytest.skip("No CUDA GPU available — pkg171 guard runs on the RTX box (/verify).")
    try:
        r.set_use_gpu(True)
    except Exception:  # noqa: BLE001 - any CUDA init failure means skip (cf. test_cuda_prewarm)
        pytest.skip("CUDA initialization failed")
    return r


@pytest.mark.parametrize("name", [
    "light_tracer_caustic",
    "caustic_path_tracer",
    "sms_caustic_path_tracer",
    "neural-cache",
])
def test_cpu_only_integrator_on_gpu_raises(name):
    """Every CPU-only integrator (gpuSupported == False) must raise on the raw
    GPU render binding rather than silently rendering near-black."""
    # Only exercise names that really are CPU-only in this build (the enumeration
    # is authoritative — a future GPU port flips capabilities() and this skips).
    if astroray.integrator_capabilities(name)["gpuSupported"]:
        pytest.skip(f"{name} now reports GPU support — no longer a CPU-only guard case")

    r = _gpu_renderer()
    r.setup_camera(
        look_from=[0, 0, 5], look_at=[0, 0, 0], vup=[0, 1, 0], vfov=40,
        aspect_ratio=1.0, aperture=0.0, focus_dist=5.0, width=16, height=16,
    )
    r.set_integrator(name)
    with pytest.raises(RuntimeError) as exc:
        r.render(4, 4)
    msg = str(exc.value)
    assert name in msg, f"error must name the integrator, got: {msg}"
    assert "GPU" in msg


def test_gpu_supported_integrator_still_renders():
    """Guardrail: the default path_tracer (gpuSupported == True) must NOT be
    caught by the pkg171 guard — GPU rendering still works."""
    r = _gpu_renderer()
    r.setup_camera(
        look_from=[0, 0, 5], look_at=[0, 0, 0], vup=[0, 1, 0], vfov=40,
        aspect_ratio=1.0, aperture=0.0, focus_dist=5.0, width=16, height=16,
    )
    r.set_integrator("path_tracer")
    img = r.render(4, 4)  # must not raise
    assert img is not None
