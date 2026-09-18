"""issue #818 — render the evidence .blend three ways (run in Blender 5.2).

    blender -b <scene.blend> --python scripts/dev/issue818_render.py -- \
            --mode {cycles_cpu|astroray_cpu|astroray_gpu} --output <png> --samples N

For the astroray modes the script enables the STAGED worktree extension
(bl_ext.user_default.astroray, staged via BLENDER_USER_EXTENSIONS) and ASSERTS
the loaded module path is under the scratch extensions root — proof we are
exercising the worktree build, not an installed profile addon.
"""
import os
import sys
import traceback

import bpy  # type: ignore


def _args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True,
                    choices=["cycles_cpu", "astroray_cpu", "astroray_gpu"])
    ap.add_argument("--output", required=True)
    ap.add_argument("--samples", type=int, default=64)
    return ap.parse_args(argv)


def _enable_staged_astroray():
    ext_root = os.environ.get("BLENDER_USER_EXTENSIONS", "")
    assert ext_root, "BLENDER_USER_EXTENSIONS not set — stage the addon first"
    bpy.ops.preferences.addon_enable(module="bl_ext.user_default.astroray")
    import bl_ext.user_default.astroray as m  # type: ignore
    loaded = os.path.abspath(m.__file__)
    root = os.path.abspath(ext_root)
    assert loaded.startswith(root), (
        f"loaded addon {loaded} is NOT under the scratch root {root} "
        "— a profile-installed addon shadowed the staged build")
    print(f"issue818: staged addon OK -> {loaded}")


def main():
    a = _args()
    scene = bpy.context.scene
    scene.render.resolution_percentage = 100
    scene.view_settings.view_transform = "Standard"
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.filepath = os.path.abspath(a.output)

    cyc = scene.cycles if hasattr(scene, "cycles") else None

    if a.mode == "cycles_cpu":
        scene.render.engine = "CYCLES"
        scene.cycles.device = "CPU"
        scene.cycles.samples = a.samples
    else:
        _enable_staged_astroray()
        scene.render.engine = "CUSTOM_RAYTRACER"
        if cyc is not None:
            cyc.samples = a.samples
        cr = getattr(scene, "custom_raytracer", None)
        assert cr is not None, "scene.custom_raytracer missing — addon not registered"
        cr.use_adaptive_sampling = False           # deterministic, colour-blind stop off
        cr.device_mode = "gpu" if a.mode == "astroray_gpu" else "cpu"
        print(f"issue818: device_mode={cr.device_mode}")

    print(f"issue818: mode={a.mode} engine={scene.render.engine} "
          f"samples={a.samples} out={scene.render.filepath}")
    try:
        bpy.ops.render.render(write_still=True)
    except Exception as e:
        print(f"FAIL: render failed {type(e).__name__}: {e}")
        traceback.print_exc()
        sys.exit(4)
    if not os.path.exists(scene.render.filepath):
        print(f"FAIL: output missing {scene.render.filepath}")
        sys.exit(5)
    print(f"OK: wrote {scene.render.filepath} ({os.path.getsize(scene.render.filepath)} bytes)")


main()
