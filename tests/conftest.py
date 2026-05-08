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
