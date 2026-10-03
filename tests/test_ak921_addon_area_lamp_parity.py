"""#921 - the addon's area-lamp export must render at Cycles' level (pkg288 scene a).

Before #940 (PR #949) the addon lowered a Diffuse BSDF to Principled with
specular_ior_level=0 but the engine still used ior 1.5 for the specular layer, so a
spurious grazing mirror layer dimmed the floor under downward lamps (0.85x Cycles).
This renders pkg288 scene (a) through the real addon in headless Blender and pins the
frame mean to the Cycles 5.2 value (1024 spp, 64 px; tests/test_pkg288_lamp_passthrough.py
``_CYCLES_A``). Skips without Blender or an OpenMP-OFF addon .pyd.
"""
import os
import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
_CYCLES_A = np.array([0.03439117, 0.02874734, 0.0651959])


def _find_blender():
    env = os.environ.get("BLENDER_EXE")
    cands = [Path(env)] if env else []
    cands += [Path(r"C:/Program Files/Blender Foundation/Blender %s/blender.exe" % v)
              for v in ("5.2", "5.1")]
    return next((c for c in cands if c.is_file()), None)


def _pyd_dir():
    env = os.environ.get("ASTRORAY_PYD_DIR")
    # dist/astroray is the staged addon build_blender_addon.py refreshes (as in
    # test_780); build_blender_addon/ is a CPU build dir that goes stale.
    for d in ([Path(env)] if env else []) + [REPO / "dist" / "astroray", REPO / "build_blender_addon"]:
        if d.is_dir() and list(d.glob("astroray*.pyd")):
            return d
    return None


@pytest.mark.cpu
def test_addon_area_lamp_scene_a_matches_cycles():
    blender, pyd = _find_blender(), _pyd_dir()
    if blender is None or pyd is None:
        pytest.skip("needs Blender 5.x and an OpenMP-OFF astroray .pyd (ASTRORAY_PYD_DIR)")
    with tempfile.TemporaryDirectory() as out:
        env = dict(os.environ, AK921_REPO=str(REPO), ASTRORAY_PYD_DIR=str(pyd),
                   AK921_OUT=out, OMP_NUM_THREADS="8",
                   AK921_DLL_DIRS=r"C:/Program Files/mingw64/bin")
        proc = subprocess.run(
            [str(blender), "--background", "--factory-startup", "--python",
             str(REPO / "tests" / "ak921_blender_scene_a.py"), "--", "256", "64"],
            capture_output=True, text=True, env=env, timeout=600)
    m = re.search(r"AK921_MEAN (\S+) (\S+) (\S+)", proc.stdout)
    assert m, proc.stdout[-1500:] + proc.stderr[-1500:]
    mean = np.array([float(x) for x in m.groups()])
    np.testing.assert_allclose(mean, _CYCLES_A, rtol=0.03, err_msg=f"addon={mean} cycles={_CYCLES_A}")
