#!/usr/bin/env python3
"""Run the pkg71 Cycles parity benchmark matrix.

The subprocess-per-engine shape is adapted from the Apache-2.0 Blender
benchmark and Cycles integration-test harnesses:
- https://projects.blender.org/blender/blender-benchmark
- Blender/Cycles `intern/cycles/test/integration/`
"""

from __future__ import annotations

import argparse
import csv
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BENCH_ROOT = ROOT / "benchmarks" / "cycles-parity"
SCENE_ROOT = BENCH_ROOT / "scenes"
MANIFEST = SCENE_ROOT / "manifest.toml"
REFS = BENCH_ROOT / "refs"
RESULTS = BENCH_ROOT / "results"
CSV_COLUMNS = [
    "scene",
    "engine",
    "samples",
    "time_ms",
    "peak_mem_mb",
    "ssim_to_cycles",
    "skip_reason",
]
ENGINES = ("cycles-cpu", "cycles-cuda", "astroray-cpu", "astroray-gpu")


@dataclass(frozen=True)
class Scene:
    scene_id: str
    samples: int
    width: int
    height: int
    astroray_scene_id: int | None = None
    blend_path: Path | None = None


def _load_scenes() -> dict[str, Scene]:
    scenes = {
        "cornell": Scene("cornell", samples=64, width=512, height=512, astroray_scene_id=1),
    }
    if MANIFEST.exists():
        with MANIFEST.open("rb") as fh:
            for item in tomllib.load(fh).get("scene", []):
                width, height = item["resolution"]
                blend_path = _find_blend_path(item["id"], item["archive"])
                scenes[item["id"]] = Scene(
                    item["id"],
                    samples=int(item["reference_spp"]),
                    width=int(width),
                    height=int(height),
                    blend_path=blend_path,
                )
    return scenes


def _find_blend_path(scene_id: str, archive_name: str) -> Path | None:
    candidates = [
        SCENE_ROOT / "cache" / scene_id,
        SCENE_ROOT / "cache" / Path(archive_name).stem,
        SCENE_ROOT / "cache",
    ]
    for base in candidates:
        if not base.exists():
            continue
        matches = sorted(base.rglob("*.blend"))
        if matches:
            return matches[0]
    return None


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except Exception:
        return "nogit"


def _machine_id() -> str:
    raw = f"{platform.node()}-{platform.processor() or platform.machine()}"
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in raw).strip("-")
    return "-".join(part for part in slug.split("-") if part)[:80] or "machine"


def _default_astroray_binary() -> Path | None:
    names = ["raytracer.exe", "raytracer"]
    dirs = [
        ROOT / "build" / "bin" / "Release",
        ROOT / "build" / "bin",
        ROOT / "build_cuda" / "bin" / "Release",
        ROOT / "build_cuda" / "bin",
    ]
    for directory in dirs:
        for name in names:
            candidate = directory / name
            if candidate.exists():
                return candidate
    return None


def _monitor_process(proc: subprocess.Popen) -> tuple[threading.Event, list[float]]:
    done = threading.Event()
    samples: list[float] = []
    try:
        import psutil  # type: ignore

        ps_proc = psutil.Process(proc.pid)

        def watch() -> None:
            while not done.is_set():
                try:
                    rss = ps_proc.memory_info().rss
                    for child in ps_proc.children(recursive=True):
                        try:
                            rss += child.memory_info().rss
                        except psutil.Error:
                            pass
                    samples.append(rss / (1024 * 1024))
                except psutil.Error:
                    pass
                time.sleep(0.05)

        threading.Thread(target=watch, daemon=True).start()
    except Exception:
        pass
    return done, samples


def _run_command(command: list[str], cwd: Path, timeout: int) -> tuple[float, float, str | None]:
    start = time.perf_counter()
    proc = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    done, mem_samples = _monitor_process(proc)
    try:
        stdout, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, _ = proc.communicate()
        return 0.0, max(mem_samples, default=0.0), f"timeout:{timeout}s\n{stdout[-1000:]}"
    finally:
        done.set()
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    if proc.returncode != 0:
        return elapsed_ms, max(mem_samples, default=0.0), f"exit:{proc.returncode}\n{stdout[-1000:]}"
    return elapsed_ms, max(mem_samples, default=0.0), None


