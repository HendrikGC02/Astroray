"""pkg296 (#833) -- multi-seed ROI means of the ``volumes_mesh`` corpus scenes
(runs INSIDE Blender; one process renders every requested scene/seed/bounce).

For each scene id (``vm_*`` in ``scenes/manifest.json``), each
``volume_bounces`` value and each seed: open the committed ``.blend``, render
with the chosen engine (``render_leg.py``'s configure/render helpers, linear,
row 0 = top), record the per-ROI per-channel means (manifest ``crops``) and the
wall time, and save the seed-mean image as ``<npy-dir>/<scene>_b<N>_<engine>.npy``.
Writes one JSON: ``{scene: {"b<N>": {"rois": {roi: [[r,g,b] per seed]},
"time_s": [...]}}}``.

Cycles references (committed as ``refs_v2/volumes_mesh_cycles.json`` + the
icosphere silhouette mask) come from ``--engine CYCLES``; the pkg296 gate test
runs ``--engine CUSTOM_RAYTRACER --device cpu`` and compares.

    blender -b --factory-startup --python volumes_mesh_bands.py -- \
        --engine CYCLES --scenes vm_icosphere vm_suzanne --seeds 278 279 280 281 282 \
        --bounces 0 4 --spp 128 --out-json <path> --npy-dir <dir>

Astroray legs load the ``.pyd`` from ``ASTRORAY_PYD_DIR`` (render_leg.py).
"""
import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "benchmarks" / "blender_parity"))
MANIFEST = REPO / "benchmarks" / "reference_corpus" / "scenes" / "manifest.json"
SENTINEL = "PKG296_BANDS"


def roi_means(img, rect):
    h, w = img.shape[:2]
    x0, y0, x1, y1 = rect
    box = img[round(y0 * h):round(y1 * h), round(x0 * w):round(x1 * w)]
    return box.reshape(-1, 3).mean(axis=0)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--engine", choices=("CYCLES", "CUSTOM_RAYTRACER"), required=True)
    p.add_argument("--device", choices=("cpu", "gpu"), default="cpu")
    p.add_argument("--scenes", nargs="+", required=True)
    p.add_argument("--seeds", nargs="+", type=int, default=[278, 279, 280, 281, 282])
    p.add_argument("--bounces", nargs="+", type=int, default=[0, 4])
    p.add_argument("--spp", type=int, default=128)
    p.add_argument("--out-json", required=True)
    p.add_argument("--npy-dir", required=True)
    a = p.parse_args(argv)
    if any(s <= 0 for s in a.seeds):
        raise SystemExit("seeds must be non-zero (0 is the random sentinel)")

    import bpy
    import numpy as np
    import render_leg as rl

    if a.engine == "CUSTOM_RAYTRACER":
        # ASTRORAY_ADDON_ROOT: a dir holding another blender_addon/ (e.g. main's,
        # for the before/after regression evidence); default = this checkout.
        import os
        rl._bootstrap_astroray_addon(Path(os.environ.get("ASTRORAY_ADDON_ROOT", str(REPO))))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))["scenes"]
    npy_dir = Path(a.npy_dir)
    npy_dir.mkdir(parents=True, exist_ok=True)
    tag = "cycles" if a.engine == "CYCLES" else "astroray_" + a.device
    out = {}
    for sid in a.scenes:
        e = manifest[sid]
        out[sid] = {}
        for nb in a.bounces:
            acc, rois, times = None, {k: [] for k in e["crops"]}, []
            for seed in a.seeds:
                bpy.ops.wm.open_mainfile(filepath=str(REPO / e["blend_path"]))
                scene = bpy.context.scene
                rl._configure_render(scene, a.engine, e["settings"]["res_x"], a.spp, a.device,
                                     res_y=e["settings"]["res_y"], seed=seed)
                scene.cycles.volume_bounces = nb
                t0 = time.perf_counter()
                npy = rl._render_to_npy(bpy, scene, npy_dir / f"_tmp_{sid}", e["settings"]["res_x"])
                times.append(time.perf_counter() - t0)
                img = np.load(npy).astype(np.float64)
                acc = img if acc is None else acc + img
                for k, rect in e["crops"].items():
                    rois[k].append(roi_means(img, rect).tolist())
                print(f"[pkg296] {sid} b{nb} seed {seed}: {times[-1]:.1f}s", flush=True)
            np.save(npy_dir / f"{sid}_b{nb}_{tag}.npy", (acc / len(a.seeds)).astype(np.float32))
            out[sid][f"b{nb}"] = {"rois": rois, "time_s": times}
    meta = {"engine": a.engine, "device": a.device, "spp": a.spp, "seeds": a.seeds,
            "bounces": a.bounces, "blender_version": bpy.app.version_string}
    Path(a.out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out_json).write_text(json.dumps({"meta": meta, "scenes": out}, indent=1) + "\n",
                                encoding="utf-8", newline="\n")
    print(f"{SENTINEL} PASS", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 - Blender swallows tracebacks; the sentinel is the contract
        import traceback
        traceback.print_exc()
        print(f"{SENTINEL} FAIL", flush=True)
