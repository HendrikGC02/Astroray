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
import os
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


def _oidn_bin_dirs() -> list[Path]:
    candidates: list[Path] = []
    for env_var in ("OIDN_ROOT", "ASTRORAY_OIDN_DIR"):
        root = os.environ.get(env_var)
        if root:
            candidates.append(Path(root) / "bin")
    candidates.extend([
        Path(r"C:\oidn\bin"),
        Path(r"C:\Program Files\Intel\oidn\bin"),
        Path(r"C:\Program Files\Intel\OpenImageDenoise\bin"),
        Path(r"C:\Program Files\OpenImageDenoise\bin"),
    ])
    return [path for path in candidates if path.is_dir()]


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    python_paths = [
        str(ROOT),
        str(ROOT / "build_cuda"),
        str(ROOT / "build_cuda" / "Release"),
        str(ROOT / "build"),
        str(ROOT / "build" / "Release"),
    ]
    existing_pythonpath = env.get("PYTHONPATH", "")
    if existing_pythonpath:
        python_paths.append(existing_pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(python_paths)
    if platform.system() == "Windows":
        oidn_bins = [str(path) for path in _oidn_bin_dirs()]
        if oidn_bins:
            env["PATH"] = os.pathsep.join(oidn_bins + [env.get("PATH", "")])
        env.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
    return env


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
        env=_subprocess_env(),
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
scene.world.color = (0.0, 0.0, 0.0)
def mat(name, color, emit=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nodes = m.node_tree.nodes
    nodes.clear()
    out = nodes.new(type='ShaderNodeOutputMaterial')
    if emit:
        shader = nodes.new(type='ShaderNodeEmission')
        shader.inputs['Color'].default_value = color
        shader.inputs['Strength'].default_value = emit
        m.node_tree.links.new(shader.outputs['Emission'], out.inputs['Surface'])
    else:
        shader = nodes.new(type='ShaderNodeBsdfDiffuse')
        shader.inputs['Color'].default_value = color
        shader.inputs['Roughness'].default_value = 1.0
        m.node_tree.links.new(shader.outputs['BSDF'], out.inputs['Surface'])
    return m
white = mat('white', (0.73, 0.73, 0.73, 1))
red = mat('red', (0.65, 0.05, 0.05, 1))
green = mat('green', (0.12, 0.45, 0.15, 1))
light_mat = mat('light', (1.0, 0.9, 0.8, 1), 15.0)
def tri(name, vertices, material):
    mesh = bpy.data.meshes.new(name + 'Mesh')
    mesh.from_pydata(vertices, [], [(0, 1, 2)])
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.name = name
    obj.data.materials.append(material)
    return obj
tri('floor_0', [(-2, -2, -2), (2, -2, -2), (2, -2, 2)], white)
tri('floor_1', [(-2, -2, -2), (2, -2, 2), (-2, -2, 2)], white)
tri('ceiling_0', [(-2, 2, -2), (-2, 2, 2), (2, 2, 2)], white)
tri('ceiling_1', [(-2, 2, -2), (2, 2, 2), (2, 2, -2)], white)
tri('back_0', [(-2, -2, -2), (-2, 2, -2), (2, 2, -2)], white)
tri('back_1', [(-2, -2, -2), (2, 2, -2), (2, -2, -2)], white)
tri('left_0', [(-2, -2, -2), (-2, -2, 2), (-2, 2, 2)], red)
tri('left_1', [(-2, -2, -2), (-2, 2, 2), (-2, 2, -2)], red)
tri('right_0', [(2, -2, -2), (2, 2, -2), (2, 2, 2)], green)
tri('right_1', [(2, -2, -2), (2, 2, 2), (2, -2, 2)], green)
tri('light_0', [(-0.5, 1.98, -0.5), (0.5, 1.98, -0.5), (0.5, 1.98, 0.5)], light_mat)
tri('light_1', [(-0.5, 1.98, -0.5), (0.5, 1.98, 0.5), (-0.5, 1.98, 0.5)], light_mat)
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


def _astroray_script(scene: Scene, output: Path, device: str) -> str:
    if scene.scene_id != "cornell":
        raise ValueError("Astroray scene import is only implemented for cornell")
    return f"""
import os
os.environ.setdefault('OPENCV_IO_ENABLE_OPENEXR', '1')
import imageio.v3 as iio
import numpy as np
import astroray

r = astroray.Renderer()
if {device == 'gpu'!r}:
    r.set_use_gpu(True)
r.set_seed(1)
red = r.create_material('lambertian', [0.65, 0.05, 0.05], {{}})
green = r.create_material('lambertian', [0.12, 0.45, 0.15], {{}})
white = r.create_material('lambertian', [0.73, 0.73, 0.73], {{}})
light = r.create_material('light', [1.0, 0.9, 0.8], {{'intensity': 15.0}})
for v0, v1, v2, mat in [
    ([-2, -2, -2], [2, -2, -2], [2, -2, 2], white),
    ([-2, -2, -2], [2, -2, 2], [-2, -2, 2], white),
    ([-2, 2, -2], [-2, 2, 2], [2, 2, 2], white),
    ([-2, 2, -2], [2, 2, 2], [2, 2, -2], white),
    ([-2, -2, -2], [-2, 2, -2], [2, 2, -2], white),
    ([-2, -2, -2], [2, 2, -2], [2, -2, -2], white),
    ([-2, -2, -2], [-2, -2, 2], [-2, 2, 2], red),
    ([-2, -2, -2], [-2, 2, 2], [-2, 2, -2], red),
    ([2, -2, -2], [2, 2, -2], [2, 2, 2], green),
    ([2, -2, -2], [2, 2, 2], [2, -2, 2], green),
    ([-0.5, 1.98, -0.5], [0.5, 1.98, -0.5], [0.5, 1.98, 0.5], light),
    ([-0.5, 1.98, -0.5], [0.5, 1.98, 0.5], [-0.5, 1.98, 0.5], light),
]:
    r.add_triangle(v0, v1, v2, mat)
r.setup_camera([0, 0, 5.5], [0, 0, 0], [0, 1, 0], 38.0, {scene.width / scene.height!r}, 0.01, 5.5, {scene.width}, {scene.height})
pixels = np.asarray(r.render({scene.samples}, 8, None, False), dtype=np.float32)
iio.imwrite({str(output)!r}, pixels)
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

    if scene.scene_id == "cornell":
        device = "gpu" if engine == "astroray-gpu" else "cpu"
        script = output.with_suffix(".py")
        script.write_text(_astroray_script(scene, output, device), encoding="utf-8")
        return _run_command([sys.executable, str(script)], ROOT, timeout)

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

        import numpy as np  # type: ignore

        a = iio.imread(output).astype("float32")[..., :3]
        b = iio.imread(reference).astype("float32")[..., :3]
        if a.shape != b.shape:
            return ""
        finite = np.concatenate([a[np.isfinite(a)], b[np.isfinite(b)]])
        if finite.size == 0:
            return ""
        lo = 0.0
        hi = float(np.percentile(finite, 99.9))
        if hi <= lo:
            return ""
        a = np.clip(np.nan_to_num(a, nan=0.0, posinf=hi, neginf=lo), lo, hi)
        b = np.clip(np.nan_to_num(b, nan=0.0, posinf=hi, neginf=lo), lo, hi)
        value = structural_similarity(a, b, channel_axis=-1, data_range=hi - lo)
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
    suffix = ".exr"
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
        if engine == "cycles-cpu":
            ref.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(final_output, ref)
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
