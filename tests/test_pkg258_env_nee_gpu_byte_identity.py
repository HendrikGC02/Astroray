#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
pkg258 (Terra item 8 follow-up) — set_env_nee(False) GPU byte-identity regression.

A GPU render with environment NEE DISABLED must take the pre-pkg258 GPU code path
byte-for-byte: the constant-bound GWavefrontEnvNeeBinding.enabled==0 short-circuit
must draw ZERO extra RNG and add ZERO env contribution, so the frame is identical
to a build that has no GPU env-NEE leg at all.

The pre-#747 module is gone, so we pin it against the lead's ORIGIN/MAIN build
(which carries the CPU env-NEE leg from #747 but no GPU env NEE): an env-NEE-off
GPU frame on THIS branch must equal an env-NEE-off GPU frame from that baseline
module, for the same fixed non-zero seed on an HDRI scene. Both frames are
rendered in fresh subprocesses (each pointed at its own astroray .pyd) so the two
modules never coexist in one interpreter.

The test SKIPS when:
  * no CUDA GPU is present, or
  * the baseline build is not on disk (PKG258_BASELINE_BUILD or the default), or
  * the worktree GPU render is not bitwise-reproducible run-to-run (a precondition
    for cross-module byte identity — reported, not silently passed).
"""
import glob
import os
import subprocess
import sys
import textwrap

import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()
sys.path.insert(0, os.path.dirname(__file__))

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

from test_world_hdri_parity import _write_radiance_hdr  # noqa: E402

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

# Lead's main checkout GPU build (origin/main module: CPU env NEE, no GPU env NEE).
DEFAULT_BASELINE = r"C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray/build_cuda"
BASELINE_BUILD = os.environ.get("PKG258_BASELINE_BUILD", DEFAULT_BASELINE)

# The worktree's own build dir (the .pyd currently imported).
WORKTREE_BUILD = os.path.dirname(os.path.dirname(os.path.abspath(astroray.__file__))) \
    if AVAILABLE else ""


def _find_pyd_dir(build_dir):
    """Return the directory holding astroray*.pyd under build_dir (VS gen puts it
    in Release/, Ninja/NMake in the root), or None."""
    if not build_dir or not os.path.isdir(build_dir):
        return None
    hits = glob.glob(os.path.join(build_dir, "**", "astroray*.pyd"), recursive=True)
    return os.path.dirname(hits[0]) if hits else None


# Render worker: run in a fresh interpreter pointed at a specific astroray .pyd.
# Env NEE OFF, GPU, fixed seed, HDRI scene. Saves the linear frame as .npy.
_WORKER = textwrap.dedent(r"""
    import sys, numpy as np
    pyd_dir, hdri, out, seed = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
    sys.path.insert(0, pyd_dir)
    import astroray
    r = astroray.Renderer()
    r.set_use_gpu(True)
    r.set_integrator("path_tracer")
    r.set_seed(seed)
    r.set_adaptive_sampling(False)
    r.set_env_nee(False)
    floor = r.create_material("lambertian", [0.75, 0.75, 0.75], {})
    s = 40.0
    r.add_triangle([-s, 0, -s], [s, 0, -s], [s, 0, s], floor)
    r.add_triangle([-s, 0, -s], [s, 0, s], [-s, 0, s], floor)
    sph = r.create_material("lambertian", [0.6, 0.5, 0.4], {})
    r.add_sphere([0.0, 1.0, 0.0], 1.0, sph)
    r.setup_camera(look_from=[0, 2.2, 6], look_at=[0, 0.8, 0], vup=[0, 1, 0],
                   vfov=42, aspect_ratio=1.0, aperture=0.0, focus_dist=6.0,
                   width=16, height=16)
    assert r.load_environment_map(hdri, 1.0, 0.0, 0.0, 0.0)
    img = np.asarray(r.render(32, 4, None, False), dtype=np.float64)
    np.save(out, img)
""")


def _run_worker(pyd_dir, hdri, out_npy, seed):
    script = out_npy + ".worker.py"
    with open(script, "w") as f:
        f.write(_WORKER)
    res = subprocess.run(
        [sys.executable, script, pyd_dir, hdri, out_npy, str(seed)],
        capture_output=True, text=True, timeout=600)
    if res.returncode != 0:
        raise RuntimeError(f"render worker failed (rc={res.returncode}):\n"
                           f"STDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}")
    return np.load(out_npy)


def _sun_disc_hdri(width=64, height=32):
    img = np.full((height, width, 3), 0.05, dtype=np.float32)
    cx, cy, rr = width // 3, height // 6, 2
    for y in range(max(0, cy - rr), min(height, cy + rr + 1)):
        for x in range(max(0, cx - rr), min(width, cx + rr + 1)):
            if (x - cx) ** 2 + (y - cy) ** 2 <= rr * rr:
                img[y, x, :] = 300.0
    return img


def test_gpu_env_nee_off_byte_identical_to_baseline(tmp_path):
    if not astroray.Renderer().gpu_available:
        pytest.skip("no CUDA GPU available")
    base_dir = _find_pyd_dir(BASELINE_BUILD)
    work_dir = _find_pyd_dir(WORKTREE_BUILD)
    if base_dir is None:
        pytest.skip(f"baseline module not found under {BASELINE_BUILD}")
    if work_dir is None:
        pytest.skip(f"worktree module not found under {WORKTREE_BUILD}")
    if os.path.normpath(base_dir) == os.path.normpath(work_dir):
        pytest.skip("baseline and worktree resolve to the same .pyd")

    SEED = 258258  # fixed, non-zero (0 is the random sentinel)
    hdri = str(tmp_path / "sun.hdr")
    _write_radiance_hdr(hdri, _sun_disc_hdri())

    # Precondition: the worktree GPU render must be bitwise-reproducible so that
    # cross-module byte identity is even meaningful. If not, report and skip
    # rather than asserting an impossible equality.
    w1 = _run_worker(work_dir, hdri, str(tmp_path / "w1.npy"), SEED)
    w2 = _run_worker(work_dir, hdri, str(tmp_path / "w2.npy"), SEED)
    if not np.array_equal(w1, w2):
        maxd = float(np.max(np.abs(w1 - w2)))
        pytest.skip(f"worktree GPU render not bitwise-deterministic run-to-run "
                    f"(max|d|={maxd:.3e}); byte-identity is unpinnable here")

    base = _run_worker(base_dir, hdri, str(tmp_path / "base.npy"), SEED)
    assert base.shape == w1.shape, f"shape mismatch {base.shape} vs {w1.shape}"
    if not np.array_equal(base, w1):
        maxd = float(np.max(np.abs(base - w1)))
        nbad = int(np.count_nonzero(base != w1))
        raise AssertionError(
            f"env-NEE-off GPU frame differs from the origin/main baseline module: "
            f"{nbad}/{base.size} elements differ, max|d|={maxd:.3e}. The "
            f"enabled==0 short-circuit is NOT byte-identical to the pre-pkg258 GPU "
            f"path (Terra item 8).")
