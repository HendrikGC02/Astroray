#!/usr/bin/env python3
"""
Build and package the Astroray Blender addon as an installable .zip.

What it does
============
1. Picks a Python interpreter matching the target Blender's bundled Python
   (auto-detected from the Blender install, or user-supplied via --python-exe).
2. Runs CMake in a dedicated build directory (default: build_blender_addon/)
   pointed at that interpreter, so pybind11 builds the `.pyd` / `.so` against
   the matching C API.
3. Stages everything Blender needs (`__init__.py`, `blender_manifest.toml`,
   the compiled module) into `dist/astroray/`.
4. Zips that directory into `dist/astroray-<version>.zip`, which can be
   installed in Blender via:
       Edit > Preferences > Get Extensions > (dropdown) > Install from Disk...
   or dropped straight into the `extensions/user_default/` directory.

Usage
-----
    python scripts/build_blender_addon.py                          # CPU build (default)
    python scripts/build_blender_addon.py --backend cuda           # CUDA GPU build
    python scripts/build_blender_addon.py --backend tcnn           # CUDA + TinyNN build
    python scripts/build_blender_addon.py --backend auto           # probe nvcc, choose best
    python scripts/build_blender_addon.py --blender "<path>"       # target a specific Blender
    python scripts/build_blender_addon.py --python-exe C:/Python313/python.exe
    python scripts/build_blender_addon.py --install                # also copy into
                                                                   # Blender's extensions dir
    python scripts/build_blender_addon.py --clean                  # wipe build dir first

Backends
--------
    tcnn  — CUDA + tiny-cuda-nn neural cache. Requires NVCC + CUDA toolkit. DEFAULT.
    cuda  — CUDA GPU rendering, no neural cache. Requires NVCC + CUDA toolkit.
    cpu   — CPU-only (CUDA off). Safe on machines without NVIDIA GPU.
    auto  — probe for nvcc; use tcnn if found, otherwise cpu.

Notes
-----
Blender's bundled Python does NOT include development headers on any OS, so
the C++ module cannot be built against it directly. You need a separately
installed Python whose *minor* version matches Blender's bundled Python
(Blender 4.x → 3.11, Blender 5.1 → 3.13). Install via:

    winget install Python.Python.3.13        # Windows
    brew install python@3.13                 # macOS
    sudo apt install python3.13-dev          # Debian/Ubuntu
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import time
import zipfile
from pathlib import Path

REPO_ROOT   = Path(__file__).resolve().parent.parent
ADDON_SRC   = REPO_ROOT / "blender_addon"
DIST_DIR    = REPO_ROOT / "dist"
STAGE_DIR   = DIST_DIR / "astroray"

# BUILD_DIR and cmake flags are set at runtime by _backend_config().
BUILD_DIR: Path = REPO_ROOT / "build_blender_addon"  # overwritten in main()

# Files that belong in the shipped addon (everything else in blender_addon/ is
# ignored — test scenes, backups, __pycache__, ...).
ADDON_FILES = ["__init__.py", "blender_manifest.toml", "shader_blending.py"]


# --------------------------------------------------------------------------- #
# Blender / Python discovery
# --------------------------------------------------------------------------- #

def _candidate_blender_paths() -> list[Path]:
    system = platform.system()
    cands: list[Path] = []
    if system == "Windows":
        base = Path("C:/Program Files/Blender Foundation")
        if base.exists():
            cands += sorted(base.glob("Blender */blender.exe"), reverse=True)
    elif system == "Darwin":
        for p in ["/Applications/Blender.app/Contents/MacOS/Blender"]:
            cands.append(Path(p))
    else:  # Linux
        for p in ["/usr/bin/blender", "/usr/local/bin/blender",
                  "/snap/bin/blender"]:
            cands.append(Path(p))
    return [p for p in cands if p.exists()]


def find_blender(explicit: str | None) -> Path | None:
    if explicit:
        p = Path(explicit).expanduser()
        if not p.exists():
            sys.exit(f"error: --blender path does not exist: {p}")
        return p
    cands = _candidate_blender_paths()
    if not cands:
        return None
    # Prefer the highest-version install we can find.
    def _ver_key(p: Path) -> tuple[int, int]:
        m = re.search(r"(\d+)\.(\d+)", str(p))
        return (int(m.group(1)), int(m.group(2))) if m else (0, 0)
    cands.sort(key=_ver_key, reverse=True)
    return cands[0]


def blender_bundled_python(blender_exe: Path) -> tuple[int, int] | None:
    """Return (major, minor) of the Python that ships with `blender_exe`."""
    try:
        out = subprocess.check_output(
            [str(blender_exe), "--background", "--factory-startup",
             "--python-expr",
             "import sys; print('PYVER:%d.%d' % sys.version_info[:2])"],
            stderr=subprocess.STDOUT, text=True, timeout=60)
    except Exception as e:
        print(f"warning: couldn't probe Blender's Python ({e})")
        return None
    m = re.search(r"PYVER:(\d+)\.(\d+)", out)
    return (int(m.group(1)), int(m.group(2))) if m else None


def _candidate_python_paths(minor_wanted: int | None) -> list[Path]:
    """Return plausible python executables, filtered by minor version if given."""
    system = platform.system()
    cands: list[Path] = []
    if system == "Windows":
        for base in [
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python",
            Path("C:/Python313"),
            Path("C:/Python312"),
            Path("C:/Python311"),
            Path("C:/Program Files/Python313"),
            Path("C:/Program Files/Python312"),
            Path("C:/Program Files/Python311"),
        ]:
            if base.exists():
                cands += list(base.glob("Python3*/python.exe"))
                exe = base / "python.exe"
                if exe.exists():
                    cands.append(exe)
    else:
        for name in ["python3.13", "python3.12", "python3.11"]:
            p = shutil.which(name)
            if p:
                cands.append(Path(p))

    def _minor_of(p: Path) -> int | None:
        try:
            out = subprocess.check_output(
                [str(p), "-c", "import sys; print(sys.version_info.minor)"],
                text=True, timeout=5)
            return int(out.strip())
        except Exception:
            return None

    out = []
    for c in cands:
        m = _minor_of(c)
        if m is None:
            continue
        if minor_wanted is not None and m != minor_wanted:
            continue
        out.append(c)
    return out


def pick_python(explicit: str | None, want_minor: int | None) -> Path:
    if explicit:
        p = Path(explicit).expanduser()
        if not p.exists():
            sys.exit(f"error: --python-exe does not exist: {p}")
        return p
    cands = _candidate_python_paths(want_minor)
    if not cands:
        if want_minor is not None:
            sys.stderr.write(
                f"\nerror: no Python 3.{want_minor} found on this system.\n"
                f"  Blender ships Python 3.{want_minor} but does not include\n"
                f"  the development headers, so a matching system Python is\n"
                f"  required to build the C++ module.\n\n"
                f"  Install one of:\n"
                f"    Windows:       winget install Python.Python.3.{want_minor}\n"
                f"    macOS:         brew install python@3.{want_minor}\n"
                f"    Debian/Ubuntu: sudo apt install python3.{want_minor}-dev\n\n"
                f"  Then re-run with  --python-exe <path-to-python3.{want_minor}>\n"
            )
        else:
            sys.stderr.write("error: no Python found; pass --python-exe\n")
        sys.exit(1)
    return cands[0]


# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #

def run(cmd: list[str], cwd: Path | None = None, env: dict | None = None):
    print("$", " ".join(str(c) for c in cmd))
    subprocess.check_call([str(c) for c in cmd], cwd=str(cwd) if cwd else None,
                          env=env)


def _find_vs_install() -> Path | None:
    """Return the VS / Build Tools installation root (the dir that contains VC/)."""
    import glob as _glob

    for vswhere in [
        Path("C:/Program Files (x86)/Microsoft Visual Studio/Installer/vswhere.exe"),
        Path("C:/Program Files/Microsoft Visual Studio/Installer/vswhere.exe"),
    ]:
        if not vswhere.exists():
            continue
        for extra in ([], ["-prerelease"], ["-all"]):
            try:
                lines = subprocess.check_output(
                    [str(vswhere), "-latest", *extra, "-property", "installationPath"],
                    text=True, timeout=10).strip().splitlines()
                for line in lines:
                    p = Path(line.strip())
                    if (p / "VC" / "Auxiliary" / "Build" / "vcvarsall.bat").exists():
                        return p
            except Exception:
                pass

    # Direct glob fallback (VS 2019/2022, Community / Professional / BuildTools)
    for pat in [
        r"C:\Program Files\Microsoft Visual Studio\*\*",
        r"C:\Program Files (x86)\Microsoft Visual Studio\*\*",
    ]:
        for m in sorted(_glob.glob(pat), reverse=True):
            if (Path(m) / "VC" / "Auxiliary" / "Build" / "vcvarsall.bat").exists():
                return Path(m)

    return None


def _msvc_env(vs_install: Path) -> dict | None:
    """Run vcvarsall.bat amd64 and return the resulting environment as a dict.

    This sets up cl.exe, link.exe, rc.exe, mt.exe (Windows SDK), include/lib
    paths — everything MSVC + Ninja need.  It is equivalent to opening a
    'x64 Native Tools Command Prompt for VS'.
    """
    vcvarsall = vs_install / "VC" / "Auxiliary" / "Build" / "vcvarsall.bat"
    if not vcvarsall.exists():
        return None
    try:
        # Run vcvarsall then dump the complete resulting environment
        out = subprocess.check_output(
            f'"{vcvarsall}" amd64 >nul 2>&1 && set',
            shell=True, text=True, timeout=60)
        env: dict[str, str] = {}
        for line in out.splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                env[k] = v
        if env.get("PATH") or env.get("Path"):
            return env
    except Exception as e:
        print(f"warning: vcvarsall.bat failed: {e}")
    return None


def _cmake_generator_args(use_cuda: bool = False) -> list[str]:
    """Return the -G <generator> args for cmake configure, or [] for auto-detect.

    CUDA builds on Windows use Ninja + MSVC so that FetchContent subbuilds
    work correctly (the VS/MSBuild generator has an incompatibility with
    CMake 4.x FetchContent that causes the subbuild to report failure even
    when all git-population steps succeed).  CPU builds on Windows prefer
    MinGW Makefiles when gcc is on PATH.
    """
    if platform.system() != "Windows":
        return []  # CMake defaults to Unix Makefiles on Linux/macOS

    if use_cuda:
        # Prefer Ninja for CUDA builds — same generator VSCode uses.
        if shutil.which("ninja") or shutil.which("ninja-build"):
            return ["-G", "Ninja"]
        # Ninja not on PATH — fall back to VS auto-detect (less reliable with tcnn)
        return []

    if shutil.which("gcc") or shutil.which("x86_64-w64-mingw32-gcc"):
        return ["-G", "MinGW Makefiles"]
    # MSVC / Ninja / default — let CMake auto-detect
    return []


def _backend_config(backend: str) -> tuple[Path, list[str]]:
    """Return (build_dir, extra_cmake_flags) for the requested backend.

    backend — one of: tcnn (default), cuda, cpu, auto
    """
    # libgomp (MinGW OpenMP) deadlocks inside Blender's MSVC host Python —
    # always keep OpenMP off for Blender builds regardless of backend.
    # All other optimizations (native arch, fast math, OIDN) are explicit ON.
    common_opts = [
        "-DASTRORAY_DISABLE_OPENMP=ON",
        "-DUSE_NATIVE_ARCH=ON",
        "-DUSE_FAST_MATH=ON",
        "-DASTRORAY_ENABLE_OIDN=ON",
    ]

    if backend == "cpu":
        return (REPO_ROOT / "build_blender_addon",
                ["-DASTRORAY_ENABLE_CUDA=OFF",
                 "-DASTRORAY_TINY_CUDA_NN=OFF",
                 *common_opts])
    if backend == "cuda":
        return (REPO_ROOT / "build_blender_addon_cuda",
                ["-DASTRORAY_ENABLE_CUDA=ON",
                 "-DASTRORAY_TINY_CUDA_NN=OFF",
                 *common_opts])
    if backend == "tcnn":
        return (REPO_ROOT / "build_blender_addon_tcnn",
                ["-DASTRORAY_ENABLE_CUDA=ON",
                 "-DASTRORAY_TINY_CUDA_NN=ON",
                 *common_opts])
    # auto: probe for nvcc (full search); use tcnn build if found, otherwise cpu
    if _find_nvcc():
        print("auto: nvcc found — building with tcnn (CUDA + neural cache) backend")
        return (REPO_ROOT / "build_blender_addon_tcnn",
                ["-DASTRORAY_ENABLE_CUDA=ON",
                 "-DASTRORAY_TINY_CUDA_NN=ON",
                 *common_opts])
    print("auto: nvcc not found — building CPU-only backend")
    return (REPO_ROOT / "build_blender_addon",
            ["-DASTRORAY_ENABLE_CUDA=OFF",
             "-DASTRORAY_TINY_CUDA_NN=OFF",
             *common_opts])


def _find_nvcc() -> Path | None:
    """Locate nvcc using the same search order as CMake / VS CUDA integration.

    Search order (first match wins):
      1. PATH  (shutil.which)
      2. CUDA_PATH / CUDA_HOME env vars  (set by CUDA toolkit installer)
      3. Windows registry  (HKLM\\SOFTWARE\\NVIDIA Corporation\\GPU Computing Toolkit\\CUDA)
      4. Common install path glob  (C:\\Program Files\\NVIDIA GPU Computing Toolkit\\CUDA\\v*\\bin)
      5. Linux common paths  (/usr/local/cuda*/bin)
    """
    nvcc_name = "nvcc.exe" if platform.system() == "Windows" else "nvcc"

    # 1. PATH
    found = shutil.which("nvcc")
    if found:
        return Path(found)

    # 2. Environment variables
    for var in ("CUDA_PATH", "CUDA_HOME", "CUDA_ROOT"):
        val = os.environ.get(var)
        if val:
            candidate = Path(val) / "bin" / nvcc_name
            if candidate.exists():
                return candidate

    if platform.system() == "Windows":
        # 3. Windows registry (same key CMake checks via FindCUDAToolkit)
        try:
            import winreg
            key_path = r"SOFTWARE\NVIDIA Corporation\GPU Computing Toolkit\CUDA"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                i = 0
                best: Path | None = None
                while True:
                    try:
                        ver_name = winreg.EnumKey(key, i)
                        with winreg.OpenKey(key, ver_name) as ver_key:
                            try:
                                install_dir, _ = winreg.QueryValueEx(ver_key, "InstallDir")
                                candidate = Path(install_dir) / "bin" / nvcc_name
                                if candidate.exists():
                                    best = candidate  # take last (highest version)
                            except FileNotFoundError:
                                pass
                        i += 1
                    except OSError:
                        break
                if best:
                    return best
        except (ImportError, OSError):
            pass

        # 4. Common install path glob
        import glob as _glob
        pattern = r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v*\bin"
        dirs = sorted(_glob.glob(pattern), reverse=True)  # highest version first
        for d in dirs:
            candidate = Path(d) / nvcc_name
            if candidate.exists():
                return candidate
    else:
        # 5. Linux/macOS common paths
        import glob as _glob
        for pattern in ["/usr/local/cuda*/bin/nvcc", "/usr/cuda*/bin/nvcc"]:
            matches = sorted(_glob.glob(pattern), reverse=True)
            if matches:
                return Path(matches[0])

    return None


def _require_nvcc(backend: str) -> Path | None:
    """For cuda/tcnn backends, find nvcc and ensure PATH is set.

    Returns the nvcc Path (so callers can pass -DCMAKE_CUDA_COMPILER=<path>
    explicitly, which works even when nvcc is not on the shell PATH).
    """
    if backend not in ("cuda", "tcnn"):
        return None
    nvcc = _find_nvcc()
    if nvcc is None:
        sys.exit(
            f"\nerror: --backend {backend} requires the CUDA toolkit but nvcc was not found.\n\n"
            f"  Searched: PATH, CUDA_PATH/CUDA_HOME env vars, Windows registry, common install paths.\n\n"
            f"  Install CUDA Toolkit (12.x recommended):\n"
            f"    Windows: https://developer.nvidia.com/cuda-downloads\n"
            f"    Linux:   sudo apt install cuda-toolkit-12-x\n\n"
            f"  After installing, re-run this script (or set CUDA_PATH to your CUDA root).\n\n"
            f"  To build without GPU acceleration use --backend cpu\n"
        )
    print(f"nvcc: {nvcc}")
    # Ensure nvcc's directory is on PATH so CMake's language-enable step finds it
    nvcc_bin = str(nvcc.parent)
    if nvcc_bin not in os.environ.get("PATH", ""):
        os.environ["PATH"] = nvcc_bin + os.pathsep + os.environ.get("PATH", "")
    return nvcc


def _verify_cuda_compiled_in(build_dir: Path, backend: str):
    """After a cuda/tcnn build, confirm CMake actually found nvcc.
    If it silently fell back to CPU-only, fail loudly so the user isn't misled."""
    if backend not in ("cuda", "tcnn"):
        return
    cache = build_dir / "CMakeCache.txt"
    if not cache.exists():
        return
    text = cache.read_text(errors="replace")
    if "CMAKE_CUDA_COMPILER:FILEPATH=NOTFOUND" in text or "CMAKE_CUDA_COMPILER:FILEPATH=" not in text:
        sys.exit(
            f"\nerror: CUDA was requested (--backend {backend}) but CMake could not find nvcc.\n"
            f"  The built module will NOT have GPU support.\n\n"
            f"  Diagnose:\n"
            f"    • Run: nvcc --version   (should print CUDA release x.y)\n"
            f"    • Check CUDA_PATH env var points to your CUDA toolkit root\n"
            f"    • Re-run with --clean to force CMake reconfiguration after fixing nvcc\n\n"
            f"  Or use --backend cpu to build a CPU-only addon.\n"
        )
    # Also verify ASTRORAY_CUDA_FOUND was set true in the generated config
    if "ASTRORAY_CUDA_FOUND:INTERNAL=TRUE" not in text and "ASTRORAY_CUDA_FOUND:BOOL=TRUE" not in text:
        # CMake found nvcc but ASTRORAY logic may have still disabled it — warn
        print("warning: nvcc was found but ASTRORAY_CUDA_FOUND may not be set — "
              "check CMake output for CUDA configuration errors")


