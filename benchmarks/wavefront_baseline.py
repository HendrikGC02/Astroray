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


def main() -> int:
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
