"""pkg294 Phase 0 render driver (run inside Blender; reuses the canonical
benchmarks/blender_parity/render_leg.py bootstrap/configure/render helpers).

  blender --background <scene.blend> --python drive.py -- \
      --engine CYCLES|CUSTOM_RAYTRACER --tree on|off --samples 64 \
      --seeds 1,2,3 --out <dir> --tag <name>

Astroray variants are selected by ASTRORAY_PKG294_DIAG in the environment
(read once per process). Writes <out>/<tag>_s<seed>.npy and appends the
wall time of each bpy.ops.render.render to <out>/<tag>_times.json.
One-off verification script; delete when pkg294 closes.
"""
import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

import bpy

REPO = Path(__file__).resolve().parents[3]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", required=True)
    ap.add_argument("--tree", choices=("on", "off"), required=True)
    ap.add_argument("--samples", type=int, default=64)
    ap.add_argument("--seeds", default="1,2,3")
    ap.add_argument("--out", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--no-light-mis", action="store_true",
                    help="Cycles NEE-only: light.cycles.use_multiple_importance_sampling=False")
    ap.add_argument("--vol-sampling", default="",
                    help="Cycles material.cycles.volume_sampling (DISTANCE/EQUIANGULAR/MULTIPLE_IMPORTANCE)")
    ap.add_argument("--clamp-indirect", type=float, default=0.0,
                    help="scene.cycles.sample_clamp_indirect (0 = off; Blender default 10)")
    args = ap.parse_args(sys.argv[sys.argv.index("--") + 1:])

    spec = importlib.util.spec_from_file_location(
        "render_leg", REPO / "benchmarks" / "blender_parity" / "render_leg.py")
    leg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(leg)

    scene = bpy.context.scene
    if args.no_light_mis:
        for light in bpy.data.lights:
            light.cycles.use_multiple_importance_sampling = False
    if args.vol_sampling:
        for mat in bpy.data.materials:
            mat.cycles.volume_sampling = args.vol_sampling
    if args.engine == "CUSTOM_RAYTRACER":
        astroray, _ = leg._bootstrap_astroray_addon(REPO)
        print("[pkg294] module", astroray.__file__, flush=True)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    times = {}
    for seed in (int(s) for s in args.seeds.split(",")):
        leg._configure_render(scene, args.engine, scene.render.resolution_x, args.samples,
                              "cpu", res_y=scene.render.resolution_y, seed=seed)
        scene.cycles.use_light_tree = args.tree == "on"
        scene.cycles.sample_clamp_direct = 0.0
        scene.cycles.sample_clamp_indirect = args.clamp_indirect
        scene.cycles.device = "CPU"
        t0 = time.perf_counter()
        leg._render_to_npy(bpy, scene, out / f"{args.tag}_s{seed}", scene.render.resolution_x)
        times[seed] = time.perf_counter() - t0
        print(f"[pkg294] {args.tag} seed {seed}: {times[seed]:.2f} s", flush=True)
    (out / f"{args.tag}_times.json").write_text(json.dumps(times))
    print("PKG294_DRIVE_DONE", flush=True)


main()
