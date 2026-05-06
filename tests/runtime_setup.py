#!/usr/bin/env python
"""Shared test-time runtime/bootstrap helpers."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BUILD_DIR = PROJECT_ROOT / "build"
DEFAULT_TCNN_BUILD_DIR = PROJECT_ROOT / "build_tcnn"
TEST_RESULTS_DIR = PROJECT_ROOT / "test_results"
DEFAULT_TEMP_DIR = TEST_RESULTS_DIR / "tmp"


def _unique_existing(paths: list[Path]) -> list[str]:
    seen: set[str] = set()
    existing: list[str] = []
    for path in paths:
        normalized = os.path.normcase(str(path.resolve()).rstrip(os.sep))
        if normalized in seen:
            continue
        seen.add(normalized)
        if path.is_dir():
            existing.append(str(path))
    return existing


def configure_test_temp_dir() -> str:
    """Keep pytest/tempfile scratch data inside the repo by default.

    Windows + OneDrive + pytest's default AppData temp roots can create
    frustrating permission/cleanup failures. Tests may still override this with
    ASTRORAY_TEST_TEMP_DIR, TMP, or TEMP when needed.
    """
    preferred = os.environ.get("ASTRORAY_TEST_TEMP_DIR")
    temp_dir = Path(preferred) if preferred else DEFAULT_TEMP_DIR
    temp_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("TMP", str(temp_dir))
    os.environ.setdefault("TEMP", str(temp_dir))
    tempfile.tempdir = os.environ.get("TMP", str(temp_dir))
    return tempfile.tempdir or str(temp_dir)


def candidate_build_dirs() -> list[str]:
    candidates: list[Path] = []
    env_dir = os.environ.get("ASTRORAY_BUILD_DIR")
    if env_dir:
        candidates.append(Path(env_dir))
        candidates.append(Path(env_dir) / "Release")
        candidates.append(Path(env_dir) / "Debug")
        candidates.append(Path(env_dir) / "RelWithDebInfo")

    candidates.extend([
        DEFAULT_TCNN_BUILD_DIR,
        DEFAULT_TCNN_BUILD_DIR / "Release",
        DEFAULT_TCNN_BUILD_DIR / "Debug",
        DEFAULT_TCNN_BUILD_DIR / "RelWithDebInfo",
        DEFAULT_BUILD_DIR,
        DEFAULT_BUILD_DIR / "Release",
        DEFAULT_BUILD_DIR / "Debug",
        DEFAULT_BUILD_DIR / "RelWithDebInfo",
    ])

    return _unique_existing(candidates)


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
        r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.9\bin",
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


def candidate_oidn_dirs(build_dirs: list[str]) -> list[str]:
    candidates: list[Path] = []
    env_dir = os.environ.get("OIDN_BIN_DIR")
    if env_dir:
        candidates.append(Path(env_dir))
    oidn_root = os.environ.get("OIDN_DIR")
    if oidn_root:
        candidates.append(Path(oidn_root) / "bin")

    for build_dir in build_dirs:
        root = Path(build_dir)
        cache_path = root / "CMakeCache.txt"
        if not cache_path.exists() and root.name.lower() in {"release", "debug", "relwithdebinfo"}:
            cache_path = root.parent / "CMakeCache.txt"
        if cache_path.exists():
            for line in cache_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith("oidn_prebuilt_SOURCE_DIR:"):
                    source_dir = Path(line.split("=", 1)[1].strip())
                    candidates.append(source_dir / "bin")
                    break

        candidates.extend([
            root / "_deps" / "oidn_prebuilt-src" / "bin",
            root.parent / "_deps" / "oidn_prebuilt-src" / "bin",
        ])

    candidates.extend([
        Path(r"C:\oidn\bin"),
        Path(r"C:\Program Files\Intel\OpenImageDenoise\bin"),
        Path(r"C:\Program Files\OpenImageDenoise\bin"),
    ])

    return _unique_existing(candidates)


def build_runtime_dirs(build_dirs: list[str]) -> list[str]:
    candidates: list[Path] = []
    for build_dir in build_dirs:
        root = Path(build_dir)
        candidates.extend([
            root,
            root / "bin",
            root / "bin" / "Release",
            root / "bin" / "Debug",
            root / "bin" / "RelWithDebInfo",
        ])
        if root.name.lower() in {"release", "debug", "relwithdebinfo"}:
            candidates.extend([
                root.parent / "bin" / root.name,
                root.parent / "bin",
            ])
    return _unique_existing(candidates)


def _prepend_path(dirs: list[str]) -> None:
    current = os.environ.get("PATH", "")
    entries = current.split(os.pathsep) if current else []
    normalized_entries = {
        os.path.normcase(os.path.abspath(entry).rstrip(os.sep))
        for entry in entries
        if entry
    }
    additions = [
        path for path in dirs
        if os.path.normcase(os.path.abspath(path).rstrip(os.sep)) not in normalized_entries
    ]
    if additions:
        os.environ["PATH"] = os.pathsep.join(additions + entries)


def configure_test_imports(include_blender_addon: bool = False) -> str:
    configure_test_temp_dir()
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
        runtime_dirs = (
            build_runtime_dirs(build_dirs)
            + candidate_mingw_dirs(build_dirs)
            + candidate_cuda_dirs(build_dirs)
            + candidate_oidn_dirs(build_dirs)
        )
        for dll_dir in runtime_dirs:
            os.add_dll_directory(dll_dir)
        _prepend_path(runtime_dirs)

    return build_dirs[0] if build_dirs else str(DEFAULT_BUILD_DIR)


def find_standalone_executable(build_dir: str | None = None) -> str | None:
    build_dirs = [build_dir] if build_dir else candidate_build_dirs()
    candidates: list[Path] = []
    for candidate in build_dirs:
        root = Path(candidate)
        candidates.extend([
            root / "bin" / "raytracer",
            root / "bin" / "raytracer.exe",
            root / "bin" / "Release" / "raytracer.exe",
            root / "bin" / "Debug" / "raytracer.exe",
            root / "bin" / "RelWithDebInfo" / "raytracer.exe",
        ])
        if root.name.lower() in {"release", "debug", "relwithdebinfo"}:
            candidates.append(root.parent / "bin" / root.name / "raytracer.exe")

    candidates.extend([
        PROJECT_ROOT / "bin" / "raytracer",
        PROJECT_ROOT / "bin" / "raytracer.exe",
    ])

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None
