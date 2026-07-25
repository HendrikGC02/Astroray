"""pkg88-B — real-Blender end-to-end verification of object + camera motion blur.

Run headless:
    "C:/Program Files/Blender Foundation/Blender 5.1/blender.exe" --background \
        --factory-startup --python scripts/verify_pkg88b_blender.py

Closes the gap the mocked-`bpy` suites structurally cannot: those stub
`setup_camera` and do not model `renderer.clear()`'s side effect on camera
state, so they never exercised a real depsgraph re-cook under `frame_set` nor
the real `convert_scene` call ORDER. Both defects below were invisible to them
and fatal in real Blender.

Builds a REAL Blender scene: a cube keyframed to translate along X between
frames 1 and 3, evaluated at frame 2. Runs the addon's real `convert_scene`
(NOT a mock) for each of START / CENTER / END and renders on the real engine,
measuring the moving cube's horizontal streak width.

Asserts:
  * `convert_scene` does not raise when `use_motion_blur=True` — the PR #525
    regression guard. `clear()` resets the camera, so if `set_camera_motion_blur`
    is ever reordered ahead of `setup_camera` again this dies with
    "Camera not set up" and every motion-blur render fails.
  * OBJECT motion blur fires for all three shutter positions (streak wider than
    the object's own static silhouette). END matters most: a pre-fix bug made it
    produce exactly the static width, because `t_end == frame` meant the object
    never registered as moving.
  * CAMERA motion blur (pkg88-A) still fires — a static object blurs when the
    CAMERA is the thing animated. This guards the hoisted `setup_camera` not
    having broken the path it was moved across, and would also catch a future
    `setup_camera` placed after `set_camera_motion_blur` silently resetting
    `Camera::shutter` to its 0.0f default (blur off) instead of crashing.

Runs on CPU deliberately: the defects are in addon-side Python ordering and are
backend-independent, and a CPU run avoids the concurrent-CUDA-verifier
false-positive footgun on this box.

Prints PKG88B_BLENDER_RESULT PASS / FAIL.
"""
import os
import sys
import importlib.util

import bpy
import numpy as np

