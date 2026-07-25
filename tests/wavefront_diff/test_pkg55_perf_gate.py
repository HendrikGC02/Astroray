"""pkg55 Phase-C7 performance gate — wavefront absolute-time regression guard
on the balanced 7-material Disney contact sheet (tests/scenes/disney_contact_sheet).

HISTORY (the live WF-vs-megakernel ratio gates retired 2026-07-25 with the
megakernel deletion — C7):
- Phase-B floor >= 1.30x / target 1.5x, measured vs the LIVE MW megakernel.
- Final pre-deletion record (RTX 5070 Ti, GPU lock held, median-of-5,
  2026-07-25, C7 acceptance): 1.494x @512spp, 1.500x @1024spp on a cool GPU
  (43 C); session spread across clock states 1.476-1.539x. Absolute times and
  the full protocol are pinned in
  benchmarks/wavefront/megakernel_final_2026-07-25.json.
- The spec's original ">= 2x vs the Phase-A baseline" was RESCOPED by the
  owner (2026-07-25): the Phase-A pin is dead as a comparator — the megakernel
  itself regressed ~5.7x per launch between 2026-05 and 2026-07 (feature cost,
  regs 125->188; see pkg155) — and the meaningful live ratio stabilized at
  1.48-1.54x. C7 acceptance floor >= 1.40x: MET (see spec execution status).

WHAT THIS FILE NOW GATES: with the megakernel gone, a live ratio cannot be
measured, so this is a wavefront-only absolute wall-time ceiling — a
gross-regression tripwire (catches >~40% slowdowns; finer perf tracking is
pkg155's scope). Machine-pinned to the RTX 5070 Ti workstation like the other
wavefront_diff gates. Measured 2026-07-25: WF 1024spp median 0.570-0.711 s
across cool/warm clock states; ceiling 1.0 s keeps ~40% headroom above the
worst observed state.

Linear output (applyGamma=False) — memory: render-probe-applygamma-footgun.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from runtime_setup import configure_test_imports  # noqa: E402

configure_test_imports()

try:
    import astroray  # noqa: E402
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

if AVAILABLE and not hasattr(astroray, "cuda_wavefront_render"):
    pytest.skip(
        "cuda_wavefront_render not in this build — needs "
        "-DASTRORAY_WAVEFRONT_CUDA_N3=ON + CUDA (RTX box).",
        allow_module_level=True,
    )

WIDTH = HEIGHT = 256
SPP = 1024
MAX_DEPTH = 8
SEED = 424242
CEILING_S = 1.0  # RTX 5070 Ti pin, 2026-07-25 (see module docstring)


def _build():
    scenes_dir = Path(__file__).resolve().parent.parent / "scenes"
    sys.path.insert(0, str(scenes_dir))
    import disney_contact_sheet as scene_mod  # noqa: E402

    r = astroray.Renderer()
    scene_mod.build_scene(r)
    scene_mod.setup_camera(r, width=WIDTH, height=HEIGHT)
    r.set_seed(SEED)
    r.set_integrator_param("max_depth", MAX_DEPTH)
    r.set_integrator("path_tracer")
    _ = r.render(1, 1, None, False)  # warmup / BVH build
    return r


def test_wavefront_contact_sheet_ceiling():
    """Wavefront 1024spp contact sheet: median-of-3 wall time under the pinned
    ceiling, and the image is non-black (route sanity)."""
    if not astroray.Renderer().gpu_available:
        pytest.skip("No CUDA GPU available")
    r = _build()
    _ = astroray.cuda_wavefront_render(r, 64, MAX_DEPTH, SEED)  # warm / JIT
    times = []
    img = None
    for _i in range(3):
        t0 = time.perf_counter()
        img = np.asarray(astroray.cuda_wavefront_render(r, SPP, MAX_DEPTH, SEED),
                         dtype=np.float32).reshape(HEIGHT, WIDTH, 3)
        times.append(time.perf_counter() - t0)
    med = float(np.median(times))
    print(f"[perf-gate] WF {SPP}spp median-of-3 {med:.3f}s "
          f"(runs {[round(t, 3) for t in times]}; ceiling {CEILING_S}s)")
    assert img is not None and float(img.mean()) > 1e-4, (
        "wavefront render came back (near-)black — route/upload regression")
    assert med <= CEILING_S, (
        f"Wavefront perf REGRESSED: median {med:.3f}s > {CEILING_S}s ceiling "
        f"(2026-07-25 pin: 0.570-0.711s across clock states; see "
        f"benchmarks/wavefront/megakernel_final_2026-07-25.json)"
    )
