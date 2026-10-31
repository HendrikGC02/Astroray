"""#1038 - plain Glass ball of prod_light_path vs Cycles 5.2 (pinned), CPU and GPU.

Scene: ``production/prod_light_path.blend`` with the ball's Mix(Glass, Transparent, Is Shadow Ray)
replaced by its plain Glass BSDF (Color (0.9, 1, 0.95), Roughness 0.02, IOR 1.45), the issue's
configuration. Rendered at 2048 spp, seed 278, 320x240, against Cycles means pinned from seven seeds
(1301 2711 4177 6113 7001 8111 9203) x 1024 spp, Blender 5.2 CPU (evidence
``%LOCALAPPDATA%/astroray-evidence/2026-10-25/i1038/seeds``).

* ``glass_ball_centre`` (camera view through the ball): every channel within 1 +- 0.02 (the issue's
  1 +- 0.03, tightened so the pre-fix 0.971 fails; per-seed sd 0.002). It read R 1.087 / B 1.057 on
  b4e15d06 (Glass tint, fixed by #1103) and R 0.971 on 4d5d1188 (the delta glass spectral weight,
  fixed with this test: tint upsampled once, scalars linear); now 0.996 / 1.007 / 1.002 (seven-seed
  means).
* ``glass_sun_shadow_floor`` (the ball's sun shadow) is a real refractive caustic of the 0.6 deg sun
  through the ball: Cycles renders it too (with Cycles caustics_refractive off the ROI drops to
  0.45x), and the seven-seed CPU/Cycles mean is 0.95 +- 0.08 (L). The ~2x of the issue was a single
  pre-#1103/#1112 seed. The ROI is firefly-dominated: CPU per-seed relative sd 0.163 at 1024 spp,
  so ~0.115 at 2048 spp; with the pinned mean's 0.053 the 3-sigma band on the luminance ratio is
  [0.62, 1.38]. That excludes both a missing caustic (0.45) and a doubled one (2x).
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import numpy as np
import pytest

from benchmarks.reference_corpus import mc_tolerance as MC

REPO = Path(__file__).resolve().parents[1]
PROD = REPO / "benchmarks" / "reference_corpus" / "production"
SRC = PROD / "prod_light_path.blend"
SEED, SPP = 278, 2048
# Cycles 5.2 CPU, seven seeds x 1024 spp (r, g, b, L). ROI rects from gates_production.toml.
CYCLES = {
    "glass_ball_centre": ([0.2107, 0.4938, 0.2807, 0.5871], (0.17384, 0.16989, 0.22043, 0.17438)),
    "glass_sun_shadow_floor": ([0.1513, 0.6191, 0.2313, 0.7258], (0.15598, 0.14038, 0.21510, 0.14909)),
}
CENTRE_TOL = 0.02
SHADOW_L_BAND = (0.62, 1.38)

_VARIANT = r'''
import sys, bpy
out = sys.argv[sys.argv.index("--") + 1]
src = bpy.data.filepath
for im in bpy.data.images:
    if im.filepath:
        im.filepath = bpy.path.abspath(im.filepath)
nt = bpy.data.materials["ShadowlessGlass"].node_tree
glass = next(n for n in nt.nodes if n.type == "BSDF_GLASS")
outn = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
nt.links.new(glass.outputs["BSDF"], outn.inputs["Surface"])
bpy.ops.wm.save_as_mainfile(filepath=out, copy=True, relative_remap=False)
print("I1038_VARIANT_OK")
'''


def _skip_unless_blender():
    if not MC.BLENDER.is_file() or not os.environ.get("ASTRORAY_PYD_DIR"):
        pytest.skip("needs Blender 5.2 (ASTRORAY_BLENDER) and a staged addon (ASTRORAY_PYD_DIR)")


@pytest.fixture(scope="module")
def plain_glass_blend(tmp_path_factory):
    _skip_unless_blender()
    sha = json.loads((PROD / "manifest.json").read_text(encoding="utf-8"))["scenes"]["prod_light_path"]["sha256"]
    assert hashlib.sha256(SRC.read_bytes()).hexdigest() == sha, "prod_light_path.blend changed: re-pin CYCLES"
    d = tmp_path_factory.mktemp("i1038")
    script, out = d / "variant.py", d / "plain_glass.blend"
    script.write_text(_VARIANT, encoding="utf-8")
    r = subprocess.run([str(MC.BLENDER), "-b", str(SRC), "--factory-startup", "--python", str(script),
                        "--", str(out)], capture_output=True, text=True, timeout=300, check=False)
    assert "I1038_VARIANT_OK" in r.stdout and out.is_file(), r.stdout[-1500:] + r.stderr[-500:]
    return out


def _render(blend: Path, device: str, stem: Path) -> np.ndarray:
    cmd = [str(MC.BLENDER), "-b", "--factory-startup", "--threads", "8", "--python", str(MC.RENDER_LEG), "--",
           "--engine", "CUSTOM_RAYTRACER", "--device", device, "--load-blend", str(blend),
           "--out", str(stem), "--seed", str(SEED), "--spp-override", str(SPP), "--res", "320", "--res-y", "240"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800, check=False,
                       env=dict(os.environ, OMP_NUM_THREADS="8"))
    assert "PKG119B_LEG PASS" in r.stdout, r.stdout[-1500:] + r.stderr[-500:]
    return np.load(stem.with_suffix(".npy"))


@pytest.mark.slow
@pytest.mark.parametrize("device", [pytest.param("cpu", marks=pytest.mark.serial),
                                    pytest.param("gpu", marks=pytest.mark.gpu)])
def test_plain_glass_ball_matches_cycles(plain_glass_blend, tmp_path, device):
    report = Path(os.environ["ASTRORAY_PYD_DIR"]) / "build_report.json"
    if device == "gpu" and report.is_file() and json.loads(report.read_text(encoding="utf-8")).get("backend") == "cpu":
        pytest.skip("staged addon is a CPU build")
    img =_render(plain_glass_blend, device, tmp_path / f"plain_glass_{device}")
    rect, ref = CYCLES["glass_ball_centre"]
    centre = MC.roi_means(img, rect) / np.array(ref)
    rect, ref = CYCLES["glass_sun_shadow_floor"]
    shadow = MC.roi_means(img, rect) / np.array(ref)
    assert np.all(np.abs(centre[:3] - 1.0) <= CENTRE_TOL), f"{device} centre/Cycles {np.round(centre, 4)}"
    lo, hi = SHADOW_L_BAND
    assert lo <= shadow[3] <= hi, f"{device} sun-shadow caustic L/Cycles {shadow[3]:.3f} outside [{lo}, {hi}]"
