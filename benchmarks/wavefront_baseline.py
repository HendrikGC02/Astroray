#!/usr/bin/env python
"""pkg55 Phase A — wavefront SoA baseline measurement harness.

Spec: .astroray_plan/packages/pkg55-wavefront-soa-refactor.md (§ Phase A.0)

What this does:
  1. Sets ASTRORAY_PROFILE=1 + ASTRORAY_PROFILE_OUT=<per-scene .json>
     in a child process for each scene we want to measure.
  2. Renders each scene at a fixed (small but representative) spp using
     the existing GPU megakernel path (CUDARenderer::render).
  3. Reads each per-scene profile JSON written by the C++ aggregator
     and merges them into benchmarks/wavefront/baseline.json. That file
     is the published baseline pkg55 Phases B + C must beat.

Scenes (2): both already exist in the repo, so we don't depend on
pkg76 (`.blend` importer, still open) for Phase A. The brief originally
asked for "Cornell + Classroom (post-pkg76)"; Classroom is not yet
importable, so we substitute the existing high-material-diversity
Cornell-with-glass scene from the integrator_compare gallery.

  - cornell_diffuse:  convergence_grid.build_cornell — 3 lambertian
                      materials, 1 area light. Low material diversity,
                      easy reference for the megakernel.
  - cornell_glass:    integrator_compare.build_cornell_with_glass —
                      adds a dielectric sphere. 4 material types,
                      moderate divergence. This is the scene whose
                      shade-stage warp coherence Phase B must improve.

Reference patterns (cite, do not mirror):
  - intern/cycles/device/cuda/queue.cpp  — Cycles' per-launch event
    timing dumped via CUDADeviceQueue::print_render_kernels(). We
    follow the same "subprocess-per-scene; collect JSON" pattern.
  - PBRT-v4 src/pbrt/wavefront/integrator.cpp WAVEFRONT_PROFILER hooks.

Acceptance for Phase A.0 (this file is the gate):
  - benchmarks/wavefront/baseline.json populated with measured numbers
    for at least 2 scenes.
  - Each scene's record contains, per kernel:
        mean_ms, min_ms, max_ms, count, regs_per_thread,
        shared_mem_bytes, active_blocks_per_sm, launch_threads,
        launch_blocks.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "benchmarks" / "wavefront"
OUT_FILE = OUT_DIR / "baseline.json"

# (scene_id, scene_module, builder_name, default_resolution)
SCENES: list[tuple[str, str, str, int]] = [
    ("cornell_diffuse",
     "benchmarks.showcase.scenes.convergence_grid", "build_cornell", 256),
    ("cornell_glass",
     "benchmarks.showcase.scenes.integrator_compare",
     "build_cornell_with_glass", 256),
]


def render_one(scene_id: str, scene_module: str, builder_name: str,
               resolution: int, spp: int, max_depth: int,
               out_json: Path, soa_mode: str = "off") -> dict:
    """Spawn a subprocess that renders the scene with profiling on.

    Subprocess isolation matters: the C++ Aggregator dumps its JSON
    on static destruction at process exit. Doing it in-process across
    multiple scenes would either overwrite the file or accumulate all
    scenes' kernels into one bag.
    """
    out_json.parent.mkdir(parents=True, exist_ok=True)
    if out_json.exists():
        out_json.unlink()

    # The child renders the scene and exits. Importing astroray, the
    # registered scene builder, and CUDARenderer all happen in-process.
    code = f"""
import sys
from pathlib import Path
sys.path.insert(0, {str(ROOT / 'tests')!r})
sys.path.insert(0, {str(ROOT)!r})
import runtime_setup
runtime_setup.configure_test_imports()

import astroray
from importlib import import_module

mod = import_module({scene_module!r})
build = getattr(mod, {builder_name!r})

r = astroray.Renderer()
build(r, {resolution}, {resolution})

# Engage the GPU path. set_use_gpu returns None on success; CUDA
# absence surfaces as an exception from the first .render() call,
# which we propagate as exit code 2 so the parent records "skipped".
r.set_use_gpu(True)

WARMUP = 1
MEASURE = 5
try:
    for i in range(WARMUP + MEASURE):
        r.render({spp}, {max_depth}, None, False)