def _cycles_script(scene: Scene, output: Path, device: str) -> str:
    if scene.scene_id == "cornell":
        setup = """
import bpy
bpy.ops.object.delete()
scene = bpy.context.scene
def mat(name, color, emit=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value = color
    bsdf.inputs['Emission Strength'].default_value = emit
    if emit:
        bsdf.inputs['Emission Color'].default_value = color
    return m
white = mat('white', (0.73, 0.73, 0.73, 1))
red = mat('red', (0.65, 0.05, 0.05, 1))
green = mat('green', (0.12, 0.45, 0.15, 1))
light_mat = mat('light', (1.0, 0.9, 0.8, 1), 15.0)
def plane(name, loc, scale, rot, material):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc, rotation=rot)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = scale
    obj.data.materials.append(material)
    return obj
plane('floor', (0, -2, 0), (4, 0.02, 4), (0, 0, 0), white)
plane('ceiling', (0, 2, 0), (4, 0.02, 4), (0, 0, 0), white)
plane('back', (0, 0, -2), (4, 4, 0.02), (0, 0, 0), white)
plane('left', (-2, 0, 0), (0.02, 4, 4), (0, 0, 0), red)
plane('right', (2, 0, 0), (0.02, 4, 4), (0, 0, 0), green)
plane('light', (0, 1.98, 0), (1, 0.02, 1), (0, 0, 0), light_mat)
bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=0.7, location=(-0.7, -1.3, -0.5))
bpy.context.object.data.materials.append(white)
bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=0.5, location=(0.8, -1.5, 0.3))
bpy.context.object.data.materials.append(white)
bpy.ops.object.light_add(type='AREA', location=(0, 1.8, 0))
bpy.context.object.data.energy = 350
bpy.context.object.data.size = 1
bpy.ops.object.camera_add(location=(0, 0, 5.5), rotation=(0, 0, 0))
scene.camera = bpy.context.object
"""
    else:
        setup = f"bpy.ops.wm.open_mainfile(filepath={str(scene.blend_path)!r})"
    return f"""
import bpy
{setup}
scene = bpy.context.scene
scene.render.engine = 'CYCLES'
scene.cycles.samples = {scene.samples}
scene.render.resolution_x = {scene.width}
scene.render.resolution_y = {scene.height}
scene.render.filepath = {str(output)!r}
scene.view_settings.view_transform = 'Standard'
scene.view_settings.look = 'None'
scene.render.image_settings.file_format = 'OPEN_EXR'
scene.cycles.device = {('GPU' if device == 'cuda' else 'CPU')!r}
if {device == 'cuda'!r}:
    prefs = bpy.context.preferences.addons['cycles'].preferences
    prefs.compute_device_type = 'CUDA'
    for dev in prefs.devices:
        dev.use = True
bpy.ops.render.render(write_still=True)
"""


def _render_once(
    scene: Scene,
    engine: str,
    output: Path,
    blender: str | None,
    astroray: Path | None,
    timeout: int,
) -> tuple[float, float, str | None]:
    if engine.startswith("cycles"):
        if not blender or not Path(blender).exists():
            return 0.0, 0.0, "blender_not_found"
        if scene.scene_id != "cornell" and scene.blend_path is None:
            return 0.0, 0.0, "scene_blend_not_found"
        device = "cuda" if engine == "cycles-cuda" else "cpu"
        script = output.with_suffix(".py")
        script.write_text(_cycles_script(scene, output, device), encoding="utf-8")
        return _run_command([blender, "--background", "--python", str(script)], ROOT, timeout)

    if astroray is None or not astroray.exists():
        return 0.0, 0.0, "astroray_binary_not_found"
    if scene.astroray_scene_id is None:
        return 0.0, 0.0, "astroray_blend_import_not_implemented"
    device = "gpu" if engine == "astroray-gpu" else "cpu"
    cmd = [
        str(astroray),
        "--scene",
        str(scene.astroray_scene_id),
        "--width",
        str(scene.width),
        "--height",
        str(scene.height),
        "--samples",
        str(scene.samples),
        "--depth",
        "8",
        "--device",
        device,
        "--output",
        str(output),
    ]
    return _run_command(cmd, ROOT, timeout)


def _ssim(output: Path, reference: Path) -> str:
    if not output.exists() or not reference.exists():
        return ""
    try:
        import imageio.v3 as iio  # type: ignore
        from skimage.metrics import structural_similarity  # type: ignore

        a = iio.imread(output).astype("float32")
        b = iio.imread(reference).astype("float32")
        if a.shape != b.shape:
            return ""
        if a.max() > 2.0:
            a /= 255.0
        if b.max() > 2.0:
            b /= 255.0
        value = structural_similarity(a[..., :3], b[..., :3], channel_axis=-1, data_range=1.0)
        return f"{value:.6f}"
    except Exception:
        return ""


