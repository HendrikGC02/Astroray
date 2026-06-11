"""pkg55-B' plugin registration (spec sec. 6) — wavefront_path_tracer.

- Capabilities: gpuSupported True (the original Phase-B acceptance item:
  `integrator_capabilities("wavefront_path_tracer")["gpuSupported"]`).
- GPU: set_integrator("wavefront_path_tracer") + set_use_gpu(True) routes
  the render through the wavefront pipeline — asserted by exact equality
  with the cuda_wavefront_render binding at the same seed (same code path).
- CPU: the plugin delegates to the production SpectralPathTracer
  (decorator), so a CPU render is finite and non-black.
"""

from __future__ import annotations

import sys
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

W = H = 64
SPP = 16
DEPTH = 8
SEED = 424242


def _build(integrator, gpu):
    scenes_dir = Path(__file__).resolve().parent.parent / "scenes"
    sys.path.insert(0, str(scenes_dir))
    import disney_contact_sheet as scene_mod  # noqa: E402

    r = astroray.Renderer()
    scene_mod.build_scene(r)
    scene_mod.setup_camera(r, width=W, height=H)
    r.set_seed(SEED)
    r.set_integrator_param("max_depth", DEPTH)
    r.set_integrator(integrator)
    if gpu:
        r.set_use_gpu(True)
    return r


def test_capabilities_gpu_supported():
    caps = astroray.integrator_capabilities("wavefront_path_tracer")
    assert caps["gpuSupported"] is True


@pytest.mark.skipif(
    AVAILABLE and not hasattr(astroray, "cuda_wavefront_render"),
    reason="wavefront CUDA pipeline not in this build",
)
def test_gpu_routes_to_wavefront_pipeline():
    r = _build("wavefront_path_tracer", gpu=True)
    img = np.asarray(r.render(SPP, DEPTH, None, False),
                     dtype=np.float32).reshape(H, W, 3)

    r2 = _build("path_tracer", gpu=False)
    _ = r2.render(1, 1, None, False)  # BVH build for the direct binding
    ref = np.asarray(astroray.cuda_wavefront_render(r2, SPP, DEPTH, SEED),
                     dtype=np.float32).reshape(H, W, 3)

    # Same pipeline, same seed. Identical-run outputs differ by ~1 ULP from
    # the regen kernel's atomicAdd accumulation ordering (documented in the
    # N+7p4 review: maxabsdiff 4.77e-07 between identical-seed reruns), so
    # the routing assertion is a tight allclose, not bitwise equality.
    assert np.allclose(img, ref, atol=1e-5), (
        f"plugin route differs from cuda_wavefront_render: "
        f"maxabs={np.abs(img - ref).max()}"
    )
    assert float(img.mean()) > 1e-4


def test_cpu_fallback_renders():
    r = _build("wavefront_path_tracer", gpu=False)
    img = np.asarray(r.render(4, DEPTH, None, False),
                     dtype=np.float32).reshape(H, W, 3)
    assert np.all(np.isfinite(img))
    assert float(img.mean()) > 1e-4
