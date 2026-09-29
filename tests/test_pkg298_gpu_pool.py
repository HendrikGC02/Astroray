"""pkg298 — GPU wavefront path-pool floor and its VRAM budget.

With spp > 1 the pool grows past width*height (Cycles-style floor), capped by
free VRAM. ASTRORAY_WF_POOL_BUDGET_MB=0 forces the old width*height pool.
Pool size only changes which slot runs a sample (regen is work-indexed), so
both renders must match to float-atomic accumulation order (<= 1e-6 abs).
Each leg runs in a subprocess so the env hook and the pool log are isolated.
"""
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

astroray = pytest.importorskip("astroray")

pytestmark = pytest.mark.gpu

_CHILD = r"""
import sys
sys.path.insert(0, {tests!r})
import runtime_setup
runtime_setup.configure_test_imports()
import numpy as np
import astroray
r = astroray.Renderer()
if not r.gpu_available:
    print("NOGPU"); sys.exit(0)
W = 64
r.setup_camera([0, 0, 4], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 4.0, W, W)
r.set_background_color([0.1, 0.1, 0.12])
r.set_seed(5)
r.set_adaptive_sampling(False)
g = r.create_material("lambertian", [0.7, 0.7, 0.7], {{}})
li = r.create_material("light", [1.0, 1.0, 1.0], {{"intensity": 6.0}})
r.add_triangle([-2, -1, -2], [2, -1, -2], [2, -1, 2], g)
r.add_triangle([-2, -1, -2], [2, -1, 2], [-2, -1, 2], g)
r.add_sphere([0.0, -0.3, 0.0], 0.6, g)
r.add_triangle([-0.5, 1.9, -0.5], [0.5, 1.9, -0.5], [0.5, 1.9, 0.5], li)
r.add_triangle([-0.5, 1.9, -0.5], [0.5, 1.9, 0.5], [-0.5, 1.9, 0.5], li)
r.set_use_gpu(True)
img = np.asarray(r.render(64, 4, None, False), dtype=np.float32)
np.save({out!r}, img)
print("OK")
"""


def _leg(tmp_path, name, budget_mb):
    out = tmp_path / f"{name}.npy"
    env = dict(os.environ)
    env.pop("ASTRORAY_WF_POOL_BUDGET_MB", None)
    if budget_mb is not None:
        env["ASTRORAY_WF_POOL_BUDGET_MB"] = str(budget_mb)
    code = _CHILD.format(tests=str(Path(__file__).resolve().parent), out=str(out))
    p = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True,
                       text=True, timeout=600, check=False)
    assert p.returncode == 0, p.stderr[-2000:]
    if "NOGPU" in p.stdout:
        pytest.skip("CUDA device not available")
    return np.load(out), p.stderr


def test_pool_budget_zero_forces_pixel_pool_and_same_image(tmp_path):
    floor_img, floor_log = _leg(tmp_path, "floor", None)
    pix_img, pix_log = _leg(tmp_path, "pix", 0)
    assert "wavefront path pool" in floor_log          # 64^2 x 64 spp: pool grew
    assert "wavefront path pool" not in pix_log        # budget 0: width*height
    assert float(np.max(np.abs(floor_img - pix_img))) <= 1e-6
