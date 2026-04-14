"""
Headless render script invoked by Blender to exercise the Astroray engine
against a .blend file.

This file is NOT meant to be run directly — it's fed to Blender via:

    blender --background path/to/scene.blend --python render_test_scene.py \
            -- --output out.png --samples 32

Arguments after the lone `--` are parsed by this script; everything before
belongs to Blender.

What it does:
  1. Enables the `astroray` extension (bl_ext.user_default.astroray).
  2. Flips `scene.render.engine` to `CUSTOM_RAYTRACER` (the bl_idname of the
     Astroray engine).
  3. Applies sane overrides: resolution, samples, output path, PNG format.
  4. Calls `bpy.ops.render.render(write_still=True)` and prints a success
     summary so the caller can verify the end-to-end path.
"""

import os
import sys
import traceback

# Locate the `--` separator and parse our own args from everything after it.
try:
    sep = sys.argv.index("--")
    script_argv = sys.argv[sep + 1:]
except ValueError:
    script_argv = []

import argparse
import bpy   # type: ignore  # noqa: E402  (must come after Blender boots)


def parse_args(argv):
    ap = argparse.ArgumentParser(prog="render_test_scene")
    ap.add_argument("--output", required=True,
                    help="Destination PNG file path")
    ap.add_argument("--samples", type=int, default=32,
                    help="Samples per pixel (default: 32)")
    ap.add_argument("--width", type=int, default=0,
                    help="Override resolution X (0 = keep scene value)")
    ap.add_argument("--height", type=int, default=0,
                    help="Override resolution Y (0 = keep scene value)")
    ap.add_argument("--percentage", type=int, default=100,
                    help="Resolution percentage (default: 100)")
    ap.add_argument("--max-bounces", type=int, default=6,
                    help="Path-tracer max bounces (default: 6)")
    return ap.parse_args(argv)


def enable_astroray_extension() -> bool:
    """Try to enable the astroray extension. Returns True on success."""
    # Blender 4.2+ extension identifier format:
    #   bl_ext.<repo>.<module>   — e.g. bl_ext.user_default.astroray
    candidates = [
        "bl_ext.user_default.astroray",
        # Legacy addon-style (if someone dropped it into scripts/addons/)
        "astroray",
    ]
    last_err = None
    for module_name in candidates:
        try:
            bpy.ops.preferences.addon_enable(module=module_name)
            print(f"enabled addon: {module_name}")
            return True
        except Exception as e:
            last_err = e
            continue
    print(f"FAIL: could not enable astroray addon ({last_err})")
    return False


def main():
    args = parse_args(script_argv)

    if not enable_astroray_extension():
        sys.exit(2)

    scene = bpy.context.scene

    # Point the scene at our render engine
    try:
        scene.render.engine = "CUSTOM_RAYTRACER"
    except Exception as e:
        print(f"FAIL: couldn't set render engine to CUSTOM_RAYTRACER: {e}")
        sys.exit(3)

    # Engine-side sampling settings (we registered these as scene.custom_raytracer)
    cr = getattr(scene, "custom_raytracer", None)
    if cr is not None:
        cr.samples = args.samples
        cr.max_bounces = args.max_bounces
        # Keep adaptive sampling off for deterministic timings in tests
        cr.use_adaptive_sampling = False

    # Resolution / percentage / output
    if args.width > 0:
        scene.render.resolution_x = args.width
    if args.height > 0:
        scene.render.resolution_y = args.height
    scene.render.resolution_percentage = args.percentage

    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.filepath = os.path.abspath(args.output)

    print(f"engine:     {scene.render.engine}")
    print(f"resolution: {scene.render.resolution_x}x{scene.render.resolution_y} "
          f"@ {scene.render.resolution_percentage}%")
    print(f"samples:    {args.samples}")
    print(f"output:     {scene.render.filepath}")

    try:
        bpy.ops.render.render(write_still=True)
    except Exception as e:
        print(f"FAIL: render failed with {type(e).__name__}: {e}")
        traceback.print_exc()
        sys.exit(4)

    if not os.path.exists(scene.render.filepath):
        print(f"FAIL: render finished but output file missing at {scene.render.filepath}")
        sys.exit(5)

    size = os.path.getsize(scene.render.filepath)
    print(f"OK: wrote {scene.render.filepath} ({size} bytes)")


if __name__ == "__main__":
    main()