def configure_and_build(python_exe: Path, clean: bool, jobs: int, backend: str = "tcnn"):
    global BUILD_DIR
    nvcc = _require_nvcc(backend)
    BUILD_DIR, extra_flags = _backend_config(backend)

    # Pass the compiler path explicitly so CMake finds it even when nvcc is not
    # on the shell PATH (e.g. CUDA installed via VS integration or registry only).
    if nvcc is not None:
        extra_flags = [f"-DCMAKE_CUDA_COMPILER={nvcc}", *extra_flags]

    # For CUDA builds on Windows, set up the full MSVC developer environment via
    # vcvarsall.bat amd64.  This puts cl.exe, link.exe, rc.exe, mt.exe, and the
    # Windows SDK include/lib paths into the subprocess environment — exactly what
    # VSCode does via its kit selection.  Without it, Ninja+MSVC fails because the
    # Windows SDK tools (rc, mt) are not on PATH.
    cmake_env: dict | None = None
    if nvcc is not None and platform.system() == "Windows":
        vs = _find_vs_install()
        if vs:
            print(f"VS install: {vs}")
            cmake_env = _msvc_env(vs)
            if cmake_env:
                print("MSVC environment configured (vcvarsall.bat amd64)")
                # Also ensure nvcc is reachable from within the MSVC environment
                nvcc_bin = str(nvcc.parent)
                path_key = "PATH" if "PATH" in cmake_env else "Path"
                if nvcc_bin.lower() not in cmake_env.get(path_key, "").lower():
                    cmake_env[path_key] = nvcc_bin + os.pathsep + cmake_env.get(path_key, "")
            else:
                print("warning: vcvarsall.bat failed — CUDA build will likely fail")
        else:
            print("warning: Visual Studio not found — install VS 2019/2022 Build Tools")

    if clean and BUILD_DIR.exists():
        print(f"removing {BUILD_DIR}")
        _force_remove(BUILD_DIR)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)

    cache_file = BUILD_DIR / "CMakeCache.txt"
    if not cache_file.exists():
        generator_args = _cmake_generator_args(use_cuda=(nvcc is not None))
        run([
            "cmake", "-S", str(REPO_ROOT), "-B", str(BUILD_DIR),
            *generator_args,
            "-DCMAKE_BUILD_TYPE=Release",
            "-DBUILD_PYTHON_MODULE=ON",
            *extra_flags,
            f"-DPython3_EXECUTABLE={python_exe}",
            f"-DPython3_ROOT_DIR={python_exe.parent}",
            "-DPython3_FIND_STRATEGY=LOCATION",
        ], env=cmake_env)

    _verify_cuda_compiled_in(BUILD_DIR, backend)

    run(["cmake", "--build", str(BUILD_DIR),
         "--config", "Release", "--target", "astroray",
         "-j", str(jobs)], env=cmake_env)


