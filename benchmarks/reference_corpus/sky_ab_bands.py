"""pkg256 — Cycles vs Preetham/Perez sky-band A/B (run inside Blender).

Renders the corpus scene ``world_sky_sky.blend`` in Cycles at low res, bakes
the SAME Sky-Texture node with ``blender_addon/sky_bake.py``, projects the
baked equirect into the camera, and prints per-band mean colour + luminance
ratios (upper-sky and horizon). Consumed by
``tests/test_pkg256_sky_bake.py::test_sky_band_luminance_within_25pct_of_cycles``
(gated ±25% per-band luminance; per-channel colour differs by design —
Preetham warm horizon vs Cycles' Nishita blue).

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

out = os.path.join(tempfile.gettempdir(), "pkg256_sky_ab_cycles.exr")
scene.render.image_settings.file_format = "OPEN_EXR"
scene.render.image_settings.color_depth = "32"
scene.render.filepath = out
bpy.ops.render.render(write_still=True)

img = bpy.data.images.load(out)
w, h = img.size
px = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)[:, :, :3]
px = px[::-1]  # Blender pixels are bottom-up

cam = scene.camera
mw = cam.matrix_world
R = np.array([[mw[i][0], mw[i][1], mw[i][2]] for i in range(3)], dtype=np.float64)
fov_x = 2.0 * math.atan(cam.data.sensor_width / (2.0 * cam.data.lens))
tan_hx = math.tan(fov_x / 2.0)
tan_hy = tan_hx / (RES_X / RES_Y)

bake = sky_bake.bake_params(sky.sky_type, sky.sun_elevation, sky.sun_rotation,
                            turbidity=sky.turbidity, width=1024, height=512)
Hb, Wb = bake.shape[0], bake.shape[1]


def bake_dir(dw):
    d = dw / (np.linalg.norm(dw) + 1e-12)
    theta = math.acos(min(max(float(d[2]), -1.0), 1.0))
    phi = math.atan2(-d[1], d[0])
    row = int(min(Hb - 1, max(0, theta / math.pi * Hb)))
    col = int(min(Wb - 1, max(0, ((0.5 + phi / (2 * math.pi)) % 1.0) * Wb)))
    return bake[row, col] * strength


def band(y0f, y1f):
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


res = {}
for name, (a, b) in {"upper_sky": (0.02, 0.12), "horizon": (0.22, 0.32)}.items():
    cyc, bk = band(a, b)
    res[name] = {"cycles_rgb": [round(float(x), 4) for x in cyc],
                 "bake_rgb": [round(float(x), 4) for x in bk],
                 "ratio_rgb": [round(float(x), 3) for x in bk / (cyc + 1e-6)],
                 "ratio_lum": round(float(bk.mean() / (cyc.mean() + 1e-6)), 3)}
print("PKG256_AB " + json.dumps(res))
