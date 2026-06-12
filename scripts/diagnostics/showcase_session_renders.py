"""Session showcase renders — 2026-06 stabilization (timed).

Renders the new-feature showcase set with the full build and appends one
JSON record per render to test_results/showcase_2026-06/render_timings.json:
{scene, resolution, spp, max_depth, integrator, device, wall_s, out, notes}.

Scenes:
  contact_sheet  — pkg55 perf-gate 7-material sheet: GPU megakernel vs GPU
                   wavefront vs CPU at the 256x256/512spp gate config, plus
                   1024x1024 GPU-only hires legs.
  instancing     — pkg114 two-level BVH: 3 base meshes x 432 instances (GPU).
  light_tree     — pkg86-B: 128 emissive quads, set_light_sampler("tree") (GPU).
  motion_blur    — pkg88-C.0 deformation motion blur: translating boxes (CPU+GPU).

Usage:
  python scripts/diagnostics/showcase_session_renders.py [--scenes a b ...] [--quick]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests"))
import runtime_setup  # noqa: E402

runtime_setup.configure_test_imports()
import astroray  # noqa: E402

sys.path.insert(0, str(REPO / "tests" / "scenes"))
import disney_contact_sheet  # noqa: E402

OUT_DIR = REPO / "test_results" / "showcase_2026-06"
TIMING_LOG = OUT_DIR / "render_timings.json"


def log_timing(rec: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    records = []
    if TIMING_LOG.exists():
        records = json.loads(TIMING_LOG.read_text())
    records.append(rec)
    TIMING_LOG.write_text(json.dumps(records, indent=2))
    print(f"[timing] {rec['scene']} {rec['integrator']}/{rec['device']} "
          f"{rec['resolution']} {rec['spp']}spp -> {rec['wall_s']:.2f}s")


def save_png(img, path: Path) -> None:
    from PIL import Image
    arr = np.asarray(img)
    if arr.ndim == 1:  # flat buffer fallback
        n = arr.size // 3
        side = int(math.sqrt(n))
        arr = arr.reshape(side, side, 3)
    Image.fromarray((np.clip(arr, 0.0, 1.0) * 255).astype(np.uint8)).save(path)
    print(f"[saved] {path}")


def timed_render(r, *, scene: str, spp: int, depth: int, integrator: str,
                 device: str, width: int, height: int, out_name: str,
                 notes: str = "") -> np.ndarray:
    t0 = time.perf_counter()
    img = r.render(spp, depth, None, True)
    wall = time.perf_counter() - t0
    out = OUT_DIR / out_name
    save_png(img, out)
    log_timing({
        "scene": scene, "resolution": f"{width}x{height}", "spp": spp,
        "max_depth": depth, "integrator": integrator, "device": device,
        "wall_s": round(wall, 3), "out": str(out.relative_to(REPO)),
        "notes": notes or "wall_s includes scene upload",
    })
    return img


# --------------------------------------------------------------------------- #
# contact sheet — megakernel vs wavefront vs CPU
# --------------------------------------------------------------------------- #
def run_contact_sheet(quick: bool) -> None:
    spp = 64 if quick else 512
    legs = [
        ("path_tracer", "gpu-megakernel", 256, 256, spp),
        ("wavefront_path_tracer", "gpu-wavefront", 256, 256, spp),
        ("path_tracer", "cpu", 256, 256, spp),
    ]
    if not quick:
        legs += [
            ("path_tracer", "gpu-megakernel", 1024, 1024, spp),
            ("wavefront_path_tracer", "gpu-wavefront", 1024, 1024, spp),
        ]
    for integrator, device, w, h, n in legs:
        r = astroray.Renderer()
        disney_contact_sheet.build_scene(r)
        disney_contact_sheet.setup_camera(r, width=w, height=h)
        r.set_seed(42)
        r.set_integrator(integrator)
        r.set_use_gpu(device.startswith("gpu"))
        timed_render(r, scene="disney_contact_sheet", spp=n, depth=8,
                     integrator=integrator, device=device, width=w, height=h,
                     out_name=f"contact_sheet_{device}_{w}.png",
                     notes="pkg55 perf-gate scene")


# --------------------------------------------------------------------------- #
# pkg114 instancing — 3 base meshes, 432 instances
# --------------------------------------------------------------------------- #
def _tetra(scale=0.45):
    s = scale
    v = np.array([[s, s, s], [s, -s, -s], [-s, s, -s], [-s, -s, s]], np.float32)
    f = [(0, 1, 2), (0, 3, 1), (0, 2, 3), (1, 3, 2)]
    return [tuple(np.concatenate([v[a], v[b], v[c]]).tolist()) for a, b, c in f]


def _octa(scale=0.45):
    s = scale
    v = np.array([[s, 0, 0], [-s, 0, 0], [0, s, 0], [0, -s, 0],
                  [0, 0, s], [0, 0, -s]], np.float32)
    f = [(0, 2, 4), (2, 1, 4), (1, 3, 4), (3, 0, 4),
         (2, 0, 5), (1, 2, 5), (3, 1, 5), (0, 3, 5)]
    return [tuple(np.concatenate([v[a], v[b], v[c]]).tolist()) for a, b, c in f]


def _cube(scale=0.35):
    s = scale
    c = np.array([[x, y, z] for x in (-s, s) for y in (-s, s) for z in (-s, s)],
                 np.float32)
    quads = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1),
             (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    tris = []
    for a, b, cc, d in quads:
        tris.append(tuple(np.concatenate([c[a], c[b], c[cc]]).tolist()))
        tris.append(tuple(np.concatenate([c[a], c[cc], c[d]]).tolist()))
    return tris


def _xform(tx, ty, tz, ry, s):
    cy, sy = math.cos(ry), math.sin(ry)
    return [s * cy, 0.0, s * sy, tx,
            0.0, s, 0.0, ty,
            -s * sy, 0.0, s * cy, tz,
            0.0, 0.0, 0.0, 1.0]


def run_instancing(quick: bool) -> None:
    r = astroray.Renderer()
    gold = r.create_material("metal", [0.95, 0.72, 0.32], {"roughness": 0.2})
    teal = r.create_material("disney", [0.15, 0.6, 0.65],
                             {"metallic": 0.1, "roughness": 0.35})
    coral = r.create_material("lambertian", [0.85, 0.4, 0.32], {})
    floor = r.create_material("lambertian", [0.55, 0.55, 0.58], {})
    light = r.create_material("light", [1.0, 0.95, 0.85], {"intensity": 5.0})

    mesh_ids = [r.register_mesh_triangles(_tetra(), gold, "tetra"),
                r.register_mesh_triangles(_octa(), teal, "octa"),
                r.register_mesh_triangles(_cube(), coral, "cube")]

    ext = 22.0
    r.add_triangle([-ext, -0.5, -ext], [ext, -0.5, -ext], [ext, -0.5, ext], floor)
    r.add_triangle([-ext, -0.5, -ext], [ext, -0.5, ext], [-ext, -0.5, ext], floor)
    r.add_triangle([-4, 9, -4], [4, 9, -4], [4, 9, 4], light)
    r.add_triangle([-4, 9, -4], [4, 9, 4], [-4, 9, 4], light)
    r.set_background_color([0.04, 0.05, 0.09])

    rng = np.random.default_rng(7)
    n_grid = 12
    count = 0
    for i in range(n_grid):
        for j in range(n_grid * 3):
            x = (i - n_grid / 2) * 1.4 + rng.uniform(-0.25, 0.25)
            z = -(j * 1.1) + 2.0 + rng.uniform(-0.2, 0.2)
            y = rng.uniform(-0.05, 0.65)
            ry = rng.uniform(0, 2 * math.pi)
            s = rng.uniform(0.55, 1.15)
            r.add_instance(mesh_ids[(i + j) % 3], _xform(x, y, z, ry, s))
            count += 1

    w = h = 512 if quick else 1024
    spp = 64 if quick else 512
    r.setup_camera([0.0, 4.2, 7.5], [0.0, 0.2, -10.0], [0, 1, 0],
                   55.0, 1.0, 0.02, 12.0, w, h)
    r.set_seed(42)
    r.set_integrator("path_tracer")
    r.set_use_gpu(True)
    timed_render(r, scene="pkg114_instancing_field", spp=spp, depth=8,
                 integrator="path_tracer", device="gpu-megakernel",
                 width=w, height=h, out_name="instancing_field.png",
                 notes=f"{count} instances of 3 shared BLAS meshes (pkg114)")


# --------------------------------------------------------------------------- #
# pkg86-B light tree — 128 emissive quads
# --------------------------------------------------------------------------- #
def run_light_tree(quick: bool) -> None:
    r = astroray.Renderer()
    floor = r.create_material("lambertian", [0.5, 0.5, 0.52], {})
    wall = r.create_material("lambertian", [0.42, 0.42, 0.46], {})
    ext = 20.0
    r.add_triangle([-ext, 0, -ext], [ext, 0, -ext], [ext, 0, ext], floor)
    r.add_triangle([-ext, 0, -ext], [ext, 0, ext], [-ext, 0, ext], floor)
    r.add_triangle([-ext, 0, -6], [ext, 0, -6], [ext, 9, -6], wall)
    r.add_triangle([-ext, 0, -6], [ext, 9, -6], [-ext, 9, -6], wall)

    rng = np.random.default_rng(11)
    n = 128
    for k in range(n):
        gx = (k % 16 - 7.5) * 2.2
        gz = (k // 16) * 1.6 - 4.0
        hue = rng.uniform(0, 1)
        col = [0.5 + 0.5 * math.sin(6.28 * (hue + o)) for o in (0.0, 0.33, 0.67)]
        m = r.create_material("light", col, {"intensity": float(rng.uniform(3, 9))})
        y = rng.uniform(1.2, 5.5)
        s = 0.28
        r.add_triangle([gx - s, y, gz - s], [gx + s, y, gz - s],
                       [gx + s, y, gz + s], m)
        r.add_triangle([gx - s, y, gz - s], [gx + s, y, gz + s],
                       [gx - s, y, gz + s], m)

    probe = r.create_material("metal", [0.9, 0.9, 0.92], {"roughness": 0.08})
    matte = r.create_material("lambertian", [0.8, 0.78, 0.75], {})
    glass = r.create_material("dielectric", [1, 1, 1], {"ior": 1.5})
    r.add_sphere([-2.6, 1.0, 1.5], 1.0, probe)
    r.add_sphere([0.0, 1.0, 0.5], 1.0, matte)
    r.add_sphere([2.6, 1.0, 1.5], 1.0, glass)
    r.set_background_color([0.01, 0.012, 0.02])

    w = h = 512 if quick else 1024
    spp = 64 if quick else 512
    r.setup_camera([0.0, 3.0, 10.5], [0.0, 1.2, -2.0], [0, 1, 0],
                   42.0, 1.0, 0.0, 10.0, w, h)
    r.set_seed(42)
    r.set_light_sampler("tree")
    r.set_integrator("path_tracer")
    r.set_use_gpu(True)
    timed_render(r, scene="pkg86b_light_tree_128", spp=spp, depth=6,
                 integrator="path_tracer", device="gpu-megakernel",
                 width=w, height=h, out_name="light_tree_128.png",
                 notes=f"128 area lights, light-tree NEE, upload_ms="
                       f"{r.get_light_tree_upload_ms():.3f} (pre-render)")


# --------------------------------------------------------------------------- #
# pkg88-C.0 deformation motion blur
# --------------------------------------------------------------------------- #
def _box_tris(cx, cy, cz, sx, sy, sz):
    c = np.array([[cx + dx * sx, cy + dy * sy, cz + dz * sz]
                  for dx in (-1, 1) for dy in (-1, 1) for dz in (-1, 1)],
                 np.float32)
    quads = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1),
             (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    tris = []
    for a, b, cc, d in quads:
        tris.append(np.stack([c[a], c[b], c[cc]]))
        tris.append(np.stack([c[a], c[cc], c[d]]))
    return np.stack(tris)  # (12,3,3)


def run_motion_blur(quick: bool) -> None:
    for device in ("cpu", "gpu-megakernel"):
        r = astroray.Renderer()
        floor = r.create_material("lambertian", [0.55, 0.55, 0.58], {})
        r.add_triangle([-12, -1.0, -12], [12, -1.0, -12], [12, -1.0, 8], floor)
        r.add_triangle([-12, -1.0, -12], [12, -1.0, 8], [-12, -1.0, 8], floor)
        light = r.create_material("light", [1, 1, 1], {"intensity": 7.0})
        r.add_triangle([-3, 6, -3], [3, 6, -3], [3, 6, 1], light)
        r.add_triangle([-3, 6, -3], [3, 6, 1], [-3, 6, 1], light)
        r.set_background_color([0.05, 0.06, 0.09])

        empty_uv = np.zeros((0,), np.float32)
        empty_n = np.zeros((0,), np.float32)

        specs = [  # (center, size, velocity, color)
            ((-2.2, 0.0, -2.0), (0.5, 0.5, 0.5), (1.8, 0.0, 0.0), [0.85, 0.30, 0.25]),
            ((0.0, 0.6, -3.0), (0.4, 0.4, 0.4), (0.0, 1.4, 0.0), [0.30, 0.65, 0.85]),
            ((2.2, 0.0, -2.0), (0.5, 0.5, 0.5), (-0.9, 0.7, 0.6), [0.95, 0.75, 0.30]),
        ]
        for (cx, cy, cz), (sx, sy, sz), (vx, vy, vz), col in specs:
            m = r.create_material("disney", col, {"roughness": 0.4, "metallic": 0.1})
            tris = _box_tris(cx, cy, cz, sx, sy, sz)
            mids = np.full((tris.shape[0],), m, np.int32)
            mpass = np.zeros((tris.shape[0],), np.int32)
            end = tris + np.array([vx, vy, vz], np.float32)
            r.add_triangles_bulk_motion(tris, end, mids, mpass, 0,
                                        empty_uv, [], empty_n)

        # static reference sphere — stays sharp next to the streaks
        chrome = r.create_material("metal", [0.9, 0.9, 0.92], {"roughness": 0.05})
        r.add_sphere([0.0, -0.3, 0.5], 0.7, chrome)

        w = h = 512 if quick else 1024
        spp = 64 if quick else 512
        r.setup_camera([0.0, 1.6, 6.0], [0.0, 0.2, -2.0], [0, 1, 0],
                       45.0, 1.0, 0.0, 8.0, w, h)
        r.set_seed(42)
        r.set_integrator("path_tracer")
        r.set_use_gpu(device.startswith("gpu"))
        timed_render(r, scene="pkg88c0_deformation_mb", spp=spp, depth=6,
                     integrator="path_tracer", device=device, width=w, height=h,
                     out_name=f"motion_blur_{device}.png",
                     notes="3 translating boxes + static chrome sphere (pkg88-C.0)")


SCENES = {
    "contact_sheet": run_contact_sheet,
    "instancing": run_instancing,
    "light_tree": run_light_tree,
    "motion_blur": run_motion_blur,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenes", nargs="*", default=list(SCENES))
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name in args.scenes:
        print(f"\n===== {name} =====")
        SCENES[name](args.quick)


if __name__ == "__main__":
    main()
