"""Opaque Disney (metallic=0, transmission=0) must conserve energy on the GPU.

The default Disney material class (metallic=0, transmission=0) lowers to a GPU
closure graph carrying TWO sampleable lobes: a diffuse lobe (weight 1) and a GGX
conductor lobe (weight 1), totalWeight W=2. Before pkg170 the closure-graph eval
summed RAW lobe weights (Sum w_i f_i) while the pdf summed NORMALIZED selection
weights (Sum (w_i/W) pdf_i); the one-sample-MIS estimator f_total/pdf_total then
targeted a W-inflated integrand and the white furnace read a flat ~1.975 across
all roughness (measured 78218f6, RTX 5070 Ti, linear) while CPU's monolithic
Disney conserved (~0.95). pkg170 weights each lobe by its selection probability
in the eval, matching the pdf (Veach 1997 §9.2.4 one-sample MIS / PBRT-v4 §9.5).

pkg166's linear-furnace conversion did NOT cover opaque-Disney-on-GPU, which is
why a ~2x gain on the DEFAULT material class survived unseen. These legs close
that coverage gap (they are the lasting deliverable). Named `*furnace*` so the
pkg166 autouse guard enforces linear rendering.
"""

from __future__ import annotations

import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray  # noqa: E402
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

_gpu = pytest.mark.skipif(
    AVAILABLE and not astroray.__features__.get("cuda", False),
    reason="CUDA feature not in this build")

_ROUGH = [0.0, 0.3, 0.6, 1.0]


def _furnace(mat_type, params, *, use_gpu, spp=128, depth=32):
    r = astroray.Renderer()
    r.set_background_color([1.0, 1.0, 1.0])           # uniform white environment
    m = r.create_material(mat_type, [1.0, 1.0, 1.0], dict(params))
    r.add_sphere([0.0, 0.0, 0.0], 1.0, m)
    r.set_integrator("path_tracer")
    if use_gpu:
        r.set_use_gpu(True)
    r.setup_camera([0, 0, 4], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 4.0, 80, 80)
    r.set_seed(7)
    # LINEAR (apply_gamma=False): a gamma furnace clamps to [0,1] and is blind to
    # energy GAIN — the exact reason this ~2x bug survived (pkg166; memory
    # gamma-furnace-cannot-detect-energy-gain).
    img = np.asarray(r.render(spp, depth, None, False), dtype=np.float32).reshape(80, 80, 3)
    return float(img[28:52, 28:52].mean())


def _opaque(roughness, metallic=0.0):
    return {"metallic": metallic, "transmission": 0.0, "roughness": roughness}


@_gpu
def test_disney_opaque_furnace_energy_gpu():
    if not astroray.Renderer().gpu_available:
        pytest.skip("CUDA GPU not available")
    vals = {R: _furnace("disney", _opaque(R), use_gpu=True) for R in _ROUGH}
    bad = {R: v for R, v in vals.items() if not (0.92 <= v <= 1.03)}
    assert not bad, f"GPU opaque Disney furnace not energy-conserving at roughness {bad}; all={vals}"


def test_disney_opaque_furnace_energy_cpu():
    # Control: CPU uses the monolithic Disney BSDF (no closure-graph recombination),
    # already conserving pre- and post-pkg170. Guards that the GPU fix did not
    # regress the CPU reference.
    vals = {R: _furnace("disney", _opaque(R), use_gpu=False) for R in _ROUGH}
    bad = {R: v for R, v in vals.items() if not (0.92 <= v <= 1.03)}
    assert not bad, f"CPU opaque Disney furnace not energy-conserving at roughness {bad}; all={vals}"


@_gpu
def test_disney_metallic_furnace_energy_gpu():
    # metallic=1 lowers to a SINGLE GGX-conductor lobe (W=weight_1), so the pkg170
    # normalization is a no-op here — this leg pins that the single-lobe conductor
    # path stays conserving and did not move.
    if not astroray.Renderer().gpu_available:
        pytest.skip("CUDA GPU not available")
    vals = {R: _furnace("disney", _opaque(R, metallic=1.0), use_gpu=True) for R in [0.3, 0.6]}
    bad = {R: v for R, v in vals.items() if not (0.92 <= v <= 1.03)}
    assert not bad, f"GPU metallic Disney furnace not energy-conserving at roughness {bad}; all={vals}"


@_gpu
def test_closure_graph_neighbour_furnace_energy_gpu():
    # Neighbour spot-check (spec acceptance): single-lobe closure graphs — plain
    # `metal` (GGX conductor) and plain `dielectric` (delta transmission) — must be
    # UNCHANGED by the recombination fix (W=weight_1 => (w_1/W)=1). Bands bracket
    # the measured baselines (metal ~0.945, dielectric ~0.993) loosely enough to
    # avoid noise flakes but far below the ~2x a leak would produce.
    if not astroray.Renderer().gpu_available:
        pytest.skip("CUDA GPU not available")
    metal = _furnace("metal", {"roughness": 0.3}, use_gpu=True)
    dielectric = _furnace("dielectric", {"ior": 1.5}, use_gpu=True)
    assert 0.90 <= metal <= 1.06, f"plain metal furnace moved: {metal:.4f}"
    assert 0.92 <= dielectric <= 1.05, f"plain dielectric furnace moved: {dielectric:.4f}"


@_gpu
def test_disney_opaque_gpu_does_not_glow_in_gray_furnace():
    """Render-level appearance guard (memory pr-named-tests-insufficient): the
    integral furnace above is necessary but not sufficient. A default opaque Disney
    sphere lit by a uniform 0.45 gray field must reflect ~that field, not ~2x it.
    Pre-pkg170 this GPU render glowed to ~0.9 (2x the environment); post-fix it sits
    at the environment. Rendered LINEAR (the gain is invisible through gamma)."""
    if not astroray.Renderer().gpu_available:
        pytest.skip("CUDA GPU not available")
    width = height = 64
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    r.set_seed(77)
    r.set_use_gpu(True)
    r.set_background_color([0.45, 0.45, 0.45])
    r.setup_camera([0.0, 0.0, 4.0], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0],
                   34.0, 1.0, 0.0, 4.0, width, height)
    m = r.create_material("disney", [0.8, 0.8, 0.8], {"metallic": 0.0, "roughness": 0.4})
    r.add_sphere([0.0, 0.0, 0.0], 0.85, m)
    pixels = np.asarray(r.render(256, 16, None, False), dtype=np.float32)
    yy, xx = np.mgrid[0:height, 0:width]
    sphere = ((xx - (width - 1) * 0.5) ** 2 + (yy - (height - 1) * 0.5) ** 2) <= 19.0 ** 2
    lum = 0.2126 * pixels[..., 0] + 0.7152 * pixels[..., 1] + 0.0722 * pixels[..., 2]
    mean_lum = float(np.mean(lum[sphere]))
    # A conserving gray surface in a 0.45 field reflects ~0.45. Ceiling 0.55 fails
    # the pre-fix ~0.9 glow; floor 0.30 keeps "no glow" from passing on a black BSDF.
    assert mean_lum <= 0.55, f"opaque Disney sphere glows in 0.45 field: mean_lum={mean_lum:.4f}"
    assert mean_lum >= 0.30, f"opaque Disney sphere reads near-black: mean_lum={mean_lum:.4f}"
