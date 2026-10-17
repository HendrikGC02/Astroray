"""#1111 (gate c Welch, materials_hall glass props ~20 % dark on GPU).

The GPU Principled rough-glass reflection sub-lobe evaluated its Fresnel as
air->glass on BOTH faces (gpu_pr_transmissionEval: F(HdotO, 1, ior)) while the
sampler and the pdf use the side-aware F(etaI, etaT). Inside the glass, f/pdf =
F(1,n)/F(n,1) < 1 (at TIR F(n,1) = 1), so every internal reflection lost energy.
A white furnace exposes it at the sphere RIM, where internal reflections dominate
(the centre patch the older furnace tests read is nearly blind to it).

Radiance invariance: clear glass in a uniform white field renders 1.0 everywhere.
Measured on main e553d753 (256 spp, ior 1.5): GPU rim 0.964 / 0.812 at r=0.05 / 0.3
(CPU 0.999 / 0.993).
"""

from __future__ import annotations

import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

_N = 80


def _furnace_rim(roughness: float, *, use_gpu: bool, spp: int = 256) -> float:
    r = astroray.Renderer()
    if use_gpu:
        r.set_use_gpu(True)
    r.set_background_color([1.0, 1.0, 1.0])
    g = r.create_material("principled", [1.0, 1.0, 1.0],
                          {"transmission_weight": 1.0, "ior": 1.5, "roughness": roughness})
    r.add_sphere([0.0, 0.0, 0.0], 1.0, g)
    r.set_integrator("path_tracer")
    r.set_adaptive_sampling(False)
    r.setup_camera([0, 0, 4], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 4.0, _N, _N)
    r.set_seed(7)
    img = np.asarray(r.render(spp, 32, None, False), dtype=np.float32).reshape(_N, _N, 3)
    yy, xx = np.mgrid[:_N, :_N]
    rad = np.hypot(yy - (_N - 1) / 2.0, xx - (_N - 1) / 2.0)
    return float(img[(rad > 20) & (rad < 26)].mean())  # sphere silhouette at ~27.5 px


@pytest.mark.skipif(
    AVAILABLE and not astroray.__features__.get("cuda", False),
    reason="CUDA feature not in this build")
@pytest.mark.parametrize("roughness", [0.05, 0.3])
def test_gpu_principled_rough_glass_furnace_rim(roughness):
    if not astroray.Renderer().gpu_available:
        pytest.skip("CUDA GPU not available")
    v = _furnace_rim(roughness, use_gpu=True)
    assert 0.97 <= v <= 1.03, f"GPU principled glass r={roughness} furnace rim = {v:.4f} (want ~1.0)"


@pytest.mark.parametrize("roughness", [0.05, 0.3])
def test_cpu_principled_rough_glass_furnace_rim(roughness):
    # CPU control (Cycles MULTI_GGX default, the GPU's shared evaluator since
    # 2026-10-06; Cycles itself reads rim 0.997 at r 0.3): conserves at the rim too.
    v = _furnace_rim(roughness, use_gpu=False)
    assert 0.97 <= v <= 1.03, f"CPU principled glass r={roughness} furnace rim = {v:.4f} (want ~1.0)"
