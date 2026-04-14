#!/usr/bin/env python3
"""
End-to-end smoke test: build the Astroray Blender addon, install it into
Blender's user_default extensions directory, and render the bundled
`blender_addon/Test_scene.blend` headlessly.

Usage
-----
    python scripts/test_blender_addon.py
    python scripts/test_blender_addon.py --blender "C:\\Program Files\\Blender Foundation\\Blender 5.1\\blender.exe"
    python scripts/test_blender_addon.py --scene path/to/other.blend --samples 8 --skip-build

Exit codes
----------
    0   success — Blender rendered the scene and wrote the PNG
    1   build / packaging error
    2   Blender not found
    3   render failed (see stderr)

This script intentionally does not edit the .blend file. If the scene's
render engine is not already set to Astroray we override it inside Blender
via `render_test_scene.py`.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT     = Path(__file__).resolve().parent.parent
SCRIPTS_DIR   = REPO_ROOT / "scripts"
DEFAULT_SCENE = REPO_ROOT / "blender_addon" / "Test_scene.blend"
OUTPUT_DIR    = REPO_ROOT / "test_results"

# Import the build helpers so we share the Python/Blender discovery logic.
sys.path.insert(0, str(SCRIPTS_DIR))
import build_blender_addon as bba   # type: ignore  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--blender", help="Path to blender executable")
    ap.add_argument("--python-exe", help="Python matching Blender's bundled Python minor version")
    ap.add_argument("--scene", default=str(DEFAULT_SCENE),
                    help="Scene .blend to render (default: %(default)s)")
    ap.add_argument("--output", default=str(OUTPUT_DIR / "blender_addon_test.png"),
                    help="Destination PNG (default: %(default)s)")
    ap.add_argument("--samples", type=int, default=16)
    ap.add_argument("--width", type=int, default=0)
    ap.add_argument("--height", type=int, default=0)
    ap.add_argument("--skip-build", action="store_true",
                    help="Reuse the existing staged build (dist/astroray/)")
    ap.add_argument("--clean", action="store_true",
                    help="Wipe build dir before configuring")
    ap.add_argument("-j", "--jobs", type=int, default=os.cpu_count() or 4)
    args = ap.parse_args()

    scene_path = Path(args.scene)
    if not scene_path.exists():
        sys.exit(f"error: scene not found: {scene_path}")

    blender = bba.find_blender(args.blender)
    if blender is None:
        sys.exit("error: could not find a Blender install; pass --blender")
    print(f"Blender: {blender}")

    # ---- 1. Build + package (unless --skip-build) -------------------------
    if not args.skip_build:
        pyver = bba.blender_bundled_python(blender)
        want_minor = pyver[1] if pyver else None
        if pyver:
            print(f"Blender bundled Python: {pyver[0]}.{pyver[1]}")
        python_exe = bba.pick_python(args.python_exe, want_minor)
        print(f"Building against Python: {python_exe}")
        try:
            bba.configure_and_build(python_exe, clean=args.clean, jobs=args.jobs)
            module_path = bba.find_built_module()
            zip_path = bba.stage_and_zip(module_path)
            print(f"Built module: {module_path.name}")
            print(f"Addon package: {zip_path}")
        except Exception as e:
            print(f"FAIL: build/packaging error: {e}")
            sys.exit(1)
    else:
        if not bba.STAGE_DIR.exists():
            sys.exit("error: --skip-build set but dist/astroray/ does not exist; "
                     "run without --skip-build first")

    # ---- 2. Install into Blender's extensions dir -------------------------
    if not bba.install_to_blender(blender):
        sys.exit(1)

    # ---- 3. Invoke Blender headlessly to render the scene -----------------
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    render_script = SCRIPTS_DIR / "render_test_scene.py"

    cmd = [
        str(blender),
        "--background",
        "--factory-startup",
        str(scene_path),
        "--python", str(render_script),
        "--",
        "--output", str(output),
        "--samples", str(args.samples),
    ]
    if args.width:
        cmd += ["--width", str(args.width)]
    if args.height:
        cmd += ["--height", str(args.height)]

    print("\n$ " + " ".join(f'"{c}"' if " " in c else c for c in cmd))
    proc = subprocess.run(cmd)
    if proc.returncode != 0:
        print(f"FAIL: Blender exited with code {proc.returncode}")
        sys.exit(3)

    if not output.exists():
        print(f"FAIL: expected render output at {output}, not found")
        sys.exit(3)

    size = output.stat().st_size
    print(f"\nOK: rendered {scene_path.name} -> {output} ({size} bytes)")


if __name__ == "__main__":
    main()
