#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Pytest configuration for Astroray tests.
Provides cross-platform path setup for finding the built module.
"""

import pytest
import os
import sys
from pathlib import Path

# Add build directory and project root to path for cross-platform support.
# Windows builds often place the module in build/Release, while local debug
# sessions may use an override build directory.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_BUILD_DIR = os.path.join(PROJECT_ROOT, 'build')
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS_DIR)
sys.path.append(PROJECT_ROOT)


def _candidate_build_dirs() -> list[str]:
    candidates: list[str] = []
    env_dir = os.environ.get('ASTRORAY_BUILD_DIR')
    if env_dir:
        candidates.append(env_dir)

    candidates.extend([
        DEFAULT_BUILD_DIR,
        os.path.join(DEFAULT_BUILD_DIR, 'Release'),
        os.path.join(PROJECT_ROOT, 'build_tcnn'),
        os.path.join(PROJECT_ROOT, 'build_tcnn', 'Release'),
    ])

    seen: set[str] = set()
    existing: list[str] = []
    for candidate in candidates:
        normalized = os.path.normcase(os.path.abspath(candidate).rstrip(os.sep))
        if normalized in seen:
            continue
        seen.add(normalized)
        if os.path.isdir(candidate):
            existing.append(candidate)
    return existing


BUILD_DIR_CANDIDATES = _candidate_build_dirs()
for _build_dir in reversed(BUILD_DIR_CANDIDATES):
    sys.path.insert(0, _build_dir)
BUILD_DIR = BUILD_DIR_CANDIDATES[0] if BUILD_DIR_CANDIDATES else DEFAULT_BUILD_DIR


def _candidate_mingw_dirs() -> list[str]:
    candidates: list[str] = []
    env_dir = os.environ.get('MINGW_BIN_DIR')
    if env_dir:
        candidates.append(env_dir)

    for build_dir in BUILD_DIR_CANDIDATES:
        cache_path = Path(build_dir) / 'CMakeCache.txt'
        if not cache_path.exists() and Path(build_dir).name.lower() == 'release':
            cache_path = Path(build_dir).parent / 'CMakeCache.txt'
        if not cache_path.exists():
            continue
        for line in cache_path.read_text(encoding='utf-8', errors='ignore').splitlines():
            prefix = 'CMAKE_CXX_COMPILER:FILEPATH='
            if line.startswith(prefix):
                compiler = Path(line[len(prefix):].strip())
                if compiler.parent:
                    candidates.append(str(compiler.parent))
                break

    candidates.extend([
        r'C:\Program Files\mingw64\bin',
        r'C:\msys64\mingw64\bin',
        r'C:\msys64\ucrt64\bin',
    ])

    seen: set[str] = set()
    unique: list[str] = []
    for candidate in candidates:
        normalized = os.path.normcase(candidate.rstrip(os.sep))
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(candidate)
    return unique

# On Windows, add runtime DLL directories so the MSVC-built .pyd and its
# dependencies (OIDN, CUDA, MinGW runtimes) can be found.
if sys.platform == 'win32' and hasattr(os, 'add_dll_directory'):
    for _mingw_bin in _candidate_mingw_dirs():
        if not os.path.isdir(_mingw_bin):
            continue
        os.add_dll_directory(_mingw_bin)
        # add_dll_directory only affects Python's loader; subprocess-launched
        # binaries (raytracer.exe in test_standalone_renderer.py) use PATH
        # for DLL search. Promote discovered MinGW dirs so the runtime that
        # matches the built .pyd wins over any older Git Bash/MSYS copy.
        _path_entries = os.environ.get('PATH', '').split(os.pathsep)
        normalized = os.path.normcase(_mingw_bin.rstrip(os.sep))
        if not any(os.path.normcase(entry.rstrip(os.sep)) == normalized for entry in _path_entries if entry):
            os.environ['PATH'] = _mingw_bin + os.pathsep + os.environ.get('PATH', '')
    # msys2 ucrt64 toolchain (libgomp-1.dll etc.)
    _ucrt64_bin = r'C:\msys64\ucrt64\bin'
    if os.path.isdir(_ucrt64_bin):
        os.add_dll_directory(_ucrt64_bin)
    for _build_dir in BUILD_DIR_CANDIDATES:
        os.add_dll_directory(os.path.abspath(_build_dir))
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
        os.path.join(BUILD_DIR, 'bin', 'Release', 'raytracer.exe'),
        os.path.join(DEFAULT_BUILD_DIR, 'bin', 'raytracer'),
        os.path.join(DEFAULT_BUILD_DIR, 'bin', 'Release', 'raytracer.exe'),
        os.path.join(PROJECT_ROOT, 'bin', 'raytracer'),
        'raytracer',
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            return path
    
    pytest.skip("raytracer executable not found")