except RuntimeError as exc:
    msg = str(exc)
    if 'CUDA' in msg or 'GPU' in msg:
        print('[wavefront-baseline] CUDA unavailable: ' + msg, file=sys.stderr)
        sys.exit(2)
    raise
"""
    env = os.environ.copy()
    env["ASTRORAY_PROFILE"] = "1"
    env["ASTRORAY_PROFILE_OUT"] = str(out_json)
    if soa_mode == "on":
        # pkg55-A.1: dual-trace the wavefront SoA intersect alongside the
        # AoS megakernel. The build must be configured with
        # -DASTRORAY_WAVEFRONT_INTERSECT=ON for this to do anything.
        env["ASTRORAY_WAVEFRONT_INTERSECT_PARITY"] = "1"

    print(f"[wavefront-baseline] rendering {scene_id} "
          f"({resolution}x{resolution}, {spp} spp, soa={soa_mode})...")
    proc = subprocess.run(
        [sys.executable, "-c", code],
        env=env, capture_output=True, text=True,
    )
    if proc.returncode == 2:
        return {"scene": scene_id, "skipped": True,
                "reason": "CUDA unavailable"}
    if proc.returncode != 0:
        return {"scene": scene_id, "skipped": True,
                "reason": f"render failed (rc={proc.returncode})",
                "stderr": proc.stderr[-2000:]}
    if not out_json.exists():
        return {"scene": scene_id, "skipped": True,
                "reason": "profile JSON not written (ASTRORAY_PROFILE wired?)",
                "stderr": proc.stderr[-2000:]}

    data = json.loads(out_json.read_text())
    return {
        "scene": scene_id,
        "soa_mode": soa_mode,
        "resolution": [resolution, resolution],
        "spp": spp,
        "max_depth": max_depth,
        "warmup_runs": 1,
        "measure_runs": 5,
        "kernels": data.get("kernels", {}),
        "stderr_tail": proc.stderr[-2000:],
    }


def gpu_info() -> dict:
    """Best-effort GPU identification for the baseline record."""
    info: dict = {"platform": platform.platform()}
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,driver_version,memory.total",
             "--format=csv,noheader"], text=True, timeout=10)
        info["nvidia_smi"] = out.strip().splitlines()
    except Exception as exc:  # nvidia-smi missing or failed; not fatal
        info["nvidia_smi_error"] = f"{type(exc).__name__}: {exc}"
    return info


# ---------------------------------------------------------------------------
# pkg298 — Cornell pair vs Cycles (research-performance-2026-09-29 §1.1, P0).
# Both engines read the same triangles from .npy. Each Astroray measurement is
# a subprocess (the ASTRORAY_PROFILE aggregator dumps its JSON at exit).
# GPU clock drift ~5 % (memory gpu-perf-ab-clock-drift): burn-in + min-of-N.
# ---------------------------------------------------------------------------
PAIR_OUT = OUT_DIR / "pkg298_cornell_pair.json"
sys.path.insert(0, str(ROOT / "tests"))
from results_layout import results_dir  # noqa: E402  (test-results conventions)

SCENE_CACHE = results_dir("perf", "cornell-pair", create=False) / "scenes"
CYCLES_LEG = OUT_DIR / "cycles_leg.py"
# Material slots in the *_mid.npy arrays (shared with cycles_leg.py).
PAIR_MATERIALS = [
    ("white", [0.74, 0.74, 0.72], 0.0),
    ("red", [0.72, 0.08, 0.06], 0.0),
    ("green", [0.10, 0.50, 0.16], 0.0),
    ("light", [1.0, 1.0, 1.0], 18.0),
]
PAIR_CAMERA = {"look_from": [0.0, 0.0, 6.8], "look_at": [0.0, 0.0, 0.0], "vfov": 39.6}
TRAVERSAL: str | None = None   # pkg299: set by --traversal (None = engine default)


def _cornell_tris() -> list[tuple[list, int]]:
    """12-triangle Cornell (box +-2, light quad at y = 1.98, side +-0.5)."""
    q = []

    def quad(a, b, c, d, m):
        q.append(([a, b, c], m))
        q.append(([a, c, d], m))

    quad([-2, -2, -2], [2, -2, -2], [2, -2, 2], [-2, -2, 2], 0)   # floor
    quad([-2, 2, -2], [-2, 2, 2], [2, 2, 2], [2, 2, -2], 0)       # ceiling
    quad([-2, -2, -2], [-2, 2, -2], [2, 2, -2], [2, -2, -2], 0)   # back
    quad([-2, -2, -2], [-2, -2, 2], [-2, 2, 2], [-2, 2, -2], 1)   # left, red
    quad([2, -2, -2], [2, 2, -2], [2, 2, 2], [2, -2, 2], 2)       # right, green
    quad([-0.5, 1.98, -0.5], [0.5, 1.98, -0.5], [0.5, 1.98, 0.5], [-0.5, 1.98, 0.5], 3)
    return q


def _displaced_sphere(center, radius, n):
    """UV sphere, n latitude x 2n longitude quads, r(1 + a sin9t sin11p + ...)."""
    import numpy as np
    th = np.linspace(0.0, np.pi, n + 1)
    ph = np.linspace(0.0, 2.0 * np.pi, 2 * n + 1)
    T, P = np.meshgrid(th, ph, indexing="ij")
    r = radius * (1.0 + 0.06 * np.sin(9 * T) * np.sin(11 * P)
                  + 0.03 * np.sin(23 * T) * np.cos(17 * P))
    xyz = np.stack([r * np.sin(T) * np.cos(P), r * np.cos(T),
                    r * np.sin(T) * np.sin(P)], axis=-1) + np.asarray(center)
    a, b = xyz[:-1, :-1], xyz[1:, :-1]
    c, d = xyz[1:, 1:], xyz[:-1, 1:]
    t0 = np.stack([a, b, c], axis=2).reshape(-1, 3, 3)
    t1 = np.stack([a, c, d], axis=2).reshape(-1, 3, 3)
    return np.concatenate([t0, t1], axis=0)


def write_cornell_npy(kind: str, out_dir: Path = SCENE_CACHE) -> tuple[Path, Path]:
    """Write <kind>_pos.npy (N,3,3) float32 + <kind>_mid.npy (N,) int32.

    kind 'simple' = 12 triangles; 'heavy' adds two displaced spheres at n=500
    (2,000,012 triangles). Deterministic, so reruns are byte-identical."""
    import numpy as np
    out_dir.mkdir(parents=True, exist_ok=True)
    pos_p, mid_p = out_dir / f"{kind}_pos.npy", out_dir / f"{kind}_mid.npy"
    if pos_p.exists() and mid_p.exists():
        return pos_p, mid_p
    tris = _cornell_tris()
    pos = [np.asarray([t for t, _ in tris], dtype=np.float32)]
    mid = [np.asarray([m for _, m in tris], dtype=np.int32)]
    if kind == "heavy":
        for c, r in (([-0.85, -1.2, 0.3], 0.8), ([0.9, -1.3, -0.5], 0.7)):
            s = _displaced_sphere(c, r, 500).astype(np.float32)
            pos.append(s)
            mid.append(np.zeros(len(s), dtype=np.int32))
    elif kind != "simple":
        raise ValueError(kind)
    np.save(pos_p, np.concatenate(pos))
    np.save(mid_p, np.concatenate(mid))
    return pos_p, mid_p


def _astro_child(cfg: dict) -> None:
    """Runs in a subprocess: build the pair scene, time render() calls, print JSON."""
    import time
    sys.path.insert(0, str(ROOT / "tests"))
    sys.path.insert(0, str(ROOT))
    import runtime_setup
    runtime_setup.configure_test_imports()
    import numpy as np
    import astroray

    pos = np.load(cfg["pos"])
    mid = np.load(cfg["mid"])
    r = astroray.Renderer()
    res = cfg["res"]
    cam = PAIR_CAMERA
    r.setup_camera(look_from=cam["look_from"], look_at=cam["look_at"],
                   vup=[0.0, 1.0, 0.0], vfov=cam["vfov"], aspect_ratio=1.0,
                   aperture=0.0, focus_dist=6.8, width=res, height=res)
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_seed(1234)
    r.set_adaptive_sampling(False)
    ids = []
    for _, col, strength in PAIR_MATERIALS:
        if strength > 0:
            ids.append(r.create_material("light", col, {"intensity": strength}))
        else:
            ids.append(r.create_material("lambertian", col, {}))
    eng = np.asarray(ids, dtype=np.int32)[mid]
    n = len(pos)
    r.add_triangles_bulk(pos, eng, np.zeros(n, np.int32), 0,
                         np.zeros((0, n, 3, 2), np.float32), [],
                         np.zeros((0, 3, 3), np.float32))
    if cfg["device"] == "gpu":
        r.set_use_gpu(True)
    out = {"calls": []}
    img = None
    for _ in range(cfg["calls"]):
        t0 = time.perf_counter()
        img = r.render(cfg["spp"], cfg["depth"], None, False)
        wall = time.perf_counter() - t0
        st = r.get_scene_stats()
        out["calls"].append({"wall_s": wall,
                             "bvh_build_count": st.get("bvh_build_count"),
                             "bvh_build_ms": r.last_render_info().get("bvh_build_ms")})
    if cfg.get("save_img"):
        np.save(cfg["save_img"], np.asarray(img, dtype=np.float32))
    out["triangles"] = int(n)
    out["module"] = astroray.__file__
    out["gpu_traversal"] = r.last_render_info().get("gpu_traversal")  # pkg299
    print("PKG298_JSON " + json.dumps(out))


def run_astro(kind: str, device: str, res: int, spp: int, depth: int, calls: int,
              profile_json: Path | None = None, save_img: Path | None = None,
              extra_env: dict | None = None) -> dict:
    pos, mid = write_cornell_npy(kind)
    cfg = {"pos": str(pos), "mid": str(mid), "device": device, "res": res,
           "spp": spp, "depth": depth, "calls": calls,
           "save_img": str(save_img) if save_img else None}
    env = os.environ.copy()
    env.setdefault("OMP_NUM_THREADS", "8")
    if TRAVERSAL:   # pkg299: --traversal software|optix -> ASTRORAY_GPU_TRAVERSAL
        env["ASTRORAY_GPU_TRAVERSAL"] = TRAVERSAL
    if profile_json:
        profile_json.parent.mkdir(parents=True, exist_ok=True)
        if profile_json.exists():
            profile_json.unlink()
        env["ASTRORAY_PROFILE"] = "1"
        env["ASTRORAY_PROFILE_OUT"] = str(profile_json)
    env.update(extra_env or {})
    proc = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                           "--_astro-child", json.dumps(cfg)],
                          env=env, capture_output=True, text=True)
    line = next((ln for ln in proc.stdout.splitlines()
                 if ln.startswith("PKG298_JSON ")), None)
    if proc.returncode != 0 or line is None:
        return {"skipped": True, "reason": f"rc={proc.returncode}",
                "stderr": proc.stderr[-2000:]}
    rec = json.loads(line[len("PKG298_JSON "):])
    rec.update({"engine": "astroray", "scene": kind, "device": device,
                "res": res, "spp": spp, "depth": depth})
    rec["stderr_tail"] = proc.stderr[-2000:]
    if profile_json and profile_json.exists():
        k = json.loads(profile_json.read_text()).get("kernels", {})
        rec["kernel_sum_ms"] = sum(v["sum_ms"] for n, v in k.items()
                                   if not n.startswith("host:"))
        rec["host_ms"] = {n: v["sum_ms"] for n, v in k.items() if n.startswith("host:")}
    return rec


def run_cycles(kind: str, device: str, res: int, spp: int, depth: int, calls: int,
               blender: str) -> dict:
    pos, mid = write_cornell_npy(kind)
    cfg = {"pos": str(pos), "mid": str(mid), "device": device, "res": res,
           "spp": spp, "depth": depth, "calls": calls,
           "camera": PAIR_CAMERA, "materials": PAIR_MATERIALS}
    proc = subprocess.run([blender, "-b", "--factory-startup", "--python",
                           str(CYCLES_LEG), "--", json.dumps(cfg)],
                          capture_output=True, text=True)
    line = next((ln for ln in proc.stdout.splitlines()
                 if ln.startswith("PKG298_JSON ")), None)
    if proc.returncode != 0 or line is None:
        return {"skipped": True, "reason": f"rc={proc.returncode}",
                "stderr": (proc.stderr or proc.stdout)[-2000:]}
    rec = json.loads(line[len("PKG298_JSON "):])
    rec.update({"engine": "cycles", "scene": kind, "device": device,
                "res": res, "spp": spp, "depth": depth})
    return rec


def _warm_min(rec: dict) -> float | None:
    """Min wall time over the warm calls (first call dropped)."""
    calls = rec.get("calls") or []
    warm = [c["wall_s"] for c in calls[1:]] or [c["wall_s"] for c in calls]
    return min(warm) if warm else None


def pair_main(args) -> int:
    record = {
        "schema": "astroray.pkg298.cornell_pair.v1",
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "git_sha": _git_sha(), "gpu": gpu_info(),
        "args": {k: (str(v) if isinstance(v, Path) else v) for k, v in vars(args).items()},
        "fixed_cost": [], "full": [], "pool": [],
    }
    devices = [d for d in args.devices.split(",") if d]
    prof = SCENE_CACHE.parent / "profile"
    # 1) Fixed per-call cost: 16^2, 1 spp, first call + warm repeats.
    for kind in ("simple", "heavy"):
        for dev in devices:
            rec = run_astro(kind, dev, 16, 1, args.depth, args.calls,
                            profile_json=prof / f"fixed_{kind}_{dev}.json")
            rec["first_s"] = (rec.get("calls") or [{}])[0].get("wall_s")
            rec["warm_min_s"] = _warm_min(rec)
            record["fixed_cost"].append(rec)
            print(f"[pkg298] fixed {kind:6s} {dev}: first {rec.get('first_s')} "
                  f"warm-min {rec['warm_min_s']}")
    # 2) Full render, both engines: burn-in call + min-of-N warm calls.
    if not args.skip_full:
        for kind in ("simple", "heavy"):
            if "gpu" in devices:
                rec = run_astro(kind, "gpu", args.res, args.spp, args.depth,
                                1 + args.repeats,
                                profile_json=prof / f"full_{kind}_gpu.json")
                rec["warm_min_s"] = _warm_min(rec)
                record["full"].append(rec)
                print(f"[pkg298] full  {kind:6s} astroray gpu: {rec['warm_min_s']}")
            if args.cycles:
                for cdev in ("OPTIX", "CUDA"):
                    rec = run_cycles(kind, cdev, args.res, args.spp, args.depth,
                                     1 + args.repeats, args.blender)
                    rec["warm_min_s"] = _warm_min(rec)
                    record["full"].append(rec)
                    print(f"[pkg298] full  {kind:6s} cycles {cdev}: {rec['warm_min_s']}")
    # 3) Path-pool floor: simple Cornell Msamples/s at 256^2 vs 1024^2.
    if args.pool and "gpu" in devices:
        for res in (256, 1024):
            rec = run_astro("simple", "gpu", res, args.spp, args.depth, 1 + args.repeats)
            t = _warm_min(rec)
            rec["warm_min_s"] = t
            rec["msamples_per_s"] = (res * res * args.spp / t / 1e6) if t else None
            record["pool"].append(rec)
            print(f"[pkg298] pool  {res}^2: {rec['msamples_per_s']} Msamples/s")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(record, indent=2))
    print(f"[pkg298] wrote {args.out}")
    return 0


def env_sweep_main(args) -> int:
    """pkg300: interleaved A/B over env-selected configs (label:K=V+K=V,...).

    Each round runs every config once per scene (burn-in call + 1 warm call), so
    GPU clock drift hits all configs alike; the record keeps min-of-rounds."""
    configs = []
    for item in args.env_sweep.split(","):
        label, _, envs = item.partition(":")
        env = dict(kv.split("=", 1) for kv in envs.split("+") if kv)
        configs.append((label, env))
    scenes = [k for k in args.scenes.split(",") if k]
    res: dict = {f"{s}/{lab}": [] for s in scenes for lab, _ in configs}
    for rnd in range(args.repeats):
        for s in scenes:
            for lab, env in configs:
                rec = run_astro(s, "gpu", args.res, args.spp, args.depth, 2, extra_env=env)
                t = _warm_min(rec) if not rec.get("skipped") else None
                res[f"{s}/{lab}"].append(t)
                print(f"[pkg300] round {rnd} {s:6s} {lab:12s} {t}", flush=True)
    record = {"schema": "astroray.pkg300.env_sweep.v1", "git_sha": _git_sha(),
              "gpu": gpu_info(), "args": {k: (str(v) if isinstance(v, Path) else v)
                                          for k, v in vars(args).items()},
              "configs": {lab: env for lab, env in configs}, "runs": res,
              "min_s": {k: min([t for t in v if t] or [None]) if any(v) else None
                        for k, v in res.items()}}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(record, indent=2))
    for k, v in record["min_s"].items():
        print(f"[pkg300] min {k:24s} {v}")
    return 0


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--_astro-child":
        _astro_child(json.loads(sys.argv[2]))
        return 0
    if "--cornell-pair" in sys.argv:
        pp = argparse.ArgumentParser()
        pp.add_argument("--cornell-pair", action="store_true")
        pp.add_argument("--devices", default="cpu,gpu",
                        help="Astroray devices for the fixed-cost leg (cpu,gpu)")
        pp.add_argument("--res", type=int, default=1024)
        pp.add_argument("--spp", type=int, default=256)
        pp.add_argument("--depth", type=int, default=8)
        pp.add_argument("--calls", type=int, default=4,
                        help="render() calls per fixed-cost run (first + warm)")
        pp.add_argument("--repeats", type=int, default=3,
                        help="min-of-N warm full renders after one burn-in call")
        pp.add_argument("--skip-full", action="store_true")
        pp.add_argument("--pool", action="store_true",
                        help="also measure the 256^2 vs 1024^2 throughput pair")
        pp.add_argument("--cycles", action="store_true",
                        help="add the Blender Cycles OptiX/CUDA leg")
        pp.add_argument("--blender", default=os.environ.get(
            "BLENDER_EXE", r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"))
        pp.add_argument("--out", type=Path, default=PAIR_OUT)
        pp.add_argument("--traversal", choices=("software", "optix"), default=None,
                        help="pkg299: force the GPU traversal (ASTRORAY_GPU_TRAVERSAL)")
        pp.add_argument("--env-sweep", default=None,
                        help="pkg300: interleaved env A/B, 'label:K=V+K=V,label2:...'")
        pp.add_argument("--scenes", default="simple,heavy")
        pargs = pp.parse_args()
        global TRAVERSAL
        TRAVERSAL = pargs.traversal
        if pargs.env_sweep:
            return env_sweep_main(pargs)
        return pair_main(pargs)

    ap = argparse.ArgumentParser()
    ap.add_argument("--spp", type=int, default=64,
                    help="Samples per pixel (default: 64)")
    ap.add_argument("--max-depth", type=int, default=8)
    ap.add_argument("--out", type=Path, default=OUT_FILE)
    ap.add_argument(
        "--soa", choices=("off", "on", "both"), default="off",
        help=("pkg55-A.1: 'off' = AoS-only baseline (Phase A.0 default); "
              "'on' = dual-trace SoA intersect (requires "
              "-DASTRORAY_WAVEFRONT_INTERSECT=ON build); "
              "'both' = run each scene twice and emit two records."))
    args = ap.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)

    record = {
        "schema": "astroray.wavefront.baseline.v1",
        "package": "pkg55",
        "phase": ("A.1 (SoA intersect dual-trace)" if args.soa != "off"
                  else "A.0 (megakernel baseline instrumentation)"),
        "soa_mode_arg": args.soa,
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "git_branch": _git_branch(),
        "git_sha": _git_sha(),
        "gpu": gpu_info(),
        "scenes": [],
    }

    tmp_dir = OUT_DIR / "_per_scene"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    modes: list[str]
    if args.soa == "both":
        modes = ["off", "on"]
    else:
        modes = [args.soa]

    for scene_id, mod, builder, res in SCENES:
        for soa_mode in modes:
            per = tmp_dir / f"{scene_id}.soa-{soa_mode}.json"
            record["scenes"].append(
                render_one(scene_id, mod, builder, res, args.spp, args.max_depth,
                           per, soa_mode=soa_mode))

    args.out.write_text(json.dumps(record, indent=2))
    print(f"[wavefront-baseline] wrote {args.out}")

    measured = sum(1 for s in record["scenes"] if not s.get("skipped"))
    if measured < 2:
        print(f"[wavefront-baseline] FAIL: only {measured} scenes measured "
              f"(acceptance requires ≥ 2).", file=sys.stderr)
        return 1
    print(f"[wavefront-baseline] OK: {measured} scenes measured.")
    return 0


def _git(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=ROOT, text=True, timeout=5).strip()
    except Exception:
        return "unknown"


def _git_branch() -> str:
    return _git("rev-parse", "--abbrev-ref", "HEAD")


def _git_sha() -> str:
    return _git("rev-parse", "--short", "HEAD")


if __name__ == "__main__":
    raise SystemExit(main())
