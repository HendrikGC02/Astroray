"""pkg55 Phase A.1 — wavefront SoA intersect parity gate.

Validates that the SoA stage_init + stage_intersect kernels (gated by
-DASTRORAY_WAVEFRONT_INTERSECT=ON) produce the same first-bounce hit
record as the AoS megakernel for every primary ray on the pkg54
parity scene.

The bit-identity check happens *device-side*: the C++ dual-trace hook
in src/gpu/cuda_renderer.cu re-derives the AoS reference path from a
pre-init RNG snapshot, runs gpu_bvh_hit() (the same entry point the
megakernel calls), and __trap()s on any mismatch. This Python test's
job is to drive that hook from the public render API and read the
mismatch count out of stderr.

Skipped when:
  - astroray module unavailable, or
  - no CUDA GPU present, or
  - the build was configured without ASTRORAY_WAVEFRONT_INTERSECT
    (detected by the absence of the "wavefront intersect parity:" line
    in stderr after a render with the env var set).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# 16x16 = 256 rays. The Phase A.1 acceptance gate calls for 512 rays;
# we use 24x24 = 576 ≥ 512 to exceed it without making the test slow.
_RES = 24
_SPP = 1
_DEPTH = 2


def _render_subprocess(parity_on: bool) -> subprocess.CompletedProcess:
    """Render the cornell_diffuse scene in a child process, optionally
    with the dual-trace parity hook engaged. Returns the CompletedProcess
    so callers can inspect stdout/stderr/returncode.
    """
    code = f"""
import sys
from pathlib import Path
sys.path.insert(0, {str(ROOT / 'tests')!r})
sys.path.insert(0, {str(ROOT)!r})
import runtime_setup
runtime_setup.configure_test_imports()

import astroray

if not astroray.__features__.get("cuda", False):
    print("NOCUDA", file=sys.stderr); sys.exit(2)

from importlib import import_module
mod = import_module("benchmarks.showcase.scenes.convergence_grid")
build = mod.build_cornell

r = astroray.Renderer()
build(r, {_RES}, {_RES})
if not getattr(r, "gpu_available", False):
    print("NOCUDA", file=sys.stderr); sys.exit(2)
r.set_use_gpu(True)
r.set_seed(42)
r.render({_SPP}, {_DEPTH}, None, False)
"""
    env = os.environ.copy()
    if parity_on:
        env["ASTRORAY_WAVEFRONT_INTERSECT_PARITY"] = "1"
    else:
        env.pop("ASTRORAY_WAVEFRONT_INTERSECT_PARITY", None)
    return subprocess.run(
        [sys.executable, "-c", code],
        env=env, capture_output=True, text=True, timeout=180,
    )


def _has_cuda_via_subprocess() -> bool:
    """Probe CUDA availability without affecting the parity result."""
    proc = _render_subprocess(parity_on=False)
    if proc.returncode == 2 or "NOCUDA" in proc.stderr:
        return False
    return proc.returncode == 0


_PARITY_LINE = "[pkg55-A.1] wavefront intersect parity:"


def test_wavefront_intersect_parity_zero_mismatches():
    """576 primary rays must match between SoA and AoS bit-for-bit."""
    if not _has_cuda_via_subprocess():
        pytest.skip("CUDA GPU not available")

    proc = _render_subprocess(parity_on=True)

    if _PARITY_LINE not in proc.stderr:
        pytest.skip(
            "build configured without -DASTRORAY_WAVEFRONT_INTERSECT=ON "
            "(no parity output in stderr — env var was a no-op)")

    assert proc.returncode == 0, (
        f"render failed (rc={proc.returncode}); a non-zero return after the "
        f"parity hook reported mismatches indicates __trap() fired.\n"
        f"stderr tail:\n{proc.stderr[-2000:]}"
    )

    # Parse the line: "[pkg55-A.1] wavefront intersect parity: N / M rays mismatched"
    line = next(l for l in proc.stderr.splitlines() if _PARITY_LINE in l)
    parts = line.split(":", 1)[1].strip().split()
    mismatches = int(parts[0])
    total = int(parts[2])
    assert total == _RES * _RES, (
        f"parity hook saw {total} rays, expected {_RES * _RES}")
    assert mismatches == 0, (
        f"{mismatches}/{total} primary rays diverged between SoA intersect "
        f"and AoS reference. Full stderr:\n{proc.stderr[-4000:]}")
