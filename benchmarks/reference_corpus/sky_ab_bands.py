"""pkg256 / #799 — Cycles vs Preetham/Perez sky-band A/B (run inside Blender).

Renders the corpus scene ``world_sky_sky.blend`` in Cycles at low res, bakes
the SAME Sky-Texture node with ``blender_addon/sky_bake.py``, projects the
baked equirect into the camera, and prints per-band mean colour + luminance
ratios (upper-sky and horizon). Consumed by
``tests/test_pkg256_sky_bake.py::test_sky_band_luminance_within_25pct_of_cycles``
(gated ±25% per-band luminance; per-channel colour differs by design —
Preetham warm horizon vs Cycles' Nishita blue).

#799 (part 1) — absolute exposure. Set ``PKG256_AB_MULTI=1`` to additionally
sweep several (sky_type, turbidity, sun-elevation) points and print one
``PKG256_AB_PT <json>`` line per point. The multi-point sweep is what shows
whether the luminance ratio drifts across turbidity/elevation (the fixed-fit
symptom, issue #799) or holds inside a documented band. The default single
run (blend-native params) still prints ``PKG256_AB`` / ``PKG256_SUNCOL`` for
the legacy gates, so the existing tests are unchanged.

Run:  blender -b --factory-startup --python benchmarks/reference_corpus/sky_ab_bands.py
"""
import json
import math
import os
import sys
import tempfile

import bpy
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "blender_addon"))
import sky_bake

BLEND = os.path.join(REPO, "benchmarks", "reference_corpus", "scenes", "world_sky_sky.blend")
RES_X, RES_Y, SAMPLES = 240, 135, 48

bpy.ops.wm.open_mainfile(filepath=BLEND)
scene = bpy.context.scene
scene.render.engine = "CYCLES"
if hasattr(scene, "cycles"):
    scene.cycles.device = "CPU"
scene.cycles.samples = SAMPLES
scene.render.resolution_x = RES_X
scene.render.resolution_y = RES_Y
scene.render.resolution_percentage = 100
scene.view_settings.view_transform = "Standard"
scene.view_settings.exposure = 0.0
scene.render.film_transparent = False

sky = next(n for n in scene.world.node_tree.nodes if n.type == "TEX_SKY")
strength = next(nn.inputs["Strength"].default_value
                for nn in scene.world.node_tree.nodes if nn.type == "BACKGROUND")

# Camera projection (fixed across all points).
cam = scene.camera
mw = cam.matrix_world
R = np.array([[mw[i][0], mw[i][1], mw[i][2]] for i in range(3)], dtype=np.float64)
fov_x = 2.0 * math.atan(cam.data.sensor_width / (2.0 * cam.data.lens))
tan_hx = math.tan(fov_x / 2.0)
tan_hy = tan_hx / (RES_X / RES_Y)

_EXR = os.path.join(tempfile.gettempdir(), "pkg256_sky_ab_cycles.exr")
scene.render.image_settings.file_format = "OPEN_EXR"
scene.render.image_settings.color_depth = "32"
scene.render.filepath = _EXR


def render_cycles():
    """Render the current scene state to EXR and return a top-down (h,w,3) array."""
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(_EXR)
    w, h = img.size
    px = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)[:, :, :3]
    bpy.data.images.remove(img)
    return px[::-1]  # Blender pixels are bottom-up


def make_bake_dir(bake, strength_):
    Hb, Wb = bake.shape[0], bake.shape[1]

    def bake_dir(dw):
        d = dw / (np.linalg.norm(dw) + 1e-12)
        theta = math.acos(min(max(float(d[2]), -1.0), 1.0))
        phi = math.atan2(-d[1], d[0])
        row = int(min(Hb - 1, max(0, theta / math.pi * Hb)))
        col = int(min(Wb - 1, max(0, ((0.5 + phi / (2 * math.pi)) % 1.0) * Wb)))
        return bake[row, col] * strength_
    return bake_dir


def band(px, bake_dir, w, h, y0f, y1f):
    r0, r1 = int(y0f * h), int(y1f * h)
    cyc = px[r0:r1].reshape(-1, 3).mean(axis=0)
    bk = np.zeros(3)
    cnt = 0
    for yy in range(r0, r1):
        for xx in range(0, w, 3):
            xnd = ((xx + 0.5) / w * 2 - 1) * tan_hx
            ynd = (1 - (yy + 0.5) / h * 2) * tan_hy
            bk += bake_dir(R @ np.array([xnd, ynd, -1.0]))
            cnt += 1
    return cyc, bk / cnt


