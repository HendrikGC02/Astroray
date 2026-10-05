"""#1060 — the run_parity cornell Cycles and Astroray legs must describe the same scene.

SSIM read 0.93 (gate 0.95) and the mean ratio 0.67 because the Cycles leg kept
Blender's default 1000 W point light (only the Cube was selected for delete),
a 0.05 grey world, a 39.6 deg camera, a two-sided light mesh and an Oren-Nayar
diffuse (Roughness 1.0), while Astroray's default world is a lit sky. With the
setup matched the measured SSIM is 0.9994 (CPU and GPU).

Unit level (no Blender): the generated scripts carry the matching setup.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import run_parity as rp

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")


def _cycles() -> str:
    scene = rp._load_scenes()["cornell"]
    return rp._cycles_script(scene, Path("out.exr"), "cpu")


def test_cycles_leg_removes_every_default_object():
    # delete() acts on the selection; the default Light is unselected.
    s = _cycles()
    assert s.index("select_all(action='SELECT')") < s.index("bpy.ops.object.delete()")


def test_cycles_leg_matches_astroray_world_camera_light_and_bsdf():
    s = _cycles()
    assert "n.inputs['Strength'].default_value = 0.0" in s  # black world node
    assert "angle_y = math.radians(38.0)" in s  # Astroray fov 38 deg, not Blender's 39.6
    assert "Backfacing" in s  # one-sided light (Astroray "light" emits front face only)
    assert "shader.inputs['Roughness'].default_value = 0.0" in s  # Lambertian, not Oren-Nayar
    assert "max_bounces = 8" in s  # Astroray render(spp, 8, ...)


def test_astroray_leg_uses_black_world():
    scene = rp._load_scenes()["cornell"]
    assert "r.set_background_color([0.0, 0.0, 0.0])" in rp._astroray_script(scene, Path("out.exr"), "cpu")