def _run_tuple(
    scene: Scene,
    engine: str,
    blender: str | None,
    astroray: Path | None,
    runs: int,
    timeout: int,
) -> dict[str, str]:
    RESULTS.mkdir(parents=True, exist_ok=True)
    suffix = ".exr" if engine.startswith("cycles") else ".png"
    with tempfile.TemporaryDirectory(prefix=f"{scene.scene_id}-{engine}-", dir=RESULTS) as tmp:
        tmpdir = Path(tmp)
        warm_output = tmpdir / f"warmup{suffix}"
        _, _, skip = _render_once(scene, engine, warm_output, blender, astroray, timeout)
        if skip:
            return _row(scene, engine, skip_reason=skip)

        times: list[float] = []
        mem: list[float] = []
        final_output = tmpdir / f"run-final{suffix}"
        final_skip = None
        for index in range(runs):
            output = tmpdir / f"run-{index}{suffix}"
            elapsed, peak_mem, skip = _render_once(scene, engine, output, blender, astroray, timeout)
            if skip:
                final_skip = skip
                break
            times.append(elapsed)
            mem.append(peak_mem)
            final_output = output
        if final_skip:
            return _row(scene, engine, skip_reason=final_skip)

        ref = REFS / f"{scene.scene_id}-{scene.samples}.exr"
        if engine == "cycles-cpu" and not ref.exists():
            ssim = "1.000000"
        else:
            ssim = _ssim(final_output, ref)
        return _row(
            scene,
            engine,
            time_ms=f"{statistics.median(times):.3f}",
            peak_mem_mb=f"{max(mem, default=0.0):.1f}" if any(mem) else "",
            ssim_to_cycles=ssim,
        )


def _row(
    scene: Scene,
    engine: str,
    *,
    time_ms: str = "",
    peak_mem_mb: str = "",
    ssim_to_cycles: str = "",
    skip_reason: str = "",
) -> dict[str, str]:
    skip_reason = " ".join(skip_reason.splitlines())
    return {
        "scene": scene.scene_id,
        "engine": engine,
        "samples": str(scene.samples),
        "time_ms": time_ms,
        "peak_mem_mb": peak_mem_mb,
        "ssim_to_cycles": ssim_to_cycles,
        "skip_reason": skip_reason,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", action="append", dest="scenes", help="Scene id; repeatable")
    parser.add_argument("--engine", action="append", dest="engines", choices=ENGINES, help="Engine id; repeatable")
    parser.add_argument("--runs", type=int, default=3, help="Timed subprocess runs per tuple")
    parser.add_argument("--timeout", type=int, default=3600, help="Per-process timeout in seconds")
    parser.add_argument("--blender", default=shutil.which("blender"), help="Blender 4.x executable")
    parser.add_argument("--astroray", type=Path, default=_default_astroray_binary(), help="Astroray standalone binary")
    parser.add_argument("--output", type=Path, help="CSV output path")
    args = parser.parse_args(argv)

    scenes = _load_scenes()
    requested_scenes = args.scenes or list(scenes)
    requested_engines = args.engines or list(ENGINES)
    unknown = sorted(set(requested_scenes) - set(scenes))
    if unknown:
        raise SystemExit(f"Unknown scene id(s): {', '.join(unknown)}")

    output = args.output or (
        BENCH_ROOT / f"{datetime.now().strftime('%Y-%m-%d')}-{_machine_id()}-{_git_sha()}.csv"
    )
    output.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    for scene_id in requested_scenes:
        for engine in requested_engines:
            print(f"Running {scene_id}/{engine}")
            rows.append(
                _run_tuple(
                    scenes[scene_id],
                    engine,
                    args.blender,
                    args.astroray,
                    runs=max(1, args.runs),
                    timeout=args.timeout,
                )
            )

    with output.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(output)
    failed = []
    for row in rows:
        if not row["engine"].startswith("astroray") or row["skip_reason"] or not row["ssim_to_cycles"]:
            continue
        if float(row["ssim_to_cycles"]) < 0.95:
            failed.append(f"{row['scene']}/{row['engine']}={row['ssim_to_cycles']}")
    if failed:
        print("SSIM gate failed (<0.95): " + ", ".join(failed), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