def measure(sky_type, turbidity, elevation, rotation):
    """Set the sky node to the requested point, render Cycles, bake with the
    SAME params, and return per-band cycles/bake means + ratios."""
    sky.sky_type = sky_type
    if hasattr(sky, "turbidity"):
        sky.turbidity = turbidity
    sky.sun_elevation = elevation
    sky.sun_rotation = rotation
    px = render_cycles()
    h, w = px.shape[0], px.shape[1]
    bake = sky_bake.bake_params(sky_type, elevation, rotation,
                                turbidity=turbidity, width=1024, height=512)
    bake_dir = make_bake_dir(bake, strength)
    res = {}
    for name, (a, b) in {"upper_sky": (0.02, 0.12), "horizon": (0.22, 0.32)}.items():
        cyc, bk = band(px, bake_dir, w, h, a, b)
        res[name] = {"cycles_rgb": [round(float(x), 4) for x in cyc],
                     "bake_rgb": [round(float(x), 4) for x in bk],
                     "ratio_rgb": [round(float(x), 3) for x in bk / (cyc + 1e-6)],
                     "ratio_lum": round(float(bk.mean() / (cyc.mean() + 1e-6)), 3)}
    return px, bake, res


# --- Default point: the blend's native params (legacy gate lines) ------------
px, bake, res = measure(sky.sky_type, getattr(sky, "turbidity", 2.0),
                        sky.sun_elevation, sky.sun_rotation)
print("PKG256_AB " + json.dumps(res))

h, w = px.shape[0], px.shape[1]
bake_dir = make_bake_dir(bake, strength)

# --- Azimuth zero-reference A/B: brightest sky COLUMN, Cycles vs bake --------
# The per-band A/B above is azimuth-insensitive (it averages whole horizontal
# strips), so a +X/+Y sun-axis swap or a 90-degree azimuth error in the bake
# would pass it silently (PR #793 cycles-parity review item 3). Compare the
# brightest sky column of the Cycles render against the brightest column of
# the baked sky projected through the SAME camera: both must land on the same
# side of the frame (toward the sun). Restricted to the upper-sky rows to
# avoid the ground/horizon geometry.
sky_r0, sky_r1 = 0, int(0.35 * h)
cyc_cols = px[sky_r0:sky_r1].mean(axis=2).mean(axis=0)   # (w,) column-mean lum
bake_cols = np.zeros(w)
for xx in range(w):
    xnd = ((xx + 0.5) / w * 2 - 1) * tan_hx
    acc = 0.0
    n = 0
    for yy in range(sky_r0, sky_r1, 2):
        ynd = (1 - (yy + 0.5) / h * 2) * tan_hy
        acc += float(bake_dir(R @ np.array([xnd, ynd, -1.0])).mean())
        n += 1
    bake_cols[xx] = acc / max(n, 1)
cyc_col = int(np.argmax(cyc_cols))
bake_col = int(np.argmax(bake_cols))
dcol = min(abs(cyc_col - bake_col), w - abs(cyc_col - bake_col))
print("PKG256_SUNCOL " + json.dumps({
    "cycles_col": cyc_col, "bake_col": bake_col, "width": w,
    "dcol": dcol, "dcol_frac": round(dcol / w, 4)}))


# --- #799: multi-point absolute-exposure sweep ------------------------------
# Same PREETHAM sky_type across all points so turbidity is a native input to
# BOTH Cycles' legacy Preetham sky AND our bake (apples-to-apples). One
# PKG256_AB_PT line per (turbidity, elevation). The spread of ratio_lum across
# these points is the #799 drift metric.
if os.environ.get("PKG256_AB_MULTI") == "1":
    POINTS = [
        {"sky_type": "PREETHAM", "turbidity": 2.6, "elevation": 28.0, "rotation": 115.0},
        {"sky_type": "PREETHAM", "turbidity": 5.0, "elevation": 10.0, "rotation": 115.0},
        {"sky_type": "PREETHAM", "turbidity": 2.0, "elevation": 60.0, "rotation": 115.0},
    ]
    for pt in POINTS:
        _, _, r = measure(pt["sky_type"], pt["turbidity"],
                          math.radians(pt["elevation"]), math.radians(pt["rotation"]))
        print("PKG256_AB_PT " + json.dumps({
            "sky_type": pt["sky_type"], "turbidity": pt["turbidity"],
            "elevation": pt["elevation"],
            "upper_ratio_lum": r["upper_sky"]["ratio_lum"],
            "horizon_ratio_lum": r["horizon"]["ratio_lum"]}))
