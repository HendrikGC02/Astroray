"""pkg53 integrator GPU capability diagnostics."""

import pytest

from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray module not available")


def test_every_registered_integrator_reports_gpu_capabilities():
    names = astroray.integrator_registry_names()
    assert names, "integrator registry should not be empty"

    for name in names:
        caps = astroray.integrator_capabilities(name)
        assert set(caps) == {"gpuSupported", "gpuFallbackReason"}
        assert isinstance(caps["gpuSupported"], bool)
        assert isinstance(caps["gpuFallbackReason"], str)
        if not caps["gpuSupported"]:
            assert caps["gpuFallbackReason"], f"{name} must explain CPU fallback"


def test_integrator_gpu_support_matrix_matches_current_cuda_kernels():
    names = set(astroray.integrator_registry_names())
    # pkg54: multiwavelength_path_tracer flipped to gpuSupported=True.
    # pkg55-C6b: restir-di flipped to gpuSupported=True — it now has a GPU
    # wavefront kernel (src/gpu/wavefront/stage_restir.cu, dispatched via
    # cuda_wavefront_render_restir). The original assertion (restir-di CPU-only,
    # "stores CPU frame history and has no CUDA kernel") is superseded by the
    # C6 ReSTIR SoA port; the CPU frame history now lives in device SoA.
    expected_supported = {"path_tracer", "ambient_occlusion",
                          "multiwavelength_path_tracer", "restir-di"}
    # pkg171: the CPU-only set is the enumeration the GPU-dispatch guard trusts
    # (capabilities().gpuSupported == false). Requesting any of these on a GPU
    # device would otherwise render silently near-black (#540: light_tracer_caustic
    # peak 0.019 vs CPU 0.500); the guard in module/blender_module.cpp render()
    # raises instead. Pin the full CPU-only list so a future GPU port must flip
    # both the integrator's capabilities() AND this expectation deliberately.
    expected_unsupported = {
        "caustic_path_tracer",
        "neural-cache",
        "light_tracer_caustic",
        "sms_caustic_path_tracer",
    }

    assert expected_supported <= names
    assert expected_unsupported <= names

    supported = {
        name for name in names
        if astroray.integrator_capabilities(name)["gpuSupported"]
    }
    assert expected_supported <= supported
    assert not (expected_unsupported & supported)


def test_multiwavelength_integrator_reports_gpu_supported():
    """pkg54: multiwavelength_path_tracer now has a CUDA megakernel."""
    caps = astroray.integrator_capabilities("multiwavelength_path_tracer")
    assert caps["gpuSupported"] is True