def find_built_module() -> Path:
    """Return the path to the freshly built astroray.*.pyd / astroray*.so."""
    for pattern in ("astroray.*.pyd", "astroray*.pyd", "astroray*.so",
                    "Release/astroray*.pyd"):
        matches = list(BUILD_DIR.glob(pattern))
        if matches:
            # Prefer the most recently built one
            matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return matches[0]
    sys.exit(f"error: no astroray module found in {BUILD_DIR}")


def probe_built_module(module_path: Path, backend: str):
    """Import the freshly built module in a subprocess and verify __features__."""
    probe = (
        "import sys, os\n"
        f"sys.path.insert(0, {str(module_path.parent)!r})\n"
        "if sys.platform=='win32' and hasattr(os,'add_dll_directory'):\n"
        f"    os.add_dll_directory({str(module_path.parent)!r})\n"
        "import astroray\n"
        "f = astroray.__features__\n"
        "print('cuda:', f.get('cuda', False))\n"
        "print('oidn:', f.get('oidn_denoiser', False))\n"
        "r = astroray.Renderer()\n"
        "print('gpu_available:', r.gpu_available)\n"
        "if r.gpu_available: print('gpu_device:', r.gpu_device_name)\n"
    )
    try:
        out = subprocess.check_output(
            [sys.executable, "-c", probe],
            text=True, timeout=30,
            stderr=subprocess.STDOUT,
        )
        print("\n--- module probe ---")
        print(out.strip())
        print("---\n")
        if backend in ("cuda", "tcnn") and "cuda: False" in out:
            sys.exit(
                "error: the built module reports cuda=False even though --backend "
                f"{backend} was requested.\n"
                "  The CUDA toolkit was likely not found by CMake.\n"
                "  Run with --clean --backend cuda and check CMake output for CUDA errors.\n"
            )
    except subprocess.CalledProcessError as e:
        print(f"warning: module probe failed ({e}); proceeding anyway\n{e.output}")


