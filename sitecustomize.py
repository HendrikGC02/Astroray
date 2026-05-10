"""Process-wide Astroray runtime bootstrap.

Python imports ``sitecustomize`` automatically during interpreter startup when
this repository or a copied build directory is on ``sys.path``. On Windows this
lets the compiled ``astroray`` extension find optional runtime DLLs before the
extension loader resolves transitive dependencies.
"""

from __future__ import annotations

import os
import sys

_DLL_DIRECTORY_HANDLES = []


def _candidate_oidn_bins() -> list[str]:
    candidates: list[str] = []
    for env_var in ("OIDN_ROOT", "ASTRORAY_OIDN_DIR"):
        root = os.environ.get(env_var)
        if root:
            candidates.append(os.path.join(root, "bin"))

    candidates.extend([
        r"C:\oidn\bin",
        r"C:\Program Files\Intel\oidn\bin",
        r"C:\Program Files\Intel\OpenImageDenoise\bin",
        r"C:\Program Files\OpenImageDenoise\bin",
    ])
    return candidates


def _candidate_cuda_bins() -> list[str]:
    candidates: list[str] = []
    cuda_path = os.environ.get("CUDA_PATH")
    if cuda_path:
        candidates.append(os.path.join(cuda_path, "bin"))
    candidates.extend([
        r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.2\bin",
        r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.9\bin",
        r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8\bin",
        r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.6\bin",
    ])
    return candidates


if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
    _path_additions: list[str] = []
    for _dll_dir in _candidate_oidn_bins() + _candidate_cuda_bins():
        if os.path.isdir(_dll_dir):
            try:
                _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(_dll_dir))
                _path_additions.append(_dll_dir)
            except (FileNotFoundError, OSError):
                pass
    if _path_additions:
        _current_path = os.environ.get("PATH", "")
        os.environ["PATH"] = os.pathsep.join(_path_additions + [_current_path])