ROOT = os.environ.get(
    "ASTRORAY_ROOT",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tests"))
import runtime_setup
runtime_setup.configure_test_imports()
sys.path.insert(0, os.path.join(ROOT, "blender_addon"))
import astroray
print("engine:", astroray.__file__)
print("addon :", os.path.join(ROOT, "blender_addon"))

# Load the addon by file path (its top-level `from _bulk_geometry import ...`
# is satisfied by the blender_addon dir on sys.path above).
_spec = importlib.util.spec_from_file_location(
    "astroray_addon", os.path.join(ROOT, "blender_addon", "__init__.py"))
addon = importlib.util.module_from_spec(_spec)
sys.modules["astroray_addon"] = addon          # register() needs it importable
_spec.loader.exec_module(addon)
# Register so Scene.custom_raytracer exists (convert_scene reads it).
try:
    addon.register()
except Exception as exc:
    print(f"addon.register() warning: {exc}")
Engine = addon.CustomRaytracerRenderEngine


def _make_engine_standin():
    """A bpy RenderEngine subclass can't be instantiated outside the render
    pipeline, so mirror its plain-Python methods onto a standalone object."""
    class _S:
        def report(self, *a, **k):
            pass
    for name, fn in Engine.__dict__.items():
        if callable(fn) and not name.startswith("__"):
            setattr(_S, name, fn)
    return _S()


W = H = 120
SAMPLES = 24
MAX_DEPTH = 3
SEED = 424242
TRAVEL = 3.0     # world units travelled between frame 1 and frame 3


def build_scene(animate_object=False, animate_camera=False):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end = 1, 3
    scene.frame_set(2)

    bpy.ops.mesh.primitive_cube_add(size=0.8, location=(0.0, 0.0, 0.0))
    mover = bpy.context.object
    mover.name = "Mover"
    if animate_object:
        mover.location = (-TRAVEL / 2.0, 0.0, 0.0)
        mover.keyframe_insert(data_path="location", frame=1)
        mover.location = (TRAVEL / 2.0, 0.0, 0.0)
        mover.keyframe_insert(data_path="location", frame=3)
        # NOTE: Blender 4.4+ moved fcurves under action slots/layers, so the old
        # `action.fcurves` walk no longer exists. Default interpolation still
        # gives monotonic motion between two keys, which is all this needs --
        # it asserts motion FIRED, not the precise arc shape.
    scene.frame_set(2)

    # The world MUST be forced black, otherwise the default grey background
    # lights every column and the streak measurement is meaningless.
    world = bpy.data.worlds.new("W")
    world.use_nodes = False
    world.color = (0.0, 0.0, 0.0)
    scene.world = world

    light_data = bpy.data.lights.new("L", type='POINT')
    light_data.energy = 4000.0
    light = bpy.data.objects.new("L", light_data)
    light.location = (0.0, -6.0, 6.0)
    scene.collection.objects.link(light)

    cam_data = bpy.data.cameras.new("C")
    cam = bpy.data.objects.new("C", cam_data)
    cam.location = (0.0, -9.0, 0.0)
    cam.rotation_euler = (1.5708, 0.0, 0.0)
    scene.collection.objects.link(cam)
    if animate_camera:
        cam.location = (-TRAVEL / 2.0, -9.0, 0.0)
        cam.keyframe_insert(data_path="location", frame=1)
        cam.location = (TRAVEL / 2.0, -9.0, 0.0)
        cam.keyframe_insert(data_path="location", frame=3)
    scene.camera = cam
    scene.render.resolution_x = W
    scene.render.resolution_y = H
    scene.frame_set(2)
    return scene


def render(position, shutter, animate_object=False, animate_camera=False):
    scene = build_scene(animate_object=animate_object,
                        animate_camera=animate_camera)
    rs = scene.render
    if position is None:
        rs.use_motion_blur = False
    else:
        rs.use_motion_blur = True
        rs.motion_blur_shutter = shutter
        rs.motion_blur_position = position
    st = _make_engine_standin()
    r = astroray.Renderer()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    # NOTE: convert_scene is called with NO prior setup_camera on purpose.
    # convert_scene owns camera setup and must establish it before uploading
    # motion blur; pre-calling setup_camera here would mask exactly the
    # regression this script exists to catch.
    st.convert_scene(depsgraph, r, W, H)   # (self, depsgraph, renderer, width, height)
    r.set_seed(SEED)
    img = np.asarray(r.render(SAMPLES, MAX_DEPTH, None, False), dtype=np.float32)
    return img


def lit_columns(img, thresh_frac=0.5):
    lum = 0.2126 * img[..., 0] + 0.7152 * img[..., 1] + 0.0722 * img[..., 2]
    col = lum.max(axis=0)
    if col.max() <= 0.0:
        return 0, (None, None)
    idx = np.nonzero(col > col.max() * thresh_frac)[0]
    if idx.size == 0:
        return 0, (None, None)
    return int(idx[-1] - idx[0] + 1), (int(idx[0]), int(idx[-1]))


def main():
    results = {}
    ok = True

    static_img = render(None, 0.0)
    sw, srange = lit_columns(static_img)
    results["static"] = sw
    print(f"static  (no animation, no blur) width={sw:>4} range={srange}")
    if sw <= 0:
        print("  FAIL: static cube not visible -- scene/camera broken")
        ok = False

    print()
    print("--- OBJECT motion blur (pkg88-B) ---")
    for pos in ("START", "CENTER", "END"):
        img = render(pos, 0.5, animate_object=True)
        w, rng = lit_columns(img)
        results[pos] = w
        fired = w > sw + 2
        ok = ok and fired
        print(f"{pos:<7} width={w:>4} range={rng}  motion fired: "
              f"{'YES' if fired else 'NO'}")

    print()
    print("--- CAMERA motion blur (pkg88-A regression) ---")
    cam_img = render("CENTER", 0.5, animate_camera=True)
    cw, crng = lit_columns(cam_img)
    results["camera_CENTER"] = cw
    cam_fired = cw > sw + 2
    ok = ok and cam_fired
    print(f"CENTER  width={cw:>4} range={crng}  camera blur fired: "
          f"{'YES' if cam_fired else 'NO'}")

    print()
    print(f"PKG88B_BLENDER_RESULT {'PASS' if ok else 'FAIL'}")
    print("PKG88B_WIDTHS " + repr(results))
    if not ok:
        sys.exit(1)


# Blender's `--python` swallows unhandled exceptions and still QUITS 0, so a
# bare crash here (e.g. the "Camera not set up" regression this script guards)
# would look like success to any automated runner. Convert it into an explicit
# FAIL line + nonzero exit. Callers should still gate on the string
# "PKG88B_BLENDER_RESULT PASS" rather than on the exit code alone.
try:
    main()
except SystemExit:
    raise
except BaseException as exc:
    import traceback
    traceback.print_exc()
    print()
    print("PKG88B_BLENDER_RESULT FAIL")
    print(f"PKG88B_ERROR {type(exc).__name__}: {exc}")
    sys.exit(1)