# --------------------------------------------------------------------------- #
# Package
# --------------------------------------------------------------------------- #

def read_manifest_version() -> str:
    manifest = ADDON_SRC / "blender_manifest.toml"
    m = re.search(r'^version\s*=\s*"([^"]+)"', manifest.read_text(), re.M)
    return m.group(1) if m else "0.0.0"


def _force_remove(path: Path, retries: int = 5):
    """rmtree with retries + read-only handling. Windows/OneDrive sometimes
    holds a directory briefly after a previous build, so we back off rather
    than bailing out on the first PermissionError."""
    if not path.exists():
        return

    def _onexc(func, p, exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            raise

    for attempt in range(retries):
        try:
            shutil.rmtree(path, onexc=_onexc)
            return
        except PermissionError:
            if attempt == retries - 1:
                raise
            time.sleep(0.5 * (attempt + 1))


def _objdump_deps(binary: Path) -> list[str]:
    """Return the lib*.dll names a PE binary depends on."""
    try:
        out = subprocess.check_output(
            ["objdump", "-p", str(binary)],
            text=True, stderr=subprocess.STDOUT, timeout=15)
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        print(f"warning: couldn't run objdump on {binary.name} ({e})")
        return []
    deps = []
    for line in out.splitlines():
        m = re.search(r"DLL Name:\s*(lib\S+\.dll)", line)
        if m:
            deps.append(m.group(1))
    return deps


def _bundle_mingw_runtime_dlls(module_path: Path) -> list[str]:
    """Copy MinGW runtime DLLs the .pyd needs into STAGE_DIR.

    libstdc++-6.dll is statically linked into the .pyd via -static-libstdc++
    in CMakeLists.txt. libgomp-1.dll, libgcc_s_seh-1.dll, libwinpthread-1.dll
    and libmcfgthread-2.dll cannot be cleanly statically linked together with
    OpenMP, so we walk the dependency tree of the .pyd transitively and ship
    every lib*.dll it pulls in. __init__.py registers the addon dir as a DLL
    search path so the OS loader can find them at import time.
    """
    if platform.system() != "Windows":
        return []

    # Search MinGW's bin directory for DLLs
    mingw_bins = [
        Path("C:/Program Files/mingw64/bin"),
        Path("C:/mingw64/bin"),
        Path("C:/msys64/mingw64/bin"),
    ]

    def _find_in_mingw(name: str) -> Path | None:
        for bindir in mingw_bins:
            p = bindir / name
            if p.exists():
                return p
        return None

    bundled: list[str] = []
    seen: set[str] = set()
    queue: list[Path] = [module_path]
    while queue:
        cur = queue.pop()
        for dll in _objdump_deps(cur):
            if dll in seen:
                continue
            seen.add(dll)
            src = _find_in_mingw(dll)
            if src is None:
                # Likely a system DLL we don't care about (api-ms-win-*, etc.)
                continue
            dst = STAGE_DIR / dll
            shutil.copy2(src, dst)
            bundled.append(dll)
            queue.append(dst)
    return bundled


def _bundle_cuda_runtime_dlls(module_path: Path) -> None:
    """Copy CUDA runtime DLLs (cudart, etc.) into STAGE_DIR for Windows cuda/tcnn builds."""
    if platform.system() != "Windows":
        return
    # Locate CUDA bin dir using the same comprehensive search as _find_nvcc()
    cuda_bin_candidates = []
    nvcc = _find_nvcc()
    if nvcc:
        cuda_bin_candidates.append(nvcc.parent)  # nvcc's own bin dir
    # Also check CUDA_PATH and common install paths as fallback
    cuda_path = os.environ.get("CUDA_PATH")
    if cuda_path:
        cuda_bin_candidates.append(Path(cuda_path) / "bin")
    import glob as _glob
    cuda_bin_candidates += [Path(p) for p in _glob.glob(
        r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v*\bin")]
    cuda_bin_candidates += [Path(r"C:\Windows\System32")]  # runtime may be here too

    # DLLs required by the CUDA runtime (cudart) and potentially CUBLAS/CUFFT
    wanted_patterns = ["cudart64_*.dll", "cublas64_*.dll", "cublasLt64_*.dll",
                       "cufft64_*.dll", "nvrtc64_*.dll"]
    bundled: list[str] = []
    for cand_dir in cuda_bin_candidates:
        if not cand_dir.exists():
            continue
        for pat in wanted_patterns:
            for dll in cand_dir.glob(pat):
                dst = STAGE_DIR / dll.name
                if not dst.exists():
                    shutil.copy2(dll, dst)
                    bundled.append(dll.name)
        if bundled:
            print(f"bundled {len(bundled)} CUDA runtime DLLs from {cand_dir}")
            return
    if not bundled:
        print("note: CUDA runtime DLLs not found locally — they must be on system PATH at runtime")


def _bundle_oidn_dlls(module_path: Path) -> None:
    """Copy OIDN runtime DLLs into STAGE_DIR/oidn/ so the addon can load them."""
    import glob as _glob

    # Candidate OIDN bin directories: build tree _deps first, then system install.
    build_dir = module_path.parent
    while build_dir != build_dir.parent:
        oidn_fetched = list(build_dir.glob("_deps/oidn_prebuilt-src/bin"))
        if oidn_fetched:
            break
        build_dir = build_dir.parent

    candidates = []
    if oidn_fetched:
        candidates.append(oidn_fetched[0])
    candidates.append(Path(r"C:\oidn\bin"))

    for oidn_bin in candidates:
        dlls = list(oidn_bin.glob("OpenImageDenoise*.dll")) + \
               list(oidn_bin.glob("tbb*.dll"))
        if dlls:
            dest = STAGE_DIR / "oidn"
            dest.mkdir(exist_ok=True)
            for dll in dlls:
                shutil.copy2(dll, dest / dll.name)
            print(f"bundled {len(dlls)} OIDN DLLs from {oidn_bin}")
            return
    print("warning: OIDN DLLs not found — addon will rely on system PATH for OpenImageDenoise.dll")


def stage_and_zip(module_path: Path, backend: str = "cpu") -> Path:
    import json, datetime
    _force_remove(STAGE_DIR)
    STAGE_DIR.mkdir(parents=True)

    # Copy the Python-side addon files
    for name in ADDON_FILES:
        src = ADDON_SRC / name
        if not src.exists():
            sys.exit(f"error: missing addon file {src}")
        shutil.copy2(src, STAGE_DIR / name)

    # Copy the built native module
    shutil.copy2(module_path, STAGE_DIR / module_path.name)

    # Bundle MinGW runtime DLLs the .pyd depends on (Windows only)
    bundled = _bundle_mingw_runtime_dlls(module_path)
    if bundled:
        print(f"bundled runtime DLLs: {', '.join(bundled)}")

    # Bundle OIDN runtime DLLs (Windows only).
    # Look for them next to the .pyd's cmake build tree, then fall back to
    # the system-wide C:/oidn install.  Placed in oidn/ inside the addon so
    # __init__.py can add them to the DLL search path at load time.
    if platform.system() == "Windows":
        _bundle_oidn_dlls(module_path)
        if backend in ("cuda", "tcnn"):
            _bundle_cuda_runtime_dlls(module_path)

    # Optional: include the LICENSE so the extension carries it
    license_src = REPO_ROOT / "LICENSE"
    if license_src.exists():
        shutil.copy2(license_src, STAGE_DIR / "LICENSE")

    # Write a build report so the packaged addon is self-describing
    _, extra_flags = _backend_config(backend)
    build_report = {
        "built_at": datetime.datetime.utcnow().isoformat() + "Z",
        "backend": backend,
        "build_dir": str(BUILD_DIR),
        "module": module_path.name,
        "cmake_flags": extra_flags,
        "platform": platform.platform(),
        "python": sys.version,
    }
    report_path = STAGE_DIR / "build_report.json"
    report_path.write_text(json.dumps(build_report, indent=2))
    print(f"build report: {report_path}")

    version = read_manifest_version()
    backend_suffix = f"-{backend}" if backend != "cpu" else ""
    zip_path = DIST_DIR / f"astroray-{version}{backend_suffix}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(STAGE_DIR):
            for f in files:
                abs_path = Path(root) / f
                # The archive layout must place files at the root of `astroray/`
                # — Blender's extension installer unpacks the zip and expects a
                # single top-level directory matching the manifest `id`.
                arc = Path("astroray") / abs_path.relative_to(STAGE_DIR)
                zf.write(abs_path, arc.as_posix())
    return zip_path


# --------------------------------------------------------------------------- #
# Install (copy staged dir into Blender's extensions path)
# --------------------------------------------------------------------------- #

def blender_user_extensions_dir(blender_exe: Path) -> Path | None:
    """Return the user_default extensions directory for the target Blender."""
    # Ask Blender directly — it knows its own paths and version.
    try:
        out = subprocess.check_output(
            [str(blender_exe), "--background", "--factory-startup",
             "--python-expr",
             "import bpy, sys; "
             "print('EXTDIR:' + bpy.utils.user_resource('EXTENSIONS', path='user_default'))"],
            stderr=subprocess.STDOUT, text=True, timeout=60)
    except Exception as e:
        print(f"warning: couldn't ask Blender for its extensions dir ({e})")
        return None
    for line in out.splitlines():
        if line.startswith("EXTDIR:"):
            return Path(line[len("EXTDIR:"):].strip())
    return None


def install_to_blender(blender_exe: Path) -> bool:
    ext_dir = blender_user_extensions_dir(blender_exe)
    if ext_dir is None:
        print("warning: could not determine Blender extensions dir — skipping install")
        return False
    target = ext_dir / "astroray"
    print(f"installing to {target}")
    ext_dir.mkdir(parents=True, exist_ok=True)
    _force_remove(target)
    shutil.copytree(STAGE_DIR, target)
    return True


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--blender", help="Path to a specific blender executable")
    ap.add_argument("--python-exe", help="Path to python matching Blender's bundled Python minor version")
    ap.add_argument("--backend", choices=["auto", "cpu", "cuda", "tcnn"], default="tcnn",
                    help="Build backend: tcnn (default, CUDA+NRC), cuda (CUDA GPU), "
                         "cpu (CPU-only), auto (probe nvcc, use tcnn if found)")
    ap.add_argument("--clean", action="store_true", help="Wipe the build dir before configuring")
    ap.add_argument("--configure-only", action="store_true",
                    help="Run cmake configure but skip the build")
    ap.add_argument("--install", action="store_true",
                    help="Also copy the staged addon into Blender's user_default extensions dir")
    ap.add_argument("-j", "--jobs", type=int, default=os.cpu_count() or 4,
                    help="Parallel build jobs (default: %(default)s)")
    args = ap.parse_args()

    # 1. Find Blender (for probing Python version and for install step)
    blender = find_blender(args.blender)
    if blender is None and args.install:
        sys.exit("error: --install requires Blender on PATH or --blender")
    if blender:
        print(f"Blender: {blender}")

    # 2. Decide which Python to build against
    want_minor: int | None = None
    if blender:
        pyver = blender_bundled_python(blender)
        if pyver:
            print(f"Blender bundled Python: {pyver[0]}.{pyver[1]}")
            want_minor = pyver[1]
    python_exe = pick_python(args.python_exe, want_minor)
    print(f"Building against Python: {python_exe}")

    # 3. Configure + build (unless configure-only)
    configure_and_build(python_exe, clean=args.clean, jobs=args.jobs, backend=args.backend)
    if args.configure_only:
        print("configure-only: skipping stage/zip")
        return

    # 4. Probe + stage + zip
    module_path = find_built_module()
    print(f"Built module: {module_path.name}")
    probe_built_module(module_path, args.backend)
    zip_path = stage_and_zip(module_path, backend=args.backend)
    print(f"\nAddon package: {zip_path}")
    print(f"Staged dir:    {STAGE_DIR}")

    # 5. Optional: install into Blender's extensions dir
    if args.install:
        if blender is None:
            sys.exit("error: --install requires Blender discovery")
        if install_to_blender(blender):
            print(f"Installed into Blender ({blender})")

    print("\nDone.")
    print("To install manually in Blender:")
    print("  Edit > Preferences > Get Extensions > (dropdown) > Install from Disk...")
    print(f"  and select {zip_path}")


if __name__ == "__main__":
    main()
