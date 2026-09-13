# Blender-side: render the corpus world_sky_sky scene in Cycles at 3 sun
# elevations (MULTIPLE_SCATTERING), project the pre-baked astroray nishita_sky
# equirect into the same camera, and print per-band luminance ratios (batch-J
# #799 gate 1). Reuses the proven projection from sky_ab_bands.py.
import json
import math
import os

import bpy
import numpy as np

REPO = os.environ["BJ_REPO"]
OUT = os.environ["BJ_OUT"]
MODE = "MULTIPLE_SCATTERING"
ROT_DEG = 115.0
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
sky.sky_type = MODE
sky.sun_rotation = math.radians(ROT_DEG)
sky.sun_disc = False  # sky-only gate
strength = next(nn.inputs["Strength"].default_value
                for nn in scene.world.node_tree.nodes if nn.type == "BACKGROUND")

cam = scene.camera
mw = cam.matrix_world
R = np.array([[mw[i][0], mw[i][1], mw[i][2]] for i in range(3)], dtype=np.float64)
fov_x = 2.0 * math.atan(cam.data.sensor_width / (2.0 * cam.data.lens))
tan_hx = math.tan(fov_x / 2.0)
tan_hy = tan_hx / (RES_X / RES_Y)

_EXR = os.path.join(OUT, "bj_cyc.exr")
scene.render.image_settings.file_format = "OPEN_EXR"
scene.render.image_settings.color_depth = "32"
scene.render.filepath = _EXR


def render_cycles():
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(_EXR)
    w, h = img.size
    px = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)[:, :, :3]
    bpy.data.images.remove(img)
    return px[::-1]


def make_bake_dir(bake):
    Hb, Wb = bake.shape[0], bake.shape[1]
    def bake_dir(dw):
        d = dw / (np.linalg.norm(dw) + 1e-12)
        theta = math.acos(min(max(float(d[2]), -1.0), 1.0))
        phi = math.atan2(-d[1], d[0])
        row = int(min(Hb - 1, max(0, theta / math.pi * Hb)))
        col = int(min(Wb - 1, max(0, ((0.5 + phi / (2 * math.pi)) % 1.0) * Wb)))
        return bake[row, col] * strength
    return bake_dir


def band(px, bake_dir, w, h, y0f, y1f):
    r0, r1 = int(y0f * h), int(y1f * h)
    cyc = px[r0:r1].reshape(-1, 3).mean(axis=0)
    bk = np.zeros(3); cnt = 0
    for yy in range(r0, r1):
        for xx in range(0, w, 3):
            xnd = ((xx + 0.5) / w * 2 - 1) * tan_hx
            ynd = (1 - (yy + 0.5) / h * 2) * tan_hy
            bk += bake_dir(R @ np.array([xnd, ynd, -1.0]))
            cnt += 1
    return cyc, bk / cnt


results = []
for elev in (10.0, 28.0, 60.0):
    sky.sun_elevation = math.radians(elev)
    px = render_cycles()
    h, w = px.shape[0], px.shape[1]
    bake = np.load(os.path.join(OUT, "astro_%s_e%02d.npy" % (MODE, int(elev))))
    bdir = make_bake_dir(bake)
    row = {"elev": elev, "bands": {}}
    for nm, (a, b) in {"upper_sky": (0.02, 0.12), "horizon": (0.22, 0.32)}.items():
        cyc, bk = band(px, bdir, w, h, a, b)
        ratio = float(bk.mean() / (cyc.mean() + 1e-9))
        row["bands"][nm] = {"cyc": [round(float(x), 4) for x in cyc],
                            "astro": [round(float(x), 4) for x in bk],
                            "ratio_lum": round(ratio, 4)}
    results.append(row)
    print("BJ_BAND", json.dumps(row))

with open(os.path.join(OUT, "bj_band_results.json"), "w") as fh:
    json.dump(results, fh, indent=2)
print("BJ_BANDS_DONE")
