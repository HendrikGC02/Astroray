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
    expected_supported = {"path_tracer", "ambient_occlusion"}
    expected_unsupported = {
        "caustic_path_tracer",
        "multiwavelength_path_tracer",
        "neural-cache",
        "restir-di",
    }

    assert expected_supported <= names
    assert expected_unsupported <= names

    supported = {
        name for name in names
        if astroray.integrator_capabilities(name)["gpuSupported"]
    }
    assert expected_supported <= supported
    assert not (expected_unsupported & supported)


def test_multiwavelength_integrator_reports_cpu_only_reason():
    caps = astroray.integrator_capabilities("multiwavelength_path_tracer")
    assert caps["gpuSupported"] is False
    assert "multi-wavelength" in caps["gpuFallbackReason"]
