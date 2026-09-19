"""#779 — run_parity renders `astroray_leg = "addon"` rows through the addon.

The pkg265 glass_sphere row used tools/blend_import (Base Color only), so its
Astroray leg rendered diffuse spheres. The row now goes through headless
Blender + the addon (benchmarks/blender_parity/render_leg.py --load-blend).

1. Unit (no Blender): manifest routing, command shape, npy -> EXR plumbing.
2. Integration (needs Blender 5.x + a built astroray module; serial): the
   glass_sphere Astroray leg renders glass, not a diffuse proxy.
"""
from __future__ import annotations

import dataclasses
import os
import shutil
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import run_parity as rp

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")


def test_glass_sphere_row_uses_addon_leg():
    scene = rp._load_scenes()["glass_sphere"]
    assert scene.astroray_leg == "addon"
    assert scene.blend_path is not None and scene.blend_path.exists()


@pytest.mark.parametrize("engine,device", [("astroray-cpu", "cpu"), ("astroray-gpu", "gpu")])
def test_addon_leg_command_and_exr(monkeypatch, tmp_path, engine, device):
    pytest.importorskip("cv2")
    scene = rp._load_scenes()["glass_sphere"]
    seen = {}
    img = np.random.default_rng(3).random((scene.height, scene.width, 3)).astype(np.float32)

    def fake_run(command, cwd, timeout):
        seen["cmd"] = command
        stem = Path(command[command.index("--out") + 1])
        np.save(stem.with_suffix(".npy"), img)
        return 12.0, 1.0, None

    monkeypatch.setattr(rp, "_run_command", fake_run)
    out = tmp_path / "leg.exr"
    _, _, skip = rp._render_once(scene, engine, out, sys.executable, None, 60)
    assert skip is None
    cmd = seen["cmd"]
    assert str(rp.RENDER_LEG) in cmd
    for flag, value in (("--load-blend", str(scene.blend_path)), ("--engine", "CUSTOM_RAYTRACER"),
                        ("--device", device), ("--samples", str(scene.samples)),
                        ("--res", str(scene.width)), ("--res-y", str(scene.height))):
        assert cmd[cmd.index(flag) + 1] == value, flag
    back = rp._read_exr_float(out)
    np.testing.assert_allclose(back, img, rtol=0, atol=1e-6)  # same orientation, RGB order


def test_ssim_reads_addon_leg_exr_as_rgb(tmp_path):
    """#779 — the addon leg writes its EXR via cv2.imwrite (BGR channel order),
    so the SSIM path must read it back RGB to compare against the RGB Cycles
    reference. Round-trip a synthetic RGB image through the addon-leg write path
    and assert the SSIM-side read is identical RGB (no Blender needed)."""
    pytest.importorskip("cv2")
    pytest.importorskip("skimage")
    import cv2
    import imageio.v3 as iio

    rng = np.random.default_rng(5)
    rgb = rng.random((48, 64, 3)).astype(np.float32)
    out = tmp_path / "addon_leg.exr"
    ref = tmp_path / "cycles_ref.exr"
    # Same write path as _render_astroray_addon (cv2.imwrite of the BGR-reversed
    # array); the Cycles reference is RGB on disk (iio.imwrite stands in for it).
    assert cv2.imwrite(str(out), np.ascontiguousarray(rgb[..., ::-1]))
    iio.imwrite(str(ref), rgb)
    # The SSIM read path returns the addon leg back in RGB order.
    back = rp._read_exr_float(out)
    assert back is not None
    np.testing.assert_allclose(back, rgb, rtol=0, atol=1e-6)
    # Identical images on both sides must score ~1.0; a BGR/RGB swap would drop it.
    ssim = rp._ssim(out, ref)
    assert ssim != ""
    assert float(ssim) > 0.999


def test_addon_leg_missing_output_is_a_skip(monkeypatch, tmp_path):
    scene = rp._load_scenes()["glass_sphere"]
    monkeypatch.setattr(rp, "_run_command", lambda *a, **k: (1.0, 0.0, None))
    _, _, skip = rp._render_once(scene, "astroray-cpu", tmp_path / "x.exr", sys.executable, None, 60)
    assert skip == "addon_leg_no_output"


def _find_blender():
    for p in (Path(r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"),
              Path(r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe")):
        if p.exists():
            return str(p)
    return shutil.which("blender")


def _has_module():
    for d in ("build_cuda", "build_cuda/Release"):
        if any((ROOT / d).glob("astroray*.pyd")) or any((ROOT / d).glob("astroray*.so")):
            return True
    pyd_dir = os.environ.get("ASTRORAY_PYD_DIR")
    if pyd_dir:
        # The dir must actually exist and hold a built module; a bare env var
        # pointing at a missing directory must not count as "has module".
        p = Path(pyd_dir)
        return p.is_dir() and any(p.glob("astroray*.pyd"))
    return False


# Module-level BLENDER_EXE also makes the test classifier run this file serially.
BLENDER_EXE = _find_blender()


@pytest.mark.skipif(not (BLENDER_EXE and _has_module()),
                    reason="needs Blender 5.x and a built astroray module")
def test_glass_sphere_addon_leg_renders_glass(tmp_path):
    """Measured (128 spp, 2026-09-20): full-frame Astroray/Cycles 1.000; sphere
    top/bottom ratio Cycles 0.56-0.66, addon 0.41-0.65. Refraction shows the lit
    floor in each sphere's lower half. A diffuse sphere lit from above has
    top/bottom > 1. The old blend_import leg rendered a different, diffuse frame
    (full-frame 0.39x Cycles)."""
    pytest.importorskip("cv2")
    blender = BLENDER_EXE
    scene = dataclasses.replace(rp._load_scenes()["glass_sphere"], samples=64)
    cyc, ast = tmp_path / "cycles.exr", tmp_path / "astroray.exr"
    assert rp._render_once(scene, "cycles-cpu", cyc, blender, None, 900)[2] is None
    assert rp._render_once(scene, "astroray-cpu", ast, blender, None, 900)[2] is None
    c, a = rp._read_exr_float(cyc), rp._read_exr_float(ast)
    ratio = a.mean() / c.mean()
    assert 0.9 <= ratio <= 1.1, f"full-frame Astroray/Cycles {ratio:.3f}"
    h, w, _ = a.shape
    for x0, x1 in ((0.18, 0.36), (0.41, 0.59), (0.64, 0.82)):
        xs = slice(int(x0 * w), int(x1 * w))
        top = a[int(0.38 * h):int(0.47 * h), xs].mean()
        bottom = a[int(0.47 * h):int(0.56 * h), xs].mean()
        assert top / bottom < 0.9, f"sphere at x={x0}: top/bottom {top / bottom:.3f} (diffuse-like)"
