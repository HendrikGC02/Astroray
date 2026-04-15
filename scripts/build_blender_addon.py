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
    python scripts/build_blender_addon.py                      # auto-detect
    python scripts/build_blender_addon.py --blender "<path>"   # target a specific Blender
    python scripts/build_blender_addon.py --python-exe C:/Python313/python.exe
    python scripts/build_blender_addon.py --install            # also copy into
                                                               # Blender's extensions dir
    python scripts/build_blender_addon.py --clean              # wipe build dir first

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
BUILD_DIR   = REPO_ROOT / "build_blender_addon"
DIST_DIR    = REPO_ROOT / "dist"
STAGE_DIR   = DIST_DIR / "astroray"

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


def _cmake_generator_args() -> list[str]:
    """Return the -G <generator> args for cmake configure, or [] for auto-detect.

    On Windows we prefer MinGW Makefiles when MinGW/MSYS gcc is on PATH
    (legacy setup), but fall back to letting CMake pick its own default —
    which will be a Visual Studio generator on MSVC machines.  Mixing
    generators causes configure failures, so we only force MinGW when it is
    actually available.
    """
    if platform.system() != "Windows":
        return []  # CMake defaults to Unix Makefiles on Linux/macOS
    if shutil.which("gcc") or shutil.which("x86_64-w64-mingw32-gcc"):
        return ["-G", "MinGW Makefiles"]
    # MSVC / Ninja / default — let CMake auto-detect
    return []


def configure_and_build(python_exe: Path, clean: bool, jobs: int):
    if clean and BUILD_DIR.exists():
        print(f"removing {BUILD_DIR}")
        _force_remove(BUILD_DIR)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)

    cache_file = BUILD_DIR / "CMakeCache.txt"
    if not cache_file.exists():
        generator_args = _cmake_generator_args()
        run([
            "cmake", "-S", str(REPO_ROOT), "-B", str(BUILD_DIR),
            *generator_args,
            "-DCMAKE_BUILD_TYPE=Release",
            "-DBUILD_PYTHON_MODULE=ON",
            # Disable CUDA — the GR/spectral headers use GCC-only attributes
            # that NVCC rejects, and the Blender addon does not use GPU rendering.
            "-DASTRORAY_ENABLE_CUDA=OFF",
            # libgomp (MinGW OpenMP runtime) deadlocks inside Blender's MSVC
            # host Python during module init, so build the Blender .pyd
            # single-threaded. pybind11 binding entry points don't use OpenMP
            # anyway — the speedup comes from within-C++ path tracer loops,
            # which Blender invokes one render at a time.
            "-DASTRORAY_DISABLE_OPENMP=ON",
            f"-DPython3_EXECUTABLE={python_exe}",
            f"-DPython3_ROOT_DIR={python_exe.parent}",
            # Tell CMake's FindPython to prefer the exact interpreter we picked
            "-DPython3_FIND_STRATEGY=LOCATION",
        ])

    run(["cmake", "--build", str(BUILD_DIR),
         "--config", "Release", "--target", "astroray",
         "-j", str(jobs)])


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


def stage_and_zip(module_path: Path) -> Path:
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

    # Optional: include the LICENSE so the extension carries it
    license_src = REPO_ROOT / "LICENSE"
    if license_src.exists():
        shutil.copy2(license_src, STAGE_DIR / "LICENSE")

    version = read_manifest_version()
    zip_path = DIST_DIR / f"astroray-{version}.zip"
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
    configure_and_build(python_exe, clean=args.clean, jobs=args.jobs)
    if args.configure_only:
        print("configure-only: skipping stage/zip")
        return

    # 4. Stage + zip
    module_path = find_built_module()
    print(f"Built module: {module_path.name}")
    zip_path = stage_and_zip(module_path)
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
