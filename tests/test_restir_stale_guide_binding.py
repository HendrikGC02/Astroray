"""A GPU ReSTIR frame larger than the previous path-tracer frame must not corrupt later renders.

The path tracer publishes its first-hit guide AOV buffers (pkg197 albedo/normal/depth,
sized width*height of THAT frame) into the process-global __constant__ c_wfGuideBinding.
cuda_wavefront_render_restir and the snapshot harness entries run intersectPathSlot,
which writes those guides per pixel at bounce 0, but never republished the binding. A
64x64 ReSTIR frame after a 32x32 path-tracer frame therefore wrote 3072 pixels past the
guide buffers, and every later GPU render in the process came out dark (64x64 curve
parity 0.157; 48x48 prefix 0.59, the pkg225/pkg316 hair "regression" of batch i).

Each leg runs in a fresh subprocess (the wavefront context and its grow-only buffers are
process-global). The prefixed render must equal the clean one to atomic-order noise.
"""
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

def scene(w, integrator):
    r = astroray.Renderer()
    r.setup_camera([0, 0, 4], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 4.0, w, w)
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_seed(7)
    r.set_adaptive_sampling(False)
    if integrator == "restir-di":
        r.set_integrator_param("use_temporal", 0)
        r.set_integrator_param("use_spatial", 0)
    r.set_integrator(integrator)
    g = r.create_material("lambertian", [0.7, 0.7, 0.7], {{}})
    li = r.create_material("light", [1.0, 1.0, 1.0], {{"intensity": 6.0}})
    r.add_triangle([-2, -1, -2], [2, -1, -2], [2, -1, 2], g)
    r.add_triangle([-2, -1, -2], [2, -1, 2], [-2, -1, 2], g)
    r.add_sphere([0.0, -0.3, 0.0], 0.6, g)
    r.add_triangle([-0.5, 1.9, -0.5], [0.5, 1.9, -0.5], [0.5, 1.9, 0.5], li)
    r.add_triangle([-0.5, 1.9, -0.5], [0.5, 1.9, 0.5], [-0.5, 1.9, 0.5], li)
    r.set_use_gpu(True)
    return r

if not astroray.Renderer().gpu_available:
    print("NOGPU"); sys.exit(0)
if {prefix!r}:
    scene(32, "path_tracer").render(16, 4, None, False)   # guides sized 32x32
    scene(64, "restir-di").render(16, 1, None, False)     # 64x64 primary hits
img = np.asarray(scene(64, "path_tracer").render(64, 4, None, False), dtype=np.float32)
np.save({out!r}, img)
print("OK")
"""


def _leg(tmp_path, prefix):
    out = tmp_path / f"leg_{int(prefix)}.npy"
    code = _CHILD.format(tests=str(Path(__file__).resolve().parent), out=str(out),
                         prefix=prefix)
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       timeout=600, check=False)
    assert p.returncode == 0, p.stderr[-2000:]
    if "NOGPU" in p.stdout:
        pytest.skip("CUDA device not available")
    return np.load(out)


def test_restir_after_smaller_path_trace_does_not_corrupt_later_renders(tmp_path):
    clean = _leg(tmp_path, False)
    after = _leg(tmp_path, True)
    cm = clean.reshape(-1, 3).mean(0)
    am = after.reshape(-1, 3).mean(0)
    print(f"  clean mean={np.round(cm, 6)}  after ReSTIR mean={np.round(am, 6)}  "
          f"ratio={np.round(am / cm, 4)}")
    assert np.all(cm > 1e-3)
    assert np.allclose(am, cm, rtol=1e-3), (
        "a 64x64 ReSTIR frame after a 32x32 path-tracer frame changed the next render "
        f"(mean ratio {am / cm}): stale guide/miss-coverage binding written out of bounds")
