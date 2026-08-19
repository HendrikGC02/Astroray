"""pkg204 -- GPU wavefront volume-pass direct/indirect split.

pkg198 Stage 2 routed ALL world-volume in-scatter into PASS_VOLUME_INDIRECT
(documented limitation). pkg204 splits it the same way Cycles splits surface
passes: the in-scatter lit directly at the FIRST scatter vertex (the NEE /
light-sampling leg) -> PASS_VOLUME_DIRECT; in-scatter arriving via a deeper
bounce (or a surface-after-fog event under the firstCat=3 lock) ->
PASS_VOLUME_INDIRECT. The split rides the existing HasLightPassAOVs partition
(no new template axis, no new live registers in the REG-254 shade / intersect
fleet kernels) via an extra parked int lane read read-only in the shadow-resolve
kernel -- see G_WF_NEE_I_LANES and the stage_advance.cu volume/shadow sites.

Gates (GPU legs skip when CUDA is absent; the RTX hardware-verifier runs them):

  1. NON-ZERO SPLIT -- a fog-with-direct-light scene populates BOTH
     PASS_VOLUME_DIRECT and PASS_VOLUME_INDIRECT (the split actually fires).
  2. SUM-TO-BEAUTY (pkg198 invariant, preserved) -- the re-bucket adds nothing
     and drops nothing: Sigma(all light-path passes, incl. volume_direct +
     volume_indirect) == GPU beauty. Because the split is a pure choice of which
     of the two volume buckets each in-scatter NEE lands in, the volume TOTAL
     (direct + indirect) equals the pre-split single-pass value by construction;
     this energy-closure gate is the empirical guard on that.

The register HARD gate (fleet shade <0,0,0,0,0> 254/3352/1700, intersect<false>
127/616, volume-scatter kernel unchanged) is a cuobjdump/-res-usage check run at
build time and reported in the PR -- not a pytest gate.

Design/citations: Cycles kernel/film/light_passes.h volume direct/indirect split
(Apache-2.0); CPU reference raytracer.h::pathTraceSpectral volPass
(firstInteraction ? PASS_VOLUME_DIRECT : PASS_VOLUME_INDIRECT).
"""
from __future__ import annotations

import os
import sys

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

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

SEED = 204331
W = H = 64

# The full light-path partition (pkg198) plus the two volume passes this package
# splits. Sum-to-beauty must hold over ALL of them.
ALL_PASSES = [
    "diffuse_direct", "diffuse_indirect",
    "glossy_direct", "glossy_indirect",
    "transmission_direct", "transmission_indirect",
    "volume_direct", "volume_indirect",
    "emission", "environment",
]


def _gpu_available() -> bool:
    return (
        AVAILABLE
        and astroray.__features__.get("cuda", False)
        and astroray.Renderer().gpu_available
    )


@pytest.fixture
def test_results_dir():
    d = os.path.join(os.path.dirname(__file__), "..", "test_results")
    os.makedirs(d, exist_ok=True)
    return os.path.abspath(d)


def _fog_scene(density=0.14, scatter=0.7, g=0.3, w=W, h=H):
    """A point light embedded in scattering fog with a diffuse floor -- gives a
    first-scatter NEE (VOLUME_DIRECT), deeper multi-scatter + surface-after-fog
    in-scatter (VOLUME_INDIRECT), and a directly-lit surface (diffuse passes)."""
    r = astroray.Renderer()
    r.set_seed(SEED)
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_world_volume(density, [1.0, 1.0, 1.0], g, scatter)
    r.add_point_light([0.0, 0.0, -3.0], {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 90.0)
    floor = r.create_material("lambertian", [0.6, 0.6, 0.6], {})
    r.add_sphere([0.0, -1001.0, -3.0], 1000.0, floor)
    r.setup_camera([0.0, 0.6, 6.0], [0.0, 0.0, -3.0], [0.0, 1.0, 0.0],
                   40.0, w / h, 0.0, 9.0, w, h)
    r.set_integrator("path_tracer")
    r.set_use_gpu(True)
    r.set_gpu_light_path_passes(True)
    r.set_wavelength_range(380.0, 780.0)
    r.set_output_mode("srgb")
    return r


def _pass(r, name):
    return np.array(r.get_render_pass_buffer(name), dtype=np.float64)


def _mean3(buf):
    return buf.reshape(-1, 3).mean(axis=0)


def test_gpu_volume_split_nonzero():
    """Gate 1: fog-with-direct-light populates BOTH volume passes."""
    if not _gpu_available():
        pytest.skip("CUDA GPU not available")
    r = _fog_scene()
    r.render(samples_per_pixel=256, max_depth=5, apply_gamma=False)
    vd = _pass(r, "volume_direct")
    vi = _pass(r, "volume_indirect")
    dmean, imean = _mean3(vd), _mean3(vi)
    print(f"\n[pkg204] volume_direct mean={np.round(dmean,6)} "
          f"volume_indirect mean={np.round(imean,6)}")
    assert float(np.abs(dmean).sum()) > 1e-6, (
        f"PASS_VOLUME_DIRECT is empty ({dmean}) -- first-scatter NEE not routed to "
        f"the direct bucket (the split did not fire)")
    assert float(np.abs(imean).sum()) > 1e-6, (
        f"PASS_VOLUME_INDIRECT is empty ({imean}) -- deeper in-scatter not routed")


def test_gpu_volume_split_sum_to_beauty():
    """Gate 2: Sigma(all passes incl. both volume buckets) == GPU beauty. The
    re-bucket conserves energy exactly (nothing added, nothing dropped)."""
    if not _gpu_available():
        pytest.skip("CUDA GPU not available")
    r = _fog_scene()
    beauty = np.array(
        r.render(samples_per_pixel=256, max_depth=5, apply_gamma=False),
        dtype=np.float64,
    )
    if beauty.ndim == 1:
        beauty = beauty.reshape(H, W, 3)

    total = None
    for name in ALL_PASSES:
        buf = _pass(r, name).reshape(beauty.shape)
        total = buf if total is None else total + buf

    beauty_mean = beauty.reshape(-1, 3).mean(axis=0)
    total_mean = total.reshape(-1, 3).mean(axis=0)
    ratio = total_mean / np.maximum(beauty_mean, 1e-6)
    denom = max(float(np.abs(beauty).sum()), 1e-6)
    rel_l1 = float(np.abs(total - beauty).sum() / denom)
    print(f"\n[pkg204] passes-sum/beauty ratio={np.round(ratio,5)} rel_L1={rel_l1:.6f}")
    # Same tolerance basis as pkg198's GPU sum-to-beauty: the per-pixel XYZ atomic
    # adds accumulate in a different order than the beauty reduction (~float floor)
    # and the deferred-NEE clamp/attribution resolves in a separate kernel.
    assert np.allclose(ratio, 1.0, atol=0.03), f"volume split broke energy closure: {ratio}"
    assert rel_l1 < 0.03, f"passes-sum vs beauty rel-L1 too high after split: {rel_l1:.6f}"
