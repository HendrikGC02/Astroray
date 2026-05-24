#!/usr/bin/env python3
"""Render classroom scene with both Cycles and Astroray, saving outputs for comparison.

This is a minimal variant of run_parity.py focused on producing the visual diff
artifacts needed by pkg76-followup-classroom-fidelity.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCH_ROOT = ROOT / "benchmarks" / "cycles-parity"
SCENE_ROOT = BENCH_ROOT / "scenes"
CACHE = SCENE_ROOT / "cache" / "classroom"
BLEND = CACHE / "000_classroom.blend"
TEST_RESULTS = ROOT / "test_results"

# Scene parameters from manifest.toml
WIDTH = 1920
HEIGHT = 1080
SAMPLES = 300


def _subprocess_env():
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
    oidn_dirs = [r"C:\oidn\bin"]
    env["PATH"] = os.pathsep.join(oidn_dirs + [env.get("PATH", "")])
    env.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
    return env


def render_cycles_cpu(output_path: Path):
    """Render classroom with Cycles CPU to an EXR."""
    if not BLEND.exists():
        raise FileNotFoundError(f"Classroom .blend not found: {BLEND}")

    script = f"""
import bpy
bpy.context.scene.render.engine = 'CYCLES'
bpy.context.scene.cycles.device = 'CPU'
bpy.context.scene.cycles.samples = {SAMPLES}
bpy.context.scene.render.resolution_x = {WIDTH}
bpy.context.scene.render.resolution_y = {HEIGHT}
bpy.context.scene.render.resolution_percentage = 100
bpy.context.scene.render.image_settings.file_format = 'OPEN_EXR'
bpy.context.scene.render.image_settings.color_mode = 'RGB'
bpy.context.scene.render.image_settings.color_depth = '32'
bpy.context.scene.render.filepath = r'{str(output_path)}'
bpy.ops.render.render(write_still=True)
"""

    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as script_file:
        script_file.write(script)
        script_path = script_file.name

    try:
        blender = "blender"  # Assume blender is on PATH
        cmd = [blender, "-b", str(BLEND), "-P", script_path]
        print(f"Running Cycles CPU render: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            print(f"STDERR: {result.stderr}")
            raise RuntimeError(f"Cycles render failed with exit code {result.returncode}")
        print(f"Cycles CPU render saved to {output_path}")
    finally:
        os.unlink(script_path)


def render_astroray_gpu(output_path: Path):
    """Render classroom with Astroray GPU to an EXR."""
    script = f"""
import sys
sys.path.insert(0, r'{str(ROOT)}')
sys.path.insert(0, r'{str(ROOT / "build_cuda" / "Release")}')

import astroray
import numpy as np
import cv2

# Import the .blend file
scene_data = astroray.import_blend(r'{str(BLEND)}')
r = astroray.Renderer()
r.loadScene(scene_data)
r.uploadScene()

# Render
pixels = np.asarray(r.render({SAMPLES}, 8, None, False), dtype=np.float32)
pixels = pixels.reshape({HEIGHT}, {WIDTH}, 3)

# Save as EXR
cv2.imwrite(str(r'{str(output_path)}'), pixels)
print(f"Astroray GPU render saved to {output_path}")
"""

    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as script_file:
        script_file.write(script)
        script_path = script_file.name

    try:
        cmd = [sys.executable, script_path]
        print(f"Running Astroray GPU render: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600, env=_subprocess_env())
        print(result.stdout)
        if result.returncode != 0:
            print(f"STDERR: {result.stderr}")
            raise RuntimeError(f"Astroray render failed with exit code {result.returncode}")
    finally:
        os.unlink(script_path)


def compute_ssim(ref_path: Path, test_path: Path) -> float:
    """Compute SSIM between two EXR images."""
    import cv2
    import numpy as np
    from skimage.metrics import structural_similarity as ssim

    ref = cv2.imread(str(ref_path), cv2.IMREAD_ANYCOLOR | cv2.IMREAD_ANYDEPTH)
    test = cv2.imread(str(test_path), cv2.IMREAD_ANYCOLOR | cv2.IMREAD_ANYDEPTH)

    if ref is None:
        raise ValueError(f"Failed to load reference: {ref_path}")
    if test is None:
        raise ValueError(f"Failed to load test: {test_path}")

    # Clip to shared 99.9th percentile (per run_parity.py)
    p999 = np.percentile(np.concatenate([ref.ravel(), test.ravel()]), 99.9)
    ref_clipped = np.clip(ref, 0, p999)
    test_clipped = np.clip(test, 0, p999)

    # Compute SSIM
    score = ssim(ref_clipped, test_clipped, channel_axis=2, data_range=p999)
    return score


def create_visual_diff(ref_path: Path, test_path: Path, output_path: Path):
    """Create a visual diff showing reference, test, and delta."""
    import cv2
    import numpy as np

    ref = cv2.imread(str(ref_path), cv2.IMREAD_ANYCOLOR | cv2.IMREAD_ANYDEPTH)
    test = cv2.imread(str(test_path), cv2.IMREAD_ANYCOLOR | cv2.IMREAD_ANYDEPTH)

    # Tone-map for display (simple Reinhard)
    def tonemap(img):
        return img / (1.0 + img)

    ref_tm = tonemap(ref)
    test_tm = tonemap(test)

    # Compute absolute difference
    diff = np.abs(ref - test)
    diff_tm = tonemap(diff)

    # Amplify diff for visibility
    diff_amplified = np.clip(diff_tm * 5.0, 0, 1)

    # Create side-by-side comparison
    h, w, _ = ref.shape
    canvas = np.zeros((h, w * 3, 3), dtype=np.float32)
    canvas[:, :w, :] = ref_tm
    canvas[:, w:2*w, :] = test_tm
    canvas[:, 2*w:, :] = diff_amplified

    # Convert to 8-bit for PNG
    canvas_8bit = (np.clip(canvas, 0, 1) * 255).astype(np.uint8)
    cv2.imwrite(str(output_path), canvas_8bit)
    print(f"Visual diff saved to {output_path}")


def main():
    TEST_RESULTS.mkdir(parents=True, exist_ok=True)

    cycles_exr = TEST_RESULTS / "pkg76-classroom-cycles-cpu.exr"
    astroray_exr = TEST_RESULTS / "pkg76-classroom-astroray-gpu.exr"
    diff_png = TEST_RESULTS / "pkg76-classroom-diff.png"

    print("=== Rendering Classroom scene ===")
    print(f"Blend file: {BLEND}")
    print(f"Resolution: {WIDTH}x{HEIGHT}")
    print(f"Samples: {SAMPLES}")
    print()

    # Render both
    print("[1/3] Rendering with Cycles CPU...")
    render_cycles_cpu(cycles_exr)
    print()

    print("[2/3] Rendering with Astroray GPU...")
    render_astroray_gpu(astroray_exr)
    print()

    # Compute SSIM
    print("[3/3] Computing SSIM and creating visual diff...")
    ssim_score = compute_ssim(cycles_exr, astroray_exr)
    print(f"SSIM: {ssim_score:.6f}")

    # Create visual diff
    create_visual_diff(cycles_exr, astroray_exr, diff_png)
    print()
    print("=== Done ===")
    print(f"Cycles reference: {cycles_exr}")
    print(f"Astroray render: {astroray_exr}")
    print(f"Visual diff: {diff_png}")
    print(f"SSIM score: {ssim_score:.6f}")


if __name__ == "__main__":
    main()
