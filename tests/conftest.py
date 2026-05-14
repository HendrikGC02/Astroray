#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Pytest configuration for Astroray tests.
Provides cross-platform path setup for finding the built module.
"""

import pytest
import os
import sys

# Add tests/ to sys.path BEFORE importing runtime_setup — when pytest is
# invoked as `python -m pytest tests/` from the repo root (CI), tests/ is
# not automatically on sys.path. Importing runtime_setup before this would
# fail with ModuleNotFoundError.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS_DIR)
sys.path.append(PROJECT_ROOT)

from runtime_setup import (
    configure_test_imports,
    configure_test_temp_dir,
    find_standalone_executable,
)

configure_test_temp_dir()
BUILD_DIR = configure_test_imports()


@pytest.fixture(scope="session")
def test_results_dir():
    """Path to the test results directory"""
    test_dir = os.path.dirname(os.path.abspath(__file__))
    results_dir = os.path.join(test_dir, '..', 'test_results')
    os.makedirs(results_dir, exist_ok=True)
    return results_dir


@pytest.fixture(scope="session")
def astroray_module():
    """Import the astroray Python module (cross-platform)"""
    try:
        import astroray
        return astroray
    except ImportError as e:
        pytest.skip(f"astroray module not available: {e}")


@pytest.fixture(scope="session")
def standalone_executable():
    """Get path to the standalone raytracer executable (cross-platform)"""
    path = find_standalone_executable(BUILD_DIR)
    if path:
        return path
    pytest.skip("raytracer executable not found")


@pytest.fixture(autouse=True)
def cuda_cleanup_and_error_check():
    """pkg85: Force Python GC and check for latent CUDA errors after each test.

    The root cause: Python's garbage collector doesn't run immediately after
    a test function ends, so Renderer objects with GPU state (CUDARenderer)
    can accumulate across tests. Explicit gc.collect() forces cleanup.

    When a CUDA operation fails but the error isn't checked immediately,
    the error persists and contaminates the next CUDA call. This fixture
    first forces GC to clean up all pending renderers, then synchronizes
    the device and checks for latent errors.
    """
    yield  # Let the test run

    import gc
    import warnings

    # Wrap entire cleanup to prevent non-test-failure exceptions from
    # surfacing as teardown ERROR. Intentional pytest.fail() is NOT caught
    # (it raises BaseException), so legitimate CUDA regression guards still
    # fail the test properly.
    try:
        gc.collect()  # pkg85: Force cleanup of any Renderer objects left by the test

        try:
            import astroray
            # Only check if astroray module loaded successfully
            try:
                renderer = astroray.Renderer()
                if renderer.gpu_available:
                    # Import ctypes to call CUDA runtime directly
                    import ctypes
                    try:
                        # Try to load CUDA runtime DLL
                        cuda = ctypes.CDLL("cudart64_12.dll") if sys.platform == "win32" else ctypes.CDLL("libcudart.so")
                        # cudaDeviceSynchronize() and cudaGetLastError()
                        sync_err = cuda.cudaDeviceSynchronize()
                        last_err = cuda.cudaGetLastError()
                        if sync_err != 0 or last_err != 0:
                            # Get error string
                            cuda.cudaGetErrorString.restype = ctypes.c_char_p
                            sync_msg = cuda.cudaGetErrorString(sync_err).decode() if sync_err != 0 else ""
                            last_msg = cuda.cudaGetErrorString(last_err).decode() if last_err != 0 else ""
                            # pkg85-B: this is now a permanent regression guard,
                            # not a diagnostic. Any latent CUDA error after a
                            # test indicates a missing CUDA_CHECK or a real
                            # GPU-side bug; fail loudly at the boundary so the
                            # culprit test is the one blamed, not whichever
                            # test happens to make the next CUDA call.
                            pytest.fail(f"Latent CUDA error after test: sync={sync_err} ({sync_msg}), last={last_err} ({last_msg})")
                    except (OSError, AttributeError):
                        pass  # CUDA runtime not available, skip check
            except Exception as e:
                # Renderer construction failed; log for diagnostic but don't fail
                warnings.warn(f"cuda_cleanup_and_error_check: Renderer construction failed: {type(e).__name__}: {e}", stacklevel=2)
        except ImportError:
            pass  # astroray not available, skip check
    except Exception as e:
        # Catch any other unexpected cleanup exception and warn instead of ERROR
        warnings.warn(f"cuda_cleanup_and_error_check: cleanup exception: {type(e).__name__}: {e}", stacklevel=2)
