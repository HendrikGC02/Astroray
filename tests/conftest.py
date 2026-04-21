#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Pytest configuration for Astroray tests.
Provides cross-platform path setup for finding the built module.
"""

import pytest
import os
import sys

# Add build directory and project root to path for cross-platform support
# This handles both Windows (.pyd) and Linux (.so) module suffixes
BUILD_DIR = os.path.join(os.path.dirname(__file__), '..', 'build')
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BUILD_DIR)
sys.path.insert(0, TESTS_DIR)
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# On Windows, add runtime DLL directories so the MSVC-built .pyd and its
# dependencies (OIDN, CUDA, MinGW runtimes) can be found.
if sys.platform == 'win32' and hasattr(os, 'add_dll_directory'):
    _mingw_bin = os.environ.get('MINGW_BIN_DIR', r'C:\Program Files\mingw64\bin')
    if os.path.isdir(_mingw_bin):
        os.add_dll_directory(_mingw_bin)
    # msys2 ucrt64 toolchain (libgomp-1.dll etc.)
    _ucrt64_bin = r'C:\msys64\ucrt64\bin'
    if os.path.isdir(_ucrt64_bin):
        os.add_dll_directory(_ucrt64_bin)
    os.add_dll_directory(os.path.abspath(BUILD_DIR))
    # OIDN runtime DLLs (OpenImageDenoise.dll etc.)
    _oidn_bin = os.environ.get('OIDN_BIN_DIR', r'C:\oidn\bin')
    if os.path.isdir(_oidn_bin):
        os.add_dll_directory(_oidn_bin)


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
    possible_paths = [
        os.path.join(BUILD_DIR, 'bin', 'raytracer'),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'bin', 'raytracer'),
        'raytracer',
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            return path
    
    pytest.skip("raytracer executable not found")
