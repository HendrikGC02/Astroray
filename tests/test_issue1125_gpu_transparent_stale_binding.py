"""#1125 - GPU transparent-pass budget: stale binding + the 31-pass saturation.

1. `c_wfTransparentLimit` is a process-global __constant__ published by
   cuda_wavefront_render only. The ReSTIR entry and the snapshot harness entries
   (which run the same intersect/shade kernels) never republished it, so a
   transparent path-tracer render left them running the #1033 pass-through
   branch (same stale-binding class as #1115/#1118). Each leg below runs in a
   fresh subprocess (the wavefront context is process-global); the measured
   ReSTIR render and PostNEE_MIS snapshot after a transparent path-tracer render
   must equal the fresh-process ones to 1e-6.

2. The per-path transparent-pass count rode lp_state bits 27-31 (saturating at
   31), so transparent_max_bounces > 31 never fired on the GPU while the CPU
   honours it (#1047 item 4). The count is now a full uint32 lane
   (GPUWavefrontState.pass_count). A stack of N alpha-0 sheets in front of a white
   background: the camera ray escapes iff N <= transparent_max_bounces (the
   (T+1)-th sheet is hit with count T >= T and terminates), CPU is the oracle.
"""
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("astroray")
from test_issue991_light_path import BACKENDS, _quad, _renderer, _roi

SIZE = 32


# ---- 2. 40-sheet stack: GPU honours transparent_max_bounces > 31 like the CPU ----
def _stack_value(use_gpu, sheets, transparent):
    from base_helpers import setup_camera
    r = _renderer(use_gpu)
    r.set_background_color([1.0, 1.0, 1.0])
    sheet = r.create_material("principled", [1.0, 1.0, 1.0], {"alpha": 0.0})
    for i in range(sheets):
        _quad(r, sheet, [0, 1.0 + 0.1 * i, 0], [4.0, 0, 0], [0, 0, 4.0])
    setup_camera(r, look_from=[0, 0, 0], look_at=[0, 1, 0], vup=[0, 0, 1], vfov=10,
                 width=SIZE, height=SIZE)
    img = r.render(8, 4, None, False, -1, -1, -1, -1, transparent)
    return float(_roi(img, SIZE // 2, SIZE // 2, 4).mean())


# (sheets, transparent_max_bounces): escape iff sheets <= limit. The 31-saturating
# counter let (35, 33) and (40, 39) escape on the GPU.
@pytest.mark.parametrize("use_gpu", BACKENDS)
@pytest.mark.parametrize("sheets,limit,escapes", [
    (35, 35, True), (35, 33, False), (40, 40, True), (40, 39, False),
])
def test_transparent_limit_above_31_is_honoured(use_gpu, sheets, limit, escapes):
    v = _stack_value(use_gpu, sheets, limit)
    if escapes:
        assert v > 0.5, (sheets, limit, v)
    else:
        assert v < 0.02, (sheets, limit, v)


# ---- 1. transparent path-tracer render must not leak into ReSTIR / snapshots -----
_CHILD = r"""
import sys
sys.path.insert(0, {tests!r})
import runtime_setup
runtime_setup.configure_test_imports()
import numpy as np
import astroray

W = 16

def scene(integrator, sheet=True):
    r = astroray.Renderer()
    r.setup_camera([0, 0, 4], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 4.0, W, W)
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_seed(7)
    r.set_adaptive_sampling(False)
    if integrator == "restir-di":
        r.set_integrator_param("use_temporal", 0)
        r.set_integrator_param("use_spatial", 0)
    r.set_integrator(integrator)
    g = r.create_material("lambertian", [0.7, 0.7, 0.7], {{}})
    li = r.create_material("light", [1.0, 1.0, 1.0], {{"intensity": 6.0}})
    sh = r.create_material("principled", [1.0, 1.0, 1.0], {{"alpha": 0.0}})
    r.add_triangle([-2, -1, -2], [2, -1, -2], [2, -1, 2], g)
    r.add_triangle([-2, -1, -2], [2, -1, 2], [-2, -1, 2], g)
    r.add_sphere([0.0, -0.3, 0.0], 0.6, g)
    if sheet:   # alpha-0 sheet between the camera and the sphere
        r.add_triangle([-1.5, -1.5, 2.0], [1.5, -1.5, 2.0], [1.5, 1.5, 2.0], sh)
        r.add_triangle([-1.5, -1.5, 2.0], [1.5, 1.5, 2.0], [-1.5, 1.5, 2.0], sh)
    r.add_triangle([-0.5, 1.9, -0.5], [0.5, 1.9, -0.5], [0.5, 1.9, 0.5], li)
    r.add_triangle([-0.5, 1.9, -0.5], [0.5, 1.9, 0.5], [-0.5, 1.9, 0.5], li)
    r.set_use_gpu(True)
    return r

if not astroray.Renderer().gpu_available:
    print("NOGPU"); sys.exit(0)
if {prefix!r}:
    # transparent path-tracer render: publishes c_wfTransparentLimit = 1
    scene("path_tracer").render(16, 4, None, False, -1, -1, -1, -1, 1)
# #1150: GPU ReSTIR-DI renders black behind an alpha-0 surface (pre-existing), so this
# leg has no sheet and only checks the reset leaves ReSTIR byte-identical to a fresh process.
restir = np.asarray(scene("restir-di", sheet=False).render(16, 1, None, False), dtype=np.float64)
r = scene("path_tracer")
# CPU warmup render builds the BVH the snapshot upload needs (pkg55 gate idiom);
# it never touches the CUDA module, so the stale c_wfTransparentLimit stays armed.
r.set_use_gpu(False)
r.render(1, 1, None, False)
r.set_use_gpu(True)
snap = np.asarray(astroray.cuda_wavefront_snapshot_post_nee_mis(r, W, W, 7), dtype=np.float64)
np.savez({out!r}, restir=restir, snap=snap)
print("OK")
"""


def _leg(tmp_path, prefix):
    out = tmp_path / f"leg_{int(prefix)}.npz"
    code = _CHILD.format(tests=str(Path(__file__).resolve().parent), out=str(out),
                         prefix=prefix)
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       timeout=600, check=False)
    assert p.returncode == 0, p.stderr[-2000:]
    if "NOGPU" in p.stdout:
        pytest.skip("CUDA device not available")
    return np.load(out)


@pytest.mark.gpu
def test_restir_and_snapshots_ignore_a_prior_transparent_render(tmp_path):
    clean = _leg(tmp_path, False)
    after = _leg(tmp_path, True)
    assert np.isfinite(clean["restir"]).all() and clean["restir"].mean() > 1e-3
    for key in ("restir", "snap"):
        d = float(np.max(np.abs(after[key] - clean[key])))
        print(f"  {key}: max |after - clean| = {d:.3e}")
        assert d <= 1e-6, (
            f"{key} after a transparent path-tracer render differs from a fresh process "
            f"(max abs diff {d:.3e}): stale c_wfTransparentLimit binding")
