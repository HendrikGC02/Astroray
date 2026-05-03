#!/usr/bin/env python
"""Shared test-time runtime/bootstrap helpers."""

from __future__ import annotations

import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BUILD_DIR = PROJECT_ROOT / "build"


def candidate_build_dirs() -> list[str]:
    candidates: list[Path] = []
    env_dir = os.environ.get("ASTRORAY_BUILD_DIR")
    if env_dir:
        candidates.append(Path(env_dir))
        candidates.append(Path(env_dir) / "Release")
    candidates.extend([DEFAULT_BUILD_DIR, DEFAULT_BUILD_DIR / "Release"])

    seen: set[str] = set()
    existing: list[str] = []
    for candidate in candidates:
        normalized = os.path.normcase(str(candidate.resolve()).rstrip(os.sep))
        if normalized in seen:
            continue
        seen.add(normalized)
        if candidate.is_dir():
            existing.append(str(candidate))
    return existing


def candidate_mingw_dirs(build_dirs: list[str]) -> list[str]:
    candidates: list[str] = []
    env_dir = os.environ.get("MINGW_BIN_DIR")
    if env_dir:
        candidates.append(env_dir)

    for build_dir in build_dirs:
        cache_path = Path(build_dir) / "CMakeCache.txt"
        if not cache_path.exists() and Path(build_dir).name.lower() == "release":
            cache_path = Path(build_dir).parent / "CMakeCache.txt"
        if not cache_path.exists():
            continue

        for line in cache_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            prefix = "CMAKE_CXX_COMPILER:FILEPATH="
            if line.startswith(prefix):
                compiler = Path(line[len(prefix):].strip())
                if compiler.is_absolute() and compiler.parent:
                    candidates.append(str(compiler.parent))
                break

    candidates.extend([
        r"C:\Program Files\mingw64\bin",
        r"C:\msys64\mingw64\bin",
        r"C:\msys64\ucrt64\bin",
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


def candidate_cuda_dirs(build_dirs: list[str]) -> list[str]:
    candidates: list[str] = []
    env_dir = os.environ.get("CUDA_BIN_DIR")
    if env_dir:
        candidates.append(env_dir)

    for build_dir in build_dirs:
        cache_path = Path(build_dir) / "CMakeCache.txt"
        if not cache_path.exists() and Path(build_dir).name.lower() == "release":
            cache_path = Path(build_dir).parent / "CMakeCache.txt"
        if not cache_path.exists():
            continue

        for line in cache_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            prefix = "CMAKE_CUDA_COMPILER:FILEPATH="
            if line.startswith(prefix):
                compiler = Path(line[len(prefix):].strip())
                if compiler.is_absolute() and compiler.parent:
                    candidates.append(str(compiler.parent))
                break

    candidates.extend([
        r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.2\bin",
        r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8\bin",
        r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.6\bin",
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


def configure_test_imports(include_blender_addon: bool = False) -> str:
    build_dirs = candidate_build_dirs()

    for build_dir in reversed(build_dirs):
        if build_dir not in sys.path:
            sys.path.insert(0, build_dir)

    project_root = str(PROJECT_ROOT)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    if include_blender_addon:
        addon_dir = str(PROJECT_ROOT / "blender_addon")
        if addon_dir not in sys.path:
            sys.path.insert(0, addon_dir)

    if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
        for dll_dir in candidate_mingw_dirs(build_dirs):
            os.add_dll_directory(dll_dir)
        for dll_dir in candidate_cuda_dirs(build_dirs):
            os.add_dll_directory(dll_dir)
        for build_dir in build_dirs:
            os.add_dll_directory(os.path.abspath(build_dir))
        oidn_dir = os.environ.get("OIDN_BIN_DIR", r"C:\oidn\bin")
        if os.path.isdir(oidn_dir):
            os.add_dll_directory(oidn_dir)

    return build_dirs[0] if build_dirs else str(DEFAULT_BUILD_DIR)
